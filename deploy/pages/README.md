# Hybrid GitHub Pages Builder (`deploy/pages/`)

[`build_pages.py`](build_pages.py) builds the static GitHub Pages bundle in `_site/` by combining:
- The custom suite landing page (`/` from [`docs/index.html`](../../docs/index.html) and [`docs/404.html`](../../docs/404.html))
- The OpenAlert showcase page (`/openalert/` from [`docs/openalert/index.html`](../../docs/openalert/index.html))
- The full MkDocs Material documentation portal (`/manual/` configured in [`mkdocs.yml`](../../mkdocs.yml))

Before staging `docs/`, `build_pages.py` imports [`export_openapi.py`](export_openapi.py) and regenerates all 9 service OpenAPI 3.0.3 specifications plus `catalog.json` **in place** under [`docs/assets/openapi/`](../../docs/assets/openapi/) (consumed offline by [`docs/api-explorer.md`](../../docs/api-explorer.md)). Any edit to service routes or OpenAPI schemas requires re-running `task docs:build` (or `python3 deploy/pages/export_openapi.py`) so the committed JSON specs remain synchronized.

During staging, `build_pages.py` normalizes GitHub Flavored Markdown (GFM alerts, breakless lists/fences/tables, 2-space nested lists, and inline LaTeX arrows) so Python-Markdown renders every guide cleanly, and injects GitHub `View source` links pointing back to `main`.

## Rebuild & Coherence Gates

Run these commands from the repository root in order so [`tests/test_docs_coherence.py`](../../tests/test_docs_coherence.py) validates both source Markdown/version parity and the freshly rendered `_site/manual/*.html` output:

```bash
# 1. Rebuild _site/ (runs mkdocs + mkdocs-material via uv tool run if not globally installed)
task docs:build

# 2. Verify coherence, Python/packaging suite, Rust Clippy/tests, and fast security gates
task verify:all

# 3. Run full PR/CI AppSec gates (SAST, SCA, and Trivy IaC)
task sec:ci
```

### Useful Shortcuts
- **Regenerate OpenAPI 3.0.3 specs only**: `python3 deploy/pages/export_openapi.py`
- **Local live preview (`http://127.0.0.1:8008`)**: `task docs:serve` (or `python3 deploy/pages/build_pages.py --output-dir _site --serve --port 8008`)
- **Version parity check only**: `task version:check`
- **Coherence suite only**: `uv run --no-sync pytest tests/test_docs_coherence.py -v`
