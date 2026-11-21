#!/usr/bin/env python3
"""Export supplied artifacts on an explicitly authorized disposable builder only.

No downloads, Git operations, SSH, service changes, package installation or transfer.
Run with Python >= 3.11 on Debian 13 / Ubuntu 26.04, as root, after the parent
has joined the connected-build work and reviewed the input paths and checksums.

API: --acknowledge-disposable [--checker PATH] export --spec FILE (or - for stdin).
When transferring this helper alone, --checker must name the unchanged role validator.
The JSON object requires these keys:
  output_root, source_root, uv_binary, python_root, uv_cache, cargo_home,
  rustup_home, rust_toolchain, architecture, python_version, uv_version,
  build_constraints (list of exact name==version pins already in pyproject.toml),
  piper_model, piper_config, piper_model_sha256, piper_config_sha256, piper_language.
Optional model_caches maps huggingface/torch/cache to supplied directory paths.
output_root must not exist; its parent must be root-owned and non-writable by
others. Output: source/, py-phone-caller/, source-manifest.json,
bundle-manifest.json and fixture-vars.json. Transfer and revalidation are the
parent's responsibility. The final bundle path must be preserved on the target.

Source is a COMPLETE operator-sanitized release tree, not an installed app or
Git checkout. Do not include live settings, secrets, keys, venvs or Git metadata.
The path/content guards are defense in depth, NOT a general secret sanitizer.
uv_cache must be a relocatable, credential-free cache from the successful frozen
workspace AND pinned maturin build. cargo_home/rustup_home include the complete
locked registry, tool proxies and pinned toolchain; python_root is the standalone
runtime prefix (the directory containing bin/, lib/, etc.), not a virtualenv.
All symlinks must already be relative, non-dangling and internal to each input.

manifest --kind source|bundle --root DIR --output FILE [--spec FILE] inventories
an already prepared tree and calls the real role validator. Bundle mode requires
the export specification (including source_root for matching build pins).

apt --debs DIR --output-root DIR --signing-home DIR --signing-key FINGERPRINT
    --architecture amd64|arm64
uses predownloaded, operator-trusted .debs and an EXISTING ephemeral GPG home.
It exports only the selected public key; private keys never enter the mirror.
It creates a signed flat file: repository, a public keyring and a source snippet,
but does not configure APT or prove dependency closure on a fresh target.

Success means contract validation, NOT a qualified offline installation, cache
closure, authentic model inference, or enterprise/standard/Caddy parity.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys


SOURCE_REQUIRED = (
    "pyproject.toml", "uv.lock",
    "src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.lock",
)
SPEC_REQUIRED = {
    "output_root", "source_root", "uv_binary", "python_root", "uv_cache", "cargo_home",
    "rustup_home", "rust_toolchain", "architecture", "python_version", "uv_version",
    "build_constraints", "piper_model", "piper_config", "piper_model_sha256",
    "piper_config_sha256", "piper_language",
}
FORBIDDEN_PARTS = {
    ".git", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".venv",
    ".netrc", ".pypirc", "credentials", "credentials.toml", "credentials.json",
    "pyvenv.cfg", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_checker(path):
    spec = importlib.util.spec_from_file_location("fixture_airgap_contract", path)
    require(spec is not None and spec.loader is not None, "Cannot load the reviewed role validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authorize(acknowledged):
    require(acknowledged, "Explicit --acknowledge-disposable is required; never run on a controller/live host")
    release = platform.freedesktop_os_release()
    require((release.get("ID"), release.get("VERSION_ID")) in {("debian", "13"), ("ubuntu", "26.04")},
            "Only an authorized disposable Debian 13 / Ubuntu 26.04 builder is supported")
    require(os.geteuid() == 0, "Run locally as root on the acknowledged disposable builder")


def local_path(value):
    require(isinstance(value, str) and re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
            and ".." not in Path(value).parts and str(Path(value)) == value and value != "/",
            "Use normalized absolute local paths without spaces: " + str(value))
    path = Path(value)
    require(not any(parent.is_symlink() for parent in (path, *path.parents)),
            "Input/output path or ancestor is symlinked: " + value)
    return path


def guard_name(relative, source=False):
    parts = Path(relative).parts
    for part in parts:
        lower = part.lower()
        require(lower not in FORBIDDEN_PARTS and not lower.startswith((".env", ".secrets"))
                and not re.fullmatch(r"secrets?\.(toml|json|ya?ml)", lower)
                and not lower.endswith((".key", ".p12", ".pfx", ".kdbx")),
                "Secret/state path forbidden; supply a sanitized input: " + str(relative))
    if source:
        require(not any(part in ("venv", "__pycache__", "group_vars", "host_vars") for part in parts)
                and not (len(parts) >= 2 and parts[-2:] == ("config", "settings.toml")),
                "Live configuration/state path forbidden in source: " + str(relative))


def checked_digest(path):
    with path.open("rb") as stream:
        head = stream.read(65536)
        require(not re.search(rb"(?m)^[ \t]*-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[ \t\r]*$", head),
                "Private key material forbidden: " + str(path))
        stream.seek(0)
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root, source=False):
    root = local_path(str(root))
    require(root.is_dir(), "Missing input directory: " + str(root))
    files, links = {}, {}

    def failed_scan(error):
        raise error

    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=failed_scan):
        for name in sorted(directories + filenames):
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            guard_name(relative, source)
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(path)
                require(target and not target.startswith("/"), "Absolute symlink forbidden: " + relative)
                require(path.resolve(strict=True).is_relative_to(root), "Symlink escapes input: " + relative)
                links[relative] = target
            elif stat.S_ISREG(mode):
                files[relative] = checked_digest(path)
            else:
                require(stat.S_ISDIR(mode), "Special file forbidden: " + relative)
    return {"version": 1, "files": files, "symlinks": links}


def copy_file(source, destination):
    source, destination = Path(source), Path(destination)
    require(not any(path.is_symlink() for path in (source, *source.parents)),
            "Copy input or ancestor is symlinked: " + str(source))
    require(source.is_file(), "Missing regular input file: " + str(source))
    guard_name(source.name)
    checksum = checked_digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    destination.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
    require(checked_digest(destination) == checksum, "Input changed while copying: " + str(source))


def copy_tree(source, destination, source_tree=False):
    before = inventory(source, source=source_tree)
    require(not destination.exists(), "Refusing to replace staged tree: " + str(destination))
    shutil.copytree(source, destination, symlinks=True, copy_function=copy_file)
    for directory, directories, filenames in os.walk(destination, followlinks=False):
        Path(directory).chmod(0o755)
        for name in directories + filenames:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    require(inventory(destination, source=source_tree) == before,
            "Input changed during export; stop the connected build/cache writers and retry to a new root")


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
    path.chmod(0o644)


def source_pins(checker, root, manifest):
    require(all(name in manifest["files"] for name in SOURCE_REQUIRED),
            "Source must contain pyproject.toml, uv.lock and the native SMS Cargo.lock")
    return checker.source_build_constraints(root)


def model_config(bundle, specification):
    return {
        "caller_sms": {"caller_sms_carrier": "on_premise"},
        "generate_audio": {
            "tts_engine": "piper_tts", "pre_trained_models_folder": str(bundle / "models"),
            "piper_models_folder": "piper", "piper_language_code": specification["piper_language"],
            "preload": {"piper_tts": []},
        },
    }


def validate_manifest(checker, root, output, kind, specification=None):
    manifest = inventory(root, source=kind == "source")
    if kind == "source":
        source_pins(checker, root, manifest)
    else:
        require(specification is not None, "Bundle manifest requires --spec")
        manifest.update({key: specification[key] for key in ("architecture", "python_version", "uv_version")})
        pins = source_pins(checker, specification["source_root"],
                           inventory(specification["source_root"], source=True))
        require(sorted(pins) == sorted(specification["build_constraints"]), "Source/build constraints differ")
        checker.verify_bundle(root, manifest, specification["architecture"], specification["python_version"],
                              specification["uv_version"], specification["rust_toolchain"],
                              model_config(Path(root), specification), pins)
    output = local_path(str(output))
    require(not output.is_relative_to(Path(root)), "Manifest must be outside its inventoried tree")
    require(not output.exists(), "Refusing to overwrite manifest: " + str(output))
    write_json(output, manifest)
    checksum = "sha256:" + checker.digest(output)
    checker.verify_manifest(root, output, checksum, root_owned=kind == "bundle")
    return checksum


def read_spec(path):
    if path == "-":
        return json.load(sys.stdin)
    with local_path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def validate_inputs(specification, checker):
    require(isinstance(specification, dict), "Preparation specification must be a JSON object")
    missing = sorted(SPEC_REQUIRED - specification.keys())
    require(not missing, "Preparation checklist missing fields: " + ", ".join(missing))
    require(not (specification.keys() - SPEC_REQUIRED - {"model_caches"}), "Unknown preparation fields")
    require(specification["architecture"] in ("x86_64", "aarch64"), "Unsupported architecture")
    require(re.fullmatch(r"3\.14\.\d+", specification["python_version"]), "Pin Python 3.14 patch version")
    require(re.fullmatch(r"\d+\.\d+\.\d+", specification["uv_version"]), "Pin exact uv version")
    triple = specification["architecture"] + "-unknown-linux-gnu"
    require(re.fullmatch(r"\d+\.\d+\.\d+-" + triple, specification["rust_toolchain"]),
            "Pin exact architecture-matched Rust toolchain")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", specification["piper_language"]), "Invalid Piper voice/language name")
    roots = {key: local_path(specification[key]) for key in
             ("source_root", "python_root", "uv_cache", "cargo_home", "rustup_home")}
    missing_paths = [str(path) for path in roots.values() if not path.is_dir()]
    tools = [local_path(specification["uv_binary"]), roots["python_root"] / "bin/python3.14",
             roots["cargo_home"] / "bin/cargo", roots["cargo_home"] / "bin/rustc",
             roots["rustup_home"] / "toolchains" / specification["rust_toolchain"] / "bin/rustc"]
    missing_paths += [str(path) for path in tools if not path.is_file() or not os.access(path, os.X_OK)]
    for key in ("piper_model", "piper_config"):
        path = local_path(specification[key])
        if not path.is_file() or path.stat().st_size == 0:
            missing_paths.append(str(path))
    require(not missing_paths, "Preparation checklist missing directories/executable tools/models:\n- "
            + "\n- ".join(missing_paths))
    for key, path in roots.items():
        manifest = inventory(path, source=key == "source_root")
        require(manifest["files"], "Empty staged input: " + str(path))
    pins = source_pins(checker, roots["source_root"], inventory(roots["source_root"], source=True))
    require(isinstance(specification["build_constraints"], list)
            and sorted(specification["build_constraints"]) == sorted(pins),
            "Explicit build_constraints must match exact prepared pyproject.toml pins")
    for key in ("piper_model", "piper_config"):
        expected = specification[key + "_sha256"]
        require(isinstance(expected, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", expected),
                "Supply reviewed sha256: digest for " + key)
        require("sha256:" + checked_digest(Path(specification[key])) == expected,
                "Reviewed model checksum mismatch: " + key)
    with Path(specification["piper_config"]).open(encoding="utf-8") as stream:
        config = json.load(stream)
    require(isinstance(config, dict) and isinstance(config.get("audio"), dict)
            and isinstance(config["audio"].get("sample_rate"), int)
            and config["audio"]["sample_rate"] > 0, "Piper config needs an audio.sample_rate")
    caches = specification.get("model_caches", {})
    require(isinstance(caches, dict) and set(caches) <= {"huggingface", "torch", "cache"}, "Unknown model caches")
    for path in caches.values():
        inventory(path)
    return pins


def new_output(path, inputs):
    path = local_path(str(path))
    require(not path.exists(), "Refusing to overwrite output; choose a NEW output_root: " + str(path))
    require(path.parent.is_dir(), "Create a secure output parent on the disposable host first")
    for parent in path.parents:
        info = parent.lstat()
        require(info.st_uid == 0 and not info.st_mode & 0o022,
                "Output ancestors must be root-owned and not group/world writable: " + str(parent))
    for value in inputs:
        source = local_path(str(value))
        require(not path.is_relative_to(source) and not source.is_relative_to(path),
                "Output must not overlap an input: " + str(source))
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    return path


def stage_bundle(specification, bundle, pins):
    bundle.mkdir(mode=0o755)
    copy_file(Path(specification["uv_binary"]), bundle / "bin/uv")
    for key, name in (("python_root", "python"), ("uv_cache", "uv-cache"),
                      ("cargo_home", "cargo"), ("rustup_home", "rustup")):
        copy_tree(Path(specification[key]), bundle / name)
    (bundle / "build-constraints.txt").write_text("\n".join(pins) + "\n", encoding="utf-8")
    (bundle / "build-constraints.txt").chmod(0o644)
    language = specification["piper_language"]
    voice = bundle / "models/piper" / language / language
    for key, suffix in (("piper_model", ".onnx"), ("piper_config", ".onnx.json")):
        destination = voice.with_suffix(suffix)
        copy_file(Path(specification[key]), destination)
        require("sha256:" + checked_digest(destination) == specification[key + "_sha256"],
                "Reviewed model changed during export: " + key)
    for name in ("huggingface", "torch", "cache"):
        target = bundle / "models" / name
        if name in specification.get("model_caches", {}):
            copy_tree(Path(specification["model_caches"][name]), target)
        else:
            target.mkdir(mode=0o755)


def export_fixture(specification, checker):
    pins = validate_inputs(specification, checker)
    require(platform.machine() == specification["architecture"], "Builder/target architecture mismatch")
    inputs = [specification[key] for key in ("source_root", "uv_binary", "python_root", "uv_cache",
                                            "cargo_home", "rustup_home", "piper_model", "piper_config")]
    inputs.extend(specification.get("model_caches", {}).values())
    output = new_output(specification["output_root"], inputs)
    # Failure leaves a diagnosable, incomplete tree; fixture-vars.json is published last.
    source, bundle = output / "source", output / "py-phone-caller"
    copy_tree(Path(specification["source_root"]), source, source_tree=True)
    stage_bundle(specification, bundle, pins)
    source_manifest, bundle_manifest = output / "source-manifest.json", output / "bundle-manifest.json"
    source_checksum = validate_manifest(checker, source, source_manifest, "source")
    staged_specification = dict(specification, source_root=str(source))
    bundle_checksum = validate_manifest(checker, bundle, bundle_manifest, "bundle", staged_specification)
    variables = {
        "py_phone_caller_local_src_path": str(source), "py_phone_caller_git_repo": "",
        "py_phone_caller_airgap_bundle_dir": str(bundle),
        "py_phone_caller_airgap_manifest_path": str(bundle_manifest),
        "py_phone_caller_airgap_manifest_checksum": bundle_checksum,
        "py_phone_caller_airgap_source_manifest_path": str(source_manifest),
        "py_phone_caller_airgap_source_manifest_checksum": source_checksum,
        "py_phone_caller_airgap_rust_toolchain": specification["rust_toolchain"],
        "py_phone_caller_python_version": specification["python_version"],
        "py_phone_caller_uv_version": specification["uv_version"],
        "py_phone_caller_config": model_config(bundle, specification),
    }
    write_json(output / "fixture-vars.json", variables)
    return {"contract_validated": True, "offline_install_qualified": False,
            "variables": str(output / "fixture-vars.json")}


def run_command(argv, cwd=None, stdout=None):
    return subprocess.run(argv, cwd=cwd, stdout=stdout if stdout is not None else subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True,
                          env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})


def signing_commands(home, fingerprint, mirror, keyring):
    common = ["gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty",
              "--pinentry-mode", "error"]
    signer = common + ["--local-user", fingerprint + "!", "--digest-algo", "SHA256"]
    return [common + ["--output", str(keyring), "--export", fingerprint],
            signer + ["--output", str(mirror / "Release.gpg"), "--detach-sign", str(mirror / "Release")],
            signer + ["--output", str(mirror / "InRelease"), "--clearsign", str(mirror / "Release")]]


def prepare_apt(debs, output_root, signing_home, signing_key, architecture):
    require(architecture in ("amd64", "arm64"), "APT architecture must be amd64 or arm64")
    require(re.fullmatch(r"(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})", signing_key),
            "Supply the full ephemeral signing-key fingerprint, not an email/key ID")
    missing = [name for name in ("apt-ftparchive", "dpkg-deb", "gpg", "gpgv")
               if shutil.which(name, path="/usr/sbin:/usr/bin:/sbin:/bin") is None]
    require(not missing, "Missing local mirror tools (operator must prepare them): " + ", ".join(missing))
    debs, signing_home = local_path(debs), local_path(signing_home)
    info = signing_home.stat()
    require(signing_home.is_dir() and info.st_uid == 0 and not info.st_mode & 0o077,
            "Ephemeral signing home must be a private root-owned directory")
    manifest = inventory(debs)
    require(not manifest["symlinks"], "Supply regular trusted .deb files, not symlinks")
    packages = [debs / name for name in manifest["files"] if name.endswith(".deb")]
    require(packages, "No predownloaded trusted .deb files supplied; no download fallback")
    require(len({path.name for path in packages}) == len(packages), "Duplicate .deb basenames")
    for path in packages:
        require(re.fullmatch(r"[A-Za-z0-9_.+%:~-]+\.deb", path.name), "Unsafe .deb filename")
        actual = run_command(["dpkg-deb", "--field", str(path), "Architecture"]).stdout.decode().strip()
        require(actual in (architecture, "all"), "Wrong .deb architecture: " + str(path))
    output = new_output(output_root, [debs, signing_home])
    mirror = output / "mirror"
    pool = mirror / "pool"
    pool.mkdir(parents=True, mode=0o755)
    for path in sorted(packages):
        copy_file(path, pool / path.name)
    with (mirror / "Packages").open("xb") as stream:
        run_command(["apt-ftparchive", "packages", "pool"], cwd=mirror, stdout=stream)
    require((mirror / "Packages").stat().st_size, "apt-ftparchive produced an empty index")
    release = run_command(["apt-ftparchive", "-o", "APT::FTPArchive::Release::Origin=DisposableOfflineFixture",
                           "-o", "APT::FTPArchive::Release::Architectures=" + architecture,
                           "release", "."], cwd=mirror).stdout
    require(b"SHA256:" in release, "Release lacks SHA256 package-index digests")
    with (mirror / "Release").open("xb") as stream:
        stream.write(release)
    keyring = output / "fixture-archive-keyring.gpg"
    for argv in signing_commands(signing_home, signing_key, mirror, keyring):
        run_command(argv)
    require(keyring.is_file() and keyring.stat().st_size, "Public key export is empty")
    # An isolated verification home avoids consulting the operator's default keyrings.
    verification_home = output / "verification-home"
    verification_home.mkdir(mode=0o700)
    for signature in ("Release.gpg", "InRelease"):
        argv = ["gpgv", "--homedir", str(verification_home), "--keyring", str(keyring), str(mirror / signature)]
        if signature == "Release.gpg":
            argv.append(str(mirror / "Release"))
        run_command(argv)
    for directory, directories, filenames in os.walk(output):
        Path(directory).chmod(0o700 if Path(directory) == verification_home else 0o755)
        for name in filenames:
            (Path(directory) / name).chmod(0o644)
    source = f"deb [arch={architecture} signed-by={keyring}] file:{mirror} ./\n"
    (output / "fixture.list").write_text(source, encoding="utf-8")
    (output / "fixture.list").chmod(0o644)
    result = {"mirror": str(mirror), "keyring": str(keyring), "source_list": str(output / "fixture.list"),
              "public_key_sha256": "sha256:" + checked_digest(keyring), "signing_fingerprint": signing_key,
              "signatures_verified": True, "dependency_closure_qualified": False}
    write_json(output / "apt-result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--acknowledge-disposable", action="store_true")
    parser.add_argument("--checker", default=str((Path(__file__).resolve().parent
                                                / "../../deploy/ansible/roles/stack_airgap/library/stack_airgap_check.py").resolve()))
    commands = parser.add_subparsers(dest="command", required=True)
    exporter = commands.add_parser("export", help="Copy and validate supplied artifacts; never download")
    exporter.add_argument("--spec", required=True)
    manifest = commands.add_parser("manifest", help="Inventory a prepared source or target bundle")
    manifest.add_argument("--kind", choices=("source", "bundle"), required=True)
    manifest.add_argument("--root", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--spec")
    apt = commands.add_parser("apt", help="Sign a local mirror of predownloaded trusted packages")
    apt.add_argument("--debs", required=True)
    apt.add_argument("--output-root", required=True)
    apt.add_argument("--signing-home", required=True)
    apt.add_argument("--signing-key", required=True)
    apt.add_argument("--architecture", choices=("amd64", "arm64"), required=True)
    args = parser.parse_args(argv)
    try:
        authorize(args.acknowledge_disposable)
        sys.dont_write_bytecode = True
        os.umask(0o022)
        if args.command == "apt":
            result = prepare_apt(args.debs, args.output_root, args.signing_home, args.signing_key, args.architecture)
        else:
            checker = load_checker(local_path(args.checker))
            if args.command == "export":
                result = export_fixture(read_spec(args.spec), checker)
            else:
                checksum = validate_manifest(checker, local_path(args.root), local_path(args.output), args.kind,
                                             read_spec(args.spec) if args.spec else None)
                result = {"manifest": args.output, "checksum": checksum,
                          "contract_validated": True, "offline_install_qualified": False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("Fixture preparation failed: " + str(error)
              + "\nNo offline-install qualification. Fix the supplied inputs; partial output is not reusable.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())