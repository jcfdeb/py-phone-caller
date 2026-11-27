#!/usr/bin/env python3
"""Build the hybrid GitHub Pages site (_site/) combining custom hero pages and MkDocs Material."""

from __future__ import annotations

import argparse
import http.server
import json
import re
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

GITHUB_REPO_BASE = "https://github.com/jcfdeb/py-phone-caller"
EXTRA_STAGE_DOCS: dict[str, str] = {
    "src/caller_prometheus_webhook/README.md": "integrations/prometheus-alertmanager.md",
    "assets/scripts/nagios/README.md": "integrations/nagios.md",
    "assets/scripts/zabbix/README.md": "integrations/zabbix.md",
}
ALERT_MAP = {
    "NOTE": "note",
    "TIP": "tip",
    "IMPORTANT": "important",
    "WARNING": "warning",
    "CAUTION": "danger",
}

MD_LINK_RE = re.compile(r"(!?\[[^\]]*\])\(([^)]+)\)")
THEMATIC_BREAK_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)(\s+)(.*)$")
FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")

INLINE_LATEX_MAP = {
    r"$\rightarrow$": "→",
    r"$\longrightarrow$": "⟶",
    r"$\to$": "→",
    r"$\leftarrow$": "←",
    r"$\leftrightarrow$": "↔",
    r"$\longleftrightarrow$": "⟷",
}


def _replace_inline_latex_outside_code(line: str) -> str:
    if "$" not in line:
        return line
    parts = re.split(r"(`+[^`]*`+)", line)
    for idx in range(0, len(parts), 2):
        chunk = parts[idx]
        for src_tok, dst_tok in INLINE_LATEX_MAP.items():
            chunk = chunk.replace(src_tok, dst_tok)
        parts[idx] = chunk
    return "".join(parts)


def normalize_commonmark_for_mkdocs(markdown_text: str) -> str:
    """Normalize GitHub/CommonMark constructs (breakless lists/fences/tables & 2-space sublists) for Python-Markdown."""
    lines = markdown_text.splitlines()
    out: list[str] = []

    in_fence = False
    fence_char = ""
    fence_len = 0
    fence_orig_indent = 0
    fence_new_indent = 0
    prev_was_closing_fence = False

    # Stack of active list levels: (orig_indent, normalized_indent)
    list_stack: list[tuple[int, int]] = []

    for i, raw_line in enumerate(lines):
        if in_fence:
            stripped = raw_line.lstrip()
            if stripped.startswith(fence_char * fence_len) and stripped.strip(fence_char).strip() == "":
                out.append((" " * fence_new_indent) + stripped)
                in_fence = False
                prev_was_closing_fence = True
                continue
            if raw_line.strip() == "":
                out.append("")
            else:
                cur_ind = len(raw_line) - len(stripped)
                rel_ind = max(0, cur_ind - fence_orig_indent)
                out.append((" " * (fence_new_indent + rel_ind)) + stripped)
            continue

        # Check opening code fence
        m_fence = FENCE_OPEN_RE.match(raw_line)
        if m_fence:
            ind_str, marker, info = m_fence.groups()
            orig_ind = len(ind_str)
            new_ind = orig_ind
            if list_stack and orig_ind > list_stack[-1][0]:
                new_ind = max(orig_ind, list_stack[-1][1] + 4)
            elif orig_ind == 0:
                list_stack.clear()

            # Sanitize multi-word plain info strings like ```http request -> ```http
            info_stripped = info.strip()
            if " " in info_stripped and not any(ch in info_stripped for ch in ("{", "=", ".", "#", '"', "'")):
                info_stripped = info_stripped.split()[0]

            if out and out[-1].strip() != "" and not out[-1].lstrip().startswith((">", "!!!", "???")):
                out.append("")

            out.append((" " * new_ind) + marker + info_stripped)
            in_fence = True
            fence_char = marker[0]
            fence_len = len(marker)
            fence_orig_indent = orig_ind
            fence_new_indent = new_ind
            prev_was_closing_fence = False
            continue

        line = _replace_inline_latex_outside_code(raw_line)

        if line.strip() == "":
            out.append("")
            prev_was_closing_fence = False
            continue

        # Check pipe table header missing preceding blank line
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:-]+\|", lines[i + 1]):
            if out and out[-1].strip() != "" and not out[-1].lstrip().startswith(("|", ">")):
                out.append("")
            list_stack.clear()
            out.append(line)
            prev_was_closing_fence = False
            continue

        # Check list items (excluding thematic breaks like `* * *` or `- - -`)
        m_list = None if THEMATIC_BREAK_RE.match(line) else LIST_ITEM_RE.match(line)
        if m_list:
            ind_str, marker, sep_spaces, rest = m_list.groups()
            orig_ind = len(ind_str)

            while list_stack and orig_ind < list_stack[-1][0]:
                list_stack.pop()

            if list_stack and orig_ind == list_stack[-1][0]:
                norm_ind = list_stack[-1][1]
            elif list_stack and orig_ind > list_stack[-1][0]:
                norm_ind = list_stack[-1][1] + 4
                list_stack.append((orig_ind, norm_ind))
            else:
                norm_ind = orig_ind
                list_stack.append((orig_ind, norm_ind))

            prev_line = out[-1] if out else ""
            prev_nonblank = prev_line.strip() != ""
            prev_is_list_item = bool(
                prev_nonblank
                and not THEMATIC_BREAK_RE.match(prev_line)
                and LIST_ITEM_RE.match(prev_line)
            )
            prev_is_heading_or_quote = prev_line.lstrip().startswith(("#", ">", "!!!", "???"))

            if prev_nonblank and (
                prev_was_closing_fence
                or (not prev_is_list_item and not prev_is_heading_or_quote)
            ):
                out.append("")

            norm_sep = " " if len(sep_spaces) >= 1 else sep_spaces
            out.append((" " * norm_ind) + marker + norm_sep + rest)
            prev_was_closing_fence = False
            continue

        # Non-empty, non-fence, non-list line
        cur_ind = len(line) - len(line.lstrip())
        if line.lstrip().startswith(("#", "!!!", "???")) or THEMATIC_BREAK_RE.match(line):
            list_stack.clear()
            out.append(line)
        elif list_stack:
            if cur_ind == 0 and (
                (out and out[-1].strip() == "") or line.rstrip().endswith(":")
            ):
                if out and out[-1].strip() != "":
                    out.append("")
                list_stack.clear()
                out.append(line)
            elif cur_ind > list_stack[-1][0]:
                norm_cont = max(cur_ind, list_stack[-1][1] + 4)
                out.append((" " * norm_cont) + line.lstrip())
            else:
                out.append(line)
        else:
            out.append(line)
        prev_was_closing_fence = False

    return "\n".join(out) + ("\n" if markdown_text.endswith("\n") else "")


def convert_github_alerts(markdown_text: str) -> str:
    """Convert GitHub-style `> [!NOTE]` blockquotes into MkDocs Material `!!! note` admonitions."""
    lines = markdown_text.splitlines()
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue

        if not in_fence:
            m = re.match(r"^(\s*)>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$", line)
            if m:
                indent, kind, inline_title = m.groups()
                admon_type = ALERT_MAP[kind]
                title_part = f' "{inline_title.strip()}"' if inline_title.strip() else ""
                out.append(f"{indent}!!! {admon_type}{title_part}")
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    bm = re.match(rf"^{re.escape(indent)}>\s?(.*)$", nxt)
                    if not bm:
                        break
                    out.append(f"{indent}    {bm.group(1)}")
                    i += 1
                continue

        out.append(line)
        i += 1

    return "\n".join(out) + ("\n" if markdown_text.endswith("\n") else "")


def rewrite_links(markdown_text: str, src_repo_file: Path, dest_stage_file: Path, stage_docs_root: Path, repo_root: Path) -> str:
    """Rewrite relative Markdown links so internal staged docs resolve locally and code paths link to GitHub."""
    out_chunks: list[str] = []
    # Preserve fenced code blocks untouched
    parts = re.split(r"(```.*?```|~~~.*?~~~)", markdown_text, flags=re.DOTALL)
    for idx, chunk in enumerate(parts):
        if idx % 2 == 1:
            out_chunks.append(chunk)
            continue

        def _replace(match: re.Match[str]) -> str:
            label, raw_target = match.group(1), match.group(2).strip()
            if not raw_target or raw_target.startswith(("#", "http://", "https://", "mailto:", "tel:", "javascript:", "lightning:")):
                return match.group(0)

            target_clean = raw_target.split()[0]
            path_part, sep, frag = target_clean.partition("#")
            frag_suffix = f"#{frag}" if sep else ""
            if not path_part:
                return match.group(0)

            resolved_repo = (src_repo_file.parent / path_part).resolve()
            try:
                rel_to_repo = resolved_repo.relative_to(repo_root)
            except ValueError:
                return match.group(0)

            # Map repo paths into `.pages-stage/docs/` if staged there
            staged_rel: Path | None = None
            rel_posix = rel_to_repo.as_posix()
            if rel_posix == "docs/README.md":
                staged_rel = Path("index.md")
            elif rel_posix.startswith("docs/"):
                staged_rel = Path(rel_posix.removeprefix("docs/"))
            elif rel_posix.startswith("deploy/docs/"):
                staged_rel = Path("deploy") / rel_posix.removeprefix("deploy/docs/")
            elif rel_posix in {"CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"}:
                staged_rel = Path(rel_posix)
            elif rel_posix in EXTRA_STAGE_DOCS:
                staged_rel = Path(EXTRA_STAGE_DOCS[rel_posix])

            if staged_rel is not None:
                target_stage = stage_docs_root / staged_rel
                if target_stage.exists():
                    rel_link = Path(
                        __import__("os").path.relpath(target_stage, dest_stage_file.parent)
                    ).as_posix()
                    return f"{label}({rel_link}{frag_suffix})"

            # Otherwise point cleanly to GitHub blob/tree on `main`
            if resolved_repo.exists():
                kind = "tree" if resolved_repo.is_dir() else "blob"
                return f"{label}({GITHUB_REPO_BASE}/{kind}/main/{rel_posix}{frag_suffix})"

            return match.group(0)

        out_chunks.append(MD_LINK_RE.sub(_replace, chunk))

    return "".join(out_chunks)


def stage_docs_tree(repo_root: Path, stage_root: Path) -> None:
    # Regenerate live OpenAPI 3.0.3 specs directly from codebase before staging docs/assets/openapi/
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import export_openapi  # type: ignore[import-not-found]

        export_openapi.export_all_openapi_specs(repo_root, repo_root / "docs" / "assets" / "openapi")
    finally:
        sys.path.pop(0)

    if stage_root.exists():
        shutil.rmtree(stage_root)
    docs_out = stage_root / "docs"
    docs_out.mkdir(parents=True, exist_ok=True)

    docs_src = repo_root / "docs"
    skip_docs_names = {"index.html", "404.html", "styles.css"}

    # 1. Copy non-markdown assets & markdown files from docs/ (excluding openalert/dist and .xcf)
    stage_pairs: list[tuple[Path, Path]] = []
    source_map: dict[str, str] = {}
    for item in sorted(docs_src.rglob("*")):
        rel = item.relative_to(docs_src)
        if rel.parts[0] == "openalert" and len(rel.parts) > 1 and rel.parts[1] == "dist":
            continue
        if rel.as_posix() in skip_docs_names or rel.as_posix() == "openalert/index.html":
            continue
        if item.suffix.lower() == ".xcf" or item.name.startswith("."):
            continue
        dest_rel = Path("index.md") if rel.as_posix() == "README.md" else rel
        dest = docs_out / dest_rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif item.suffix.lower() == ".md":
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            stage_pairs.append((item, dest))
            source_map[dest_rel.as_posix()] = item.relative_to(repo_root).as_posix()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    # 2. Copy deploy/docs/ -> .pages-stage/docs/deploy/
    deploy_docs_src = repo_root / "deploy" / "docs"
    for item in sorted(deploy_docs_src.rglob("*")):
        if item.is_file() and item.suffix.lower() == ".md":
            rel = item.relative_to(deploy_docs_src)
            dest_rel = Path("deploy") / rel
            dest = docs_out / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            stage_pairs.append((item, dest))
            source_map[dest_rel.as_posix()] = item.relative_to(repo_root).as_posix()

    # 3. Copy root governance docs + external integration guides
    for gov_name in ("CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
        src_gov = repo_root / gov_name
        if src_gov.is_file():
            dest_gov = docs_out / gov_name
            shutil.copy2(src_gov, dest_gov)
            stage_pairs.append((src_gov, dest_gov))
            source_map[gov_name] = gov_name

    for src_rel_str, dst_rel_str in EXTRA_STAGE_DOCS.items():
        src_extra = repo_root / src_rel_str
        if src_extra.is_file():
            dest_extra = docs_out / dst_rel_str
            dest_extra.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_extra, dest_extra)
            stage_pairs.append((src_extra, dest_extra))
            source_map[dst_rel_str] = src_rel_str

    # 4. Transform GitHub alerts, normalize CommonMark lists/fences/tables, and rewrite links
    for src_md, dst_md in stage_pairs:
        raw = src_md.read_text(encoding="utf-8")
        converted = convert_github_alerts(raw)
        normalized = normalize_commonmark_for_mkdocs(converted)
        rewritten = rewrite_links(normalized, src_md, dst_md, docs_out, repo_root)
        dst_md.write_text(rewritten, encoding="utf-8")

    # 5. Write source_map.json and MkDocs hook for exact GitHub source URLs & local/remote Showcase links
    (stage_root / "source_map.json").write_text(json.dumps(source_map, indent=2), encoding="utf-8")
    (stage_root / "hooks.py").write_text(
        "import json\n"
        "from pathlib import Path\n\n"
        "_MAP = json.loads((Path(__file__).parent / 'source_map.json').read_text(encoding='utf-8'))\n"
        "_REPO = 'https://github.com/jcfdeb/py-phone-caller/blob/main/'\n\n"
        "def on_pre_page(page, config, files):\n"
        "    src = page.file.src_uri\n"
        "    if src in _MAP:\n"
        "        page.edit_url = _REPO + _MAP[src]\n"
        "    return page\n\n"
        "def on_post_page(output, page, config):\n"
        "    parts = [p for p in (page.url or '').strip('/').split('/') if p]\n"
        "    up = '/'.join(['..'] * (len(parts) + 1))\n"
        "    output = output.replace(\n"
        "        'https://github.com/jcfdeb/py-phone-caller/raw/main/',\n"
        "        'https://github.com/jcfdeb/py-phone-caller/blob/main/',\n"
        "    )\n"
        "    output = output.replace(\n"
        "        'href=\"https://jcfdeb.github.io/py-phone-caller/openalert/\"',\n"
        "        f'href=\"{up}/openalert/\"',\n"
        "    )\n"
        "    output = output.replace(\n"
        "        'href=\"https://jcfdeb.github.io/py-phone-caller/\"',\n"
        "        f'href=\"{up}/\"',\n"
        "    )\n"
        "    return output\n",
        encoding="utf-8",
    )


def resolve_mkdocs_cmd() -> list[str]:
    mkdocs_bin = shutil.which("mkdocs")
    if mkdocs_bin:
        return [mkdocs_bin]
    uv_bin = shutil.which("uv")
    if uv_bin:
        return [uv_bin, "tool", "run", "--python", "3.12", "--from", "mkdocs", "--with", "mkdocs-material", "mkdocs"]
    raise RuntimeError("Neither 'mkdocs' nor 'uv' was found on PATH to build the documentation manual.")


def build_pages(repo_root: Path, output_dir: Path) -> None:
    stage_root = repo_root / ".pages-stage"
    try:
        stage_docs_tree(repo_root, stage_root)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Configure staged mkdocs.yml pointing docs_dir at staged docs and enabling hooks.py
        mkdocs_src = (repo_root / "mkdocs.yml").read_text(encoding="utf-8")
        staged_mkdocs = stage_root / "mkdocs.yml"
        staged_mkdocs.write_text(
            mkdocs_src.replace(
                'docs_dir: ".pages-stage/docs"',
                'docs_dir: "docs"\nhooks:\n  - hooks.py',
            ),
            encoding="utf-8",
        )

        manual_dir = output_dir / "manual"
        cmd = [*resolve_mkdocs_cmd(), "build", "-f", str(staged_mkdocs), "-d", str(manual_dir)]
        print(f"==> [Pages/MkDocs] {' '.join(cmd)}")
        env = {**__import__("os").environ, "NO_MKDOCS_2_WARNING": "1"}
        subprocess.run(cmd, cwd=repo_root, env=env, check=True)

        # Copy custom root landing page + 404 page + CSS + SVG/PNG assets
        shutil.copy2(repo_root / "docs" / "index.html", output_dir / "index.html")
        if (repo_root / "docs" / "404.html").is_file():
            shutil.copy2(repo_root / "docs" / "404.html", output_dir / "404.html")
        shutil.copy2(repo_root / "docs" / "styles.css", output_dir / "styles.css")
        shutil.copytree(repo_root / "docs" / "assets", output_dir / "assets", dirs_exist_ok=True)

        # Copy OpenAlert custom showcase page + logos + OG preview card
        oa_out = output_dir / "openalert"
        oa_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo_root / "docs" / "openalert" / "index.html", oa_out / "index.html")
        for logo in ("openalert-logo.png", "openalert-logo-day.png", "og-openalert.png"):
            logo_src = repo_root / "docs" / "openalert" / logo
            if logo_src.is_file():
                shutil.copy2(logo_src, oa_out / logo)

        # Prevent GitHub Pages Jekyll interference with `_` or `assets/` folders
        (output_dir / ".nojekyll").write_text("", encoding="utf-8")
        print(f"==> Hybrid GitHub Pages site built cleanly in {output_dir} (/, /openalert/, /manual/)")
    finally:
        if stage_root.exists():
            shutil.rmtree(stage_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="_site", help="Output directory for built Pages site (default: _site)")
    parser.add_argument("--serve", action="store_true", help="Serve the built site locally after building")
    parser.add_argument("--port", type=int, default=8008, help="Local HTTP port when --serve is passed (default: 8008)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    output_dir = (repo_root / args.output_dir).resolve()
    build_pages(repo_root, output_dir)

    if args.serve:
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(output_dir))
        with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
            print(f"Serving GitHub Pages preview at http://127.0.0.1:{args.port}/ (Ctrl+C to stop)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
