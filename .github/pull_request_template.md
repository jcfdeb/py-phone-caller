## Summary

Briefly describe what this PR changes and why.

## Related Issue

Closes #

## Verification & Security Checklist

- [ ] No real secrets, personal phone numbers, or private hostnames are included (`task sec:fast` passes cleanly).
- [ ] Python & Rust lint/unit suites pass (`task verify:all`).
- [ ] Documentation & version coherence tests pass (`uv run pytest tests/test_docs_coherence.py` and `task docs:build` if docs/routes changed).
- [ ] BitChat BLE codec / wire framing (`src/openalert/src/bitchat.rs`) and constant-time auth checks remain intact.
