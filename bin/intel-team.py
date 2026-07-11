#!/usr/bin/env python3
"""StrikeCore — Intel Team CLI.

Standalone entry point for the embedded multi-agent intel team. Designed to
be invoked directly:

    ./strikecore/bin/python3 bin/intel-team.py --target alice123 \
        --pir "Is alice123 the same person as alice.smith@example.com?"

It does **not** replace the existing ``cli/shell.py`` REPL; it provides a
batch-mode CLI suitable for scripting and for the eventual integration into
the shell as the ``intel-team`` command.

Output: writes a Markdown dossier to
``~/strikecore-data/reports/intel_team/<UTC>_<target>_<pir_id>.md`` and a
JSON twin alongside it. Returns exit 0 on success, 1 on pipeline error,
2 on usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on the path so 'core.*' / 'intel_team.*' resolve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# --- Optional: load .env so ANTHROPIC_API_KEY override works ---------------
# Uses stdlib only to avoid a hard dependency on python-dotenv.

def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass

_load_dotenv(_ROOT / ".env")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="strikecore-intel-team",
        description="Run the embedded intel team against a Priority Intelligence Requirement.",
    )
    parser.add_argument("--target", required=True, help="Subject (handle / email / phone / domain / name)")
    parser.add_argument("--pir", required=True, help="Priority Intelligence Requirement question")
    parser.add_argument("--domains", default="", help="Comma-separated domain hints (socint,geoint,…)")
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Constraint key=value (repeatable, e.g. --constraint passive_only=true)",
    )
    parser.add_argument("--operator-notes", default="", help="Free-text notes to pass to the analyst")
    parser.add_argument(
        "--reports-dir",
        default=str(Path.home() / "strikecore-data" / "reports" / "intel_team"),
        help="Where to write the dossier (default: ~/strikecore-data/reports/intel_team/)",
    )
    parser.add_argument("--no-store", action="store_true", help="Do not consult InvestigationStore")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse_constraints(items: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for s in items:
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip()
        if v.lower() in ("true", "false"):
            out[k] = (v.lower() == "true")
        else:
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = v
    return out


async def _amain(args: argparse.Namespace) -> int:
    # Late imports so --help works even if heavy deps are missing
    from config.settings import get_settings
    from core.provider_router import ProviderRouter
    from intel_team import IntelTeam, PIR, Domain

    try:
        from core.investigation_store import InvestigationStore
    except Exception as exc:  # noqa: BLE001
        logging.warning("InvestigationStore unavailable: %s", exc)
        InvestigationStore = None  # type: ignore[assignment]

    settings = get_settings()
    router = ProviderRouter(settings)

    store = None
    if not args.no_store and InvestigationStore is not None:
        try:
            store = InvestigationStore(args.target)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Could not load InvestigationStore(%s): %s", args.target, exc)
            store = None

    domains_hint = []
    for token in (args.domains or "").split(","):
        token = token.strip().lower()
        if not token:
            continue
        try:
            domains_hint.append(Domain(token))
        except ValueError:
            logging.warning("Unknown domain hint %r — ignored", token)

    pir = PIR(
        question=args.pir,
        target=args.target,
        domains_hint=domains_hint,
        constraints=_parse_constraints(args.constraint),
    )

    team = IntelTeam(router, investigation_store=store)

    try:
        from core import dossier_output
    except Exception:  # noqa: BLE001
        dossier_output = None  # type: ignore[assignment]

    print(f"[intel-team] PIR={pir.id} target={pir.target!r}", file=sys.stderr)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if dossier_output is not None:
        with dossier_output.tee_streams() as _cap:
            dossier = await team.investigate(pir, operator_notes=args.operator_notes)
        transcript = _cap.get("text", "")
    else:
        dossier = await team.investigate(pir, operator_notes=args.operator_notes)
        transcript = ""

    # Persist dossier
    reports_dir = Path(args.reports_dir).expanduser()
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_target = "".join(c if c.isalnum() or c in "._-" else "_" for c in pir.target)[:80]
    base = reports_dir / f"{ts}_{safe_target}_{pir.id}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")

    md_path.write_text(dossier.to_markdown(), encoding="utf-8")
    json_path.write_text(json.dumps(dossier.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[intel-team] dossier: {md_path}")
    print(f"[intel-team] dossier-json: {json_path}")
    print(f"[intel-team] bluf: {dossier.bluf[:240]}")

    # Unified dossieroutputs/ mirror for Hephaestus autoimprove (best-effort).
    if dossier_output is not None:
        try:
            run_dir = dossier_output.new_run_dir(pir.target, "intel_team")
            dossier_output.write_run(
                run_dir,
                meta={"source": "intel_team", "target": pir.target,
                      "pir_id": pir.id, "pir": pir.question, "started_at": started,
                      "report_md": str(md_path), "report_json": str(json_path)},
                dossier_json=dossier.to_dict(),
                transcript=transcript,
                markdown=dossier.to_markdown(),
            )
            print(f"[intel-team] dossier-output: {run_dir}")
        except Exception as exc:  # noqa: BLE001
            print(f"[intel-team] dossier-output capture skipped: {exc}", file=sys.stderr)

    # CATEGORICAL STANDARD: leave the dashboard artifacts behind (Report/Graph
    # tabs + GeoMap) for this target, exactly like the console and agent-dossier
    # paths. Enforced centrally; never breaks the run.
    if dossier_output is not None and store is not None:
        try:
            arts = dossier_output.finalize_dashboard_artifacts(
                store, dossier_json=dossier.to_dict())
            if arts.get("report_html"):
                print(f"[intel-team] report-tab: {arts['report_html']}")
            if arts.get("graph_html"):
                print(f"[intel-team] graph-tab: {arts['graph_html']}")
            for _k in ("report_error", "graph_error"):
                if arts.get(_k):
                    print(f"[intel-team] {_k}: {arts[_k]}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[intel-team] dashboard artifacts skipped: {exc}", file=sys.stderr)
    return 0


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        logging.error("intel-team failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
