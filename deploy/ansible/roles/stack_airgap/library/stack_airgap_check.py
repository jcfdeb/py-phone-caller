#!/usr/bin/python
"""Read-only checks for the deliberately narrow signed-file APT backend."""

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tomllib
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def private_networks(networks, deny, allow):
    require(isinstance(networks, list), "airgap_networks must be a list of explicit CIDRs")
    ranges = [ipaddress.ip_network(value) for value in
              ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")]
    for value in networks:
        require(isinstance(value, str) and "/" in value and value == value.strip(),
                "Use canonical RFC1918/ULA CIDRs, not hostnames or systemd keywords")
        network = ipaddress.ip_network(value, strict=True)
        require(str(network) == value and any(network.version == block.version and
                                             network.subnet_of(block) for block in ranges),
                "Only RFC1918/ULA subnets are allowed; public and overbroad networks are forbidden")
    require(deny == ["any"] and allow == ["localhost", *networks],
            "Air-gapped service isolation must deny any and allow only localhost plus airgap_networks")


def safe_path(value):
    require(isinstance(value, str) and re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
            and ".." not in Path(value).parts and str(Path(value)) == value
            and value != "/", "Expected a safe absolute local path")
    return Path(value)


def relative_path(value):
    require(isinstance(value, str) and value and not value.startswith("/")
            and ".." not in value.split("/") and str(Path(value)) == value,
            "Manifest paths must be normalized relative paths")
    return value


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate manifest key")
        result[key] = value
    return result


def verify_manifest(root, manifest_path, checksum, root_owned=False):
    root = safe_path(str(root))
    manifest_path = safe_path(str(manifest_path))
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", checksum or ""), "Supply a trusted manifest SHA256")
    require(root.is_dir() and not root.is_symlink(), "Staged input directory is missing or symlinked")
    if root_owned:
        for parent in root.parents:
            info = parent.lstat()
            require(not parent.is_symlink() and info.st_uid == 0 and not info.st_mode & 0o022,
                    "Target bundle ancestors must be root-owned and not writable by other users")
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "Manifest is missing or symlinked")
    require(not manifest_path.is_relative_to(root), "Keep the manifest outside its inventoried tree")
    content = manifest_path.read_bytes()
    require(hashlib.sha256(content).hexdigest() == checksum[7:], "Manifest checksum mismatch")
    manifest = json.loads(content, object_pairs_hook=unique_object)
    require(isinstance(manifest, dict) and manifest.get("version") == 1, "Unsupported manifest version")
    files = manifest.get("files")
    links = manifest.get("symlinks", {})
    require(isinstance(files, dict) and files and isinstance(links, dict), "Manifest needs files and symlinks maps")
    require(not (files.keys() & links.keys()), "Manifest file/symlink overlap")
    for name, checksum_value in files.items():
        relative_path(name)
        require(isinstance(checksum_value, str) and re.fullmatch(r"[0-9a-f]{64}", checksum_value),
                "Every file needs a SHA256 digest")
    for name, target in links.items():
        relative_path(name)
        require(isinstance(target, str) and target and not target.startswith("/"),
                "Bundle symlinks must be relative and remain inside the tree")
    found_files, found_links = set(), set()
    paths = [root]
    for directory, directories, filenames in os.walk(root, followlinks=False):
        paths.extend(Path(directory) / name for name in directories + filenames)
    for path in paths:
        info = path.lstat()
        if root_owned:
            require(info.st_uid == 0 and (path.is_symlink() or not info.st_mode & 0o022),
                    "Target bundle must be root-owned and not group/world writable: " + str(path))
        name = str(path.relative_to(root))
        if path.is_symlink():
            require(name in links and os.readlink(path) == links[name], "Unlisted or altered symlink: " + name)
            resolved = path.resolve(strict=True)
            require(resolved.is_relative_to(root.resolve()), "Symlink escapes the staged tree: " + name)
            found_links.add(name)
        elif stat.S_ISREG(info.st_mode):
            require(name in files, "Unlisted file in staged tree: " + name)
            require(digest(path) == files[name], "Artifact checksum mismatch: " + name)
            found_files.add(name)
        else:
            require(stat.S_ISDIR(info.st_mode), "Special files are forbidden in staged inputs")
    require(found_files == set(files) and found_links == set(links), "Manifest lists missing artifacts")
    return manifest


def local_uri(value):
    parsed = urlsplit(value)
    require(parsed.scheme == "file" and not parsed.netloc and not parsed.query and not parsed.fragment,
            "Every active APT URI must use file:/absolute/path (no HTTP or remote authority)")
    path = safe_path(parsed.path)
    require(path.is_dir(), "Local signed APT mirror is missing: " + str(path))


def signed_by(value):
    path = safe_path(value)
    require(path.is_file(), "APT Signed-By must reference an existing local keyring")


def classic_sources(text):
    count = 0
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"(deb|deb-src)\s+(?:\[([^\]]+)\]\s+)?(\S+)\s+(\S+)(?:\s+(.+))?", line)
        require(match is not None, "Malformed classic APT source")
        options = {}
        for option in shlex.split(match[2] or ""):
            key, separator, value = option.partition("=")
            require(separator and key in ("signed-by", "arch") and key not in options,
                    "Unsupported/unsafe classic APT option: " + key)
            options[key] = value
        require("signed-by" in options, "Every APT source needs an explicit Signed-By keyring")
        signed_by(options["signed-by"])
        local_uri(match[3])
        count += 1
    return count


def deb822_sources(text):
    count = 0
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        fields = {}
        previous = None
        for line in paragraph.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[0].isspace():
                require(previous is not None, "Invalid deb822 continuation")
                fields[previous] += " " + line.strip()
                continue
            key, separator, value = line.partition(":")
            key = key.lower()
            require(separator and key not in fields, "Malformed or duplicate deb822 field")
            fields[key] = value.strip()
            previous = key
        if not fields:
            continue
        require(fields.get("enabled", "yes") in ("yes", "no"), "Invalid deb822 Enabled value")
        if fields.get("enabled") == "no":
            continue
        require(set(fields) <= {"types", "uris", "suites", "components", "architectures", "signed-by", "enabled"},
                "Unsupported/unsafe deb822 option")
        require(fields.get("types") and set(fields["types"].split()) <= {"deb", "deb-src"}
                and fields.get("uris") and fields.get("suites") and fields.get("signed-by"),
                "Incomplete signed deb822 source")
        signed_by(fields["signed-by"])
        for uri in fields["uris"].split():
            local_uri(uri)
            count += len(fields["types"].split())
    return count


def apt_configuration(text, environment):
    require(not environment.get("APT_CONFIG"), "APT_CONFIG overrides are forbidden")
    require(not any(value for key, value in environment.items() if key.lower().endswith("_proxy")),
            "Proxy environment is forbidden for air-gapped APT")
    expected = {"dir": "/", "dir::etc": "etc/apt", "dir::etc::sourcelist": "sources.list",
                "dir::etc::sourceparts": "sources.list.d", "dir::etc::main": "apt.conf",
                "dir::etc::parts": "apt.conf.d", "dir::bin::methods": "/usr/lib/apt/methods",
                "dir::bin::dpkg": "/usr/bin/dpkg", "dir::bin::gpg": "/usr/bin/gpg",
                "dir::bin::gpgv": "/usr/bin/gpgv"}
    for line in text.splitlines():
        match = re.fullmatch(r'([^\s]+)\s+"([^"\n]*)";', line.strip())
        require(match is not None, "Unrecognized apt-config dump syntax")
        key, value = match[1].lower(), match[2]
        require(key != "rootdir" and not key.startswith("rootdir::"), "APT RootDir overrides are forbidden")
        require(not any(word in key for word in ("proxy", "invoke", "pre-install", "post-install")),
                "APT proxies and executable hooks are forbidden")
        require(not any(word in key for word in ("allowinsecure", "allowweak", "allowdowngrade", "allowunauthenticated"))
                or value.lower() in ("0", "false", "no", ""), "APT signature checks must not be disabled")
        require(not key.endswith(("verify-peer", "verify-host", "check-valid-until", "check-date"))
                or value.lower() in ("1", "true", "yes"), "APT verification must remain enabled")
        if key in expected:
            require(value == expected[key], "APT path override is forbidden: " + key)
        elif key.startswith("dir::etc::"):
            require(key in ("dir::etc::preferences", "dir::etc::preferencesparts", "dir::etc::trusted",
                            "dir::etc::trustedparts", "dir::etc::netrc", "dir::etc::netrcparts"),
                    "Unknown APT configuration path override")
        elif key.startswith("dir::bin::"):
            paths = {
                "dir::bin::solvers": ("", "/usr/lib/apt/solvers"),
                "dir::bin::planners": ("", "/usr/lib/apt/planners"),
                "dir::bin::gzip": ("/bin/gzip", "/usr/bin/gzip"),
                "dir::bin::bzip2": ("/bin/bzip2", "/usr/bin/bzip2"),
                "dir::bin::xz": ("/bin/xz", "/usr/bin/xz"),
                "dir::bin::lz4": ("/bin/lz4", "/usr/bin/lz4"),
                "dir::bin::zstd": ("/bin/zstd", "/usr/bin/zstd"),
                "dir::bin::lzma": ("/bin/xz", "/usr/bin/xz", "/bin/lzma", "/usr/bin/lzma"),
            }
            require(key.rstrip(":") in paths and value in paths[key.rstrip(":")],
                    "Custom APT executables are forbidden")
        if key == "apt::solver":
            require(value in ("", "internal", "3.0"), "Custom APT/DPKG execution options are forbidden")
        else:
            require(not key.startswith(("apt::solver", "apt::planner", "dpkg::options", "apt::get::allow",
                                        "apt::key::gpg", "dpkg::tools::", "acquire::gpgv::options", "acquire::sqv::options"))
                    or value == "", "Custom APT/DPKG execution options are forbidden")


def verify_apt(root, configuration, environment):
    apt_configuration(configuration, environment)
    root = Path(root)
    count = 0
    sources = [root / "sources.list"]
    parts = root / "sources.list.d"
    if parts.exists():
        sources.extend(sorted(path for path in parts.iterdir() if path.suffix in (".list", ".sources")))
    for path in sources:
        if not path.exists():
            continue
        require(path.is_file() and not path.is_symlink(), "APT source entries must be regular files")
        count += (deb822_sources if path.suffix == ".sources" else classic_sources)(path.read_text())
    require(count > 0, "No active signed file: APT source found")
    return count


def verify_models(root, manifest, audio, engine, model_dir):
    base = "models/" + model_dir

    def present(name):
        relative_path(name)
        path = root / name
        require(path.is_file() and path.stat().st_size > 0 and
                (name in manifest["files"] or name in manifest.get("symlinks", {})),
                "Missing checksum-pinned model/preload asset: " + name)

    preload = audio.get("preload", {}).get(engine, [])
    require(isinstance(preload, list), "Selected engine preload must be a list")
    if engine == "kokoro_tts":
        require(audio.get("kokoro_model_filename") == "kokoro-v1_0.pth",
                "The Kokoro runner requires kokoro-v1_0.pth")
        present(base + "/config.json")
        present(base + "/kokoro-v1_0.pth")
        present(base + "/voices/af_heart.pt")
        require(audio.get("kokoro_lang") in ("a", "b", "e", "f", "h", "i", "p"),
                "Kokoro Japanese/Chinese auxiliary model caches are not qualified for this backend")
    else:
        language_key = {"piper_tts": "piper_language_code", "facebook_mms": "facebook_mms_language_code",
                        "silero_tts": "silero_lang"}[engine]
        languages = [audio.get(language_key, ""), *preload]
        for language in languages:
            require(isinstance(language, str) and re.fullmatch(r"[A-Za-z0-9_-]+", language),
                    "Invalid selected/preload language")
            if engine == "piper_tts":
                present(f"{base}/{language}/{language}.onnx")
                present(f"{base}/{language}/{language}.onnx.json")
            elif engine == "facebook_mms":
                directory = f"{base}/mms-tts-{language}"
                for name in ("config.json", "tokenizer_config.json", "vocab.json"):
                    present(directory + "/" + name)
                weights = (directory + "/model.safetensors", directory + "/pytorch_model.bin")
                require(any((root / name).is_file() for name in weights), "Missing MMS model weights")
                present(next(name for name in weights if (root / name).is_file()))
            else:
                require(language in ("en", "ru", "de", "es", "fr", "indic"), "Unsupported Silero language")
                filename = "v4_ru.pt" if language == "ru" else f"v3_{language}.pt"
                nested = f"{base}/{language}/{filename}"
                present(nested if (root / nested).is_file() else f"{base}/{filename}")


def verify_bundle(root, manifest, architecture, python_version, uv_version, toolchain, config, build_constraints):
    root = Path(root)
    require(architecture in ("x86_64", "aarch64") and manifest.get("architecture") == architecture,
            "Bundle architecture must match the supported target architecture")
    require(re.fullmatch(r"3\.14\.\d+", python_version) and manifest.get("python_version") == python_version,
            "Bundle must pin the configured Python 3.14 patch version")
    require(re.fullmatch(r"\d+\.\d+\.\d+", uv_version) and manifest.get("uv_version") == uv_version,
            "Bundle must pin the configured uv version")
    triple = "x86_64-unknown-linux-gnu" if architecture == "x86_64" else "aarch64-unknown-linux-gnu"
    require(re.fullmatch(r"\d+\.\d+\.\d+-" + triple, toolchain or ""), "Pin an exact architecture-matched Rust toolchain")
    required = ["bin/uv", "python/bin/python3.14", "cargo/bin/cargo", "cargo/bin/rustc",
                "rustup/toolchains/" + toolchain + "/bin/rustc", "build-constraints.txt"]
    require(config.get("caller_sms", {}).get("caller_sms_carrier") == "on_premise",
            "Air-gapped SMS requires caller_sms_carrier=on_premise; cloud carriers are forbidden")
    audio = config.get("generate_audio", {})
    engines = {"kokoro_tts": "kokoro_models_folder", "piper_tts": "piper_models_folder",
               "facebook_mms": "facebook_mms_models_folder", "silero_tts": "silero_models_folder"}
    engine = audio.get("tts_engine")
    require(engine in engines, "Air-gapped TTS requires a supported local engine, not a cloud provider")
    require(audio.get("pre_trained_models_folder") == str(root / "models"),
            "Set generate_audio.pre_trained_models_folder to the absolute bundle models directory")
    model_dir = relative_path(audio.get(engines[engine], ""))
    verify_models(root, manifest, audio, engine, model_dir)
    if engine == "kokoro_tts":
        required.append("wheels/en_core_web_sm-3.8.0-py3-none-any.whl")
    for name in required:
        require((root / name).is_file(), "Missing required bundle input: " + name)
    for name in required[:5]:
        require(os.access(root / name, os.X_OK), "Staged tool is not executable: " + name)
    for directory in ("uv-cache", "cargo", "rustup", "models/huggingface", "models/torch", "models/cache"):
        require((root / directory).is_dir(), "Missing staged cache directory: " + directory)
    constraints = (root / "build-constraints.txt").read_text().splitlines()
    pins = [line.strip() for line in constraints if line.strip() and not line.lstrip().startswith("#")]
    require(pins and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line) for line in pins),
            "Build constraints must contain only exact name==version pins")
    require(sorted(pins) == sorted(build_constraints),
            "Bundle build-constraints.txt must match the staged root pyproject.toml tool.uv.build-constraint-dependencies")


def source_build_constraints(root):
    with (Path(root) / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    pins = project.get("tool", {}).get("uv", {}).get("build-constraint-dependencies", [])
    require(isinstance(pins, list) and pins and
            all(isinstance(pin, str) and re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", pin) for pin in pins),
            "Staged root pyproject.toml needs exact tool.uv.build-constraint-dependencies pins; uv sync has no build-constraint CLI flag")
    return pins


def main():
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(argument_spec={
        "operation": {"choices": ["policy", "source", "target", "apt"], "required": True},
        "root": {"type": "path", "default": ""},
        "manifest_path": {"type": "path", "default": ""},
        "checksum": {"default": ""},
        "architecture": {"default": ""},
        "python_version": {"default": ""},
        "uv_version": {"default": ""},
        "toolchain": {"default": ""},
        "build_constraints": {"type": "list", "elements": "str", "default": []},
        "config": {"type": "dict", "default": {}, "no_log": True},
        "networks": {"type": "list", "elements": "str", "default": []},
        "deny": {"type": "list", "elements": "str", "default": []},
        "allow": {"type": "list", "elements": "str", "default": []},
    }, supports_check_mode=True)
    params = module.params
    try:
        if params["operation"] == "policy":
            private_networks(params["networks"], params["deny"], params["allow"])
        elif params["operation"] == "apt":
            apt_configuration("", os.environ)
            result = subprocess.run(["/usr/bin/apt-config", "dump"], check=True, capture_output=True, text=True)
            verify_apt("/etc/apt", result.stdout, os.environ)
        else:
            manifest = verify_manifest(params["root"], params["manifest_path"], params["checksum"],
                                       root_owned=params["operation"] == "target")
            if params["operation"] == "target":
                verify_bundle(params["root"], manifest, params["architecture"], params["python_version"],
                              params["uv_version"], params["toolchain"], params["config"], params["build_constraints"])
            else:
                required = ("pyproject.toml", "uv.lock", "src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.lock")
                require(all(name in manifest["files"] for name in required), "Source manifest must include workspace and Cargo lockfiles")
                module.exit_json(changed=False, build_constraints=source_build_constraints(params["root"]))
        module.exit_json(changed=False)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        module.fail_json(msg="Air-gap preflight: " + str(error))


if __name__ == "__main__":
    main()
