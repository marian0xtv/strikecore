import io
from hephaestus.reporting import RunReporter, NullReporter, StreamReporter


class _FakeIn:
    def __init__(self, line="", tty=True):
        self._line, self._tty = line, tty
    def isatty(self): return self._tty
    def readline(self): return self._line


def test_null_reporter_defers_gates():
    r = NullReporter()
    assert r.request_gate({"gate": "H1", "reason": "x"}) is False
    # no-op methods don't raise
    r.phase("discovery"); r.info("x"); r.stream_start("l", "m")
    r.stream_delta("t"); r.stream_end(); r.gate_result({"gate": "H1"}, False, None)


def test_stream_reporter_writes_phases_and_streams():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn())
    r.phase("discovery", "voip")
    r.stream_start("research: x", "claude-opus-4-8")
    r.stream_delta("hello")
    r.stream_end()
    text = out.getvalue()
    assert "DISCOVERY" in text and "voip" in text
    assert "claude-opus-4-8" in text and "hello" in text


def test_stream_reporter_approves_on_tty_yes():
    r = StreamReporter(out=io.StringIO(), in_=_FakeIn(line="y\n", tty=True))
    assert r.request_gate({"gate": "H1", "reason": "x"}) is True


def test_stream_reporter_defers_on_tty_no():
    r = StreamReporter(out=io.StringIO(), in_=_FakeIn(line="n\n", tty=True))
    assert r.request_gate({"gate": "H1", "reason": "x"}) is False


def test_stream_reporter_defers_when_not_tty():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn(line="y\n", tty=False))
    assert r.request_gate({"gate": "H3", "reason": "x"}) is False
    assert "non-interactive" in out.getvalue().lower()


def test_gate_result_prints_register_cmd_on_approve():
    out = io.StringIO()
    r = StreamReporter(out=out, in_=_FakeIn())
    r.gate_result({"gate": "H3"}, True, "python3 bin/sc-registry.py register tools/foo")
    assert "sc-registry.py register tools/foo" in out.getvalue()
