#!/usr/bin/env python3
"""sc-__TOOLNAME__ — __ONE_LINE_DESCRIPTION__.

TEMPLATE. Copy this directory to tools/<your-tool>/ and:
  1. rename this file sc-<your-tool>.py and set TOOL/VERSION below;
  2. implement run() to do the real work and emit results via sctool.result(...)
     with honest NATO Admiralty reliability (A-F) + credibility (1-6) + sources;
  3. implement _selftest_check() to exercise the tool OFFLINE (no real targets);
  4. fill tool.manifest.json (keep gate_approved=false until the manual gate);
  5. wire install.sh; run: python3 sc-<your-tool>.py --selftest --json

Exit codes: 0 success · 1 failure · 2 usage · 3 internal (per contract).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# locate the shared contract lib (tools/lib/sctool.py)
_LIB = Path(__file__).resolve().parent.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import sctool  # noqa: E402

TOOL = "__TOOLNAME__"
VERSION = "0.1.0"


def run(target: str) -> tuple[bool, list[dict], list[dict]]:
    """Do the real work. Return (ok, results, errors).

    Replace this stub. Each result MUST carry honest Admiralty scoring.
    Remember CLAUDE.md §3.4: never emit a phone-type result from a
    non-phone tool.
    """
    results = [sctool.result(
        "stub",
        {"echo": target},
        sctool.RELIABILITY_F,            # unknown until you implement it
        sctool.CREDIBILITY_CANNOT_JUDGE,
        [],
    )]
    return True, results, []


def _selftest_check() -> tuple[bool, list[dict], list[dict]]:
    """OFFLINE self-test. Must not touch real targets. Replace with real checks."""
    res = [sctool.result(
        "selftest", {"ok": True},
        sctool.RELIABILITY_A, sctool.CREDIBILITY_CONFIRMED, [],
    )]
    return True, res, []


def main(argv: list[str] | None = None) -> int:
    parser = sctool.base_argparser("sc-__TOOLNAME__", "__ONE_LINE_DESCRIPTION__")
    parser.add_argument("target", nargs="?", help="The thing to act on.")
    args = parser.parse_args(argv)

    if args.selftest:
        return sctool.run_selftest(TOOL, VERSION, _selftest_check)

    if not args.target:
        parser.print_usage(sys.stderr)
        sys.stderr.write("sc-__TOOLNAME__: error: provide a target\n")
        return sctool.EXIT_USAGE

    run_id = sctool.new_run_id()
    start = time.monotonic()
    ok, results, errors = run(args.target)
    duration_ms = int((time.monotonic() - start) * 1000)
    env = sctool.build_envelope(
        TOOL, VERSION, {"target": args.target},
        results, errors, run_id, False, duration_ms, target=args.target,
    )
    sctool.emit(env)
    return sctool.EXIT_OK if ok else sctool.EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
