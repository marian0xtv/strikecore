import sys; sys.path.insert(0, ".")
from governance.model_router import ModelPolicy, policy_from_settings

def check(got, want, msg):
    assert got == want, f"{msg}: got {got!r} want {want!r}"

# auto (default profile)
p = ModelPolicy()
check(p.resolve("tool_call")[0], "claude-haiku-4-5", "tool_call->haiku")
check(p.resolve("specialist:socint")[0], "claude-haiku-4-5", "socint->haiku")
check(p.resolve("planner")[0], "claude-opus-4-8", "planner->opus")
check(p.resolve("specialist:analyst")[0], "claude-fable-5", "analyst->fable")

# global pin wins
p = ModelPolicy(mode="pinned", pinned_model="haiku")
check(p.resolve("specialist:analyst")[0], "claude-haiku-4-5", "pin overrides analyst")

# per-phase override
p = ModelPolicy(overrides={"planner": "fable"})
check(p.resolve("planner")[0], "claude-fable-5", "override planner->fable")
check(p.resolve("critic")[0], "claude-opus-4-8", "critic still auto opus")

# dossier lethality
p = ModelPolicy(profile="dossier", lethality="max")
check(p.resolve("specialist:analyst")[0], "claude-fable-5", "max analyst->fable")
check(p.resolve("specialist:audit")[0], "claude-fable-5", "max audit->fable")
check(p.resolve("planner")[0], "claude-fable-5", "max planner->fable")
check(p.resolve("specialist:socint")[0], "claude-haiku-4-5", "max bulk stays haiku")

p = ModelPolicy(profile="dossier", lethality="economy")
check(p.resolve("specialist:analyst")[0], "claude-opus-4-8", "economy analyst->opus")
check(p.resolve("specialist:audit")[0], "claude-opus-4-8", "economy audit->opus")
check(p.resolve("specialist:socint")[0], "claude-haiku-4-5", "economy bulk haiku")

p = ModelPolicy(profile="dossier", lethality="balanced")
check(p.resolve("specialist:analyst")[0], "claude-fable-5", "balanced analyst->fable")
check(p.resolve("specialist:audit")[0], "claude-opus-4-8", "balanced audit->opus")

# hephaestus profile
p = ModelPolicy(profile="hephaestus")
check(p.resolve("hephaestus:discovery")[0], "claude-haiku-4-5", "discovery->haiku")
check(p.resolve("hephaestus:research")[0], "claude-opus-4-8", "research->opus")
check(p.resolve("hephaestus:design")[0], "claude-fable-5", "design->fable")
check(p.resolve("hephaestus:gap")[0], "claude-fable-5", "gap->fable")

# policy_from_settings fallback
class FakeSettings:
    def get(self, k, d): return d
check(policy_from_settings(FakeSettings()).mode, "auto", "settings default mode")

print("ALL MODEL ROUTER TESTS PASSED")
