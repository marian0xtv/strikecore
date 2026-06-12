# StrikeCore Integration Contract

> **Status: MANDATORY.** Every OSINT tool added to StrikeCore — whether written
> from scratch, forked, or wrapped from upstream — MUST conform to this
> contract. It **formalizes the existing daprofiler pattern**
> (`bin/sc-daprofiler.py` + `bin/install-daprofiler.sh`); it does not replace it
> with a competing one. The reference implementation is `tools/cf-validate/`;
> the copy-me skeleton is `tools/_template/`.

This contract is owned by the **Hephaestus** subagent
(`.claude/agents/hephaestus.md`) and enforced at deploy time by the
`post-receive` hook on atlas.

---

## Global rules this contract sits under

- **GR1 — Git-only deployment.** All changes are made in the local clone,
  committed (conventional commits), and pushed to atlas. Project files are
  **never** edited, created, or installed directly on atlas over SSH.
- **GR2 — Hook exception.** Git hooks live in `.git/hooks/` and are NOT part of
  the pushed tree. The `post-receive` hook is therefore the **single** sanctioned
  artifact installed directly on atlas. This is the only exception to GR1.
- **GR3 — Model routing.** Default `claude-opus-4-8`; `claude-fable-5` for heavy
  reasoning (research, design, gap analysis). Pinned per-subagent in the agent's
  frontmatter (`.claude/agents/<name>.md` → `model:`).
- **GR4 — Sandbox doctrine.** Untrusted upstream code is sandboxed and
  human-gated (H1/H3) before any real run. The gate is the manifest
  `gate_approved` flag + the `post-receive` enforcement + the offline
  `--selftest` — **reusing** StrikeCore's execution constraints
  (`core/executor.py` allowlist + dangerous-pattern + timeout;
  `core/proxy_manager.py` egress), **not** a parallel mechanism. Honest scope
  note: StrikeCore's isolation is an allowlist + pattern + process-group timeout,
  **not** an OS jail; treat real-target runs accordingly.

### Hard stops (operator approval required)

| Gate | Trigger |
|---|---|
| **H1** | Running untrusted upstream/GitHub tool code against REAL targets. |
| **H2** | Installing system-level dependencies on atlas (package manager, sudo). |
| **H3** | Registering/enabling a tool that has NOT passed the sandbox gate. |
| **H4** | Any irreversible production action beyond a Git push + the hook install. |

---

## 1. Canonical directory layout (mirrors daprofiler)

Each tool is a self-contained directory under `tools/`:

```
tools/
  lib/sctool.py            # shared: envelope builder, Admiralty grades, CLI flags, selftest harness
  _template/               # copy-me skeleton (gate_approved=false)
  <name>/
    tool.manifest.json     # machine-readable descriptor (schema/tool.manifest.schema.json)
    sc-<name>.py           # uniform CLI wrapper / entrypoint (mirrors sc-daprofiler.py)
    install.sh             # installer (mirrors bin/install-daprofiler.sh)
    README.md              # human docs + conformance checklist
    tests/test_selftest.sh # offline conformance test
```

Directories named `lib` or starting with `_` are internal and are **skipped** by
the registry scan and the deploy hook.

The legacy daprofiler wrapper (`bin/sc-daprofiler.py` + `bin/install-daprofiler.sh`)
predates this layout and remains valid; it MAY be migrated into
`tools/daprofiler/` later without behavior change.

## 2. Manifest — `tool.manifest.json`

Validated against `schema/tool.manifest.schema.json`. Required fields:

| Field | Meaning |
|---|---|
| `manifest_version` | `1` |
| `name` | unique registry key, `^[a-z0-9][a-z0-9_-]{1,63}$`; wrapper is `sc-<name>` |
| `version` | tool semver |
| `category` | OSINT taxonomy enum: `domain·network·person·social·geoint·image·document·breach·infrastructure·email·phone·username·threatint·cloud·code-repo·crypto·dark-web·italian-specific·misc` |
| `description` | 8–500 chars |
| `provenance` | `{upstream_url, pinned_commit, first_party?}` — pin the exact commit |
| `license` | SPDX id / `proprietary` / `unknown` |
| `reliability` | NATO Admiralty A–F (default trust in the tool's output) |
| `confidence` | NATO Admiralty 1–6 |
| `maintainer`, `added_by`, `added_at` | accountability (UTC ISO-8601) |
| `runtime` | `python3·bash·node·go·binary·other` |
| `deps` | pinned dependency strings (e.g. `requests==2.32.0`) |
| `install_method` | `git-clone-venv·pip·go-install·apt·symlink-only·none` |
| `entrypoint` | wrapper path within the tool dir |
| `capabilities[]` | machine-readable tags for agent routing (e.g. `validate:codice-fiscale`) |
| `io` | `{input_schema, output_envelope}` — output_envelope = `schema/io.envelope.schema.json` |
| `safety` | `{network_egress, rate_limits, touches_real_targets, tos_notes, sandbox_required}` |
| `gate_approved` | bool — **set true ONLY after the manual sandbox gate (H3)** |

## 3. CLI interface (uniform)

Every wrapper exposes, via `tools/lib/sctool.py:base_argparser`:

- positional/domain args specific to the tool;
- `--config PATH` — JSON/TOML config (secrets via env only, never in the file);
- `--selftest` — offline health check (§8), then exit;
- `--json` — emit the I/O envelope on stdout (the default machine channel).

**Exit codes (shared):** `0` success · `1` tool-level failure / negative result ·
`2` usage error · `3` internal/integration error.

## 4. I/O envelope (JSON)

Validated against `schema/io.envelope.schema.json`. Built by
`sctool.build_envelope(...)`. Shape:

```json
{
  "schema_version": 1,
  "tool": "<name>", "tool_version": "<semver>",
  "timestamp": "<UTC ISO-8601>",
  "input": { "...echo of normalized input..." },
  "results": [
    { "type": "...", "value": ...,
      "reliability": "A-F", "confidence": 1-6,
      "sources": ["...provenance..."] }
  ],
  "errors": [ { "code": "...", "message": "...", "detail": "..." } ],
  "audit": { "run_id": "...", "selftest": false, "duration_ms": 12, "target": "..." }
}
```

Each **result carries its own Admiralty reliability + credibility + sources**, so
scoring propagates end-to-end into the intel pipeline (`intel_team/quality_gate.py`,
the analyst) without re-derivation. Deterministic algorithmic results (e.g. a
checksum) may use an empty `sources` array with reliability `A` / confidence `1`.

## 5. Config & secrets

- Config is layered and validated; tools read a `--config` file for non-secret
  parameters.
- **Secrets never live in the manifest, the config file, or the code.** They come
  from the environment / secret store (consistent with StrikeCore's `.env` +
  `config/settings.py` env-override layer). A tool reads `os.environ[...]`.
- Versioning: the manifest `version` + `provenance.pinned_commit` are the
  authoritative version record; updates re-pin (see §10).

## 6. Safety / sandbox metadata + gates

- The manifest `safety{}` block declares `network_egress`,
  `touches_real_targets`, `rate_limits`, `tos_notes`, `sandbox_required`.
- A tool with `touches_real_targets=true` or any untrusted upstream code ships
  `gate_approved=false`. It is **flagged for the manual sandbox gate** and is
  never auto-run or registered by the hook (H3). A human reviews it (H1) and
  flips `gate_approved=true`.
- Execution, when wired through StrikeCore, flows through `core/executor.py`
  (allowlist + dangerous-pattern + process-group timeout) wrapped by
  `core/proxy_manager.py` for egress. Adding a new binary to the executor
  allowlist is a separate, test-gated change (CLAUDE.md §10).

## 7. Logging & audit

- Each tool run emits the envelope (with `audit.run_id`).
- Registry mutations append a SHA-256-hashed line to
  `~/.strikecore/audit/YYYY-MM-DD.jsonl` (component `sc-registry`), matching the
  `intel_team` audit entry shape (`{ts, component, event, name, ..., hash}`).
- The deploy hook appends an append-only line per action to
  `~/.strikecore/audit/hook-deploy.log` (who/what/when/target/outcome).

## 8. `--selftest` health check

- MUST run **offline** — no real targets, no network egress to third parties.
- Exercises the tool's core logic against fixtures and asserts expected output.
- Emits a selftest envelope (`audit.selftest=true`); exit `0` pass, `1` fail.
- This is the automated half of the sandbox gate; the hook runs it only on
  `gate_approved=true` tools.

## 9. Registry entry format + (de)register flow

The registry is an **overlay** keyed off the committed manifests — it does NOT
mutate the §10-protected `core/tool_registry.py` `_TOOLS` list or
`core/executor.py` `ALLOWED_BINARIES`. CLI: `bin/sc-registry.py`.

```bash
python3 bin/sc-registry.py validate   tools/<name>     # check vs schema
python3 bin/sc-registry.py register   tools/<name>     # validate + add to index (refuses gate_approved=false)
python3 bin/sc-registry.py deregister <name>           # remove from index
python3 bin/sc-registry.py list [--json]               # show registered tools
python3 bin/sc-registry.py index --tools-dir tools     # bulk re-scan
```

Index lives at `~/.strikecore/registry/index.json`. A `gate_approved=false` tool
is refused unless `--force-pending` (recorded inactive/pending). **Registry
changes ship via Git (GR1):** the manifests are the source of truth; the hook
rebuilds the index on push.

## 10. Lifecycle (all Git operations)

- **Install:** commit the `tools/<name>/` dir + push → hook self-tests &
  registers (if gated). Operators run `tools/<name>/install.sh` to provision the
  upstream binary/venv locally.
- **Update:** bump `provenance.pinned_commit` + `version` in the manifest,
  adjust the wrapper if the upstream interface changed, re-run `--selftest`,
  commit, push. The new pin is the new truth.
- **Deprecate:** `bin/sc-registry.py deregister <name>` (committed via the
  index/manifest change) or set the tool aside; document in the README. Removing
  the `tools/<name>/` dir in a push causes the hook to skip it (no manifest).

---

## Authoring checklist (copy when shipping a tool)

- [ ] `tools/<name>/` created from `tools/_template/` (or `cf-validate`).
- [ ] `run()` implemented; results carry honest Admiralty reliability/confidence/sources.
- [ ] `_selftest_check()` implemented — offline, no real targets.
- [ ] `tool.manifest.json` filled; `gate_approved=false` for any untrusted upstream code.
- [ ] `python3 tools/<name>/sc-<name>.py --selftest --json` exits 0.
- [ ] `python3 bin/sc-registry.py validate tools/<name>` passes.
- [ ] Conventional commit + push (GR1). Operator runs the gate (H1/H3) before activation.
