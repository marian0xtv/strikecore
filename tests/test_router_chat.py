import sys, asyncio; sys.path.insert(0, ".")
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy

class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)

async def main():
    r = ProviderRouter(FakeSettings())
    r.set_dry_run(True)
    r.set_policy(ModelPolicy(profile="dossier", lethality="max"))
    msg = [{"role": "user", "content": "x" * 4000}]

    # Fable tier is remapped to Opus 4.8 at the provider layer (Fable 5 is not
    # available on this account); policy intent is unchanged, the call uses Opus.
    resp = await r.chat(msg, task_type="specialist:analyst")
    assert r.call_log[-1].model == "claude-opus-4-8", r.call_log[-1].model
    assert r.call_log[-1].cost_micros > 0
    assert resp.routing_reason.startswith("dossier[max]")

    await r.chat(msg, task_type="specialist:socint")
    assert r.call_log[-1].model == "claude-haiku-4-5", r.call_log[-1].model

    await r.chat(msg, task_type="planner")
    assert r.call_log[-1].model == "claude-opus-4-8", "max->planner fable-tier remapped to opus"

    # explicit model override beats policy
    await r.chat(msg, model="haiku", task_type="specialist:analyst")
    assert r.call_log[-1].model == "claude-haiku-4-5"

    rc = r.run_cost()
    print("calls:", rc["totals"]["calls"], "cost_micros:", rc["totals"]["cost_usd_micros"])
    print("by_model:", {k: v["calls"] for k, v in rc["by_model"].items()})
    assert rc["totals"]["cost_usd_micros"] > 0
    print("ALL ROUTER CHAT (dry-run) TESTS PASSED")

asyncio.run(main())
