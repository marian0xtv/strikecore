"""Regression test: TroubleshootAgent._extract_target() must not pick a
value out of a trailing multi-value flag as the OSINT target.

Root cause (see investigation): the previous implementation walked the
command tokens in reverse and returned the first one not starting with "-"
or "/". For a command like
`socialscan mohameddn ... --platforms twitter spotify github instagram`,
that reverse walk hit "instagram" (a value of --platforms) before ever
reaching the real target, so the auto-generated fix silently searched for
the wrong identity instead of crashing loudly.
"""
from core.troubleshoot_agent import TroubleshootAgent


def test_extract_target_skips_trailing_multivalue_flag():
    agent = TroubleshootAgent()
    cmd = (
        "socialscan mohamed.d.n.2002 mohameddn mohamed.abouelseod "
        "mohamedaboueleseod --platforms twitter spotify github instagram"
    )
    assert agent._extract_target(cmd) == "mohamed.d.n.2002"


def test_extract_target_positional_style():
    agent = TroubleshootAgent()
    assert (
        agent._extract_target("sherlock mohameddn --print-found --timeout 10")
        == "mohameddn"
    )
    assert (
        agent._extract_target("maigret mohameddn --timeout 8 --no-color")
        == "mohameddn"
    )


def test_extract_target_flag_argument_style():
    agent = TroubleshootAgent()
    assert agent._extract_target("blackbird -u mohameddn") == "mohameddn"
    assert agent._extract_target("h8mail -t someone@example.com") == "someone@example.com"


def test_diagnose_socialscan_bad_platform_generates_correct_fix():
    agent = TroubleshootAgent()
    cmd = (
        "socialscan mohamed.d.n.2002 mohameddn mohamed.abouelseod "
        "mohamedaboueleseod --platforms twitter spotify github instagram"
    )
    diagnosis = agent.diagnose(
        "socialscan", cmd, "ValueError: spotify is not a valid platform", 1
    )
    assert diagnosis is not None
    assert diagnosis.fix_command == "sherlock mohamed.d.n.2002 --print-found --timeout 10"
