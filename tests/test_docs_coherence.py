"""Automated repository coherence tests: unified versioning, governance files, and zero broken links."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from html.parser import HTMLParser
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, val in attrs:
            if val and key in {"href", "src"}:
                self.links.append(val)


class RepositoryCoherenceTests(unittest.TestCase):
    def test_unified_version_parity_across_manifests_and_pages(self) -> None:
        root_ver = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        self.assertRegex(root_ver, r"^\d+\.\d+\.\d+$")

        # 1. All 12 workspace Python packages + PyPI meta-package
        for p in sorted((REPO_ROOT / "src").glob("*/pyproject.toml")):
            pkg_ver = tomllib.loads(p.read_text(encoding="utf-8"))["project"]["version"]
            self.assertEqual(pkg_ver, root_ver, f"Version drift in {p}")

        meta_toml_path = REPO_ROOT / "deploy/packaging/pypi/meta_package/pyproject.toml"
        meta_toml_raw = meta_toml_path.read_text(encoding="utf-8")
        meta_toml = tomllib.loads(meta_toml_raw)
        self.assertEqual(meta_toml["project"]["version"], root_ver)
        self.assertNotIn("==1.0.0", meta_toml_raw)

        meta_init = (REPO_ROOT / "deploy/packaging/pypi/meta_package/py_phone_caller/__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{root_ver}"', meta_init)

        # 2. Rust crates (openalertd + rust_engine)
        for cargo_rel in (
            "src/openalert/Cargo.toml",
            "src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.toml",
        ):
            cargo_ver = tomllib.loads((REPO_ROOT / cargo_rel).read_text(encoding="utf-8"))["package"]["version"]
            self.assertEqual(cargo_ver, root_ver, f"Version drift in {cargo_rel}")

        # 3. Helm Chart.yaml & values.yaml + Taskfile.yml
        chart = yaml.safe_load((REPO_ROOT / "deploy/helm/py-phone-caller/Chart.yaml").read_text(encoding="utf-8"))
        values = yaml.safe_load((REPO_ROOT / "deploy/helm/py-phone-caller/values.yaml").read_text(encoding="utf-8"))
        self.assertEqual(str(chart["version"]), root_ver)
        self.assertEqual(str(chart["appVersion"]), root_ver)
        self.assertEqual(str(values["global"]["imageTag"]), root_ver)

        taskfile_raw = (REPO_ROOT / "Taskfile.yml").read_text(encoding="utf-8")
        self.assertIn(f'default "{root_ver}"', taskfile_raw)

        # 4. Both GitHub Pages landing pages reflect current version and zero external Google Fonts
        for html_rel in ("docs/index.html", "docs/openalert/index.html"):
            html_text = (REPO_ROOT / html_rel).read_text(encoding="utf-8")
            self.assertIn(f"v{root_ver}", html_text, f"{html_rel} missing v{root_ver}")
            self.assertNotIn("v0.2.0", html_text, f"{html_rel} still mentions stale v0.2.0")
            self.assertNotIn("fonts.googleapis.com", html_text, f"{html_rel} must not load Google Fonts CDN")

    def test_governance_license_and_sanitized_config_files_exist(self) -> None:
        required_files = (
            "LICENSE",
            "CHANGELOG.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "CITATION.cff",
            "mkdocs.yml",
            "deploy/pages/build_pages.py",
            "deploy/pages/export_openapi.py",
            "deploy/dashboards/prometheus-alerting-rules.yml",
            "docs/404.html",
            "docs/assets/og-py-phone-caller.png",
            "docs/openalert/og-openalert.png",
            "docs/quickstart-5-minutes.md",
            "docs/api-explorer.md",
            "docs/hardware-and-field-kit-bom.md",
            "docs/sre-day2-operations-and-watchdog.md",
            "docs/asterisk-pbx-configuration-guide.md",
            ".github/FUNDING.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/pull_request_template.md",
            ".github/workflows/pages.yml",
            ".github/workflows/ci.yml",
            "src/openalert/LICENSE-MIT",
            "src/openalert/LICENSE-APACHE",
            "src/openalert/config/openalertd.toml",
        )
        for rel in required_files:
            self.assertTrue((REPO_ROOT / rel).is_file(), f"Missing required file: {rel}")
        self.assertFalse((REPO_ROOT / ".github/workflows/FUNDING.yml").exists())

        oa_cfg = (REPO_ROOT / "src/openalert/config/openalertd.toml").read_text(encoding="utf-8")
        self.assertNotIn("0039", oa_cfg, "Sanitized openalertd.toml must not contain personal phone numbers")

        # Validate CITATION.cff version parity & YAML validity of Issue templates and Prometheus rules
        root_ver = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        cff = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        self.assertEqual(str(cff["version"]), root_ver)
        for yml_rel in (
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            "deploy/dashboards/prometheus-alerting-rules.yml",
        ):
            parsed = yaml.safe_load((REPO_ROOT / yml_rel).read_text(encoding="utf-8"))
            self.assertIsInstance(parsed, dict, f"Invalid YAML object in {yml_rel}")

    def test_zero_broken_relative_links_across_markdown_and_landing_pages(self) -> None:
        tracked = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True).splitlines()
        md_files = sorted({REPO_ROOT / f for f in tracked if f.endswith(".md") and (REPO_ROOT / f).is_file()})
        for extra_md in (
            "CHANGELOG.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            ".github/pull_request_template.md",
            "docs/asterisk-pbx-configuration-guide.md",
            "docs/quickstart-5-minutes.md",
            "docs/api-explorer.md",
            "docs/hardware-and-field-kit-bom.md",
            "docs/sre-day2-operations-and-watchdog.md",
        ):
            md_files.append(REPO_ROOT / extra_md)

        broken: list[str] = []
        for md in sorted(set(md_files)):
            raw = md.read_text(encoding="utf-8", errors="replace")
            stripped = re.sub(r"```.*?```|~~~.*?~~~", "", raw, flags=re.DOTALL)
            for match in MD_LINK_RE.finditer(stripped):
                target = match.group(1).strip().split()[0]
                if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:", "javascript:", "lightning:")):
                    continue
                path_part = target.split("#")[0].split("?")[0]
                if not path_part:
                    continue
                resolved = (md.parent / path_part).resolve()
                if not resolved.exists():
                    broken.append(f"{md.relative_to(REPO_ROOT)} -> {target}")
                    continue
                if resolved.is_relative_to(REPO_ROOT):
                    ign = subprocess.run(
                        ["git", "check-ignore", "-q", str(resolved.relative_to(REPO_ROOT))],
                        cwd=REPO_ROOT,
                        check=False,
                    )
                    if ign.returncode == 0:
                        broken.append(f"{md.relative_to(REPO_ROOT)} -> {target} (points to gitignored path)")

        # Validate landing page relative href/src links (allowing `manual/...` and `../manual/...` built into _site/)
        for html_rel in ("docs/index.html", "docs/openalert/index.html"):
            html_file = REPO_ROOT / html_rel
            raw_html = html_file.read_text(encoding="utf-8")
            self.assertIn("og:image", raw_html, f"{html_rel} missing OpenGraph og:image tag")
            self.assertIn("twitter:image", raw_html, f"{html_rel} missing Twitter card image tag")
            self.assertNotIn("hero-wave.svg", raw_html.split("</head>")[0], f"{html_rel} must use PNG for og:image")
            parser = _HrefParser()
            parser.feed(raw_html)
            for link in parser.links:
                if not link or link.startswith(("#", "http://", "https://", "mailto:", "tel:", "javascript:", "data:")):
                    continue
                clean = link.split("#")[0].split("?")[0]
                if not clean or clean.startswith(("manual/", "../manual/")):
                    continue
                resolved = (html_file.parent / clean).resolve()
                if not resolved.exists():
                    broken.append(f"{html_rel} -> {link}")

        self.assertEqual(broken, [], "Broken relative links found:\n  " + "\n  ".join(broken))

    def test_mkdocs_commonmark_normalizer_and_rendered_manual_formatting(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "deploy" / "pages"))
        try:
            import build_pages  # type: ignore[import-not-found]
        finally:
            sys.path.pop(0)

        sample_md = (
            "OpenAlert provides a portal:\n"
            "* **Item One:** Details (`GET /a` $\\rightarrow$ `POST /b`)\n"
            "  - **Subitem:** Nested details\n"
            "Operators have 2 options:\n"
            "1. **First:**\n"
            "   ```http request\n"
            "   POST /test\n"
            "   ```\n"
            "2. **Second:** Done\n"
        )
        normalized = build_pages.normalize_commonmark_for_mkdocs(sample_md)
        self.assertIn("portal:\n\n* **Item One:**", normalized)
        self.assertIn("→", normalized)
        self.assertNotIn("$\\rightarrow$", normalized)
        self.assertIn("\n    - **Subitem:**", normalized)
        self.assertIn("options:\n\n1. **First:**", normalized)
        self.assertIn("    ```http\n", normalized)

        # Ensure source manual Markdown files contain zero raw LaTeX arrow/relation commands outside code
        manual_sources = [
            p
            for p in sorted((REPO_ROOT / "docs").rglob("*.md"))
            if p.relative_to(REPO_ROOT / "docs").parts[:2] != ("openalert", "dist")
        ] + sorted((REPO_ROOT / "deploy" / "docs").rglob("*.md"))
        for md in manual_sources:
            stripped = re.sub(r"```.*?```|~~~.*?~~~|`[^`\n]+`", "", md.read_text(encoding="utf-8"), flags=re.DOTALL)
            self.assertIsNone(
                re.search(r"\$\\(?:rightarrow|leftarrow|leftrightarrow|longleftrightarrow|to|ge|le|in|cdot)\b", stripped),
                f"Unrendered LaTeX command left in {md.relative_to(REPO_ROOT)}",
            )

        # If _site/manual has been built locally, verify zero unrendered bullets, fences, alerts, checkboxes, or 'None' nav tabs
        manual_dir = REPO_ROOT / "_site" / "manual"
        if manual_dir.is_dir():
            root_manual_html = (manual_dir / "index.html").read_text(encoding="utf-8")
            nav_tabs = [
                " ".join(re.sub(r"<[^>]+>", " ", m.group(0)).split())
                for m in re.finditer(r'<li class="md-tabs__item[^"]*">.*?</li>', root_manual_html, flags=re.DOTALL)
            ]
            self.assertNotIn("None", nav_tabs, f"Unexpected 'None' tab in top navigation: {nav_tabs}")
            self.assertTrue((REPO_ROOT / "_site" / "404.html").is_file(), "Missing _site/404.html")
            self.assertTrue((REPO_ROOT / "_site" / "assets" / "og-py-phone-caller.png").is_file())
            self.assertTrue((REPO_ROOT / "_site" / "openalert" / "og-openalert.png").is_file())

            # Verify exported OpenAPI 3.0.3 specs include concrete parameter & requestBody examples
            import json as _json

            oas_dir = manual_dir / "assets" / "openapi"
            catalog = _json.loads((oas_dir / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["service_count"], 9)
            body_examples = 0
            param_examples = 0
            for svc in catalog["services"]:
                spec = _json.loads((oas_dir / svc["spec_file"]).read_text(encoding="utf-8"))
                for pitem in spec.get("paths", {}).values():
                    for m in ("get", "post", "put", "delete", "patch"):
                        op = pitem.get(m)
                        if not isinstance(op, dict):
                            continue
                        for prm in op.get("parameters", []):
                            self.assertIn("example", prm, f"Missing parameter example in {svc['id']} {m}")
                            param_examples += 1
                        rb = op.get("requestBody", {})
                        for media in rb.get("content", {}).values():
                            self.assertIn("example", media, f"Missing requestBody example in {svc['id']} {m}")
                            body_examples += 1
            self.assertGreaterEqual(body_examples, 35)
            self.assertGreaterEqual(param_examples, 50)

            # Verify every "View source" button in _site/manual points to an existing file in REPO_ROOT
            view_count = 0
            for html_file in sorted(manual_dir.rglob("*.html")):
                txt = html_file.read_text(encoding="utf-8")
                for view_rel in re.findall(
                    r'href="https://github\.com/jcfdeb/py-phone-caller/blob/main/([^"#?]+)"[^>]*title="View source of this page"',
                    txt,
                ):
                    view_count += 1
                    self.assertTrue(
                        (REPO_ROOT / view_rel).is_file(),
                        f"View-source link in {html_file.relative_to(manual_dir)} points to non-existent {view_rel}",
                    )
            self.assertGreaterEqual(view_count, 40, "Expected View-source GitHub links across all manual pages")

            html_defects: list[str] = []
            for html_file in sorted(manual_dir.rglob("*.html")):
                m_art = re.search(
                    r'<article class="md-content__inner[^"]*">(.*?)</article>',
                    html_file.read_text(encoding="utf-8"),
                    flags=re.DOTALL,
                )
                if not m_art:
                    continue
                clean = re.sub(r"<pre\b[^>]*>.*?</pre>", "", m_art.group(1), flags=re.DOTALL)
                clean = re.sub(r"<code\b[^>]*>.*?</code>", "", clean, flags=re.DOTALL)
                rel_h = html_file.relative_to(manual_dir)
                for defect_name, pat in (
                    ("literal_fence", r"```"),
                    ("inline_star_bullet", r"(?:<p>|:\s+|\.\s+)\*\s+<strong>"),
                    ("inline_dash_bullet", r"(?:<p>|:\s+|</strong>)\s+-\s+<strong>"),
                    ("inline_numbered_item", r"(?:<p>|:\s+)\d+\.\s+<strong>"),
                    ("raw_latex_cmd", r"\$\\[a-zA-Z]+"),
                    ("raw_github_alert", r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]"),
                    ("raw_checkbox", r"<li>\s*\[[ xX]\]\s"),
                ):
                    if re.search(pat, clean):
                        html_defects.append(f"{rel_h}: {defect_name}")
            self.assertEqual(html_defects, [], "HTML formatting defects in _site/manual:\n  " + "\n  ".join(html_defects))

    def test_openapi_specs_version_parity_and_zero_drift(self) -> None:
        """Ensure committed docs/assets/openapi/*.json match pyproject.toml version and export_openapi.py output."""
        root_ver = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        tracked_dir = REPO_ROOT / "docs" / "assets" / "openapi"
        self.assertTrue(tracked_dir.is_dir(), f"Missing tracked OpenAPI directory: {tracked_dir}")

        sys.path.insert(0, str(REPO_ROOT / "deploy" / "pages"))
        try:
            import export_openapi  # type: ignore[import-not-found]
        finally:
            sys.path.pop(0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            generated_dir = Path(tmp_dir)
            export_openapi.export_all_openapi_specs(REPO_ROOT, generated_dir)

            generated_names = sorted(p.name for p in generated_dir.glob("*.json"))
            tracked_names = sorted(p.name for p in tracked_dir.glob("*.json"))
            self.assertEqual(
                tracked_names,
                generated_names,
                "Tracked docs/assets/openapi/*.json file set differs from export_openapi.py; run 'task docs:build' or 'python3 deploy/pages/export_openapi.py'.",
            )

            catalog = json.loads((tracked_dir / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(catalog["version"], root_ver, "OpenAPI catalog.json version drift")
            self.assertEqual(catalog["service_count"], len(export_openapi.SERVICE_META))
            for svc in catalog["services"]:
                spec = json.loads((tracked_dir / svc["spec_file"]).read_text(encoding="utf-8"))
                self.assertEqual(spec.get("openapi"), "3.0.3", f"Unexpected OpenAPI version in {svc['spec_file']}")
                self.assertEqual(
                    spec.get("info", {}).get("version"),
                    root_ver,
                    f"Version drift in docs/assets/openapi/{svc['spec_file']}",
                )
                paths = spec.get("paths")
                self.assertTrue(
                    isinstance(paths, dict) and len(paths) > 0,
                    f"Empty or invalid paths in docs/assets/openapi/{svc['spec_file']}",
                )

            stale_files = [
                name
                for name in generated_names
                if (tracked_dir / name).read_text(encoding="utf-8") != (generated_dir / name).read_text(encoding="utf-8")
            ]
            self.assertEqual(
                stale_files,
                [],
                f"Stale OpenAPI specs in docs/assets/openapi/ ({stale_files}); run 'task docs:build' or 'python3 deploy/pages/export_openapi.py' to refresh.",
            )


if __name__ == "__main__":
    unittest.main()
