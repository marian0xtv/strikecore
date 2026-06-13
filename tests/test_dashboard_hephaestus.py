import importlib.util
from pathlib import Path
import pytest

pytest.importorskip("flask")  # dashboard requires Flask; skip where absent

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "sc_dashboard", _REPO / "osint_agent" / "dashboard" / "app.py")
dash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dash)


@pytest.fixture
def client():
    dash.app.config["TESTING"] = True
    return dash.app.test_client()


def test_hephaestus_route_ok_when_empty(client, monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "_HEPH_RUNS_DIR", tmp_path / "empty", raising=False)
    resp = client.get("/hephaestus")
    assert resp.status_code == 200
    assert b"Hephaestus" in resp.data
