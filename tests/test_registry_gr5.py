import json
import importlib.util
from pathlib import Path
import argparse
import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("sc_registry", _REPO / "bin" / "sc-registry.py")
sc_registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc_registry)


def _manifest(name, added_by):
    return {
        "name": name, "version": "0.1.0", "category": "socint",
        "capabilities": ["x"], "entrypoint": "sc-x.py",
        "provenance": {"upstream_url": "https://example/x", "pinned_commit": "abc1234"},
        "added_by": added_by, "gate_approved": True,
        "io": {"input_schema": "schema/io.envelope.schema.json",
               "output_envelope": "schema/io.envelope.schema.json"},
    }


def _write_tool(tmp_path, name, added_by):
    d = tmp_path / name
    d.mkdir()
    (d / "tool.manifest.json").write_text(json.dumps(_manifest(name, added_by)))
    return d


def _args(target, override=None, force_pending=False):
    return argparse.Namespace(target=str(target), operator_override=override,
                              force_pending=force_pending)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sc_registry, "_INDEX_PATH", tmp_path / "index.json", raising=False)
    monkeypatch.setattr(sc_registry, "_AUDIT_DIR", tmp_path / "audit", raising=False)
    monkeypatch.setattr(sc_registry, "_validate_manifest", lambda m: [])


def test_hephaestus_originated_registers(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    d = _write_tool(tmp_path, "tool-h", "hephaestus")
    rc = sc_registry.cmd_register(_args(d))
    assert rc == sc_registry.EXIT_OK
    assert "REGISTERED" in capsys.readouterr().out


def test_non_hephaestus_refused(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    d = _write_tool(tmp_path, "tool-o", "operator")
    rc = sc_registry.cmd_register(_args(d))
    assert rc == sc_registry.EXIT_NOTFOUND
    err = capsys.readouterr().err
    assert "GR5" in err or "hephaestus" in err.lower()


def test_operator_override_registers_and_audits(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(sc_registry, "_audit",
                        lambda ev, name, payload: events.append((ev, name, payload)))
    d = _write_tool(tmp_path, "tool-o2", "operator")
    rc = sc_registry.cmd_register(_args(d, override="manual first-party import"))
    assert rc == sc_registry.EXIT_OK
    assert any(ev == "register_override" for ev, _, _ in events)
