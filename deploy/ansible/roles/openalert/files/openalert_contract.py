#!/usr/bin/env python3
"""Deployment safety checks; Python 3.11+, no daemon execution or network I/O.

The service must use state_dir as WorkingDirectory, without OPENALERT_/OPENALERTD_
configuration overrides. Capabilities and device paths are JSON string arrays.
Archive installation runs as root; config validation runs as the service user.
"""

import argparse
import ctypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.parse import urlsplit


ARCHITECTURES = {
    "amd64": ("x86_64-unknown-linux-gnu", 62, "/lib64/ld-linux-x86-64.so.2", "x86_64"),
    "arm64": ("aarch64-unknown-linux-gnu", 183, "/lib/ld-linux-aarch64.so.1", "aarch64"),
}
DEFAULT_TEMPLATE = "prometheus_alertmanager.json.tera"
HEX = re.compile(r"[0-9a-fA-F]{64}\Z")
SONAME = re.compile(r"[A-Za-z0-9_+.-]+\.so(?:\.[A-Za-z0-9_.-]+)?\Z")
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024


class ContractError(ValueError):
    """Only fixed, non-secret messages may cross the CLI boundary."""


def require(condition, message="deployment contract rejected"):
    if not condition:
        raise ContractError(message)


def text(value):
    require(isinstance(value, str) and bool(value.strip()) and "\x00" not in value)
    return value


def table(value):
    require(isinstance(value, dict))
    return value


def flag(section, key, default=False):
    value = section.get(key, default)
    require(type(value) is bool)
    return value


def string_list(value):
    require(isinstance(value, list))
    require(all(isinstance(item, str) and item for item in value))
    return value


def json_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def load_json(value):
    return json.loads(value, object_pairs_hook=json_object)


def digest(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def version(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", value),
            "invalid runtime version")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (3 - len(parts))


def elf_header(data, machine):
    require(len(data) >= 64 and data[:7] == b"\x7fELF\x02\x01\x01", "invalid ELF header")
    require(struct.unpack_from("<H", data, 18)[0] == machine, "ELF architecture mismatch")
    require(struct.unpack_from("<H", data, 16)[0] in (2, 3), "invalid ELF type")


def inspect_elf(data, machine):
    """Read ELF64 program headers and dynamic strings, never load the release."""
    elf_header(data, machine)
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 54)
    require(phsize == 56 and 0 < phnum < 4096, "invalid ELF program headers")
    require(phoff + phsize * phnum <= len(data), "truncated ELF")
    segments = []
    interpreter = None
    dynamic = None
    for index in range(phnum):
        kind, _, offset, address, _, size, _, _ = struct.unpack_from(
            "<IIQQQQQQ", data, phoff + index * phsize)
        require(offset + size <= len(data), "truncated ELF segment")
        if kind == 1:
            segments.append((address, offset, size))
        elif kind == 3:
            require(interpreter is None and 1 < size < 4096, "invalid ELF interpreter")
            raw = data[offset:offset + size]
            require(raw[-1:] == b"\x00" and b"\x00" not in raw[:-1], "invalid ELF interpreter")
            interpreter = raw[:-1].decode("ascii")
        elif kind == 2:
            require(dynamic is None and size % 16 == 0, "invalid ELF dynamic section")
            dynamic = (offset, size)
    require(interpreter is not None and dynamic is not None, "missing ELF runtime data")
    entries = []
    offset, size = dynamic
    terminated = False
    for index in range(offset, offset + size, 16):
        tag, value = struct.unpack_from("<qQ", data, index)
        if tag == 0:
            terminated = True
            break
        require(tag not in (15, 29), "ELF runtime search paths are not permitted")
        entries.append((tag, value))
    require(terminated, "unterminated ELF dynamic section")
    strings = [value for tag, value in entries if tag == 5]
    sizes = [value for tag, value in entries if tag == 10]
    require(len(strings) == len(sizes) == 1, "invalid ELF string table")
    locations = [offset + strings[0] - address for address, offset, size in segments
                 if address <= strings[0] and strings[0] + sizes[0] <= address + size]
    require(len(locations) == 1, "invalid ELF string table location")
    raw = data[locations[0]:locations[0] + sizes[0]]
    libraries = []
    for tag, value in entries:
        if tag != 1:
            continue
        require(value < len(raw) and b"\x00" in raw[value:], "invalid ELF dependency")
        name = raw[value:raw.index(b"\x00", value)].decode("ascii")
        require(SONAME.fullmatch(name), "invalid ELF dependency")
        libraries.append(name)
    require(libraries and len(libraries) == len(set(libraries)), "invalid ELF dependencies")
    versions = [version(item.decode("ascii")) for item in
                re.findall(rb"GLIBC_([0-9]+\.[0-9]+(?:\.[0-9]+)?)\x00", data)]
    require(versions, "missing ELF glibc requirements")
    return interpreter, set(libraries), max(versions)


def validate_metadata(metadata, architecture, binary):
    metadata = table(metadata)
    require(type(metadata.get("schema_version")) is int and metadata["schema_version"] == 1,
            "unsupported release schema")
    target, machine, interpreter, _ = ARCHITECTURES[architecture]
    require(metadata.get("package") == "openalertd", "invalid release package")
    require(metadata.get("architecture") == architecture and metadata.get("target") == target,
            "release architecture mismatch")
    for key in ("version", "release_id", "source_revision"):
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", text(metadata.get(key))),
                "invalid release identity")
    build = table(metadata.get("build"))
    text(build.get("rustc_version"))
    text(build.get("baseline"))
    prebuilt = flag(build, "prebuilt", None)
    if prebuilt:
        require("source_dirty" in metadata
                and (metadata["source_dirty"] is None or type(metadata["source_dirty"]) is bool))
        require("cargo_locked" in build
                and (build["cargo_locked"] is None or type(build["cargo_locked"]) is bool))
    else:
        flag(metadata, "source_dirty", None)
        flag(build, "cargo_locked", None)
    record = table(metadata.get("binary"))
    require(record.get("path") == "bin/openalertd" and isinstance(record.get("sha256"), str)
            and HEX.fullmatch(record["sha256"]), "invalid binary metadata")
    require(hashlib.sha256(binary).hexdigest() == record["sha256"].lower(), "binary checksum mismatch")
    runtime = table(metadata.get("runtime"))
    require(runtime.get("libc") == "glibc" and runtime.get("interpreter") == interpreter,
            "invalid runtime metadata")
    minimum = version(runtime.get("minimum_glibc"))
    libraries = string_list(runtime.get("needed_libraries"))
    require(libraries and all(SONAME.fullmatch(item) for item in libraries)
            and len(libraries) == len(set(libraries)), "invalid runtime libraries")
    actual_interpreter, actual_libraries, actual_minimum = inspect_elf(binary, machine)
    require(actual_interpreter == interpreter and actual_libraries == set(libraries)
            and minimum >= actual_minimum, "ELF runtime metadata mismatch")
    return metadata


def host_glibc():
    try:
        output = subprocess.run(["/usr/bin/getconf", "GNU_LIBC_VERSION"], check=True,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        require(output.startswith("glibc "), "glibc unavailable")
        return version(output[6:])
    except (OSError, subprocess.SubprocessError, ContractError):
        try:
            function = ctypes.CDLL(None).gnu_get_libc_version
            function.restype = ctypes.c_char_p
            return version(function().decode("ascii"))
        except (AttributeError, OSError, UnicodeError):
            raise ContractError("glibc unavailable") from None


def library_candidates(libraries, architecture):
    candidates = {name: [] for name in libraries}
    for command in ("/sbin/ldconfig", "/usr/sbin/ldconfig"):
        try:
            output = subprocess.run([command, "-p"], check=True, capture_output=True,
                                    text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[0] in candidates and fields[-2] == "=>":
                path = Path(fields[-1])
                if path.is_absolute():
                    candidates[fields[0]].append(path)
        break
    multiarch = ARCHITECTURES[architecture][3] + "-linux-gnu"
    for name in libraries:
        for base in ("/lib", "/usr/lib", "/lib64", "/usr/lib64"):
            candidates[name].extend((Path(base) / multiarch / name, Path(base) / name))
    return candidates


def compatible_library(path, machine):
    try:
        with path.open("rb") as stream:
            elf_header(stream.read(64), machine)
        return True
    except (OSError, ContractError):
        return False


def validate_runtime(metadata, architecture):
    _, machine, interpreter, host = ARCHITECTURES[architecture]
    require(platform.system() == "Linux" and platform.machine() == host, "host architecture mismatch")
    runtime = metadata["runtime"]
    require(host_glibc() >= version(runtime["minimum_glibc"]), "host glibc is too old")
    require(os.access(interpreter, os.X_OK) and compatible_library(Path(interpreter), machine),
            "required interpreter unavailable")
    for paths in library_candidates(runtime["needed_libraries"], architecture).values():
        require(any(compatible_library(path, machine) for path in paths), "required library unavailable")


def safe_member(name):
    require(isinstance(name, str) and name and "\\" not in name and "\x00" not in name,
            "unsafe archive path")
    require(not name.startswith("/") and all(part not in ("", ".", "..")
            for part in name.split("/")), "unsafe archive path")
    return PurePosixPath(name)


def secure_directory(path):
    require(path.is_absolute(), "absolute destination required")
    for component in (path, *path.parents):
        info = component.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and not info.st_mode & 0o022, "unsafe destination directory")


def archive_contract(archive, sha256, architecture, destination):
    require(isinstance(sha256, str) and HEX.fullmatch(sha256), "invalid trusted checksum")
    require(architecture in ARCHITECTURES, "unsupported architecture")
    destination = Path(destination)
    require(destination.is_absolute() and destination.name and ".." not in destination.parts,
            "absolute destination required")
    secure_directory(destination.parent)
    # Snapshot first: the checked bytes and the parsed/extracted bytes must be identical.
    with tempfile.TemporaryFile(dir=destination.parent) as snapshot:
        with Path(archive).open("rb") as source:
            shutil.copyfileobj(source, snapshot)
        snapshot.seek(0)
        require(digest(snapshot) == sha256.lower(), "archive checksum mismatch")
        snapshot.seek(0)
        with tarfile.open(fileobj=snapshot, mode="r:*") as bundle:
            members = {}
            directories = set()
            hashes = {}
            total = 0
            for member in bundle:
                name = member.name.rstrip("/") if member.isdir() else member.name
                path = safe_member(name)
                require(name not in members and len(members) < 20000, "duplicate or excessive archive entries")
                require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE) and not member.sparse,
                        "unsupported archive entry")
                require(0 <= member.size <= MAX_FILE, "archive entry too large")
                total += member.size
                require(total <= MAX_TOTAL, "archive too large")
                members[name] = member
                directories.update(str(parent) for parent in path.parents if str(parent) != ".")
                if member.isdir():
                    directories.add(name)
                else:
                    with bundle.extractfile(member) as stream:
                        hashes[name] = digest(stream)
            roots = {PurePosixPath(name).parts[0] for name in members}
            require(len(roots) == 1, "archive must have one release root")
            root = roots.pop()
            require(re.fullmatch(r"openalertd-[A-Za-z0-9][A-Za-z0-9_.+-]*", root), "invalid release root")
            require(not directories.intersection(hashes), "archive path type conflict")
            required = ("release.json", "bin/openalertd", "templates/" + DEFAULT_TEMPLATE,
                        "systemd/openalertd.service")
            require(all(root + "/" + name in hashes and members[root + "/" + name].size > 0
                        for name in required), "missing release assets")
            require(any(name.startswith(root + "/profiles/") and members[name].size > 0
                        for name in hashes), "missing release profiles")
            require(members[root + "/bin/openalertd"].mode & 0o111, "binary is not executable")
            require(members[root + "/release.json"].size <= 1024 * 1024, "release metadata too large")
            metadata = load_json(bundle.extractfile(members[root + "/release.json"]).read())
            binary = bundle.extractfile(members[root + "/bin/openalertd"]).read()
            validate_metadata(metadata, architecture, binary)
            validate_runtime(metadata, architecture)
            empty_destination = False
            if destination.exists() or destination.is_symlink():
                secure_directory(destination)
                empty_destination = not any(destination.iterdir())
            if destination.exists() and not empty_destination:
                actual = set()
                for parent, dirs, files in os.walk(destination, followlinks=False):
                    for name in dirs + files:
                        path = Path(parent) / name
                        key = path.relative_to(destination).as_posix()
                        actual.add(key)
                        info = path.lstat()
                        require(info.st_uid == os.geteuid(), "cached release ownership mismatch")
                        if key in directories:
                            require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o755,
                                    "cached release directory mismatch")
                        else:
                            require(key in hashes and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                                    "cached release entry mismatch")
                            mode = 0o755 if members[key].mode & 0o111 else 0o644
                            require(stat.S_IMODE(info.st_mode) == mode, "cached release mode mismatch")
                            with path.open("rb") as stream:
                                require(digest(stream) == hashes[key], "cached release checksum mismatch")
                require(actual == directories | hashes.keys(), "cached release contents mismatch")
                validate_templates(destination / root / "templates", DEFAULT_TEMPLATE)
                return {"release_dir": str(destination / root), "metadata": metadata, "changed": False}
            staging = Path(tempfile.mkdtemp(prefix=".openalert-", dir=destination.parent))
            try:
                for name in sorted(directories, key=lambda item: (item.count("/"), item)):
                    path = staging / name
                    path.mkdir(mode=0o755)
                    path.chmod(0o755)
                for name in hashes:
                    path = staging / name
                    with bundle.extractfile(members[name]) as source, path.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    path.chmod(0o755 if members[name].mode & 0o111 else 0o644)
                validate_templates(staging / root / "templates", DEFAULT_TEMPLATE)
                staging.chmod(0o755)
                require(not destination.is_symlink() and (not destination.exists()
                        or (empty_destination and not any(destination.iterdir()))), "destination already exists")
                staging.rename(destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
    return {"release_dir": str(destination / root), "metadata": metadata, "changed": True}


def ip(value):
    value = text(value)
    require("%" not in value, "scoped listeners are not supported")
    if value.lower() == "localhost":
        return "localhost"
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ContractError("listener must use an IP literal or localhost") from None
    return str(address.ipv4_mapped or address) if address.version == 6 else str(address)


def listener(host, port, protocol):
    require(type(port) is int and 1 <= port <= 65535, "invalid listener port")
    require(protocol in ("tcp", "udp"), "invalid listener protocol")
    return {"host": ip(host), "port": port, "protocol": protocol}


def socket_listener(value, protocol):
    value = text(value)
    match = re.fullmatch(r"(?:\[([^\]]+)\]|([^:]+)):([0-9]+)", value)
    require(match is not None, "invalid listener address")
    return listener(match[1] or match[2], int(match[3]), protocol)


def loopback(host):
    return host == "localhost" or ipaddress.ip_address(host).is_loopback


def overlaps(left, right):
    if left["port"] != right["port"] or left["protocol"] != right["protocol"]:
        return False
    a, b = left["host"], right["host"]
    if a == b or "::" in (a, b):
        return True  # Conservatively assume an IPv6 wildcard is dual-stack.
    if a == "localhost":
        return loopback(b) or b == "0.0.0.0"
    if b == "localhost":
        return loopback(a) or a == "0.0.0.0"
    return ipaddress.ip_address(a).version == ipaddress.ip_address(b).version and "0.0.0.0" in (a, b)


def listeners_contract(results):
    require(isinstance(results, list), "invalid listener input")
    listeners = []
    for result in results:
        records = table(result).get("listeners")
        require(isinstance(records, list), "invalid listener input")
        for record in records:
            record = table(record)
            current = listener(record.get("host"), record.get("port"), record.get("protocol"))
            require(not any(overlaps(current, other) for other in listeners), "listener conflict")
            listeners.append(current)
    return {"listeners": listeners}


def absolute_path(value):
    path = Path(text(str(value) if isinstance(value, Path) else value))
    require(path.is_absolute() and ".." not in path.parts, "absolute safe path required")
    return path


def state_path(value, state, directory=False):
    require(not text(value).startswith("file:"), "database URI escapes state path validation")
    path = Path(text(value))
    if not path.is_absolute():
        path = state / path
    require(".." not in path.parts and path.resolve().is_relative_to(state), "path escapes state directory")
    if path.exists():
        require(path.is_dir() if directory else path.is_file(), "invalid state path")
        if not directory:
            require(path.stat().st_nlink == 1, "linked file escapes state isolation")
        require(os.access(path, os.W_OK | (os.X_OK if directory else 0)), "state path is not writable")
    ancestor = path if directory else path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    require(ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK), "state directory is not writable")
    return path


def validate_state_data(state):
    directory = state_path("data", state, directory=True)
    if not directory.exists():
        return
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            require(not path.is_symlink(), "linked identity or database escapes state isolation")
            state_path(str(path), state, directory=name in dirs)


def readable_file(path):
    require(path.is_file() and os.access(path, os.R_OK), "required asset unavailable")


def validate_templates(directory, default_template):
    require(directory.is_dir() and os.access(directory, os.R_OK | os.X_OK), "templates unavailable")
    name = safe_member(text(default_template))
    target = directory / str(name)
    require(target.resolve().is_relative_to(directory), "template escapes template directory")
    readable_file(target)
    templates = list(directory.rglob("*.tera"))
    require(templates, "missing template assets")
    for path in templates:
        require(path.resolve().is_relative_to(directory), "template escapes template directory")
        readable_file(path)
        content = path.read_text(encoding="utf-8")
        for tag in re.findall(r"{%[-+]?\s*(?:include|extends|import)\s+(.+?)[-+]?%}", content, re.S):
            names = re.findall(r"[\"']([^\"']+)[\"']", tag)
            require(names, "dynamic template references are not supported")
            for reference in names:
                asset = directory / str(safe_member(reference))
                require(asset.resolve().is_relative_to(directory), "template escapes template directory")
                readable_file(asset)


def valid_hash(value):
    return isinstance(value, str) and bool(HEX.fullmatch(value.removeprefix("sha256:")))


def dashboard_auth(section):
    auth = table(section.get("auth", {}))
    enabled = flag(auth, "enabled")
    if enabled:
        require(valid_hash(auth.get("password_hash")) and bool(text(auth.get("username"))),
                "invalid dashboard authentication")
    return enabled


def rest_auth(rest):
    auth = table(rest.get("auth", {}))
    kind = auth.get("type", "none")
    require(isinstance(kind, str) and kind.lower() in ("none", "basic", "bearer"), "invalid REST authentication")
    kind = kind.lower()
    if kind == "basic":
        require(valid_hash(auth.get("password_hash")) and bool(text(auth.get("username"))), "invalid REST authentication")
    if kind == "bearer":
        require(valid_hash(auth.get("token_hash")), "invalid REST authentication")
    token = rest.get("auth_token")
    if token is not None:
        text(token)
    return kind != "none" or bool(token)


def validate_tls(section, state):
    tls = table(section.get("tls", {}))
    enabled = flag(tls, "enabled")
    if enabled:
        for key in ("cert_path", "key_path"):
            path = Path(text(tls.get(key)))
            readable_file(path if path.is_absolute() else state / path)
        if flag(tls, "require_client_cert"):
            path = Path(text(tls.get("client_ca_path")))
            readable_file(path if path.is_absolute() else state / path)
    return enabled


def validate_device(value, declared):
    path = absolute_path(value)
    require(str(path) in declared and str(path).startswith("/dev/"), "serial device is not declared")
    require(stat.S_ISCHR(path.stat().st_mode) and os.access(path, os.R_OK | os.W_OK), "serial device is inaccessible")


def config_contract(config, state_dir, templates_dir, health_url, capabilities,
                    device_paths, allow_unauthenticated_nonloopback, exposure_policy):
    require(not any(key.upper().startswith(("OPENALERT_", "OPENALERTD_")) for key in os.environ),
            "configuration environment overrides are not supported")
    capabilities = string_list(capabilities)
    require(all(re.fullmatch(r"CAP_[A-Z0-9_]+", item) for item in capabilities), "invalid capability declaration")
    device_paths = string_list(device_paths)
    for path in device_paths:
        absolute_path(path)
    require(type(allow_unauthenticated_nonloopback) is bool and isinstance(exposure_policy, str))
    exception = allow_unauthenticated_nonloopback and bool(exposure_policy.strip())
    require(not allow_unauthenticated_nonloopback or exception, "exposure exception requires policy")
    state = absolute_path(state_dir).resolve(strict=True)
    require(state.is_dir() and os.access(state, os.W_OK | os.X_OK), "state directory is not writable")
    with Path(config).open("rb") as stream:
        data = tomllib.load(stream)
    templates = table(data.get("templates", {}))
    expected = absolute_path(templates_dir).resolve(strict=True)
    configured = Path(text(templates.get("template_dir", "templates")))
    if not configured.is_absolute():
        configured = state / configured
    require(configured.resolve() == expected, "template directory mismatch")
    validate_templates(expected, templates.get("default_template", DEFAULT_TEMPLATE))
    # Identity and auxiliary databases use the daemon's relative data directory.
    validate_state_data(state)
    storage = table(data.get("storage", {}))
    if flag(storage, "enabled", True):
        path = text(storage.get("path", "data/openalert.db"))
        if path != ":memory:":
            state_path(path, state)
    rest = table(data.get("rest", {}))
    rest_listener = listener(rest.get("listen_host", "0.0.0.0"), rest.get("listen_port", 8090), "tcp")
    authenticated = rest_auth(rest)
    admin_authenticated = dashboard_auth(table(data.get("dashboard", {})))
    sos = table(data.get("sos", {}))
    sos_authenticated = dashboard_auth(sos)
    if not loopback(rest_listener["host"]):
        require((authenticated and admin_authenticated) or exception, "unprotected nonloopback HTTP exposure")
        require(not flag(sos, "enabled", True) or sos_authenticated or exception,
                "unprotected nonloopback SOS exposure")
    tls = validate_tls(rest, state)
    url = urlsplit(text(health_url))
    require(url.scheme == ("https" if tls else "http") and not url.username and not url.password
            and not url.query and not url.fragment and url.path in ("/health", "/api/v1/status"),
            "invalid health URL")
    health_host = ip(url.hostname)
    require(loopback(health_host) and (url.port or (443 if tls else 80)) == rest_listener["port"],
            "health URL does not match REST listener")
    health_listener = listener(health_host, rest_listener["port"], "tcp")
    require(overlaps(rest_listener, health_listener), "health URL does not match REST listener")
    listeners = [rest_listener]
    nostr = table(data.get("nostr", {}))
    relay = table(nostr.get("relay_server", {}))
    if flag(relay, "enabled"):
        current = socket_listener(relay.get("bind_address", "0.0.0.0:8088"), "tcp")
        require(loopback(current["host"]) or exception, "unprotected nonloopback relay exposure")
        validate_tls(relay, state)
        listeners.append(current)
    peering = table(data.get("peering", {}))
    if flag(peering, "enabled"):
        current = socket_listener(peering.get("listen_addr", "0.0.0.0:9876"), "udp")
        require(isinstance(peering.get("shared_key"), str) and HEX.fullmatch(peering["shared_key"]),
                "invalid peering key")
        listeners.append(current)
        sync = table(peering.get("time_sync", {}))
        if flag(sync, "enabled", True) and flag(sync, "step_system_clock", True):
            require("CAP_SYS_TIME" in capabilities, "clock stepping requires CAP_SYS_TIME")
        nodes = peering.get("nodes", [])
        require(isinstance(nodes, list))
        for node in nodes:
            node = table(node)
            if node.get("link_type") == "lora_serial":
                validate_device(node.get("serial_device"), device_paths)
    sms = table(data.get("sms", {}))
    if flag(sms, "enabled"):
        validate_device(sms.get("port", "/dev/ttyUSB2"), device_paths)
    bitchat = table(data.get("bitchat", {}))
    if flag(bitchat, "enabled"):
        require({"CAP_NET_ADMIN", "CAP_NET_RAW"} <= set(capabilities), "BLE requires explicit capabilities")
    return listeners_contract([{"listeners": listeners}])


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ContractError("invalid command arguments")


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        archive = commands.add_parser("archive")
        for option in ("archive", "sha256", "architecture", "destination"):
            archive.add_argument("--" + option, required=True)
        config = commands.add_parser("config")
        for option in ("config", "state-dir", "templates-dir", "health-url", "capabilities",
                       "device-paths", "allow-unauthenticated-nonloopback", "exposure-policy"):
            config.add_argument("--" + option, required=True)
        listeners = commands.add_parser("listeners")
        listeners.add_argument("--input", required=True)
        args = vars(parser.parse_args(argv))
        command = args.pop("command")
        if command == "archive":
            require(os.geteuid() == 0, "archive installation requires root")
            result = archive_contract(**args)
        elif command == "config":
            for key in ("capabilities", "device_paths"):
                args[key] = load_json(args[key])
            value = args["allow_unauthenticated_nonloopback"].lower()
            require(value in ("true", "false"), "invalid boolean argument")
            args["allow_unauthenticated_nonloopback"] = value == "true"
            result = config_contract(**args)
        else:
            result = listeners_contract(load_json(Path(args["input"]).read_text(encoding="utf-8")))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        # TOML, JSON, OS and argument errors may contain credentials or file contents.
        print('{"error": "deployment contract validation failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())