import importlib
import pytest
from cli import shell as shell_mod
from hephaestus import cli_core


def _bare_shell():
    # Avoid heavy __init__ (settings/NLP); we only test the command method.
    return shell_mod.StrikeCoreShell.__new__(shell_mod.StrikeCoreShell)


def test_command_registered():
    assert "hephaestus" in shell_mod.StrikeCoreShell._commands
    assert "/hephaestus" in shell_mod.StrikeCoreShell._commands
    assert "hephaestus" in shell_mod._ALL_COMMANDS


def test_help_table_has_hephaestus():
    cmds = {row[0] for row in shell_mod._COMMAND_HELP}
    assert "hephaestus" in cmds


def test_status_subcommand_lists_runs(monkeypatch, capsys):
    monkeypatch.setattr(cli_core, "list_runs", lambda: [
        {"run_id": "heph-1", "status": "completed",
         "params": {"focus_category": "voip"},
         "totals": {"cost_usd_micros": 1200},
         "started_at": "2026-06-12T00:00:00+00:00",
         "pending_approvals": []}
    ])
    sh = _bare_shell()
    sh._cmd_hephaestus(["status"])
    out = capsys.readouterr().out
    assert "heph-1" in out and "voip" in out


def test_run_subcommand_requires_focus(monkeypatch, capsys):
    sh = _bare_shell()
    sh._cmd_hephaestus(["run"])  # missing --focus
    out = capsys.readouterr().out
    assert "focus" in out.lower()


def test_approve_reports_error(monkeypatch, capsys):
    monkeypatch.setattr(cli_core, "approve_gate",
                        lambda rid, gate: {"ok": False, "error": "no such run: x", "remaining": 0})
    sh = _bare_shell()
    sh._cmd_hephaestus(["approve", "x", "H1"])
    out = capsys.readouterr().out
    assert "no such run" in out
