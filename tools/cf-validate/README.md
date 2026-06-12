# cf-validate — Italian Codice Fiscale validator

Offline, deterministic validation of an Italian *Codice Fiscale* (CF): verifies
the control character and decodes birth metadata (year/month/day/gender),
tolerating *omocodia* (letter-substituted digits). No network, no real targets.

This is the **reference implementation** for the StrikeCore Integration
Contract (`docs/INTEGRATION_CONTRACT.md`) — copy its structure for new tools,
or start from `tools/_template/`.

## Usage

```bash
sc-cf-validate RSSMRA85T10A562S          # exit 0 = valid, 1 = invalid
sc-cf-validate --json RSSMRA85T10A562S   # emit the I/O envelope
sc-cf-validate --selftest                # offline health check (no real targets)
```

## Contract conformance

| Requirement | How |
|---|---|
| Uniform CLI | `--config / --selftest / --json` via `tools/lib/sctool.py` |
| Exit codes | 0 valid · 1 invalid · 2 usage · 3 internal |
| I/O envelope | emits `schema/io.envelope.schema.json` with per-result Admiralty A/1 |
| Self-test | validates a known-good + rejects a mutated CF, offline |
| Manifest | `tool.manifest.json`, `gate_approved=true` (offline, first-party) |
| Install | `install.sh`, `install_method=symlink-only` |

## Files

- `sc-cf-validate.py` — wrapper / entrypoint
- `tool.manifest.json` — registry manifest
- `install.sh` — installer (symlink + self-test gate)
- `tests/test_selftest.sh` — CI-style self-test assertion
