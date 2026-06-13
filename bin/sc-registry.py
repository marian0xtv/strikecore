#!/usr/bin/env python3
"""sc-registry — StrikeCore tool registry CLI (Integration Contract §9).

The registry is an OVERLAY keyed off the committed tool manifests — it does
NOT mutate the §10-protected core/tool_registry.py _TOOLS list or
core/executor.py ALLOWED_BINARIES. Registry state ships via Git (GR1): the
manifests are the source of truth; this CLI validates them and maintains a
runtime index at ~/.strikecore/registry/index.json.

The post-receive hook (deploy) calls `register` on gate_approved=true tools.

Subcommands:
    validate <tool-dir|manifest>     check a manifest against the schema
    register <tool-dir> [--force-pending]
                                     validate then add/replace in the index
                                     (refuses gate_approved=false unless --force-pending,
                                      which records it as pending/inactive)
    deregister <name>                remove from the index
    list [--json]                    show registered tools
    index [--tools-dir tools]        bulk re-scan & rebuild the index

Exit codes: 0 ok · 1 not-found/refused · 2 usage · 3 invalid manifest.
Pure standard library. Uses `jsonschema` if importable, else a built-in
schema-subset validator sufficient for the contract schemas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _REPO_ROOT / "schema" / "tool.manifest.schema.json"
_DEFAULT_TOOLS_DIR = _REPO_ROOT / "tools"

_HOME = Path.home()
_INDEX_PATH = Path(
    __import__("os").environ.get(
        "SC_REGISTRY_INDEX", str(_HOME / ".strikecore" / "registry" / "index.json")
    )
)
_AUDIT_DIR = _HOME / ".strikecore" / "audit"

EXIT_OK = 0
EXIT_NOTFOUND = 1
EXIT_USAGE = 2
EXIT_INVALID = 3

_SKIP_DIRS = {"lib"}  # plus any dir starting with "_" (template/internal)


# --------------------------------------------------------------------------- #
# Minimal JSON-Schema-subset validator (fallback when jsonschema is absent)
# --------------------------------------------------------------------------- #
def _type_ok(value, t: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, bool) is False and isinstance(value, int),
        "number": isinstance(value, bool) is False and isinstance(value, (int, float)),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(t, True)


def _validate_subset(value, schema: dict, path: str, errors: list[str]) -> None:
    t = schema.get("type")
    if t and not _type_ok(value, t):
        errors.append(f"{path}: expected type {t}")
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match /{schema['pattern']}/")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: > maximum {schema['maximum']}")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required '{req}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errors.append(f"{path}: unexpected property '{k}'")
        for k, sub in props.items():
            if k in value:
                _validate_subset(value[k], sub, f"{path}.{k}", errors)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate_subset(item, item_schema, f"{path}[{i}]", errors)


def _validate_manifest(manifest: dict) -> list[str]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
        validator = jsonschema.Draft202012Validator(schema)
        return [
            f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in validator.iter_errors(manifest)
        ]
    except ImportError:
        errors: list[str] = []
        _validate_subset(manifest, schema, "manifest", errors)
        return errors


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_manifest(target: Path) -> tuple[dict | None, Path | None, str]:
    """Resolve a tool dir or manifest file to (manifest, manifest_path, err)."""
    if target.is_dir():
        mp = target / "tool.manifest.json"
    else:
        mp = target
    if not mp.exists():
        return None, None, f"no tool.manifest.json at {mp}"
    try:
        return json.loads(mp.read_text(encoding="utf-8")), mp, ""
    except json.JSONDecodeError as exc:
        return None, mp, f"invalid JSON in {mp}: {exc}"


def _load_index() -> dict:
    if _INDEX_PATH.exists():
        try:
            return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"schema_version": 1, "tools": {}}


def _save_index(index: dict) -> None:
    _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _audit(event: str, name: str, payload: dict) -> None:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now(),
            "component": "sc-registry",
            "event": event,
            "name": name,
            **payload,
        }
        entry["hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        path = _AUDIT_DIR / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # audit is best-effort, never blocks


def _entry_from_manifest(manifest: dict, manifest_path: Path, pending: bool) -> dict:
    try:
        rel = str(manifest_path.resolve().relative_to(_REPO_ROOT))
    except ValueError:
        rel = str(manifest_path.resolve())
    return {
        "name": manifest["name"],
        "version": manifest["version"],
        "category": manifest["category"],
        "capabilities": manifest.get("capabilities", []),
        "entrypoint": manifest.get("entrypoint"),
        "gate_approved": bool(manifest.get("gate_approved")),
        "pending": pending,
        "manifest_path": rel,
        "registered_at": _now(),
    }


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_validate(args) -> int:
    manifest, mp, err = _load_manifest(Path(args.target))
    if err:
        print(f"INVALID: {err}", file=sys.stderr)
        return EXIT_INVALID
    errors = _validate_manifest(manifest)
    if errors:
        print(f"INVALID: {mp}", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return EXIT_INVALID
    print(f"OK: {manifest['name']} v{manifest['version']} ({mp})")
    return EXIT_OK


def cmd_register(args) -> int:
    manifest, mp, err = _load_manifest(Path(args.target))
    if err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return EXIT_INVALID
    errors = _validate_manifest(manifest)
    if errors:
        print(f"REFUSED: manifest invalid ({mp})", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return EXIT_INVALID

    gate = bool(manifest.get("gate_approved"))
    if not gate and not args.force_pending:
        print(
            f"REFUSED: {manifest['name']} has gate_approved=false "
            f"(pending manual sandbox gate, H3). "
            f"Use --force-pending to record as inactive.",
            file=sys.stderr,
        )
        _audit("register_refused", manifest["name"],
               {"reason": "gate_not_approved"})
        return EXIT_NOTFOUND

    # GR5 — Hephaestus-mediated integration. New tools must originate from a
    # Hephaestus run unless the operator explicitly overrides (audited).
    index = _load_index()
    already_registered = manifest["name"] in index.get("tools", {})
    added_by = str(manifest.get("added_by", "")).strip().lower()
    heph_originated = added_by.startswith("hephaestus")
    override = getattr(args, "operator_override", None)
    if not heph_originated and not already_registered and not override:
        print(
            f"REFUSED: {manifest['name']} violates GR5 (Hephaestus-mediated "
            f"integration): added_by={added_by or 'none'} is not a Hephaestus run. "
            f"Run it through the toolsmith (console: hephaestus run --focus <cat>) "
            f"or re-run with --operator-override \"<reason>\".",
            file=sys.stderr,
        )
        _audit("register_refused", manifest["name"],
               {"reason": "gr5_not_hephaestus_originated", "added_by": added_by})
        return EXIT_NOTFOUND
    if override and not heph_originated and not already_registered:
        _audit("register_override", manifest["name"],
               {"reason": str(override), "added_by": added_by})

    pending = not gate  # registered but inactive
    entry = _entry_from_manifest(manifest, mp, pending)
    index.setdefault("tools", {})[manifest["name"]] = entry
    _save_index(index)
    _audit("registered", manifest["name"],
           {"version": manifest["version"], "gate_approved": gate,
            "pending": pending})
    state = "PENDING (inactive)" if pending else "ACTIVE"
    print(f"REGISTERED: {manifest['name']} v{manifest['version']} [{state}]")
    return EXIT_OK


def cmd_deregister(args) -> int:
    index = _load_index()
    if args.name not in index.get("tools", {}):
        print(f"NOT FOUND: {args.name}", file=sys.stderr)
        return EXIT_NOTFOUND
    del index["tools"][args.name]
    _save_index(index)
    _audit("deregistered", args.name, {})
    print(f"DEREGISTERED: {args.name}")
    return EXIT_OK


def cmd_list(args) -> int:
    index = _load_index()
    tools = index.get("tools", {})
    if args.json:
        print(json.dumps(index, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not tools:
        print("(no tools registered)")
        return EXIT_OK
    for name, e in sorted(tools.items()):
        state = "pending" if e.get("pending") else "active"
        print(f"{name:<24} v{e['version']:<10} {e['category']:<16} "
              f"[{state}]  {','.join(e.get('capabilities', []))}")
    return EXIT_OK


def cmd_index(args) -> int:
    tools_dir = Path(args.tools_dir).resolve()
    if not tools_dir.is_dir():
        print(f"no such tools dir: {tools_dir}", file=sys.stderr)
        return EXIT_USAGE
    registered, skipped, refused = 0, 0, 0
    for child in sorted(tools_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name in _SKIP_DIRS:
            continue
        if not (child / "tool.manifest.json").exists():
            continue
        ns = argparse.Namespace(target=str(child), force_pending=False,
                                operator_override=None)
        rc = cmd_register(ns)
        if rc == EXIT_OK:
            registered += 1
        elif rc == EXIT_NOTFOUND:
            refused += 1  # gate-pending
        else:
            skipped += 1  # invalid
    print(f"index: {registered} registered, {refused} pending-gate, "
          f"{skipped} invalid")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sc-registry",
                                description="StrikeCore tool registry CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sv = sub.add_parser("validate", help="validate a manifest")
    sv.add_argument("target")
    sv.set_defaults(func=cmd_validate)

    sr = sub.add_parser("register", help="validate + add to index")
    sr.add_argument("target")
    sr.add_argument("--force-pending", action="store_true",
                    help="record a gate_approved=false tool as inactive/pending")
    sr.add_argument("--operator-override", default=None, metavar="REASON",
                    help="GR5 escape hatch: register a non-Hephaestus-originated "
                         "tool; REASON is written to the audit chain")
    sr.set_defaults(func=cmd_register)

    sd = sub.add_parser("deregister", help="remove from index")
    sd.add_argument("name")
    sd.set_defaults(func=cmd_deregister)

    sl = sub.add_parser("list", help="list registered tools")
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=cmd_list)

    si = sub.add_parser("index", help="bulk re-scan tools dir")
    si.add_argument("--tools-dir", default=str(_DEFAULT_TOOLS_DIR))
    si.set_defaults(func=cmd_index)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
