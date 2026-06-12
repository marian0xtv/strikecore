"""Dossier-mode dry-run harness: drives the canonical dossier step task_types
through the cost-aware router (dry-run) under the dossier 'lethality' profile,
so routing + cost are demonstrated without Postgres/live API. These are the
exact task_types the real agent/dossier_flow emits (planner/critic/specialists)."""
import sys, asyncio; sys.path.insert(0, ".")
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy

class S:
    def get(self, k, d=None):
        return {"ai.active_provider":"anthropic","ai.fallback_chain":["anthropic"],"ai.anthropic":{}}.get(k,d)

# canonical dossier pipeline (bulk collection -> analysis -> synthesis -> review)
STEPS = [
    ("planner", "decompose PIR into steps"),
    ("specialist:socint", "username/social extraction"),
    ("specialist:webint", "web/domain extraction"),
    ("specialist:geoint", "geo metadata extraction"),
    ("specialist:audit", "devil's advocate + hypothesis generation"),
    ("specialist:analyst", "ACH + key judgments + final dossier narrative"),
    ("critic", "post-run quality review"),
]

async def run(lethality):
    r = ProviderRouter(S()); r.set_dry_run(True)
    r.set_policy(ModelPolicy(profile="dossier", lethality=lethality))
    for tt, prompt in STEPS:
        await r.chat([{"role":"user","content":prompt*60}], task_type=tt)
    rc = r.run_cost()
    print(f"\n=== DOSSIER dry-run · lethality={lethality} ===")
    for u in rc["by_task_type"].values() if False else r.call_log:
        pass
    for c in r.call_log:
        tag = "ANALYSIS" if c.model!="claude-haiku-4-5" else "bulk"
        print(f"  {c.task_type:<22} -> {c.model:<18} {tag:<8} ${c.cost_micros/1e6:.4f}  [{c.routing_reason}]")
    print(f"  TOTAL: {rc['totals']['calls']} calls  ${rc['totals']['cost_usd_micros']/1e6:.4f}")

asyncio.run(run("max"))
asyncio.run(run("balanced"))
asyncio.run(run("economy"))
