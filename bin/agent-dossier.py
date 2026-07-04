#!/usr/bin/env python3
"""StrikeCore — Hermes-style agent dossier CLI (Phase B).

Parallel entry point to ``bin/intel-team.py`` — same outcome (a dossier),
different path (planner / executor / critic / synthesis through the new
``agent/`` package, all persisted to Postgres).

Example:
    ./strikecore/bin/python3 ./bin/agent-dossier.py \
        --target alice123 \
        --pir "Is alice123 the same person as alice.smith@example.com?" \
        --constraint passive_only=true \
        --operator-notes "Phase B smoke"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _load_dotenv(p: Path) -> None:
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv(_ROOT / ".env")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="strikecore-agent-dossier",
                                description="Hermes-style dossier flow entry point")
    p.add_argument("--target", required=True)
    p.add_argument("--pir", required=True)
    p.add_argument("--constraint", action="append", default=[],
                   help="KEY=VALUE (repeatable)")
    p.add_argument("--operator-notes", default="")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--reports-dir",
                   default=str(Path.home() / "strikecore-data" / "reports" / "agent_dossier"))
    p.add_argument("--no-store", action="store_true")
    return p.parse_args()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse_constraints(items: list[str]) -> dict:
    out: dict = {}
    for s in items:
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip()
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = v
    return out


async def _amain(args: argparse.Namespace) -> int:
    from config.settings import get_settings
    from core.provider_router import ProviderRouter
    from agent.dossier_flow import build_dossier

    store = None
    if not args.no_store:
        try:
            from core.investigation_store import InvestigationStore
            store = InvestigationStore(args.target)
        except Exception as exc:  # noqa: BLE001
            logging.warning("InvestigationStore unavailable: %s", exc)

    try:
        from core import dossier_output
    except Exception:  # noqa: BLE001
        dossier_output = None  # type: ignore[assignment]

    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    router = ProviderRouter(get_settings())
    if dossier_output is not None:
        with dossier_output.tee_stdout() as _buf:
            result = await build_dossier(
                router=router,
                target=args.target,
                pir=args.pir,
                operator_notes=args.operator_notes,
                constraints=_parse_constraints(args.constraint),
                investigation_store=store,
            )
            transcript = _buf.getvalue()
    else:
        result = await build_dossier(
            router=router,
            target=args.target,
            pir=args.pir,
            operator_notes=args.operator_notes,
            constraints=_parse_constraints(args.constraint),
            investigation_store=store,
        )
        transcript = ""

    reports_dir = Path(args.reports_dir).expanduser()
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_target = "".join(c if c.isalnum() or c in "._-" else "_" for c in args.target)[:80]
    base = reports_dir / f"{ts}_{safe_target}_{result['pir_id']}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")

    md_path.write_text(_render_md(result), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"[agent-dossier] dossier_id={result['dossier_id']}")
    print(f"[agent-dossier] pir_id={result['pir_id']}")
    print(f"[agent-dossier] cost_usd={result['cost_usd']}")
    print(f"[agent-dossier] steps_succeeded={result['n_steps_succeeded']}/{result['n_steps_planned']}")
    print(f"[agent-dossier] findings_persisted={result['findings_persisted']}")
    print(f"[agent-dossier] improvements={result['improvements']}")
    print(f"[agent-dossier] dossier_md={md_path}")
    print(f"[agent-dossier] dossier_json={json_path}")

    # Unified dossieroutputs/ mirror for Hephaestus autoimprove (best-effort).
    if dossier_output is not None:
        try:
            run_dir = dossier_output.new_run_dir(args.target, "agent_dossier")
            dossier_output.write_run(
                run_dir,
                meta={"source": "agent_dossier", "target": args.target,
                      "pir_id": result["pir_id"], "pir": args.pir,
                      "started_at": started, "cost_usd": result.get("cost_usd"),
                      "report_md": str(md_path), "report_json": str(json_path)},
                dossier_json=result,
                transcript=transcript,
                markdown=_render_md(result),
            )
            print(f"[agent-dossier] dossier_output={run_dir}")
        except Exception as exc:  # noqa: BLE001
            print(f"[agent-dossier] dossier-output capture skipped: {exc}", file=sys.stderr)

    # CATEGORICAL STANDARD: leave the dashboard artifacts behind (Report/Graph
    # tabs + GeoMap) for this target, exactly like the console and intel-team
    # paths. Enforced centrally; never breaks the run.
    if dossier_output is not None and store is not None:
        try:
            arts = dossier_output.finalize_dashboard_artifacts(store, dossier_json=result)
            if arts.get("report_html"):
                print(f"[agent-dossier] report-tab={arts['report_html']}")
            if arts.get("graph_html"):
                print(f"[agent-dossier] graph-tab={arts['graph_html']}")
            for _k in ("report_error", "graph_error"):
                if arts.get(_k):
                    print(f"[agent-dossier] {_k}={arts[_k]}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[agent-dossier] dashboard artifacts skipped: {exc}", file=sys.stderr)
    return 0


def _render_md(result: dict) -> str:
    raw = result.get("raw_dossier") or {}
    lines = [
        f"# Agent Dossier — {result['target']}",
        "",
        f"- **Dossier ID:** `{result['dossier_id']}`",
        f"- **PIR ID:** `{result['pir_id']}`",
        f"- **Plan steps:** {result['n_steps_succeeded']}/{result['n_steps_planned']} succeeded",
        f"- **Cost:** ${result['cost_usd']:.4f}  (= {result['cost_micros']} micros)",
        f"- **Findings persisted:** {result['findings_persisted']}",
        f"- **Improvements written:** {result['improvements']}",
        "",
    ]
    if raw.get("bluf"):
        lines += ["## BLUF", "", raw["bluf"], ""]
    if raw.get("key_judgments"):
        lines += ["## Key Judgments", "", "| # | Judgment | Confidence | Sources |", "|---|---|---|---|"]
        for i, kj in enumerate(raw["key_judgments"], 1):
            lines.append(f"| {i} | {kj.get('judgment','')} | {kj.get('confidence','')} | "
                         f"{', '.join(kj.get('sources', []))} |")
        lines.append("")
    if raw.get("intelligence_gaps"):
        lines += ["## Intelligence Gaps", ""]
        for g in raw["intelligence_gaps"]:
            lines.append(f"- {g}")
        lines.append("")
    if raw.get("recommended_actions"):
        lines += ["## Recommended Actions", ""]
        for i, a in enumerate(raw["recommended_actions"], 1):
            lines.append(f"{i}. {a}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        logging.error("agent-dossier failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
