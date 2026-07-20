"""Regression test: PYTHONPATH must not leak from the StrikeCore process into
subprocesses launched by Executor.

Root cause (see investigation): the toolbox container sets PYTHONPATH=/app so
StrikeCore's own process can import core/config. Executor previously copied
os.environ verbatim into every subprocess it spawned, so third-party OSINT
tools that ship their own top-level `config` module (blackbird, photon,
osintgram, ...) had that module shadowed by StrikeCore's own empty
`/app/config` package, crashing with AttributeError on tool-specific config
symbols (e.g. blackbird's `config.LOG_PATH`).
"""
import os

import pytest

from core.executor import Executor


@pytest.mark.asyncio
async def test_execute_strips_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/app")
    executor = Executor()
    result = await executor.execute("echo PYTHONPATH=[$PYTHONPATH]", validate=False)
    assert result.stdout.strip() == "PYTHONPATH=[]"


@pytest.mark.asyncio
async def test_execute_respects_explicit_pythonpath_override(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/app")
    executor = Executor()
    result = await executor.execute(
        "echo PYTHONPATH=[$PYTHONPATH]",
        env={"PYTHONPATH": "/custom"},
        validate=False,
    )
    assert result.stdout.strip() == "PYTHONPATH=[/custom]"


@pytest.mark.asyncio
async def test_execute_background_strips_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", "/app")
    executor = Executor()
    out_file = tmp_path / "out.txt"
    pid = await executor.execute_background(
        f"echo PYTHONPATH=[$PYTHONPATH] > {out_file}", validate=False
    )
    assert pid > 0
    # Give the background shell a moment to write its output.
    import asyncio

    for _ in range(50):
        if out_file.exists() and out_file.read_text().strip():
            break
        await asyncio.sleep(0.1)
    assert out_file.read_text().strip() == "PYTHONPATH=[]"
