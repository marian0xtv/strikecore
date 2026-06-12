"""Hephaestus run-record builder + validator (stdlib only).

Validates against schema/hephaestus.run_record.schema.json using the same
schema-subset validator used by bin/sc-registry.py (jsonschema if present, else
a built-in checker), so run records are guaranteed contract-conformant before
they reach the CLI / dashboard.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _REPO_ROOT / "schema" / "hephaestus.run_record.schema.json"
RUNS_DIR = Path.home() / ".strikecore" / "hephaestus" / "runs"


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
        errors.append(f"{path}: expected {t}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: !~ /{schema['pattern']}/")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: > {schema['maximum']}")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing '{req}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errors.append(f"{path}: unexpected '{k}'")
        for k, sub in props.items():
            if k in value:
                _validate_subset(value[k], sub, f"{path}.{k}", errors)
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate_subset(item, item_schema, f"{path}[{i}]", errors)


def validate(record: dict) -> list[str]:
    """Return a list of validation errors ([] == valid)."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
        v = jsonschema.Draft202012Validator(schema)
        return [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                for e in v.iter_errors(record)]
    except ImportError:
        errors: list[str] = []
        _validate_subset(record, schema, "run", errors)
        return errors


def save(record: dict) -> Path:
    """Write a run record to ~/.strikecore/hephaestus/runs/<run_id>.json."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def list_runs() -> list[Path]:
    """Newest-first list of saved run-record files."""
    if not RUNS_DIR.exists():
        return []
    return sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def model_usage_from_cost(cost: dict) -> list[dict]:
    """Convert ProviderRouter.run_cost() into the run-record model_usage[] shape."""
    rows = []
    for task_type, info in (cost.get("by_task_type") or {}).items():
        rows.append({
            "task_type": task_type,
            "model": info.get("model", ""),
            "reason": info.get("reason", ""),
            "calls": int(info.get("calls", 0)),
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_micros": int(info.get("cost_micros", 0)),
        })
    return rows
