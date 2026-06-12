import sys; sys.path.insert(0,".")
from governance.model_router import policy_from_settings, resolve_model_name

class DictSettings:
    """Dotted-key settings stub (get/set/save) like config.settings.Settings."""
    def __init__(self): self.d = {}; self.saved = False
    def get(self, k, d=None): return self.d.get(k, d)
    def set(self, k, v): self.d[k] = v
    def save(self): self.saved = True

s = DictSettings()
# simulate `/model fable`
s.set("ai.model_policy.mode", "pinned"); s.set("ai.model_policy.pinned_model", resolve_model_name("fable")); s.save()
p = policy_from_settings(s)
assert p.mode == "pinned" and p.pinned_model == "claude-fable-5", p.as_dict()
assert p.resolve("specialist:socint")[0] == "claude-fable-5", "pin forces fable everywhere"

# `/model auto`
s.set("ai.model_policy.mode", "auto")
assert policy_from_settings(s).mode == "auto"

# `/model profile dossier` + `/model lethality max`
s.set("ai.model_policy.profile", "dossier"); s.set("ai.model_policy.lethality", "max")
p = policy_from_settings(s)
assert p.resolve("specialist:analyst")[0] == "claude-fable-5", "dossier max analyst->fable"
assert p.resolve("specialist:socint")[0] == "claude-haiku-4-5", "dossier bulk->haiku"

# `/model planner fable` (override)
s.set("ai.model_policy.overrides", {"planner": "claude-fable-5"})
assert policy_from_settings(s).resolve("planner")[0] == "claude-fable-5"
# `/model clear planner`
s.set("ai.model_policy.overrides", {})
assert "planner" not in policy_from_settings(s).overrides

assert s.saved is True
print("ALL /model SETTINGS ROUND-TRIP TESTS PASSED")
