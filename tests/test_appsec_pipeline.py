"""Unit and contract tests for the Taskfile AppSec & Supply-Chain pipeline."""

from __future__ import annotations

import datetime
from pathlib import Path
import subprocess
import tomllib

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


def test_trivyignore_governance_invariants():
    trivy_path = REPO_ROOT / ".trivyignore.yaml"
    assert trivy_path.is_file()
    cfg = yaml.safe_load(trivy_path.read_text(encoding="utf-8"))

    entries = cfg.get("misconfigurations", [])
    assert entries, ".trivyignore.yaml should contain documented baseline entries"
    for entry in entries:
        rule_id = entry.get("id")
        paths = entry.get("paths")
        exp = entry.get("expired_at")
        stmt = entry.get("statement", "")
        assert rule_id and rule_id.startswith("AVD-"), f"Invalid rule id: {rule_id}"
        assert isinstance(paths, list) and len(paths) > 0, f"{rule_id} must be path-scoped, never global"
        assert isinstance(exp, (datetime.date, str)) and str(exp), f"{rule_id} must define expired_at"
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

