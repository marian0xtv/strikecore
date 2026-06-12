#!/usr/bin/env python3
"""sc-cf-validate — offline Italian Codice Fiscale validator.

Contract-conformant reference tool for the StrikeCore Integration Contract
(docs/INTEGRATION_CONTRACT.md). It is deliberately:

  * OFFLINE — no network egress, touches no real targets, so it is safe to
    auto-selftest and ship gate_approved=true;
  * DETERMINISTIC — a pure checksum/structure computation, hence Admiralty
    reliability A / credibility 1 on a positive validation;
  * a worked example of the uniform CLI (--config/--selftest/--json), the
    standard exit codes, and the I/O envelope with per-result scoring.

It validates the Codice Fiscale control character (NATO-grade deterministic
check) and decodes birth metadata (year/month/day/gender), tolerating
omocodia (letter-substituted digits).

Usage:
    sc-cf-validate RSSMRA85T10A562S
    sc-cf-validate --json RSSMRA85T10A562S
    sc-cf-validate --selftest

Exit codes: 0 valid · 1 invalid · 2 usage · 3 internal (per contract).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# --- locate the shared contract lib (tools/lib/sctool.py) -------------------
_LIB = Path(__file__).resolve().parent.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import sctool  # noqa: E402

TOOL = "cf-validate"
VERSION = "1.0.0"

# --- Codice Fiscale algorithm tables (Italian Ministry of Finance) ----------
_ODD = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17,
    "8": 19, "9": 21, "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13,
    "G": 15, "H": 17, "I": 19, "J": 21, "K": 2, "L": 4, "M": 18, "N": 20,
    "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14, "U": 16, "V": 10,
    "W": 22, "X": 25, "Y": 24, "Z": 23,
}
_EVEN = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5,
    "G": 6, "H": 7, "I": 8, "J": 9, "K": 10, "L": 11, "M": 12, "N": 13,
    "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19, "U": 20,
    "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
}
# omocodia: digits replaced by letters in numeric positions
_OMOCODIA = {
    "L": "0", "M": "1", "N": "2", "P": "3", "Q": "4",
    "R": "5", "S": "6", "T": "7", "U": "8", "V": "9",
}
_MONTHS = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "H": 6,
    "L": 7, "M": 8, "P": 9, "R": 10, "S": 11, "T": 12,
}
# A..Z, then 6 digits, 1 month letter, 2 digits, 1 letter, 3 digits, 1 check
_FORMAT_LEN = 16


def _control_char(first15: str) -> str:
    total = 0
    for i, ch in enumerate(first15):  # 0-indexed
        # 1-indexed position: odd positions (1,3,..) -> _ODD
        total += _ODD[ch] if (i % 2 == 0) else _EVEN[ch]
    return chr(ord("A") + (total % 26))


def _decode(cf: str) -> dict:
    """Decode birth metadata from a structurally valid CF, resolving omocodia."""
    def deomo(ch: str) -> str:
        return _OMOCODIA.get(ch, ch)

    year = deomo(cf[6]) + deomo(cf[7])
    month_letter = cf[8]
    day_raw = int(deomo(cf[9]) + deomo(cf[10]))
    gender = "F" if day_raw > 40 else "M"
    day = day_raw - 40 if gender == "F" else day_raw
    return {
        "birth_year_2digit": year,
        "birth_month": _MONTHS.get(month_letter),
        "birth_day": day,
        "gender": gender,
        "cadastral_code": cf[11] + deomo(cf[12]) + deomo(cf[13]) + deomo(cf[14]),
    }


def validate(raw: str) -> tuple[bool, dict]:
    """Return (is_valid, decoded_or_reason)."""
    cf = (raw or "").strip().upper().replace(" ", "")
    if len(cf) != _FORMAT_LEN:
        return False, {"reason": f"length must be 16, got {len(cf)}"}
    if not cf.isalnum():
        return False, {"reason": "non-alphanumeric characters present"}
    if any(c not in _ODD for c in cf):
        return False, {"reason": "characters outside the CF alphabet"}
    expected = _control_char(cf[:15])
    if cf[15] != expected:
        return False, {"reason": f"control char mismatch (expected {expected})"}
    if cf[8] not in _MONTHS:
        return False, {"reason": f"invalid month letter {cf[8]!r}"}
    decoded = _decode(cf)
    if decoded["birth_day"] < 1 or decoded["birth_day"] > 31:
        return False, {"reason": "birth day out of range"}
    decoded["codice_fiscale"] = cf
    return True, decoded


def _selftest_check() -> tuple[bool, list[dict], list[dict]]:
    """Offline self-test: a canonical valid CF validates; a mutated one fails."""
    good = "RSSMRA85T10A562S"
    bad = good[:15] + ("X" if good[15] != "X" else "A")
    ok_good, _ = validate(good)
    ok_bad, _ = validate(bad)
    passed = ok_good and not ok_bad
    res = [sctool.result(
        "validation",
        {"good_case": ok_good, "bad_case_rejected": not ok_bad},
        sctool.RELIABILITY_A, sctool.CREDIBILITY_CONFIRMED, [],
    )]
    errs = []
    if not passed:
        errs.append(sctool.error("selftest_failed",
                                 "self-test assertions did not hold"))
    return passed, res, errs


def main(argv: list[str] | None = None) -> int:
    parser = sctool.base_argparser(
        "sc-cf-validate",
        "Offline Italian Codice Fiscale validator (contract reference tool).",
    )
    parser.add_argument("codice_fiscale", nargs="?",
                        help="The Codice Fiscale to validate.")
    args = parser.parse_args(argv)

    if args.selftest:
        return sctool.run_selftest(TOOL, VERSION, _selftest_check)

    if not args.codice_fiscale:
        parser.print_usage(sys.stderr)
        sys.stderr.write("sc-cf-validate: error: provide a Codice Fiscale\n")
        return sctool.EXIT_USAGE

    run_id = sctool.new_run_id()
    start = time.monotonic()
    is_valid, info = validate(args.codice_fiscale)
    duration_ms = int((time.monotonic() - start) * 1000)

    results = [sctool.result(
        "validation",
        {"valid": is_valid, **info},
        # Valid CF = deterministic confirmed; invalid = still a confirmed
        # negative (the algorithm is authoritative), hence A/1 either way.
        sctool.RELIABILITY_A, sctool.CREDIBILITY_CONFIRMED, [],
    )]
    env = sctool.build_envelope(
        TOOL, VERSION,
        {"codice_fiscale": args.codice_fiscale.strip().upper()},
        results, [], run_id, False, duration_ms,
    )
    sctool.emit(env)
    return sctool.EXIT_OK if is_valid else sctool.EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
