"""Hephaestus — native StrikeCore OSINT toolsmith agent.

A first-class StrikeCore agent (no Claude Code dependency at runtime) that
discovers, researches, gap-analyses and decides on OSINT tooling, consuming the
platform cost-aware LLM router (the "hephaestus" routing profile). It emits a
run record validating against schema/hephaestus.run_record.schema.json and
enforces the H1/H3 sandbox gates by PAUSING and surfacing approval requests.
"""

from hephaestus.agent import Hephaestus

__all__ = ["Hephaestus"]
