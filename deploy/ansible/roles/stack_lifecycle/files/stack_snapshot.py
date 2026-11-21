#!/usr/bin/env python3
"""Private filesystem/SQLite snapshots; callers must quiesce cross-file writers.

check-plan only reads the plan, directory entries and file headers. It never opens
a SQLite connection. Metadata is opaque JSON. Hashes detect corruption, not a
malicious author who can replace both the manifest and its artifacts.

Restore stages every root before replacing any root. Previous roots are retained
in private .stack-previous-* siblings; replacement failures trigger best-effort
reverse-order rollback. This is not a crash-atomic multi-filesystem transaction.
Standalone SQLite file destinations must be sidecar-free; select the containing
directory when sidecars also need replacing. Undeclared siblings are never removed.
Callers must serialize lifecycle operations and protect source/destination parents
from concurrent modification. No portable stdlib API can eliminate every pathname
race, though paths, inode identities and file versions are repeatedly checked.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import sys
import tempfile
import time


SQLITE_HEADER = b"SQLite format 3\x00"
SIDECARS = ("-wal", "-shm", "-journal")
ALLOWED_BASES = tuple(Path(value) for value in ("/etc", "/var/lib", "/var/backups", "/opt", "/home", "/root", "/usr/share", "/tmp", "/var/tmp"))



class SnapshotError(Exception):
    pass


def _require(condition):
    if not condition:
        raise SnapshotError()


def _absolute(value, restricted=True):
    _require(isinstance(value, str) and "\x00" not in value)
    path = Path(value)
    _require(path.is_absolute() and str(path) == value and ".." not in path.parts)
    _require(path != Path("/"))
    if restricted:
        _require(any(path != base and path.is_relative_to(base) for base in ALLOWED_BASES))
    return path


def _control_path(value):
    return _absolute(str(Path(value).absolute()), restricted=False)


def _disjoint(paths):
    for index, path in enumerate(paths):
        for other in paths[:index]:
            _require(not path.is_relative_to(other) and not other.is_relative_to(path))


def _identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _version(info):
    return _identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _path_stat(path, missing=False):
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing and index == len(path.parts) - 2:
                return None
            raise
        _require(not stat.S_ISLNK(info.st_mode))
        if current != path:
            _require(stat.S_ISDIR(info.st_mode))
        else:
            _require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
            return info
    return current.lstat()


def _same_path(path, expected, content=False):
    actual = _path_stat(path)
    compare = _version if content else _identity
    _require(compare(actual) == compare(expected))
    return actual


@contextmanager
def _read_file(path, expected=None, stable=True):
    before = _path_stat(path)
    _require(stat.S_ISREG(before.st_mode))
    compare = _version if stable else _identity
    if expected is not None:
        _require(compare(before) == compare(expected))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        _require(compare(os.fstat(stream.fileno())) == compare(before))
        _same_path(path, before, content=stable)
        yield stream
        _require(compare(os.fstat(stream.fileno())) == compare(before))
        _same_path(path, before, content=stable)


def _walk(root):
    result = {}
    pending = [root]
    while pending:
        path = pending.pop()
        info = _path_stat(path)
        result[path] = info
        if stat.S_ISDIR(info.st_mode):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                _require(_version(os.fstat(descriptor)) == _version(info))
                with os.scandir(descriptor) as children:
                    names = sorted(child.name for child in children)
                _same_path(path, info, content=True)
                pending.extend(path / name for name in reversed(names))
            finally:
                os.close(descriptor)
    return result


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _invalid_constant(value):
    raise SnapshotError()


def _finite_float(value):
    number = float(value)
    _require(math.isfinite(number))
    return number


def _load_json(path):
    with _read_file(path) as stream:
        return json.load(stream, object_pairs_hook=_json_object, parse_constant=_invalid_constant, parse_float=_finite_float)


def _load_plan(path):
    plan = _load_json(_control_path(path))
    _require(isinstance(plan, dict) and set(plan) == {"paths", "metadata"})
    _require(isinstance(plan["metadata"], dict))
    _require(isinstance(plan["paths"], list) and bool(plan["paths"]))
    paths = [_absolute(value) for value in plan["paths"]]
    _disjoint(paths)
    return plan, paths


def _sqlite_neighbors(path, absent=False):
    for suffix in SIDECARS:
        info = _path_stat(Path(str(path) + suffix), missing=True)
        _require(info is None or not absent)
        if info is not None:
            _require(stat.S_ISREG(info.st_mode))


def _inspect_sources(paths):
    roots = []
    for root in paths:
        entries = {}
        for path, info in _walk(root).items():
            database = False
            if stat.S_ISREG(info.st_mode):
                with _read_file(path, info, stable=False) as stream:
                    database = stream.read(16) == SQLITE_HEADER
                if database:
                    _sqlite_neighbors(path)
            entries[path] = {"stat": info, "sqlite": database}
        for path in list(entries):
            if not stat.S_ISREG(entries[path]["stat"].st_mode):
                continue
            for suffix in SIDECARS:
                if path.name.endswith(suffix):
                    database = Path(str(path)[:-len(suffix)])
                    _require(database in entries and entries[database]["sqlite"])
                    _require(not entries[path]["sqlite"])
                    entries[path]["sidecar"] = True
                    break
        roots.append({path: entry for path, entry in entries.items() if not entry.get("sidecar")})
    return roots


def check_plan(plan_path):
    _, paths = _load_plan(plan_path)
    _inspect_sources(paths)
    return {"changed": False}


@contextmanager
def _new_file(path):
    _path_stat(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        yield stream
        stream.flush()
        os.fsync(stream.fileno())


def _copy_regular(source, target, expected):
    digest = hashlib.sha256()
    with _read_file(source, expected) as input_stream, _new_file(target) as output_stream:
        while chunk := input_stream.read(1024 * 1024):
            output_stream.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _hash_file(path, expected=None):
    digest = hashlib.sha256()
    with _read_file(path, expected) as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(connection):
    connection.execute("pragma trusted_schema=off")
    _require(connection.execute("pragma integrity_check").fetchall() == [("ok",)])


def _verify_database(path):
    before = _path_stat(path)
    _sqlite_neighbors(path, absent=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        _integrity(connection)
    finally:
        connection.close()
    _same_path(path, before, content=True)


def _backup_database(source, target, expected):
    _same_path(source, expected)
    _sqlite_neighbors(source)
    with _new_file(target):
        pass
    deadline = time.monotonic() + 60

    def progress(status, remaining, total):
        _require(time.monotonic() < deadline)

    input_connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        input_connection.execute("pragma trusted_schema=off")
        output_connection = sqlite3.connect(target)
        try:
            input_connection.backup(output_connection, pages=256, progress=progress, sleep=0.05)
            output_connection.execute("pragma journal_mode=delete")
            _integrity(output_connection)
        finally:
            output_connection.close()
    finally:
        input_connection.close()
    _same_path(source, expected)
    _sqlite_neighbors(source)
    with _read_file(target) as stream:
        os.fsync(stream.fileno())
    return _hash_file(target)


def _private_directory(parent, prefix):
    before = _path_stat(parent)
    _require(stat.S_ISDIR(before.st_mode))
    path = Path(tempfile.mkdtemp(dir=parent, prefix=prefix))
    path.chmod(0o700)
    _same_path(parent, before)
    return path


def _mkdir_private(path):
    path.mkdir(mode=0o700)
    path.chmod(0o700, follow_symlinks=False)


def _sync_directory(path):
    before = _path_stat(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _require(_identity(os.fstat(descriptor)) == _identity(before))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _entry(root_index, relative, info):
    return {
        "root": root_index, "path": str(relative),
        "type": "directory" if stat.S_ISDIR(info.st_mode) else "file",
        "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
        "atime_ns": info.st_atime_ns, "mtime_ns": info.st_mtime_ns,
    }


def create(plan_path, destination):
    plan, paths = _load_plan(plan_path)
    destination = _control_path(destination)
    _disjoint([*paths, destination])
    _require(_path_stat(destination, missing=True) is None)
    sources = _inspect_sources(paths)
    parent = _path_stat(destination.parent)
    staging = _private_directory(destination.parent, ".stack-snapshot-")
    try:
        _mkdir_private(staging / "tree")
        manifest = {"schema_version": 1, "paths": plan["paths"], "metadata": plan["metadata"], "entries": []}
        for index, entries in enumerate(sources):
            for source, record in entries.items():
                relative = source.relative_to(paths[index])
                target = staging / "tree" / str(index) / relative
                entry = _entry(index, relative, record["stat"])
                if entry["type"] == "directory":
                    _mkdir_private(target)
                else:
                    entry["sqlite"] = record["sqlite"]
                    if record["sqlite"]:
                        entry["sha256"] = _backup_database(source, target, record["stat"])
                    else:
                        entry["sha256"] = _copy_regular(source, target, record["stat"])
                manifest["entries"].append(entry)
        final_sources = _inspect_sources(paths)
        for before, after in zip(sources, final_sources):
            _require(before.keys() == after.keys())
            for path, record in before.items():
                compare = _identity if record["sqlite"] or stat.S_ISDIR(record["stat"].st_mode) else _version
                _require(compare(record["stat"]) == compare(after[path]["stat"]))
        with _new_file(staging / "manifest.json") as stream:
            stream.write(json.dumps(manifest, allow_nan=False, sort_keys=True).encode("utf-8"))
        _validate_snapshot(staging, plan)
        for path, info in reversed(list(_walk(staging).items())):
            if stat.S_ISDIR(info.st_mode):
                _sync_directory(path)
        _same_path(destination.parent, parent)
        _require(_path_stat(destination, missing=True) is None)
        published = _path_stat(staging)
        os.rename(staging, destination)
        try:
            _sync_directory(destination.parent)
        except BaseException:
            _same_path(destination, published)
            _require(_path_stat(staging, missing=True) is None)
            os.rename(destination, staging)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {"changed": True, "snapshot": str(destination)}


def _relative(value):
    _require(isinstance(value, str) and bool(value) and "\x00" not in value)
    path = PurePosixPath(value)
    _require(not path.is_absolute() and ".." not in path.parts and str(path) == value)
    return path


def _validate_manifest(manifest, plan):
    _require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "paths", "metadata", "entries"})
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
    _require(isinstance(manifest["metadata"], dict) and manifest["paths"] == plan["paths"])
    _require(isinstance(manifest["entries"], list) and bool(manifest["entries"]))
    indexed = {}
    for entry in manifest["entries"]:
        _require(isinstance(entry, dict))
        fields = {"root", "path", "type", "mode", "uid", "gid", "atime_ns", "mtime_ns"}
        if entry.get("type") == "file":
            fields |= {"sha256", "sqlite"}
        _require(set(entry) == fields and entry["type"] in ("file", "directory"))
        _require(type(entry["root"]) is int and 0 <= entry["root"] < len(plan["paths"]))
        relative = _relative(entry["path"])
        key = entry["root"], relative
        _require(key not in indexed)
        for name, maximum in (("mode", 0o7777), ("uid", 2 ** 32 - 2), ("gid", 2 ** 32 - 2)):
            _require(type(entry[name]) is int and 0 <= entry[name] <= maximum)
        for name in ("atime_ns", "mtime_ns"):
            _require(type(entry[name]) is int and -(2 ** 63) <= entry[name] < 2 ** 63)
        if entry["type"] == "file":
            _require(type(entry["sqlite"]) is bool)
            digest = entry["sha256"]
            _require(isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest))
            _require(not relative.name.endswith(SIDECARS))
        indexed[key] = entry
    for index in range(len(plan["paths"])):
        _require((index, PurePosixPath(".")) in indexed)
    for (index, relative), entry in indexed.items():
        if relative != PurePosixPath("."):
            parent = indexed.get((index, relative.parent))
            _require(parent is not None and parent["type"] == "directory")
    return indexed


def _validate_snapshot(directory, plan):
    _require(stat.S_ISDIR(_path_stat(directory).st_mode))
    manifest = _load_json(directory / "manifest.json")
    indexed = _validate_manifest(manifest, plan)
    expected = {directory: "directory", directory / "manifest.json": "file", directory / "tree": "directory"}
    for (index, relative), entry in indexed.items():
        expected[directory / "tree" / str(index) / relative] = entry["type"]
    actual = _walk(directory)
    _require(actual.keys() == expected.keys())
    for path, info in actual.items():
        is_directory = expected[path] == "directory"
        _require(stat.S_ISDIR(info.st_mode) == is_directory)
        _require(stat.S_IMODE(info.st_mode) == (0o700 if is_directory else 0o600))
        if not is_directory:
            _require(info.st_nlink == 1)
    for (index, relative), entry in indexed.items():
        artifact = directory / "tree" / str(index) / relative
        if entry["type"] == "file":
            _require(_hash_file(artifact, actual[artifact]) == entry["sha256"])
            with _read_file(artifact, actual[artifact]) as stream:
                _require((stream.read(16) == SQLITE_HEADER) == entry["sqlite"])
            if entry["sqlite"]:
                _verify_database(artifact)
    return manifest, indexed, actual


def verify(snapshot_path, plan_path):
    plan, _ = _load_plan(plan_path)
    manifest, _, _ = _validate_snapshot(_control_path(snapshot_path), plan)
    return {"changed": False, "metadata": manifest["metadata"], "paths": manifest["paths"]}


def _restore_metadata(path, entry):
    before = _path_stat(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if entry["type"] == "directory":
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        _require(_identity(os.fstat(descriptor)) == _identity(before))
        if os.geteuid() == 0:
            os.fchown(descriptor, entry["uid"], entry["gid"])
        else:
            _require(before.st_uid == entry["uid"] and before.st_gid == entry["gid"])
        os.fchmod(descriptor, entry["mode"])
        os.utime(descriptor, ns=(entry["atime_ns"], entry["mtime_ns"]))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unchanged_tree(path, expected):
    if expected is None:
        _require(_path_stat(path, missing=True) is None)
        return
    actual = _walk(path)
    _require(actual.keys() == expected.keys())
    for item, info in expected.items():
        _require(_version(actual[item]) == _version(info))


def _rollback(records):
    for record in reversed(records):
        try:
            target = record["target"]
            _same_path(target.parent, record["parent"])
            if record["installed"]:
                _same_path(target, record["staged_stat"])
                _require(_path_stat(record["stage"] / "data", missing=True) is None)
                os.replace(target, record["stage"] / "data")
                record["installed"] = False
            if record["moved"]:
                _require(_path_stat(target, missing=True) is None)
                _same_path(record["previous"] / "data", record["original"][target])
                os.replace(record["previous"] / "data", target)
                record["moved"] = False
            _sync_directory(target.parent)
        except Exception:
            # Continue recovering other roots; never delete an unrecovered old root.
            continue


def restore(snapshot_path, plan_path, mapping_path=None):
    plan, paths = _load_plan(plan_path)
    directory = _control_path(snapshot_path)
    _, indexed, artifacts = _validate_snapshot(directory, plan)
    if mapping_path is None:
        targets = paths
    else:
        mapping = _load_json(_control_path(mapping_path))
        _require(isinstance(mapping, dict) and set(mapping) == set(plan["paths"]))
        targets = [_absolute(mapping[str(path)]) for path in paths]
    _disjoint([directory, *targets])
    records = []
    for index, target in enumerate(targets):
        info = _path_stat(target, missing=True)
        sqlite_file = indexed[index, PurePosixPath(".")].get("sqlite", False)
        if sqlite_file:
            _sqlite_neighbors(target, absent=True)
        records.append({
            "target": target, "parent": _path_stat(target.parent),
            "original": _walk(target) if info is not None else None,
            "sqlite_file": sqlite_file,
            "stage": None, "previous": None, "moved": False, "installed": False,
        })
    try:
        for index, record in enumerate(records):
            stage = _private_directory(record["target"].parent, ".stack-stage-")
            record["stage"] = stage
            entries = [(relative, entry) for (root, relative), entry in indexed.items() if root == index]
            entries.sort(key=lambda pair: (len(pair[0].parts), str(pair[0])))
            for relative, entry in entries:
                target = stage / "data" / relative
                artifact = directory / "tree" / str(index) / relative
                if entry["type"] == "directory":
                    _mkdir_private(target)
                else:
                    _require(_copy_regular(artifact, target, artifacts[artifact]) == entry["sha256"])
            for relative, entry in reversed(entries):
                _restore_metadata(stage / "data" / relative, entry)
            record["staged_stat"] = _path_stat(stage / "data")
            _sync_directory(stage)
            if record["original"] is not None:
                record["previous"] = _private_directory(record["target"].parent, ".stack-previous-")
        for record in records:
            target = record["target"]
            _same_path(target.parent, record["parent"])
            _unchanged_tree(target, record["original"])
            if record["sqlite_file"]:
                _sqlite_neighbors(target, absent=True)
            if record["previous"] is not None:
                _require(_path_stat(record["previous"] / "data", missing=True) is None)
                os.replace(target, record["previous"] / "data")
                record["moved"] = True
                _sync_directory(record["previous"])
            _require(_path_stat(target, missing=True) is None)
            _same_path(record["stage"] / "data", record["staged_stat"])
            os.replace(record["stage"] / "data", target)
            record["installed"] = True
            _sync_directory(target.parent)
    except BaseException:
        _rollback(records)
        raise
    finally:
        for record in records:
            if record["stage"] is not None:
                shutil.rmtree(record["stage"], ignore_errors=True)
            if record["previous"] is not None and not record["moved"]:
                try:
                    record["previous"].rmdir()
                except OSError:
                    pass
    previous_paths = {str(record["target"]): str(record["previous"] / "data")
                      for record in records if record["moved"]}
    return {"changed": True, "previous_paths": previous_paths}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SnapshotError()


def main(arguments=None):
    try:
        parser = _Parser(description="Private stack snapshots", allow_abbrev=False)
        commands = parser.add_subparsers(dest="command", required=True)
        for command in ("check-plan", "create", "verify", "restore"):
            subparser = commands.add_parser(command, allow_abbrev=False)
            subparser.add_argument("--plan", required=True)
            if command == "create":
                subparser.add_argument("--destination", required=True)
            elif command in ("verify", "restore"):
                subparser.add_argument("--snapshot", required=True)
            if command == "restore":
                subparser.add_argument("--mapping")
        options = parser.parse_args(arguments)
        if options.command == "check-plan":
            result = check_plan(options.plan)
        elif options.command == "create":
            result = create(options.plan, options.destination)
        elif options.command == "verify":
            result = verify(options.snapshot, options.plan)
        else:
            result = restore(options.snapshot, options.plan, options.mapping)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (Exception, KeyboardInterrupt):
        print('{"error": "snapshot operation failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())