import asyncio
from core.provider_router import ProviderRouter
from governance.model_router import ModelPolicy


class FakeSettings:
    def get(self, k, d=None):
        return {"ai.active_provider": "anthropic",
                "ai.fallback_chain": ["anthropic"],
                "ai.anthropic": {}}.get(k, d)


def test_stream_chat_dry_run_records_routed_cost():
    async def main():
        r = ProviderRouter(FakeSettings())
        r.set_dry_run(True)
        r.set_policy(ModelPolicy(profile="hephaestus"))
        r.reset_log()
        chunks = []
        async for delta in r.stream_chat(
            [{"role": "user", "content": "x" * 4000}],
            system="s", task_type="hephaestus:gap"):
            chunks.append(delta)
        assert "".join(chunks)               # produced content
        rec = r.call_log[-1]
        # hephaestus:gap -> fable tier, remapped to opus on this account
        assert rec.model == "claude-opus-4-8", rec.model
        assert rec.cost_micros > 0
        assert rec.task_type == "hephaestus:gap"
    asyncio.run(main())


def test_resolve_model_applies_substitution():
    r = ProviderRouter(FakeSettings())
    r.set_policy(ModelPolicy(profile="hephaestus"))
    assert r.resolve_model("hephaestus:gap") == "claude-opus-4-8"
    assert r.resolve_model("hephaestus:discovery") == "claude-haiku-4-5"
