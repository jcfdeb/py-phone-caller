import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock


HELPER = Path(__file__).resolve().parents[1] / "roles/stack_lifecycle/files/stack_snapshot.py"
SPEC = importlib.util.spec_from_file_location("stack_snapshot", HELPER)
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class StackSnapshotTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parents[3] / "tests/.runtime"
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "config"
        self.source.mkdir(mode=0o750)
        self.source.chmod(0o750)
        (self.source / "secret.key").write_bytes(b"private credential\x00")
        (self.source / "secret.key").chmod(0o640)
        (self.source / "templates").mkdir(mode=0o710)
        (self.source / "templates").chmod(0o710)
        (self.source / "templates/message.txt").write_text("message {{ name }}")
        self.plan = self.base / "plan.json"
        self.metadata = {
            "schema_id": 1, "release_id": "r1", "kind": "checkpoint",
            "units": ["caller"], "postgresql": {"names": ["calls"]},
        }
        self.write_plan([self.source])
        self.destination = self.base / "snapshot"

    def write_plan(self, paths):
        self.plan.write_text(json.dumps({"paths": [str(path) for path in paths], "metadata": self.metadata}))

    def cli(self, *arguments, success=True):
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = snapshot.main(list(map(str, arguments)))
        if success:
            self.assertEqual(status, 0, errors.getvalue())
            self.assertEqual(errors.getvalue(), "")
            return json.loads(output.getvalue())
        self.assertNotEqual(status, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), '{"error": "snapshot operation failed"}\n')

    def create(self):
        return self.cli("create", "--plan", self.plan, "--destination", self.destination)

    def verify(self, success=True):
        return self.cli("verify", "--plan", self.plan, "--snapshot", self.destination, success=success)

    def restore(self, mapping=None, success=True):
        arguments = ["restore", "--plan", self.plan, "--snapshot", self.destination]
        if mapping is not None:
            mapping_file = self.base / "mapping.json"
            mapping_file.write_text(json.dumps(mapping))
            arguments.extend(["--mapping", mapping_file])
        return self.cli(*arguments, success=success)

    def manifest(self):
        return json.loads((self.destination / "manifest.json").read_text())

    def change_manifest(self, manifest):
        (self.destination / "manifest.json").write_text(json.dumps(manifest))

    def test_check_plan_is_read_only_and_metadata_is_opaque(self):
        database = self.source / "state.sqlite"
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("create table calls (id integer)")
        before = {str(path): path.stat() for path in self.base.rglob("*")}
        with mock.patch.object(snapshot.sqlite3, "connect", side_effect=AssertionError("database opened")), \
                mock.patch.object(snapshot.tempfile, "mkdtemp", side_effect=AssertionError("directory created")):
            self.assertEqual(self.cli("check-plan", "--plan", self.plan), {"changed": False})
        after = {str(path): path.stat() for path in self.base.rglob("*")}
        self.assertEqual(before.keys(), after.keys())
        for path in before:
            self.assertEqual(before[path].st_mtime_ns, after[path].st_mtime_ns)
            self.assertEqual(before[path].st_ctime_ns, after[path].st_ctime_ns)

    def test_check_plan_rejects_invalid_sources(self):
        for paths in ([self.source, self.source], [self.source, self.source / "templates"],
                      [self.base / "missing"], [Path("/etc")], [Path("/")]):
            with self.subTest(paths=paths):
                self.write_plan(paths)
                self.cli("check-plan", "--plan", self.plan, success=False)
        self.write_plan([self.source])
        (self.source / "orphan.sqlite-wal").write_bytes(b"wal")
        self.cli("check-plan", "--plan", self.plan, success=False)
        (self.source / "orphan.sqlite-wal").unlink()
        os.mkfifo(self.source / "fifo")
        self.cli("check-plan", "--plan", self.plan, success=False)

    def test_check_plan_rejects_links_and_linked_parent(self):
        (self.source / "link").symlink_to(self.source / "secret.key")
        self.cli("check-plan", "--plan", self.plan, success=False)
        (self.source / "link").unlink()
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.write_plan([alias / "secret.key"])
        self.cli("check-plan", "--plan", self.plan, success=False)

    def test_roundtrip_and_private_artifacts(self):
        original_mtime = (self.source / "secret.key").stat().st_mtime_ns
        self.assertEqual(self.create(), {"changed": True, "snapshot": str(self.destination)})
        for path in [self.destination, *self.destination.rglob("*")]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        self.assertEqual(self.verify(), {"changed": False, "metadata": self.metadata, "paths": [str(self.source)]})
        (self.source / "secret.key").write_bytes(b"new key")
        (self.source / "obsolete").write_text("old destination only")
        result = self.restore()
        self.assertTrue(result["changed"])
        self.assertEqual((self.source / "secret.key").read_bytes(), b"private credential\x00")
        self.assertFalse((self.source / "obsolete").exists())
        self.assertEqual((self.source / "secret.key").stat().st_mtime_ns, original_mtime)
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE((self.source / "secret.key").stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE((self.source / "templates").stat().st_mode), 0o710)
        self.assertEqual((self.source / "secret.key").stat().st_uid, os.getuid())
        self.assertEqual((self.source / "secret.key").stat().st_gid, os.getgid())
        previous = Path(result["previous_paths"][str(self.source)])
        self.assertEqual((previous / "secret.key").read_bytes(), b"new key")
        self.assertTrue((previous / "obsolete").exists())
        self.assertEqual(stat.S_IMODE(previous.parent.stat().st_mode), 0o700)

    def test_sqlite_committed_wal_without_uncommitted_rows(self):
        database = self.source / "calls.sqlite"
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("pragma journal_mode=wal")
        connection.execute("pragma wal_autocheckpoint=0")
        connection.execute("create table calls (id integer)")
        connection.execute("insert into calls values (1)")
        connection.commit()
        connection.execute("insert into calls values (2)")
        self.assertTrue(Path(str(database) + "-wal").exists())
        with mock.patch.object(snapshot.sqlite3, "connect", side_effect=AssertionError("database opened")):
            self.assertEqual(self.cli("check-plan", "--plan", self.plan), {"changed": False})
        self.create()
        self.verify()
        self.assertFalse(any(path.name.endswith(("-wal", "-shm", "-journal")) for path in self.destination.rglob("*")))
        connection.rollback()
        connection.close()
        self.restore()
        with contextlib.closing(sqlite3.connect(database)) as restored:
            self.assertEqual(restored.execute("select id from calls").fetchall(), [(1,)])
            self.assertEqual(restored.execute("pragma integrity_check").fetchall(), [("ok",)])

    def test_separate_file_roots_and_postgresql_directory(self):
        dump = self.base / "postgresql"
        dump.mkdir()
        (dump / "toc.dat").write_bytes(b"pg_dump directory fixture")
        key = self.source / "secret.key"
        self.write_plan([key, dump])
        self.create()
        key.write_bytes(b"changed")
        result = self.restore()
        self.assertEqual(key.read_bytes(), b"private credential\x00")
        self.assertEqual(len(result["previous_paths"]), 2)

    def test_mapped_restore_does_not_touch_original_or_omitted_paths(self):
        self.create()
        (self.source / "secret.key").write_bytes(b"keep original")
        omitted = self.base / "not-selected"
        omitted.write_text("untouched")
        target = self.base / "adopted"
        result = self.restore({str(self.source): str(target)})
        self.assertEqual(result, {"changed": True, "previous_paths": {}})
        self.assertEqual((target / "secret.key").read_bytes(), b"private credential\x00")
        self.assertEqual((self.source / "secret.key").read_bytes(), b"keep original")
        self.assertEqual(omitted.read_text(), "untouched")

    def test_verify_does_not_require_sources_to_exist(self):
        self.create()
        self.source.rename(self.base / "moved")
        self.verify()
        self.restore()
        self.assertTrue((self.source / "secret.key").exists())

    def test_corruption_is_rejected_before_destination_changes(self):
        self.create()
        (self.destination / "tree/0/secret.key").write_bytes(b"tampered")
        (self.source / "secret.key").write_bytes(b"current")
        self.verify(success=False)
        self.restore(success=False)
        self.assertEqual((self.source / "secret.key").read_bytes(), b"current")
        self.assertFalse(list(self.base.glob(".stack-previous-*")))

    def test_manifest_validation(self):
        self.create()
        original = self.manifest()
        mutations = [
            lambda m: m.update(schema_version=True),
            lambda m: m.update(metadata=[]),
            lambda m: m["entries"][0].update(mode=True),
            lambda m: m["entries"][0].update(uid=-1),
            lambda m: m["entries"][0].update(type="symlink"),
            lambda m: m["entries"].append(m["entries"][0].copy()),
            lambda m: m["entries"][1].update(path="../escape"),
            lambda m: m["entries"][1].update(path="/absolute"),
            lambda m: m["entries"][1].update(root=True),
            lambda m: m["paths"].append(m["paths"][0]),
            lambda m: m["entries"].pop(),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                manifest = json.loads(json.dumps(original))
                mutate(manifest)
                self.change_manifest(manifest)
                self.verify(success=False)
                self.restore(success=False)
        self.change_manifest(original)
        self.verify()

    def test_snapshot_symlinks_and_unlisted_files_rejected(self):
        self.create()
        artifact = self.destination / "tree/0/secret.key"
        artifact.unlink()
        artifact.symlink_to(self.source / "secret.key")
        self.verify(success=False)
        artifact.unlink()
        artifact.write_bytes(b"private credential\x00")
        artifact.chmod(0o600)
        self.verify()
        (self.destination / "unlisted").write_text("extra")
        self.verify(success=False)

    def test_invalid_mapping_and_destinations(self):
        extra = self.base / "extra"
        extra.mkdir()
        self.write_plan([self.source, extra])
        self.create()
        cases = [
            {},
            {str(self.source): str(self.base / "one")},
            {str(self.source): str(self.base / "one"), str(extra): str(self.base / "one/child")},
            {str(self.source): str(self.destination / "nested"), str(extra): str(extra)},
            {str(self.source): str(self.base), str(extra): str(extra)},
        ]
        for mapping in cases:
            with self.subTest(mapping=mapping):
                self.restore(mapping, success=False)
        (extra / "link").symlink_to(self.source / "secret.key")
        self.restore(success=False)
        (extra / "link").unlink()
        os.mkfifo(extra / "fifo")
        self.restore(success=False)

    def test_multiple_root_failure_rolls_back_all_replacements(self):
        others = [self.base / "second", self.base / "third"]
        for path in others:
            path.mkdir()
            (path / "value").write_text("snapshot")
        self.write_plan([self.source, *others])
        self.create()
        (self.source / "secret.key").write_bytes(b"current first")
        for path in others:
            (path / "value").write_text("current")
        real_replace = snapshot.os.replace

        def fail_third(source, target, *args, **kwargs):
            if Path(target) == others[1] and Path(source).parent.name.startswith(".stack-stage-"):
                raise OSError("injected replacement failure")
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(snapshot.os, "replace", side_effect=fail_third):
            self.restore(success=False)
        self.assertEqual((self.source / "secret.key").read_bytes(), b"current first")
        for path in others:
            self.assertEqual((path / "value").read_text(), "current")

    def test_existing_snapshot_and_failed_create_are_not_published(self):
        self.create()
        manifest = (self.destination / "manifest.json").read_bytes()
        self.create_failure()
        self.assertEqual((self.destination / "manifest.json").read_bytes(), manifest)
        self.destination = self.base / "failed"
        with mock.patch.object(snapshot, "_copy_regular", side_effect=OSError("secret path")):
            self.create_failure()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.base.glob(".stack-snapshot-*")))

    def create_failure(self):
        self.cli("create", "--plan", self.plan, "--destination", self.destination, success=False)

    def test_plan_json_and_cli_errors_are_generic(self):
        for content in ('{"paths": [], "metadata": {}}', '{"paths": [], "paths": [], "metadata": {}}',
                        '{"paths": [42], "metadata": {}}', '{"paths": [], "metadata": NaN}', 'secret invalid JSON'):
            self.plan.write_text(content)
            self.cli("check-plan", "--plan", self.plan, success=False)
        self.cli("check-plan", "--plan", self.plan, "--secret-unexpected", success=False)
        self.cli("check-plan", success=False)

    def test_nonfinite_metadata_rejected_in_preflight(self):
        self.plan.write_text('{"paths": [' + json.dumps(str(self.source)) + '], "metadata": {"number": 1e999}}')
        self.cli("check-plan", "--plan", self.plan, success=False)

    def test_orphan_sidecars_and_unselected_sqlite_symlink(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = self.source / ("data.sqlite" + suffix)
                sidecar.write_bytes(b"sidecar")
                self.cli("check-plan", "--plan", self.plan, success=False)
                self.create_failure()
                sidecar.unlink()
        database = self.source / "data.sqlite"
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("create table calls (id integer)")
        self.write_plan([database])
        Path(str(database) + "-wal").symlink_to(self.source / "secret.key")
        self.cli("check-plan", "--plan", self.plan, success=False)
        self.create_failure()

    def test_corrupt_sqlite_with_matching_hash_is_rejected(self):
        database = self.source / "data.sqlite"
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("create table calls (id integer)")
        self.create()
        artifact = self.destination / "tree/0/data.sqlite"
        artifact.write_bytes(snapshot.SQLITE_HEADER + b"not a database")
        manifest = self.manifest()
        for entry in manifest["entries"]:
            if entry["path"] == "data.sqlite":
                entry["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.change_manifest(manifest)
        self.verify(success=False)
        self.restore(success=False)

    def test_staging_failure_leaves_every_destination_untouched(self):
        other = self.base / "second"
        other.write_text("snapshot")
        self.write_plan([self.source, other])
        self.create()
        other.write_text("current second")
        (self.source / "secret.key").write_bytes(b"current first")
        real_copy = snapshot._copy_regular

        def fail_second(source, target, expected):
            if source == self.destination / "tree/1":
                raise OSError("injected staging failure")
            return real_copy(source, target, expected)

        with mock.patch.object(snapshot, "_copy_regular", side_effect=fail_second):
            self.restore(success=False)
        self.assertEqual(other.read_text(), "current second")
        self.assertEqual((self.source / "secret.key").read_bytes(), b"current first")

    def test_rollback_failure_keeps_previous_data_and_recovers_other_roots(self):
        others = [self.base / "second", self.base / "third"]
        for path in others:
            path.write_text("snapshot")
        self.write_plan([self.source, *others])
        self.create()
        (self.source / "secret.key").write_bytes(b"current first")
        for path in others:
            path.write_text("current " + path.name)
        real_replace = snapshot.os.replace

        def fail_replace(source, target, *args, **kwargs):
            if (Path(target) == others[1] and Path(source).parent.name.startswith(".stack-stage-")) or Path(source) == others[0]:
                raise OSError("injected replacement/rollback failure")
            return real_replace(source, target, *args, **kwargs)

        # Fail only after the second original has been moved into its private sibling.
        replacements = 0

        def fail_later(source, target, *args, **kwargs):
            nonlocal replacements
            replacements += 1
            if replacements > 4:
                return fail_replace(source, target, *args, **kwargs)
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(snapshot.os, "replace", side_effect=fail_later):
            self.restore(success=False)
        self.assertEqual((self.source / "secret.key").read_bytes(), b"current first")
        self.assertEqual(others[1].read_text(), "current third")
        retained = list(self.base.glob(".stack-previous-*/data"))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_text(), "current second")
        self.assertEqual(stat.S_IMODE(retained[0].parent.stat().st_mode), 0o700)

    def test_failed_publication_is_not_left_complete(self):
        real_sync = snapshot._sync_directory

        def fail_publication(path):
            if path == self.base and self.destination.exists():
                raise OSError("injected publication sync failure")
            return real_sync(path)

        with mock.patch.object(snapshot, "_sync_directory", side_effect=fail_publication):
            self.create_failure()
        self.assertFalse(self.destination.exists())

    def test_source_change_during_copy_is_not_published(self):
        real_copy = snapshot._copy_regular

        def mutate_source(source, target, expected):
            digest = real_copy(source, target, expected)
            if source == self.source / "secret.key":
                source.write_bytes(b"concurrent replacement")
            return digest

        with mock.patch.object(snapshot, "_copy_regular", side_effect=mutate_source):
            self.create_failure()
        self.assertFalse(self.destination.exists())

    def test_relative_cli_paths_and_restrictive_umask(self):
        previous_mask = os.umask(0o777)
        try:
            with contextlib.chdir(self.base):
                self.assertEqual(self.cli("check-plan", "--plan", "plan.json"), {"changed": False})
                self.cli("create", "--plan", "plan.json", "--destination", "snapshot")
                self.cli("verify", "--plan", "plan.json", "--snapshot", "snapshot")
                self.cli("restore", "--plan", "plan.json", "--snapshot", "snapshot")
        finally:
            os.umask(previous_mask)
        self.assertEqual((self.source / "secret.key").read_bytes(), b"private credential\x00")

    def test_new_destination_is_removed_on_later_root_failure(self):
        other = self.base / "second"
        other.write_text("original")
        self.write_plan([self.source, other])
        self.create()
        new_target = self.base / "adopted"
        real_replace = snapshot.os.replace

        def fail_second(source, target, *args, **kwargs):
            if Path(target) == other and Path(source).parent.name.startswith(".stack-stage-"):
                raise OSError("injected replacement failure")
            return real_replace(source, target, *args, **kwargs)

        with mock.patch.object(snapshot.os, "replace", side_effect=fail_second):
            self.restore({str(self.source): str(new_target), str(other): str(other)}, success=False)
        self.assertFalse(new_target.exists())
        self.assertEqual(other.read_text(), "original")

    def test_destination_and_manifest_parent_symlinks_rejected(self):
        self.create()
        alias = self.base / "alias"
        alias.symlink_to(self.base, target_is_directory=True)
        self.cli("verify", "--snapshot", alias / "snapshot", "--plan", self.plan, success=False)
        self.restore({str(self.source): str(alias / "target")}, success=False)
        manifest = self.destination / "manifest.json"
        moved = self.base / "manifest.json"
        manifest.rename(moved)
        manifest.symlink_to(moved)
        self.verify(success=False)
        self.assertFalse((self.base / "target").exists())

    def test_ownership_must_be_restorable(self):
        self.create()
        manifest = self.manifest()
        for entry in manifest["entries"]:
            if entry["path"] == "secret.key":
                entry["uid"] = os.geteuid() + 1
        self.change_manifest(manifest)
        if os.geteuid() == 0:
            self.restore()
            self.assertEqual((self.source / "secret.key").stat().st_uid, 1)
        else:
            self.restore(success=False)
            self.assertEqual((self.source / "secret.key").stat().st_uid, os.geteuid())

    def test_sqlite_file_root_restore_rejects_adjacent_live_sidecars(self):
        database = self.source / "calls.sqlite"
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("pragma journal_mode=wal")
        connection.execute("pragma wal_autocheckpoint=0")
        connection.execute("create table calls (id integer)")
        connection.execute("insert into calls values (1)")
        connection.commit()
        self.write_plan([database])
        self.create()
        connection.execute("insert into calls values (2)")
        connection.commit()
        before = database.stat().st_ino
        self.restore(success=False)
        self.assertEqual(database.stat().st_ino, before)
        self.assertEqual(connection.execute("select id from calls").fetchall(), [(1,), (2,)])
        connection.close()
        self.restore()
        with contextlib.closing(sqlite3.connect(database)) as restored:
            self.assertEqual(restored.execute("select id from calls").fetchall(), [(1,)])


if __name__ == "__main__":
    unittest.main()