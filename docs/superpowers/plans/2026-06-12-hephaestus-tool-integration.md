# Hephaestus Tool-Integration System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline, autonomous per user automode). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Formalize StrikeCore's informal OSINT-tool integration pattern (daprofiler) into a machine-readable contract, build a git-push deployment loop with a self-test/registration hook, and add the "Hephaestus" R&D subagent that discovers/builds/integrates new OSINT tooling under that contract.

**Architecture:** Per-tool directories under `tools/<name>/` each carry a `tool.manifest.json` (validated against `schema/tool.manifest.schema.json`), a uniform CLI wrapper (`--config/--selftest/--json`, standard exit codes) that emits a JSON **I/O envelope** (`schema/io.envelope.schema.json`) with per-result NATO Admiralty reliability + confidence, an `install.sh` (mirrors `bin/install-daprofiler.sh`), tests, and a README. A stdlib-only registry CLI (`bin/sc-registry.py`) validates manifests and maintains an index. A `post-receive` hook on atlas runs `--selftest` only on `gate_approved=true` tools and registers them. Hephaestus is a native Claude Code subagent (`.claude/agents/hephaestus.md`).

**Tech Stack:** Python 3.13 stdlib only (no jq, no jsonschema dep), bash, git push-to-deploy (`receive.denyCurrentBranch=updateInstead`), Claude Code native subagents.

---

## Grounding facts (from Phase 1 discovery — do not re-derive)

- **No registry CLI exists.** Registry = hardcoded `_TOOLS` list of frozen `ToolDefinition` dataclasses (`core/tool_registry.py:143`) + separate hardcoded `ALLOWED_BINARIES` frozenset (`core/executor.py:41`). CLAUDE.md §10 forbids editing `ALLOWED_BINARIES` without a test run and forbids changing the registry schema. → **Do NOT mutate those.** Build an overlay registry keyed off committed manifests.
- **No OS sandbox / human gate exists.** Only isolation = executor allowlist + dangerous-pattern regex + process-group timeout (`core/executor.py:218,308`); egress via `core/proxy_manager.py:wrap_command`. → The "gate" is the manifest `gate_approved` bool + hook enforcement + offline `--selftest`. Document honestly; no parallel mechanism.
- **Audit (hashed) pattern to match:** `intel_team/orchestrator.py:249 _audit()` — per-entry SHA-256 over `{ts,component,event,...}`. The hook's audit log mirrors this shape (append-only).
- **Native subagent mechanism = `.claude/agents/*.md`** with frontmatter `name/description/tools/model`. StrikeCore's Python "agents" are internal and unrelated. `.claude/agents/` does not exist yet.
- **Model ids** `claude-opus-4-8` / `claude-fable-5` are NOT in StrikeCore's internal provider lists — irrelevant here because Hephaestus uses the **native CC frontmatter** `model:` field, not the dormant Postgres router. Internal model-routing wiring is explicitly OUT of scope (follow-up).
- **`bin/sc-daprofiler.py` is missing** (was untracked, deleted in prior sync; in `.backup/`). The committed `bin/install-daprofiler.sh` references it and errors without it → restore it (fix).
- **`post-receive` does not exist** → write from scratch.
- Local toolchain: py3.13, tomllib+flock present, **no jq/jsonschema**.
- Canonical tools dir for the hook diff = `tools/`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `docs/INTEGRATION_CONTRACT.md` | Human-readable contract (the 10 required definitions) |
| `schema/tool.manifest.schema.json` | JSON Schema for `tool.manifest.json` |
| `schema/io.envelope.schema.json` | JSON Schema for the runtime I/O envelope |
| `tools/cf-validate/` | Conforming **worked example** = offline Italian Codice Fiscale validator (real capability, no network, selftest passes, `gate_approved=true`) |
| `tools/_template/` | Copy-me skeleton (placeholders, `gate_approved=false`) |
| `tools/lib/sctool.py` | Shared helper lib: envelope builder, Admiralty types, arg parsing, selftest harness |
| `bin/sc-registry.py` | Registry CLI (REGISTRY_CMD): `validate/register/deregister/list/index` |
| `bin/sc-daprofiler.py` | Restored daprofiler wrapper (fixes broken installer ref) |
| `post-receive` | Git hook source (installed to atlas `.git/hooks/`) |
| `.claude/agents/hephaestus.md` | Native Hephaestus subagent (model: claude-opus-4-8) |
| `CLAUDE.md` | +§13 Hephaestus, Integration Contract mandatory, GR1/GR2 |

---

## Task 1: Manifest + envelope JSON Schemas (Phase 2 machine-readable)

**Files:** Create `schema/tool.manifest.schema.json`, `schema/io.envelope.schema.json`.

- [ ] Write `schema/tool.manifest.schema.json` (draft 2020-12). Required: `manifest_version, name, version(semver), category(enum: domain/network/person/social/geoint/image/document/breach/infrastructure/email/phone/username/threatint/cloud/code-repo/crypto/dark-web/italian-specific), description, provenance{upstream_url,pinned_commit}, license, reliability(enum A-F), confidence(enum 1-6), maintainer, added_by, added_at, runtime, deps, install_method, capabilities[], io{input_schema,output_envelope}, safety{network_egress,rate_limits,touches_real_targets,tos_notes,sandbox_required}, gate_approved(bool)`.
- [ ] Write `schema/io.envelope.schema.json`: `{schema_version, tool, tool_version, timestamp, input, results[]{type,value,reliability,confidence,sources[]}, errors[], audit{run_id,selftest,duration_ms}}`.
- [ ] Verify both are valid JSON: `python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('schema/*.json')];print('OK')"` → Expected: `OK`.
- [ ] Commit: `chore(contract): add tool.manifest + io.envelope JSON schemas`.

## Task 2: Shared tool library `tools/lib/sctool.py`

**Files:** Create `tools/lib/sctool.py`, `tools/lib/__init__.py`.

- [ ] Implement: `AdmiraltyReliability`/`AdmiraltyCredibility` constants; `build_envelope(tool, version, input_echo, results, errors, run_id, selftest, duration_ms)`; `result(type,value,reliability,confidence,sources)`; `base_argparser(prog,desc)` adding `--config/--selftest/--json`; `emit(envelope, as_json)`; `run_selftest(fn)` returning exit 0/1. No third-party imports.
- [ ] Self-check: `python3 -c "import sys;sys.path.insert(0,'tools/lib');import sctool;print(sctool.build_envelope('x','1',{}, [],[],'r',True,1)['tool'])"` → `x`.
- [ ] Commit: `feat(contract): shared sctool envelope/admiralty helper lib`.

## Task 3: Conforming worked example `tools/cf-validate/`

**Files:** Create `tools/cf-validate/{tool.manifest.json,sc-cf-validate.py,install.sh,README.md,tests/test_selftest.sh}`.

- [ ] Implement `sc-cf-validate.py`: offline Italian Codice Fiscale checksum validator (the official odd/even char tables + control char). Uniform CLI (`--config/--selftest/--json`); emits envelope; reliability `A`, credibility `1` for a deterministic algorithmic check. `--selftest` validates a known-good CF (e.g. `RSSMRA85T10A562S`) and a known-bad one, offline. Exit 0 valid / 1 invalid CF / 2 usage / selftest: 0 pass.
- [ ] `tool.manifest.json`: category `italian-specific`, `safety.network_egress=false`, `touches_real_targets=false`, `sandbox_required=false`, `gate_approved=true` (offline first-party).
- [ ] `install.sh`: mirror `install-daprofiler.sh` (no upstream clone needed; symlink wrapper to `~/.local/bin/sc-cf-validate`).
- [ ] Run selftest: `python3 tools/cf-validate/sc-cf-validate.py --selftest --json` → Expected: exit 0, envelope `audit.selftest=true`, no errors.
- [ ] Validate manifest against schema via the CLI once Task 5 lands (revisit).
- [ ] Commit: `feat(tool): cf-validate — offline Codice Fiscale validator (contract reference impl)`.

## Task 4: Copy-me template `tools/_template/`

**Files:** Create `tools/_template/{tool.manifest.json,sc-TEMPLATE.py,install.sh,README.md,tests/test_selftest.sh}`.

- [ ] Skeleton mirroring cf-validate with `__PLACEHOLDER__` markers; `gate_approved=false`; `--selftest` returns a trivial pass so a freshly-copied tool starts green.
- [ ] Verify selftest of the raw template passes offline: `python3 tools/_template/sc-TEMPLATE.py --selftest --json` → exit 0.
- [ ] Commit: `feat(contract): conforming tool scaffold template`.

## Task 5: Registry CLI `bin/sc-registry.py` (Phase 2 item 9, REGISTRY_CMD)

**Files:** Create `bin/sc-registry.py`. Index at `~/.strikecore/registry/index.json`.

- [ ] Implement subcommands (stdlib only; `jsonschema` used if importable else structural validation reading the schema's required/enum/type):
  - `validate <tool-dir|manifest>` → exit 0 ok / 3 invalid (prints reasons).
  - `register <tool-dir>` → validate, then add/replace entry in index (name,version,category,capabilities,gate_approved,manifest_path,registered_at). Refuses `gate_approved=false` unless `--force-pending` (records as pending, not active).
  - `deregister <name>` → remove from index.
  - `list [--json]` → show registered tools.
  - `index --tools-dir tools` → bulk re-scan/rebuild.
- [ ] Append-only audit line per mutation to `~/.strikecore/audit/YYYY-MM-DD.jsonl` with SHA-256 over the entry (match `intel_team` shape: `{ts,component:"sc-registry",event,name,...,hash}`).
- [ ] Test: `python3 bin/sc-registry.py validate tools/cf-validate && python3 bin/sc-registry.py register tools/cf-validate && python3 bin/sc-registry.py list` → cf-validate listed; `register` of `_template` (gate_approved=false) without `--force-pending` → exit non-zero "pending manual gate".
- [ ] Re-validate Task 3/4 manifests now. Commit: `feat(registry): sc-registry CLI (validate/register/deregister/list/index)`.

## Task 6: `post-receive` hook (Phase 4)

**Files:** Create `post-receive` (repo root).

- [ ] Bash, `set -euo pipefail`. Behavior: read stdin `oldrev newrev refname` lines; `unset GIT_DIR`; act on work tree (post `updateInstead`); only proceed for `DEPLOY_BRANCH` (default `main`). Compute changed files `git diff --name-only oldrev..newrev -- "$TOOLS_DIR"` handling new-branch (oldrev all-zeros → diff against empty tree `4b825dc...`) and deletion (newrev all-zeros → exit 0). Derive affected tool dirs. For each: parse `tool.manifest.json` with **python3** (no jq); if `gate_approved==true` run `--selftest --json` (via the tool's entrypoint) and on pass call `REGISTRY_CMD register <dir>`; if `gate_approved!=true` print "FLAGGED for manual gate — not auto-run" (enforces H3, never selftest/register). `flock` a lockfile for concurrent pushes. Append-only audit log `~/.strikecore/audit/hook-deploy.log`. Report per-tool status to the pushing client (stdout). Resolve `REGISTRY_CMD` (`bin/sc-registry.py`) and warn if absent.
- [ ] `bash -n post-receive` → Expected: no output (syntax OK).
- [ ] Commit: `feat(deploy): post-receive hook — gated selftest + registry on push`.

## Task 7: Restore `bin/sc-daprofiler.py` (fix broken installer ref)

**Files:** Restore `bin/sc-daprofiler.py` from `.backup/<ts>/files/bin/sc-daprofiler.py`.

- [ ] Copy back, `chmod +x`. Verify `python3 bin/sc-daprofiler.py --help` exits 0.
- [ ] Commit: `fix(tools): restore sc-daprofiler.py wrapper referenced by installer`.

## Task 8: Hephaestus subagent `.claude/agents/hephaestus.md` (Phase 3)

**Files:** Create `.claude/agents/hephaestus.md`.

- [ ] Frontmatter: `name: hephaestus`, `description:` (toolsmith; discovers/builds/integrates OSINT tooling), `tools: Read, Grep, Glob, Bash, Write, Edit, WebSearch, WebFetch`, `model: claude-opus-4-8`. Body encodes the 7 R&D doctrine points: GitHub discovery + Admiralty scoring of candidates; deep research (fable-5 for heavy reasoning; cite official sources; separate facts from recommendations); gap analysis; integrate/fork/write decision; implement strictly per `docs/INTEGRATION_CONTRACT.md`; gates H1/H3 + Git-only GR1; document+register every tool with provenance. Reference the contract + `tools/_template/`.
- [ ] Verify frontmatter parses: `python3 - <<'PY'` reads the file, splits `---`, asserts keys present.
- [ ] Commit: `feat(agent): add Hephaestus OSINT toolsmith subagent`.

## Task 9: Integration Contract doc `docs/INTEGRATION_CONTRACT.md` (Phase 2 human spec)

**Files:** Create `docs/INTEGRATION_CONTRACT.md`.

- [ ] Document all 10 required sections (dir layout mirroring daprofiler→`tools/<name>/`; manifest field-by-field; CLI interface + exit codes; I/O envelope + Admiralty propagation; config/secrets via env; safety/sandbox + H1/H3/H4 gates aligned to existing executor/proxy; logging/audit format; `--selftest` no-real-targets; registry entry format + (de)register via `sc-registry.py` shipping through Git; lifecycle install/update-by-repin/deprecate as Git ops). Cross-link schemas + cf-validate example. State GR1 (git-only) + GR2 (hook exception) + GR4 (sandbox doctrine, honest about allowlist-not-jail).
- [ ] Commit: `docs(contract): INTEGRATION_CONTRACT.md — mandatory tool integration spec`.

## Task 10: Wire doctrine into CLAUDE.md (Phase 6)

**Files:** Modify `CLAUDE.md` (append new section; do NOT touch preserved §2/§3/§8).

- [ ] Add §13 "Hephaestus & the Integration Contract": declare Hephaestus + its place in the intelligence cycle (Collection-tooling R&D), make the Integration Contract mandatory for all new tools, state GR1 (Git-only deployment) + GR2 (post-receive hook is the sanctioned on-atlas exception). Link contract + schemas + registry CLI.
- [ ] Commit: `docs(doctrine): declare Hephaestus, mandatory integration contract, GR1/GR2`.

## Task 11: Push to atlas (GR1) + install hook on atlas (Phase 5)

- [ ] Verify atlas repo path + `receive.denyCurrentBranch`; set to `updateInstead` if unset (adapt per GR1; document).
- [ ] `git push origin main` (all commits). Confirm `updateInstead` updated the server work tree.
- [ ] Pre-flight atlas: `bash -n` local hook; confirm atlas has bash, flock, python3 (jq optional). If a system install would be needed → **H2 STOP**.
- [ ] Backup existing hook → `post-receive.bak.<UTC>`; transfer local `post-receive`; `cp` to `<repo>/.git/hooks/post-receive`; `chmod +x`.
- [ ] Verify: `ls -l` executable; `head` matches local; `bash -n` on installed file; print resolved `DEPLOY_BRANCH/TOOLS_DIR/REGISTRY_CMD`; flag if `REGISTRY_CMD` missing on atlas. Do NOT trigger a real deploy/selftest.

## Task 12: Final report

- [ ] Produce: discovery summary, files created, contract+schemas, subagent, hook install result, dep/config warnings, changelog.

---

## Self-Review notes
- H1 (run untrusted upstream vs REAL targets), H2 (atlas system installs), H3 (register un-gated tool), H4 (irreversible prod beyond push+hook) are the only stops. cf-validate is first-party + offline → no H1/H3 trip. Hook install = sanctioned GR2.
- Internal Postgres model-routing wiring intentionally OUT of scope (Hephaestus uses native CC `model:` frontmatter). Noted as follow-up.
- Restoring sc-daprofiler.py is a coherence fix for the already-committed installer; flagged in final report.
