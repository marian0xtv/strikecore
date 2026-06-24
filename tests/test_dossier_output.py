"""Tests for the unified dossier output capture (core/dossier_output.py)."""

import sys

import core.dossier_output as do


def test_write_and_iter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(do, "OUTPUT_DIR", tmp_path)
    run_dir = do.new_run_dir("Mario Rossi", "console")
    written = do.write_run(
        run_dir,
        meta={"source": "console", "target": "Mario Rossi"},
        dossier_json={"target": "Mario Rossi", "findings_by_domain": {"socint": [1]}},
        transcript="line one\nline two\n",
        markdown="# dossier\n",
    )
    assert set(written) == {"dossier.json", "output.log", "meta.json", "dossier.md"}

    runs = do.iter_runs()
    assert len(runs) == 1
    r = runs[0]
    assert r["meta"]["source"] == "console"
    assert r["dossier"]["target"] == "Mario Rossi"
    assert r["log_path"].read_text() == "line one\nline two\n"


def test_iter_runs_limit_and_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(do, "OUTPUT_DIR", tmp_path)
    for i in range(3):
        d = do.new_run_dir(f"t{i}", "intel_team")
        do.write_run(d, meta={"target": f"t{i}"}, dossier_json={"i": i}, transcript="")
    runs = do.iter_runs(limit=2)
    assert len(runs) == 2  # limit honored


def test_tee_stdout_captures_and_passes_through(capsys):
    with do.tee_stdout() as buf:
        print("hello tee")
    out = capsys.readouterr().out
    assert "hello tee" in out          # still reached the terminal
    assert "hello tee" in buf.getvalue()  # and was captured
    assert sys.stdout is not None       # stdout restored


def test_record_console_failure_isolated():
    class FakeConsole:
        def __init__(self):
            self.record = False
        def export_text(self, clear=False):
            return "captured transcript"
    c = FakeConsole()
    with do.record_console(c) as holder:
        assert c.record is True
    assert holder["text"] == "captured transcript"
    assert c.record is False  # restored
