#!/usr/bin/env python3
"""Build and verify native .deb and .rpm packages for py-phone-caller and openalertd."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import tomllib


CANONICAL_SYSTEMD_SERVICES = (
    "asterisk-caller.service",
    "asterisk-recaller.service",
    "asterisk-ws-monitor.service",
    "caller-address-book.service",
    "caller-prometheus-webhook.service",
    "caller-register.service",
    "caller-scheduler.service",
    "caller-sms.service",
    "celery-worker.service",
    "generate-audio.service",
    "py-phone-caller-ui.service",
    "py-phone-caller.target",
)

WORKSPACE_DIRS = (
    "py-phone-caller-utils",
    "asterisk_caller",
    "asterisk_recaller",
    "asterisk_ws_monitor",
    "caller_address_book",
    "caller_prometheus_webhook",
    "caller_register",
    "caller_scheduler",
    "caller_sms",
    "celery_worker",
    "generate_audio",
    "py_phone_caller_ui",
)

ARCH_MAP = {
    "x86_64": ("amd64", "x86_64", 1),
    "amd64": ("amd64", "x86_64", 1),
    "aarch64": ("arm64", "aarch64", 19),
    "arm64": ("arm64", "aarch64", 19),
}


def ignore_source_junk(_directory: str, contents: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in contents:
        if (
            name in {"__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist", "pre_trained_models", "audio", "target"}
            or name.endswith(".egg-info")
            or name.startswith("Dockerfile")
            or name.endswith((".pyc", ".pyo", ".bak", ".orig"))
        ):
            ignored.add(name)
    return ignored


def stage_py_phone_caller_root(repo_root: Path, staging_root: Path) -> None:
    opt_dir = staging_root / "opt" / "py-phone-caller"
    etc_dir = staging_root / "etc" / "py-phone-caller"
    systemd_dir = staging_root / "lib" / "systemd" / "system"

    opt_dir.mkdir(parents=True, exist_ok=True)
    etc_dir.mkdir(parents=True, exist_ok=True)
    systemd_dir.mkdir(parents=True, exist_ok=True)

    for root_file in ("pyproject.toml", "uv.lock"):
        content = (repo_root / root_file).read_text(encoding="utf-8")
        translated = content.replace('"src/', '"py-phone-caller/').replace("'src/", "'py-phone-caller/")
        dst_file = opt_dir / root_file
        dst_file.write_text(translated, encoding="utf-8")
        dst_file.chmod(0o644)

    for root_file in ("README.md", "LICENSE"):
        shutil.copyfile(repo_root / root_file, opt_dir / root_file)

    for member in WORKSPACE_DIRS:
        shutil.copytree(
            repo_root / "src" / member,
            opt_dir / "py-phone-caller" / member,
            ignore=ignore_source_junk,
        )

    # Stage helper scripts
    for rel_script in (
        "assets/scripts/config/toml_to_dynaconf_env.py",
        "assets/scripts/nagios/nagios_event_handler_call.sh",
        "assets/scripts/zabbix/zabbix_alert_call.sh",
    ):
        src_script = repo_root / rel_script
        if src_script.is_file():
            dst_script = opt_dir / rel_script
            dst_script.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_script, dst_script)
            dst_script.chmod(0o755)

    # Bundle wheels if already built in dist/pypi
    pypi_dir = repo_root / "dist" / "pypi"
    if pypi_dir.is_dir():
        wheels = sorted(pypi_dir.glob("*.whl"))
        if wheels:
            wheels_dir = opt_dir / "wheels"
            wheels_dir.mkdir(parents=True, exist_ok=True)
            for whl in wheels:
                shutil.copyfile(whl, wheels_dir / whl.name)

    # Stage configuration files (never real .secrets.toml)
    shutil.copyfile(repo_root / "src" / "config" / "settings.toml", etc_dir / "settings.toml")
    (etc_dir / "settings.toml").chmod(0o640)
    secrets_example = etc_dir / ".secrets.toml.example"
    secrets_example.write_text(
        '[commons]\nasterisk_pass = "YOUR_ASTERISK_ARI_PASSWORD"\n\n'
        '[database]\ndb_password = "CHANGE_ME_STRONG_DB_PASSWORD"\n\n'
        '[caller_sms]\ntwilio_account_sid = ""\ntwilio_auth_token = ""\n\n'
        '[py_phone_caller_ui]\nui_secret_key = "YOUR_32_CHAR_RANDOM_SESSION_SECRET"\n'
        'ui_admin_password = "YOUR_ADMIN_PASSWORD"\n',
        encoding="utf-8",
    )
    secrets_example.chmod(0o600)

    prod_cfg_dir = opt_dir / "py-phone-caller" / "config"
    prod_cfg_dir.mkdir(parents=True, exist_ok=True)
    env_file = prod_cfg_dir / "py-phone-caller.env"
    env_file.write_text("CALLER_CONFIG_DIR=/etc/py-phone-caller\n", encoding="utf-8")
    env_file.chmod(0o644)

    # Stage canonical systemd units
    for unit_name in CANONICAL_SYSTEMD_SERVICES:
        src_unit = repo_root / "deploy" / "systemd" / "on-system" / unit_name
        if not src_unit.is_file():
            raise ValueError(f"Missing systemd unit: {src_unit}")
        dst_unit = systemd_dir / unit_name
        shutil.copyfile(src_unit, dst_unit)
        dst_unit.chmod(0o644)


def resolve_openalert_binary(repo_root: Path, explicit_binary: str | None) -> Path:
    if explicit_binary:
        path = Path(explicit_binary).resolve()
        if not path.is_file():
            raise ValueError(f"Specified --openalert-binary does not exist: {path}")
        return path

    candidates = [
        repo_root / "src" / "openalert" / "target" / "release" / "openalertd",
        repo_root / "src" / "openalert" / "dist" / "openalertd-v0.1.0-linux-x86_64" / "bin" / "openalertd",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand

    # Fallback: compile openalertd in release mode
    subprocess.run(
        ["cargo", "build", "--release"],
        cwd=repo_root / "src" / "openalert",
        check=True,
    )
    built = repo_root / "src" / "openalert" / "target" / "release" / "openalertd"
    if not built.is_file():
        raise ValueError("Failed to locate or build openalertd binary")
    return built


def stage_openalertd_root(repo_root: Path, staging_root: Path, binary_path: Path) -> None:
    bin_dir = staging_root / "usr" / "local" / "bin"
    etc_dir = staging_root / "etc" / "openalertd"
    profiles_dir = etc_dir / "profiles"
    share_dir = staging_root / "usr" / "share" / "openalertd"
    systemd_dir = staging_root / "lib" / "systemd" / "system"

    bin_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    share_dir.mkdir(parents=True, exist_ok=True)
    systemd_dir.mkdir(parents=True, exist_ok=True)

    dst_bin = bin_dir / "openalertd"
    shutil.copyfile(binary_path, dst_bin)
    dst_bin.chmod(0o755)

    crate_dir = repo_root / "src" / "openalert"
    pkg_dir = crate_dir / "packaging"

    shutil.copyfile(pkg_dir / "openalertd.toml.example", etc_dir / "openalertd.toml")
    (etc_dir / "openalertd.toml").chmod(0o640)

    for prof in sorted((crate_dir / "config" / "profiles").glob("*.toml")):
        shutil.copyfile(prof, profiles_dir / prof.name)
        (profiles_dir / prof.name).chmod(0o644)

    shutil.copytree(crate_dir / "templates", share_dir / "templates", ignore=ignore_source_junk)
    shutil.copytree(pkg_dir / "wifi-ap", share_dir / "wifi-ap", ignore=ignore_source_junk)

    shutil.copyfile(pkg_dir / "systemd" / "openalertd.service", systemd_dir / "openalertd.service")
    (systemd_dir / "openalertd.service").chmod(0o644)


def make_deterministic_tar_gz_bytes(root_dir: Path, prefix: str = ".") -> bytes:
    buf = io.BytesIO()

    def reset_info(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = 0
        ti.gid = 0
        ti.uname = "root"
        ti.gname = "root"
        ti.mtime = 0
        return ti

    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        with tarfile.open(mode="w", fileobj=gz, format=tarfile.GNU_FORMAT) as tf:
            for item in sorted(root_dir.rglob("*"), key=lambda p: p.relative_to(root_dir).as_posix()):
                rel = item.relative_to(root_dir).as_posix()
                arcname = f"{prefix}/{rel}" if prefix else rel
                tf.add(item, arcname=arcname, recursive=False, filter=reset_info)
    return buf.getvalue()


def pack_ar_member(name: str, data: bytes) -> bytes:
    header = (
        f"{name:<16}"
        f"{0:<12}"
        f"{0:<6}"
        f"{0:<6}"
        f"{'100644':<8}"
        f"{len(data):<10}"
        "`\n"
    ).encode("ascii")
    pad = b"\n" if (len(data) % 2 == 1) else b""
    return header + data + pad


def write_deb_package(
    data_root: Path,
    deb_meta_dir: Path,
    output_path: Path,
    pkg_name: str,
    version: str,
    release: str,
    deb_arch: str,
    depends: str,
    description: str,
) -> dict[str, object]:
    installed_kb = max(
        1,
        sum(p.stat().st_size for p in data_root.rglob("*") if p.is_file()) // 1024,
    )

    md5_lines: list[str] = []
    for fpath in sorted(data_root.rglob("*"), key=lambda p: p.relative_to(data_root).as_posix()):
        if fpath.is_file():
            rel = fpath.relative_to(data_root).as_posix()
            digest = hashlib.md5(fpath.read_bytes()).hexdigest()
            md5_lines.append(f"{digest}  {rel}")

    with tempfile.TemporaryDirectory(prefix=".deb-ctrl-") as tmp:
        ctrl_dir = Path(tmp)
        control_text = (
            f"Package: {pkg_name}\n"
            f"Version: {version}-{release}\n"
            f"Section: net\n"
            f"Priority: optional\n"
            f"Architecture: {deb_arch}\n"
            f"Installed-Size: {installed_kb}\n"
            f"Depends: {depends}\n"
            f"Maintainer: py-phone-caller contributors <admin@py-phone-caller.link>\n"
            f"Homepage: https://github.com/jcfdeb/py-phone-caller\n"
            f"Description: {description}\n"
        )
        (ctrl_dir / "control").write_text(control_text, encoding="utf-8")
        (ctrl_dir / "control").chmod(0o644)
        (ctrl_dir / "md5sums").write_text("\n".join(md5_lines) + "\n", encoding="utf-8")
        (ctrl_dir / "md5sums").chmod(0o644)

        for script_name in ("conffiles", "postinst", "prerm", "postrm"):
            src_script = deb_meta_dir / script_name
            if src_script.is_file():
                dst_script = ctrl_dir / script_name
                shutil.copyfile(src_script, dst_script)
                dst_script.chmod(0o644 if script_name == "conffiles" else 0o755)

        control_tar_gz = make_deterministic_tar_gz_bytes(ctrl_dir, prefix=".")

    data_tar_gz = make_deterministic_tar_gz_bytes(data_root, prefix=".")

    ar_bytes = (
        b"!<arch>\n"
        + pack_ar_member("debian-binary", b"2.0\n")
        + pack_ar_member("control.tar.gz", control_tar_gz)
        + pack_ar_member("data.tar.gz", data_tar_gz)
    )
    output_path.write_bytes(ar_bytes)
    sha256 = hashlib.sha256(ar_bytes).hexdigest()
    return {"filename": output_path.name, "sha256": sha256, "size": len(ar_bytes), "format": "deb"}


RPM_SYSTEM_DIRS = {
    "opt",
    "etc",
    "usr",
    "usr/local",
    "usr/local/bin",
    "usr/share",
    "lib",
    "lib/systemd",
    "lib/systemd/system",
}


def make_cpio_gz_payload(data_root: Path) -> tuple[bytes, bytes, list[dict[str, object]]]:
    """Create SVR4 New ASCII (070701) cpio.gz payload and return (compressed_bytes, uncompressed_bytes, file_records)."""
    raw_cpio = io.BytesIO()
    inode = 0
    file_records: list[dict[str, object]] = []

    def write_cpio_entry(rel_path: str, mode: int, content: bytes) -> int:
        nonlocal inode
        inode += 1
        name_bytes = f"./{rel_path}".encode("utf-8") + b"\x00"
        nlink = 2 if stat.S_ISDIR(mode) else 1
        filesize = 0 if stat.S_ISDIR(mode) else len(content)
        header = (
            "070701"
            f"{inode:08X}"
            f"{mode:08X}"
            f"{0:08X}"
            f"{0:08X}"
            f"{nlink:08X}"
            f"{0:08X}"
            f"{filesize:08X}"
            f"{0:08X}"
            f"{0:08X}"
            f"{0:08X}"
            f"{0:08X}"
            f"{len(name_bytes):08X}"
            f"{0:08X}"
        ).encode("ascii")
        raw_cpio.write(header)
        raw_cpio.write(name_bytes)
        header_plus_name = 110 + len(name_bytes)
        if header_plus_name % 4 != 0:
            raw_cpio.write(b"\x00" * (4 - (header_plus_name % 4)))
        if filesize > 0:
            raw_cpio.write(content)
            if filesize % 4 != 0:
                raw_cpio.write(b"\x00" * (4 - (filesize % 4)))
        return inode

    all_paths = sorted(data_root.rglob("*"), key=lambda p: "/" + p.relative_to(data_root).as_posix())
    for path in all_paths:
        rel = path.relative_to(data_root).as_posix()
        if path.is_dir() and rel in RPM_SYSTEM_DIRS:
            continue
        st_mode = path.stat().st_mode
        parent_posix = path.relative_to(data_root).parent.as_posix()
        dir_name = "/" if parent_posix == "." else f"/{parent_posix}/"
        base_name = path.name

        if path.is_dir():
            full_mode = stat.S_IFDIR | 0o755
            entry_inode = write_cpio_entry(rel, full_mode, b"")
            file_records.append(
                {
                    "dir_name": dir_name,
                    "base_name": base_name,
                    "size": 4096,
                    "mode": full_mode,
                    "digest": "",
                    "flags": 0,
                    "inode": entry_inode,
                }
            )
        elif path.is_file():
            perm = stat.S_IMODE(st_mode)
            full_mode = stat.S_IFREG | perm
            raw_bytes = path.read_bytes()
            entry_inode = write_cpio_entry(rel, full_mode, raw_bytes)
            is_config = rel.startswith("etc/")
            file_records.append(
                {
                    "dir_name": dir_name,
                    "base_name": base_name,
                    "size": len(raw_bytes),
                    "mode": full_mode,
                    "digest": hashlib.sha256(raw_bytes).hexdigest(),
                    "flags": 17 if is_config else 0,  # RPMFILE_CONFIG (1) | RPMFILE_NOREPLACE (16)
                    "inode": entry_inode,
                }
            )

    # Write TRAILER!!!
    trailer_name = b"TRAILER!!!\x00"
    trailer_header = (
        "070701"
        + ("00000000" * 4)
        + "00000001"
        + ("00000000" * 6)
        + f"{len(trailer_name):08X}"
        + "00000000"
    ).encode("ascii")
    raw_cpio.write(trailer_header)
    raw_cpio.write(trailer_name)
    if (110 + len(trailer_name)) % 4 != 0:
        raw_cpio.write(b"\x00" * (4 - ((110 + len(trailer_name)) % 4)))

    uncompressed = raw_cpio.getvalue()
    gz_buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=gz_buf, mtime=0) as gz:
        gz.write(uncompressed)
    return gz_buf.getvalue(), uncompressed, file_records


def build_rpm_header_section(entries: list[tuple[int, int, int, bytes]], region_tag: int) -> bytes:
    """Build an RPMv4 Header structure (\x8e\xad\xe8\x01) with an immutable region tag (62 or 63)."""
    entries_sorted = sorted(entries, key=lambda item: item[0])
    index_records: list[bytes] = []
    store = bytearray()

    for tag, dtype, count, value_bytes in entries_sorted:
        # Align int32 (type 4) to 4-byte boundary and int16 (type 3) to 2-byte boundary
        if dtype == 4 and (len(store) % 4 != 0):
            store.extend(b"\x00" * (4 - (len(store) % 4)))
        elif dtype == 3 and (len(store) % 2 != 0):
            store.extend(b"\x00")
        offset = len(store)
        store.extend(value_bytes)
        index_records.append(struct.pack("!IIII", tag, dtype, offset, count))

    total_tags = len(index_records) + 1
    trailer_offset = len(store)
    region_trailer = struct.pack("!iiii", region_tag, 7, -total_tags * 16, 16)
    store.extend(region_trailer)
    region_index = struct.pack("!IIII", region_tag, 7, trailer_offset, 16)

    all_index_records = [region_index, *index_records]
    header_intro = b"\x8e\xad\xe8\x01\x00\x00\x00\x00" + struct.pack("!II", len(all_index_records), len(store))
    return header_intro + b"".join(all_index_records) + bytes(store)


def write_rpm_package(
    data_root: Path,
    deb_meta_dir: Path,
    output_path: Path,
    pkg_name: str,
    version: str,
    release: str,
    rpm_arch: str,
    rpm_arch_num: int,
    summary: str,
    description: str,
) -> dict[str, object]:
    payload_gz, uncompressed_cpio, file_records = make_cpio_gz_payload(data_root)
    uncompressed_size = sum(int(r["size"]) for r in file_records)

    def str_tag(tag: int, val: str) -> tuple[int, int, int, bytes]:
        return (tag, 6, 1, val.encode("utf-8") + b"\x00")

    def i18n_str_tag(tag: int, val: str) -> tuple[int, int, int, bytes]:
        return (tag, 9, 1, val.encode("utf-8") + b"\x00")

    def str_array_tag(tag: int, vals: list[str]) -> tuple[int, int, int, bytes]:
        return (tag, 8, len(vals), b"".join(v.encode("utf-8") + b"\x00" for v in vals))

    def int32_tag(tag: int, val: int) -> tuple[int, int, int, bytes]:
        return (tag, 4, 1, struct.pack("!I", val))

    def int32_array_tag(tag: int, vals: list[int]) -> tuple[int, int, int, bytes]:
        return (tag, 4, len(vals), b"".join(struct.pack("!I", v & 0xFFFFFFFF) for v in vals))

    def int16_array_tag(tag: int, vals: list[int]) -> tuple[int, int, int, bytes]:
        return (tag, 3, len(vals), b"".join(struct.pack("!H", v & 0xFFFF) for v in vals))

    dir_names: list[str] = []
    dir_index_map: dict[str, int] = {}
    dir_indexes: list[int] = []
    base_names: list[str] = []
    file_sizes: list[int] = []
    file_modes: list[int] = []
    file_rdevs: list[int] = []
    file_mtimes: list[int] = []
    file_digests: list[str] = []
    file_linktos: list[str] = []
    file_flags: list[int] = []
    file_usernames: list[str] = []
    file_groupnames: list[str] = []
    file_verifyflags: list[int] = []
    file_devices: list[int] = []
    file_inodes: list[int] = []
    file_langs: list[str] = []

    for rec in file_records:
        dname = str(rec["dir_name"])
        if dname not in dir_index_map:
            dir_index_map[dname] = len(dir_names)
            dir_names.append(dname)
        dir_indexes.append(dir_index_map[dname])
        base_names.append(str(rec["base_name"]))
        file_sizes.append(int(rec["size"]))
        file_modes.append(int(rec["mode"]))
        file_rdevs.append(0)
        file_mtimes.append(0)
        file_digests.append(str(rec["digest"]))
        file_linktos.append("")
        file_flags.append(int(rec["flags"]))
        file_usernames.append("root")
        file_groupnames.append("root")
        file_verifyflags.append(0xFFFFFFFF)
        file_devices.append(1)
        file_inodes.append(int(rec["inode"]))
        file_langs.append("")

    postinst = (deb_meta_dir / "postinst").read_text(encoding="utf-8") if (deb_meta_dir / "postinst").is_file() else ""
    prerm = (deb_meta_dir / "prerm").read_text(encoding="utf-8") if (deb_meta_dir / "prerm").is_file() else ""
    postrm = (deb_meta_dir / "postrm").read_text(encoding="utf-8") if (deb_meta_dir / "postrm").is_file() else ""

    payload_sha256 = hashlib.sha256(payload_gz).hexdigest()
    payload_alt_sha256 = hashlib.sha256(uncompressed_cpio).hexdigest()

    main_entries: list[tuple[int, int, int, bytes]] = [
        str_array_tag(100, ["C"]),                      # HEADERI18NTABLE
        str_tag(1000, pkg_name),                        # NAME
        str_tag(1001, version),                         # VERSION
        str_tag(1002, release),                         # RELEASE
        i18n_str_tag(1004, summary),                    # SUMMARY
        i18n_str_tag(1005, description),                # DESCRIPTION
        int32_tag(1006, 0),                             # BUILDTIME
        str_tag(1007, "localhost"),                     # BUILDHOST
        int32_tag(1009, uncompressed_size),             # SIZE
        str_tag(1014, "BSD-3-Clause"),                  # LICENSE
        i18n_str_tag(1016, "System Environment/Daemons"),  # GROUP
        str_tag(1020, "https://github.com/jcfdeb/py-phone-caller"),  # URL
        str_tag(1021, "linux"),                         # OS
        str_tag(1022, rpm_arch),                        # ARCH
        int32_array_tag(1028, file_sizes),              # FILESIZES
        int16_array_tag(1030, file_modes),              # FILEMODES
        int16_array_tag(1033, file_rdevs),              # FILERDEVS
        int32_array_tag(1034, file_mtimes),             # FILEMTIMES
        str_array_tag(1035, file_digests),              # FILEDIGESTS
        str_array_tag(1036, file_linktos),              # FILELINKTOS
        int32_array_tag(1037, file_flags),              # FILEFLAGS
        str_array_tag(1039, file_usernames),            # FILEUSERNAME
        str_array_tag(1040, file_groupnames),           # FILEGROUPNAME
        int32_array_tag(1045, file_verifyflags),        # FILEVERIFYFLAGS
        str_array_tag(1047, [pkg_name]),                # PROVIDENAME
        str_tag(1064, "4.19.1"),                        # RPMVERSION
        int32_array_tag(1095, file_devices),            # FILEDEVICES
        int32_array_tag(1096, file_inodes),             # FILEINODES
        str_array_tag(1097, file_langs),                # FILELANGS
        int32_array_tag(1112, [8]),                     # PROVIDEFLAGS (RPMSENSE_EQUAL)
        str_array_tag(1113, [f"{version}-{release}"]),  # PROVIDEVERSION
        int32_array_tag(1116, dir_indexes),             # DIRINDEXES
        str_array_tag(1117, base_names),                # BASENAMES
        str_array_tag(1118, dir_names),                 # DIRNAMES
        str_tag(1124, "cpio"),                          # PAYLOADFORMAT
        str_tag(1125, "gzip"),                          # PAYLOADCOMPRESSOR
        str_tag(1126, "9"),                             # PAYLOADFLAGS
        str_tag(1132, f"{rpm_arch}-redhat-linux-gnu"),  # PLATFORM
        int32_tag(5011, 8),                             # FILEDIGESTALGO (SHA256)
        str_array_tag(5092, [payload_sha256]),          # PAYLOADDIGEST
        int32_tag(5093, 8),                             # PAYLOADDIGESTALGO (SHA256)
        str_array_tag(5097, [payload_alt_sha256]),      # PAYLOADDIGESTALT
    ]
    if postinst:
        main_entries.append(str_tag(1024, postinst))    # POSTIN
        main_entries.append(str_tag(1086, "/bin/sh"))   # POSTINPROG
    if prerm:
        main_entries.append(str_tag(1025, prerm))       # PREUN
        main_entries.append(str_tag(1087, "/bin/sh"))   # PREUNPROG
    if postrm:
        main_entries.append(str_tag(1026, postrm))      # POSTUN
        main_entries.append(str_tag(1088, "/bin/sh"))   # POSTUNPROG

    main_header = build_rpm_header_section(main_entries, region_tag=63)

    header_sha1 = hashlib.sha1(main_header).hexdigest()
    header_sha256 = hashlib.sha256(main_header).hexdigest()
    header_plus_payload = main_header + payload_gz
    md5_digest = hashlib.md5(header_plus_payload).digest()

    sig_entries: list[tuple[int, int, int, bytes]] = [
        str_tag(269, header_sha1),                      # SIG_SHA1
        str_tag(273, header_sha256),                    # SIG_SHA256
        int32_tag(1000, len(header_plus_payload)),      # SIG_SIZE
        (1004, 7, 16, md5_digest),                      # SIG_MD5 (BIN)
        int32_tag(1007, len(uncompressed_cpio)),        # SIG_PAYLOADSIZE
    ]
    sig_header = build_rpm_header_section(sig_entries, region_tag=62)
    if len(sig_header) % 8 != 0:
        sig_header += b"\x00" * (8 - (len(sig_header) % 8))

    full_name = f"{pkg_name}-{version}-{release}".encode("utf-8")[:65]
    full_name_padded = full_name + b"\x00" * (66 - len(full_name))
    lead = (
        b"\xed\xab\xee\xdb"
        + struct.pack("!BBHH", 3, 0, 0, rpm_arch_num)
        + full_name_padded
        + struct.pack("!HH", 1, 5)
        + (b"\x00" * 16)
    )
    assert len(lead) == 96

    rpm_bytes = lead + sig_header + main_header + payload_gz
    output_path.write_bytes(rpm_bytes)
    sha256 = hashlib.sha256(rpm_bytes).hexdigest()
    return {"filename": output_path.name, "sha256": sha256, "size": len(rpm_bytes), "format": "rpm"}


def build_all(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    linux_dir = Path(__file__).resolve().parent
    version = args.version or tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    release = args.release

    host_arch = args.arch or platform.machine()
    if host_arch not in ARCH_MAP:
        raise ValueError(f"Unsupported architecture {host_arch!r}; choose from {sorted(ARCH_MAP)}")
    deb_arch, rpm_arch, rpm_arch_num = ARCH_MAP[host_arch]

    out_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "dist" / "linux"
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise ValueError(f"Output directory {out_dir} is not empty; pass --force or a new --output-dir")

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.force:
        for existing in out_dir.glob("*"):
            if existing.is_file():
                existing.unlink()

    artifacts: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix=".linux-pkg-", dir=out_dir) as tmp:
        tmp_path = Path(tmp)

        # 1. Stage and build py-phone-caller (.deb + .rpm)
        ppc_stage = tmp_path / "py-phone-caller"
        stage_py_phone_caller_root(repo_root, ppc_stage)
        ppc_deb_meta = linux_dir / "deb" / "py-phone-caller"

        ppc_deb_path = out_dir / f"py-phone-caller_{version}-{release}_all.deb"
        artifacts.append(
            write_deb_package(
                data_root=ppc_stage,
                deb_meta_dir=ppc_deb_meta,
                output_path=ppc_deb_path,
                pkg_name="py-phone-caller",
                version=version,
                release=release,
                deb_arch="all",
                depends="bash, passwd | shadow-utils, systemd",
                description="Automated phone call and SMS alerting platform for Asterisk PBX",
            )
        )

        ppc_rpm_path = out_dir / f"py-phone-caller-{version}-{release}.noarch.rpm"
        artifacts.append(
            write_rpm_package(
                data_root=ppc_stage,
                deb_meta_dir=ppc_deb_meta,
                output_path=ppc_rpm_path,
                pkg_name="py-phone-caller",
                version=version,
                release=release,
                rpm_arch="noarch",
                rpm_arch_num=255,
                summary="Automated phone call and SMS alerting platform for Asterisk PBX",
                description="Automated phone call and SMS alerting platform for Asterisk PBX.",
            )
        )

        # 2. Stage and build openalertd (.deb + .rpm)
        oa_bin = resolve_openalert_binary(repo_root, args.openalert_binary)
        oa_stage = tmp_path / "openalertd"
        stage_openalertd_root(repo_root, oa_stage, oa_bin)
        oa_deb_meta = linux_dir / "deb" / "openalertd"

        oa_deb_path = out_dir / f"openalertd_{version}-{release}_{deb_arch}.deb"
        artifacts.append(
            write_deb_package(
                data_root=oa_stage,
                deb_meta_dir=oa_deb_meta,
                output_path=oa_deb_path,
                pkg_name="openalertd",
                version=version,
                release=release,
                deb_arch=deb_arch,
                depends="libc6, systemd, dbus",
                description="OpenAlert Daemon - Resilient Multi-Transport Alert Routing",
            )
        )

        oa_rpm_path = out_dir / f"openalertd-{version}-{release}.{rpm_arch}.rpm"
        artifacts.append(
            write_rpm_package(
                data_root=oa_stage,
                deb_meta_dir=oa_deb_meta,
                output_path=oa_rpm_path,
                pkg_name="openalertd",
                version=version,
                release=release,
                rpm_arch=rpm_arch,
                rpm_arch_num=rpm_arch_num,
                summary="OpenAlert Daemon - Resilient Multi-Transport Alert Routing",
                description="Decentralized Nostr NIP-ALERT, LoRa RF, BitChat BLE mesh, and USB GSM SMS gateway.",
            )
        )

    checksum_lines = [f"{item['sha256']}  {item['filename']}" for item in sorted(artifacts, key=lambda x: str(x["filename"]))]
    (out_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "version": version,
        "release": release,
        "deb_arch": deb_arch,
        "rpm_arch": rpm_arch,
        "packages": artifacts,
    }
    (out_dir / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(artifacts)} native Linux packages (.deb & .rpm) in {out_dir}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Package version (defaults to root pyproject.toml)")
    parser.add_argument("--release", default="1", help="Package release number (default: 1)")
    parser.add_argument("--arch", choices=sorted(ARCH_MAP), help="Target architecture for openalertd")
    parser.add_argument("--openalert-binary", help="Path to prebuilt openalertd ELF binary")
    parser.add_argument("--output-dir", help="Output directory (default: dist/linux)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output packages")
    args = parser.parse_args()
    try:
        build_all(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Linux package build error: {error}\n")


if __name__ == "__main__":
    main()
