"""Unit and contract tests for the Taskfile AppSec & Supply-Chain pipeline."""

from __future__ import annotations

import datetime
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_taskfile_structure_and_shell_safety():
    taskfile_path = REPO_ROOT / "Taskfile.yml"
    assert taskfile_path.is_file(), "Root Taskfile.yml must exist"

    data = yaml.safe_load(taskfile_path.read_text(encoding="utf-8"))
    assert str(data["version"]) == "3"
    assert set(data.get("set", [])) >= {"errexit", "nounset", "pipefail"}

    vars_cfg = data.get("vars", {})
    assert vars_cfg.get("RUST_MANIFEST") == "src/openalert/Cargo.toml"
    assert vars_cfg.get("RUST_LOCK") == "src/openalert/Cargo.lock"
    assert (REPO_ROOT / vars_cfg["RUST_MANIFEST"]).is_file()
    assert (REPO_ROOT / vars_cfg["RUST_LOCK"]).is_file()

    tasks = data.get("tasks", {})
    expected_tasks = {
        "sec:init",
        "sec:doctor",
        "sec:hooks:install",
        "sec:fast",
        "sec:ci",
        "sec:release",
        "sec:secrets:staged",
        "sec:secrets:history",
        "sec:sast:fast",
        "sec:sast:py",
        "sec:sast:rust",
        "sec:sast:full",
        "sec:sca:py",
        "sec:sca:rust",
        "sec:sca:osv",
        "sec:sca:all",
        "sec:iac",
        "sec:sbom",
        "sec:image",
        "sec:image:core",
        "sec:image:all",
        "sec:dast",
        "sec:sign:release",
        "sec:fix:py",
        "sec:fix:rust",
    }
    missing = expected_tasks - set(tasks.keys())
    assert not missing, f"Missing Taskfile tasks: {sorted(missing)}"

    # Advisory tasks must NEVER cache via `sources:` so newly published CVEs are caught
    for sca_task in ("sec:sca:py", "sec:sca:rust", "sec:sca:osv", "sec:sca:all"):
        assert "sources" not in tasks[sca_task], f"{sca_task} must not cache via sources:"

    # Python SCA must export all workspace members without editable local lines
    py_sca_cmds = " ".join(tasks["sec:sca:py"]["cmds"])
    assert "--all-packages" in py_sca_cmds
    assert "--no-emit-workspace" in py_sca_cmds
    assert "--no-deps" in py_sca_cmds
    assert "--disable-pip" in py_sca_cmds


def test_uv_export_workspace_coverage():
    """Ensure uv export --all-packages --no-emit-workspace covers production packages cleanly."""
    proc = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--all-packages",
            "--no-emit-workspace",
            "--no-dev",
            "--no-hashes",
            "--format",
            "requirements-txt",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    pkg_lines = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(pkg_lines) >= 150, f"Expected >=150 workspace prod packages, got {len(pkg_lines)}"
    assert not any(line.startswith("-e ") for line in pkg_lines), "Editable workspace lines must be excluded"


def test_deny_toml_policy_contract():
    deny_path = REPO_ROOT / "deny.toml"
    assert deny_path.is_file()
    cfg = tomllib.loads(deny_path.read_text(encoding="utf-8"))

    triples = {t["triple"] for t in cfg["graph"]["targets"]}
    assert triples == {"x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"}
    assert cfg["advisories"]["yanked"] == "deny"
    assert cfg["sources"]["unknown-registry"] == "deny"
    assert cfg["sources"]["unknown-git"] == "deny"
    assert "GPL-3.0-only" not in cfg["licenses"]["allow"]


    for item in cfg["advisories"].get("ignore", []):
        assert isinstance(item, dict) and item.get("id", "").startswith("RUSTSEC-"), (
            f"deny.toml ignore entry must be a structured RUSTSEC table: {item}"
        )
        assert "Expires " in item.get("reason", "") and len(item["reason"]) >= 30, (
            f"deny.toml ignore {item.get('id')} must document expiration date and rationale"
        )

    osv_cfg = tomllib.loads((REPO_ROOT / "osv-scanner.toml").read_text(encoding="utf-8"))
    today = datetime.datetime.now(tz=datetime.UTC).date()
    ignored_vulns = osv_cfg.get("IgnoredVulns", [])
    assert ignored_vulns, "osv-scanner.toml must define explicit baseline entries"
    for vuln in ignored_vulns:
        vid = vuln.get("id", "")
        until = vuln.get("ignoreUntil")
        reason = vuln.get("reason", "")
        assert not vid.startswith("PYSEC-"), f"Python advisories ({vid}) must be fixed in uv.lock, not ignored"
        assert isinstance(until, datetime.date) and until > today, (
            f"osv-scanner.toml ignore {vid} is missing or past ignoreUntil ({until} <= {today})"
        )
        assert len(reason.strip()) >= 25, f"osv-scanner.toml ignore {vid} must document engineering rationale"


def test_trivyignore_governance_invariants():
    trivy_path = REPO_ROOT / ".trivyignore.yaml"
    assert trivy_path.is_file()
    cfg = yaml.safe_load(trivy_path.read_text(encoding="utf-8"))

    today = datetime.datetime.now(tz=datetime.UTC).date()
    entries = cfg.get("misconfigurations", [])
    assert entries, ".trivyignore.yaml should contain documented baseline entries"
    for entry in entries:
        rule_id = entry.get("id")
        paths = entry.get("paths")
        exp = entry.get("expired_at")
        stmt = entry.get("statement", "")
        assert rule_id and rule_id.startswith("AVD-"), f"Invalid rule id: {rule_id}"
        assert isinstance(paths, list) and len(paths) > 0, f"{rule_id} must be path-scoped, never global"
        exp_date = datetime.date.fromisoformat(exp) if isinstance(exp, str) else exp
        assert isinstance(exp_date, datetime.date) and exp_date > today, (
            f"{rule_id} expired_at must be a valid future date, got {exp}"
        )
        assert len(stmt.strip()) >= 20, f"{rule_id} must include an engineering rationale statement"


def test_gitleaks_and_mise_configs_valid():
    gitleaks_cfg = tomllib.loads((REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert gitleaks_cfg["extend"]["useDefault"] is True

    mise_cfg = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    tools = mise_cfg.get("tools", {})
    for required in ("task", "gitleaks", "trufflehog", "osv-scanner", "trivy", "syft", "cosign", "cargo-deny"):
        assert required in tools, f"Missing {required} in mise.toml"


def test_pyproject_security_lint_and_gitignore_contracts():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "S" in pyproject["tool"]["ruff"]["lint"]["extend-select"]

    # High-risk injection rules must never be suppressed on production src/ code
    per_file = pyproject["tool"]["ruff"]["lint"]["per-file-ignores"]
    forbidden_prod_ignores = {"S608", "S602", "S301", "S307", "S102", "S506"}
    for pattern, ignored_rules in per_file.items():
        if pattern.startswith("src/") and "tests" not in pattern:
            overlap = forbidden_prod_ignores & set(ignored_rules)
            assert not overlap, f"High-risk rules {overlap} must not be ignored in {pattern}"

    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/.security-reports/" in gitignore
    assert "/.task/" in gitignore


def test_github_appsec_workflow_and_legacy_retirement():
    workflow_path = REPO_ROOT / ".github" / "workflows" / "appsec.yml"
    assert workflow_path.is_file()
    wf = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert "appsec" in wf["jobs"]

    steps = wf["jobs"]["appsec"]["steps"]
    sarif_steps = [s for s in steps if "codeql-action/upload-sarif@" in s.get("uses", "")]
    assert sarif_steps and sarif_steps[0]["uses"].endswith("@v4"), "Must use codeql-action/upload-sarif@v4"

    artifact_steps = [s for s in steps if "actions/upload-artifact@" in s.get("uses", "")]
    assert artifact_steps and artifact_steps[0].get("with", {}).get("include-hidden-files") is True, (
        "upload-artifact must set include-hidden-files: true so .security-reports/ dot-directory is uploaded"
    )

    for retired in ("bandit-scan.yml", "codeql-analysis.yml", "shiftleft-analysis.yml"):
        assert not (REPO_ROOT / ".github" / "workflows" / retired).exists(), f"Legacy {retired} should be retired"


def test_non_regression_verify_tasks_and_transactional_rollback():
    data = yaml.safe_load((REPO_ROOT / "Taskfile.yml").read_text(encoding="utf-8"))
    tasks = data["tasks"]
    for verify_task in ("verify:smoke", "verify:py", "verify:rust", "verify:all"):
        assert verify_task in tasks, f"Missing non-regression guardrail task: {verify_task}"

    for fix_task in ("sec:fix:py", "sec:fix:rust"):
        script = " ".join(tasks[fix_task]["cmds"])
        assert "trap rollback ERR" in script, f"{fix_task} must auto-rollback lockfile on test failure"

    py_fix_script = " ".join(tasks["sec:fix:py"]["cmds"])
    assert "uv sync --frozen --all-packages --inexact" in py_fix_script, (
        "sec:fix:py must pass --all-packages --inexact so virtual workspace members and native rust_engine remain installed"
    )
    assert (REPO_ROOT / data["vars"]["SMS_RUST_LOCK"]).is_file()

    guide_path = REPO_ROOT / "docs" / "appsec-and-supply-chain-guide.md"
    assert guide_path.is_file(), "Contributor AppSec onboarding guide must exist"
    assert "appsec-and-supply-chain-guide.md" in (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "appsec-and-supply-chain-guide.md" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_workspace_service_entrypoints_importable(monkeypatch):
    """Smoke check that core workspace packages import without breaking."""
    import importlib

    monkeypatch.setenv("CALLER_CONFIG", str(REPO_ROOT / "src" / "config" / "settings.toml"))
    monkeypatch.setenv("ENABLE_TELEMETRY", "false")
    monkeypatch.setenv("UI_ADMIN_PASSWORD_RESETED", "True")
    monkeypatch.setenv("PICCOLO_CONF", "py_phone_caller_utils.py_phone_caller_db.piccolo_conf")

    for mod in (
        "py_phone_caller_utils",
        "asterisk_caller.asterisk_caller",
        "asterisk_recaller.asterisk_recaller",
        "asterisk_ws_monitor.asterisk_ws_monitor",
        "caller_address_book.caller_address_book",
        "caller_prometheus_webhook.caller_prometheus_webhook",
        "caller_register.caller_register",
        "caller_scheduler.caller_scheduler",
        "caller_sms.caller_sms",
        "celery_worker",
        "py_phone_caller_ui",
    ):
        assert importlib.import_module(mod) is not None


def _resolve_real_tool(tool_name: str) -> str:
    """Resolve the direct binary path for a CLI tool (bypassing mise shims when HOME is overridden)."""
    import os
    import shutil

    mise_bin = shutil.which("mise") or str(Path.home() / ".local" / "bin" / "mise")
    if Path(mise_bin).is_file():
        proc = subprocess.run(
            [mise_bin, "which", tool_name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            resolved = proc.stdout.strip().splitlines()[0]
            if Path(resolved).is_file():
                return resolved

    extra_path = os.pathsep.join(
        [
            str(Path.home() / ".local" / "share" / "mise" / "shims"),
            str(Path.home() / ".local" / "bin"),
            str(Path.home() / ".cargo" / "bin"),
            os.environ.get("PATH", ""),
        ]
    )
    found = shutil.which(tool_name, path=extra_path)
    if not found:
        import pytest

        pytest.skip(f"{tool_name} binary is not installed in this environment")
    return found


def _write_executable(path: Path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)


def test_sec_fix_py_transactional_auto_rollback_and_happy_path_in_sandbox(tmp_path):
    """Prove at runtime that sec:fix:py restores uv.lock & re-syncs on test failure, and commits on pass."""
    import os
    import shutil

    task_bin = _resolve_real_tool("task")
    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
    shutil.copy2(REPO_ROOT / "Taskfile.yml", sandbox / "Taskfile.yml")

    original_lock = "# original locked graph v1\naiohttp==3.11.0\n"
    upgraded_lock = "# upgraded locked graph v2\naiohttp==3.14.0\n"
    lock_file = sandbox / "uv.lock"
    lock_file.write_text(original_lock, encoding="utf-8")

    fake_home = tmp_path / "fake_home"
    fake_bin = fake_home / ".local" / "bin"
    invocations_log = tmp_path / "invocations.log"

    _write_executable(
        fake_bin / "uv",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "uv $*" >> "{invocations_log}"
if [ "${{1:-}}" = "lock" ] && [ "${{2:-}}" = "--upgrade-package" ]; then
  printf '%s' "{upgraded_lock}" > uv.lock
  exit 0
fi
if [ "${{1:-}}" = "sync" ]; then
  cp uv.lock .synced_state
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "task",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "subtask $*" >> "{invocations_log}"
if [ "${{1:-}}" = "verify:py" ] && [ "${{FAIL_VERIFY_PY:-0}}" = "1" ]; then
  echo "Simulated pytest regression!" >&2
  exit 1
fi
exit 0
""",
    )

    base_env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    # 1. Failure scenario: verify:py fails -> uv.lock and .synced_state MUST roll back to original_lock
    failed_run = subprocess.run(
        [task_bin, "sec:fix:py", "PKG=aiohttp"],
        cwd=sandbox,
        env={**base_env, "FAIL_VERIFY_PY": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed_run.returncode != 0, "sec:fix:py must exit non-zero when tests fail"
    combined_err = failed_run.stdout + failed_run.stderr
    assert "[ROLLBACK]" in combined_err
    assert lock_file.read_text(encoding="utf-8") == original_lock, "uv.lock was NOT restored after test failure!"
    assert (sandbox / ".synced_state").read_text(encoding="utf-8") == original_lock, (
        "rollback() must re-run uv sync so .venv matches the restored uv.lock"
    )
    assert not (sandbox / ".security-reports" / "uv.lock.bak").exists()

    log_lines = invocations_log.read_text(encoding="utf-8").splitlines()
    sync_calls = [line for line in log_lines if line == "uv sync --frozen --all-packages --inexact"]
    assert len(sync_calls) == 2, f"Expected 2 --all-packages --inexact sync calls (upgrade + rollback), got {log_lines}"

    # 2. Happy-path scenario: verify:smoke & verify:py pass -> upgraded uv.lock is kept cleanly
    invocations_log.unlink()
    ok_run = subprocess.run(
        [task_bin, "sec:fix:py", "PKG=aiohttp"],
        cwd=sandbox,
        env={**base_env, "FAIL_VERIFY_PY": "0"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok_run.returncode == 0, f"Expected pass on clean verification, got: {ok_run.stderr}"
    assert lock_file.read_text(encoding="utf-8") == upgraded_lock
    assert not (sandbox / ".security-reports" / "uv.lock.bak").exists()


def test_sec_fix_rust_transactional_auto_rollback_on_test_and_policy_failures(tmp_path):
    """Prove at runtime that sec:fix:rust restores Cargo.lock on either test failure or cargo-deny violation."""
    import os
    import shutil

    task_bin = _resolve_real_tool("task")
    sandbox = tmp_path / "workspace"
    rust_dir = sandbox / "src" / "openalert"
    rust_dir.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "Taskfile.yml", sandbox / "Taskfile.yml")
    (sandbox / "deny.toml").write_text("[advisories]\nversion = 2\n", encoding="utf-8")
    (rust_dir / "Cargo.toml").write_text('[package]\nname = "openalertd"\nversion = "1.0.0"\n', encoding="utf-8")

    original_cargo_lock = '# original Cargo.lock v1\nname = "rustls"\nversion = "0.23.1"\n'
    upgraded_cargo_lock = '# upgraded Cargo.lock v2\nname = "rustls"\nversion = "0.23.46"\n'
    cargo_lock = rust_dir / "Cargo.lock"
    cargo_lock.write_text(original_cargo_lock, encoding="utf-8")
    upgraded_fixture = tmp_path / "upgraded_Cargo.lock"
    upgraded_fixture.write_text(upgraded_cargo_lock, encoding="utf-8")

    fake_bin = tmp_path / "fake_bin"

    _write_executable(
        fake_bin / "cargo",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = "update" ]; then
  cp "{upgraded_fixture}" "{cargo_lock}"
  exit 0
fi
if [ "${{1:-}}" = "deny" ]; then
  if [ "${{FAIL_CARGO_DENY:-0}}" = "1" ]; then
    echo "Banned GPL-3.0 license detected!" >&2
    exit 1
  fi
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "task",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "verify:rust" ] && [ "${FAIL_VERIFY_RUST:-0}" = "1" ]; then
  echo "Simulated cargo test failure!" >&2
  exit 1
fi
exit 0
""",
    )

    base_env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    # Case A: verify:rust fails -> Cargo.lock rolls back
    res_test_fail = subprocess.run(
        [task_bin, "sec:fix:rust", "PKG=rustls"],
        cwd=sandbox,
        env={**base_env, "FAIL_VERIFY_RUST": "1", "FAIL_CARGO_DENY": "0"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert res_test_fail.returncode != 0
    assert "[ROLLBACK]" in (res_test_fail.stdout + res_test_fail.stderr)
    assert cargo_lock.read_text(encoding="utf-8") == original_cargo_lock

    # Case B: verify:rust passes, but cargo-deny policy check fails -> Cargo.lock STILL rolls back
    res_deny_fail = subprocess.run(
        [task_bin, "sec:fix:rust", "PKG=rustls"],
        cwd=sandbox,
        env={**base_env, "FAIL_VERIFY_RUST": "0", "FAIL_CARGO_DENY": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert res_deny_fail.returncode != 0
    assert "[ROLLBACK]" in (res_deny_fail.stdout + res_deny_fail.stderr)
    assert cargo_lock.read_text(encoding="utf-8") == original_cargo_lock

    # Case C: Both pass -> upgraded Cargo.lock is preserved and backup is cleaned up
    res_ok = subprocess.run(
        [task_bin, "sec:fix:rust", "PKG=rustls"],
        cwd=sandbox,
        env={**base_env, "FAIL_VERIFY_RUST": "0", "FAIL_CARGO_DENY": "0"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert res_ok.returncode == 0, f"Expected pass, got: {res_ok.stderr}"
    assert cargo_lock.read_text(encoding="utf-8") == upgraded_cargo_lock
    assert not (sandbox / ".security-reports" / "Cargo.lock.bak").exists()


def test_ruff_s_canary_catches_injected_vulnerabilities_under_real_config(tmp_path):
    """Negative canary test: verify root pyproject.toml Ruff S config catches SQLi, shell=True, pickle, YAML, eval."""
    canary_src = (
        "import pickle\n"
        "import subprocess\n"
        "import yaml\n\n"
        "def insecure_handler(user_id: str, raw_blob: bytes, cmd: str):\n"
        '    query = f"SELECT * FROM calls WHERE id = \'{user_id}\'"\n'
        "    subprocess.Popen(cmd, shell=True)\n"
        "    obj = pickle.loads(raw_blob)\n"
        "    cfg = yaml.load(user_id, Loader=yaml.Loader)\n"
        "    res = eval(user_id)\n"
        "    return query, obj, cfg, res\n"
    )

    proc = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "ruff",
            "check",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
            "--select",
            "S",
            "--stdin-filename",
            str(REPO_ROOT / "src" / "caller_register" / "_canary_vuln_probe.py"),
            "-",
        ],
        cwd=REPO_ROOT,
        input=canary_src,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "Ruff S must fail on injected production vulnerabilities"
    for expected_code in ("S608", "S602", "S301", "S506", "S307"):
        assert expected_code in proc.stdout, f"Expected {expected_code} to be flagged, got:\n{proc.stdout}"

    # Verify clean parameterized counterpart passes with exit code 0
    clean_src = (
        "async def safe_lookup(db_table, call_id: str):\n"
        '    return await db_table.raw("SELECT * FROM calls WHERE id = {}", call_id)\n'
    )
    clean_proc = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "ruff",
            "check",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
            "--select",
            "S",
            "--stdin-filename",
            str(REPO_ROOT / "src" / "caller_register" / "_canary_safe_probe.py"),
            "-",
        ],
        cwd=REPO_ROOT,
        input=clean_src,
        check=False,
        capture_output=True,
        text=True,
    )
    assert clean_proc.returncode == 0, f"Clean code should pass Ruff S, got:\n{clean_proc.stdout}"


def test_gitleaks_and_sec_fast_canary_block_staged_secret_and_redact_output(tmp_path):
    """Negative canary test: run real gitleaks + real 'task sec:fast' in an isolated git repo."""
    import os
    import shutil

    gitleaks_bin = _resolve_real_tool("gitleaks")
    task_bin = _resolve_real_tool("task")

    repo = tmp_path / "canary_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "test").mkdir()
    (repo / "tests").mkdir()
    (repo / "deploy").mkdir()
    shutil.copy2(REPO_ROOT / ".gitleaks.toml", repo / ".gitleaks.toml")
    shutil.copy2(REPO_ROOT / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy2(REPO_ROOT / "Taskfile.yml", repo / "Taskfile.yml")

    # Provide lightweight shim for `uv` that delegates `uv run ruff ...` to the existing workspace ruff binary offline
    shim_bin = tmp_path / "shim_bin"
    ruff_bin = REPO_ROOT / ".venv" / "bin" / "ruff"
    _write_executable(
        shim_bin / "uv",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = "run" ] && [ "${{2:-}}" = "ruff" ]; then
  shift 2
  exec "{ruff_bin}" "$@"
fi
exec "{shutil.which('uv') or '/home/jcf/.local/bin/uv'}" "$@"
""",
    )
    canary_env = {
        **os.environ,
        "PATH": os.pathsep.join(
            [
                str(shim_bin),
                str(Path(gitleaks_bin).parent),
                str(Path(task_bin).parent),
                os.environ.get("PATH", ""),
            ]
        ),
    }

    for git_args in (
        ["init", "-q"],
        ["config", "user.email", "canary@example.invalid"],
        ["config", "user.name", "Canary Test"],
    ):
        subprocess.run(["git", *git_args], cwd=repo, check=True, capture_output=True)

    # 1. Stage a clean Python module -> 'task sec:fast' must PASS
    target_py = repo / "src" / "service.py"
    target_py.write_text('def ok() -> str:\n    return "healthy"\n', encoding="utf-8")
    (repo / "test" / "t.py").write_text("assert True\n", encoding="utf-8")
    (repo / "tests" / "t.py").write_text("assert True\n", encoding="utf-8")
    (repo / "deploy" / "d.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)

    clean_fast = subprocess.run(
        [task_bin, "sec:fast"],
        cwd=repo,
        env=canary_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert clean_fast.returncode == 0, f"Clean staged repo must pass sec:fast:\n{clean_fast.stdout}\n{clean_fast.stderr}"

    # 2. Stage a Vulnerable Python file (eval -> S307) -> 'task sec:fast' MUST block via Ruff S
    target_py.write_text("def bad(x: str):\n    return eval(x)\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/service.py"], cwd=repo, check=True, capture_output=True)
    sast_blocked_fast = subprocess.run(
        [task_bin, "sec:fast"],
        cwd=repo,
        env=canary_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert sast_blocked_fast.returncode != 0, "task sec:fast must fail when Ruff S detects S307"
    assert "S307" in (sast_blocked_fast.stdout + sast_blocked_fast.stderr)

    # 3. Stage a dynamically constructed GitHub Personal Access Token -> gitleaks & sec:fast MUST block and redact
    synthetic_pat = "ghp_" + ("A9b8C7d6E5f4G3h2I1j0K9l8M7n6O5p4Q3r2")
    target_py.write_text(f'API_TOKEN = "{synthetic_pat}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "src/service.py"], cwd=repo, check=True, capture_output=True)

    leak_check = subprocess.run(
        [
            gitleaks_bin,
            "protect",
            "--staged",
            "--config",
            ".gitleaks.toml",
            "--redact",
            "--no-banner",
        ],
        cwd=repo,
        env=canary_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert leak_check.returncode != 0, "Gitleaks must block staged secret token"
    leak_output = leak_check.stdout + leak_check.stderr
    assert synthetic_pat not in leak_output, "Gitleaks --redact must never print raw secret value to logs"

    blocked_fast = subprocess.run(
        [task_bin, "sec:fast"],
        cwd=repo,
        env=canary_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked_fast.returncode != 0, "task sec:fast must fail when a secret is staged"


def test_dockerignore_and_release_ghcr_workflows_contract():
    """Ensure Docker build contexts block local secrets and release/GHCR workflows cover all 12 images."""
    import xml.etree.ElementTree as ET

    root_ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for required_rule in ("**/.secrets.toml", "**/*.local.toml", "**/.env", "**/.vault_pass*"):
        assert required_rule in root_ignore, f"Root .dockerignore must exclude {required_rule}"

    oa_ignore = (REPO_ROOT / "src" / "openalert" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for required_rule in ("config/*.local.toml", "**/*.local.toml", "**/.secrets*", "**/.env*"):
        assert required_rule in oa_ignore, f"src/openalert/.dockerignore must exclude {required_rule}"

    rel_wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release-packaging.yml").read_text(encoding="utf-8"))
    rel_steps_blob = str(rel_wf["jobs"]["build-and-verify-packages"]["steps"])
    for expected in ("libdbus-1-dev", "libudev-dev", "--all-packages", "--openalert-binary", "SBOM.cdx.json"):
        assert expected in rel_steps_blob, f"release-packaging.yml missing {expected}"

    ghcr_wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "container-images.yml").read_text(encoding="utf-8"))
    assert ghcr_wf["permissions"].get("packages") == "write"
    matrix_items = ghcr_wf["jobs"]["build-and-push"]["strategy"]["matrix"]["include"]
    services = {item["service"] for item in matrix_items}
    expected_services = {
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
        "openalertd",
    }
    assert services == expected_services
    for item in matrix_items:
        assert (REPO_ROOT / item["dockerfile"]).is_file(), f"Missing Dockerfile: {item['dockerfile']}"

    svg_path = REPO_ROOT / "docs" / "assets" / "live-signal-flow.svg"
    assert svg_path.is_file(), "Animated signal-flow SVG must exist"
    root_el = ET.fromstring(svg_path.read_text(encoding="utf-8"))  # noqa: S314
    assert root_el.tag.endswith("svg")
    assert "docs/assets/live-signal-flow.svg" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")



