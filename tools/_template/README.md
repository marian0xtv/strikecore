# __TOOLNAME__ — __ONE_LINE_DESCRIPTION__

> TEMPLATE. Copy `tools/_template/` → `tools/<name>/`, replace every
> `__PLACEHOLDER__`, then implement `run()` and `_selftest_check()`.

See `docs/INTEGRATION_CONTRACT.md` for the full contract and
`tools/cf-validate/` for a complete worked example.

## Checklist to ship a new tool

- [ ] Rename `sc-TEMPLATE.py` → `sc-<name>.py`; set `TOOL`/`VERSION`.
- [ ] Implement `run()` — emit results with honest Admiralty reliability/confidence + sources.
- [ ] Implement `_selftest_check()` — OFFLINE, no real targets.
- [ ] Fill `tool.manifest.json` (provenance pinned_commit, license, capabilities, safety).
- [ ] Keep `gate_approved=false` until a human runs the sandbox gate (H1/H3).
- [ ] `python3 sc-<name>.py --selftest --json` exits 0.
- [ ] `python3 bin/sc-registry.py validate tools/<name>` passes.
- [ ] Commit + push (GR1). The atlas `post-receive` hook gates & registers.

## Usage (after copy)

```bash
sc-<name> <target>
sc-<name> --json <target>
sc-<name> --selftest
```
