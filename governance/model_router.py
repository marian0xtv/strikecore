"""Cost-aware model routing policy for StrikeCore (GR3).

A single, shared decision function maps a *task_type* (the kind of LLM work)
to a concrete model id, applying the active routing profile and — for dossier
mode — a "lethality" level that biases analysis steps toward stronger models.

Principle: the cheapest model that meets the quality bar; escalate only on
need. Bulk work (tool calls, extraction, normalization, formatting, bulk
collection) → Haiku. Reasoning / planning → Opus. Heaviest reasoning
(deep-research synthesis, novel design, complex gap analysis, ACH +
hypothesis generation, the final dossier narrative) → Fable.

This module is pure logic (stdlib only) so it is unit-testable without any
network or provider. ``ProviderRouter`` consumes it to pick a model per call.

Model ids verified via the claude-api skill (2026-06):
    fable  -> claude-fable-5   ($10/$50 per Mtok)
    opus   -> claude-opus-4-8  ($5/$25)
    haiku  -> claude-haiku-4-5 ($1/$5)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- tiers -> concrete model ids -------------------------------------------
TIER_MODEL: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "opus": "claude-opus-4-8",
    "fable": "claude-fable-5",
}
FRIENDLY_TO_ID: dict[str, str] = {
    "fable": "claude-fable-5",
    "opus": "claude-opus-4-8",
    "haiku": "claude-haiku-4-5",
}
KNOWN_MODEL_IDS = set(TIER_MODEL.values())
LETHALITY_LEVELS = ("economy", "balanced", "max")


def resolve_model_name(name: str) -> str:
    """Map a friendly name (fable/opus/haiku) to a model id; pass ids through."""
    n = (name or "").strip()
    return FRIENDLY_TO_ID.get(n.lower(), n)


# --- base "auto" classification: task_type -> tier -------------------------
# Bulk / cheap work.
_BULK_TIER = "haiku"
# Reasoning / planning.
_REASON_TIER = "opus"
# Heaviest reasoning.
_HEAVY_TIER = "fable"

# Exact task_type -> tier (the default/auto policy).
_AUTO_TIERS: dict[str, str] = {
    # bulk collection / extraction / normalization / classification
    "tool_call": _BULK_TIER,
    "extract": _BULK_TIER,
    "classify": _BULK_TIER,
    "normalize": _BULK_TIER,
    "summarize": _BULK_TIER,
    "collect": _BULK_TIER,
    "enrich": _BULK_TIER,
    "format": _BULK_TIER,
    # intel-team specialists doing extraction over already-collected data
    "specialist:socint": _BULK_TIER,
    "specialist:webint": _BULK_TIER,
    "specialist:geoint": _BULK_TIER,
    "specialist:socialint": _BULK_TIER,
    "specialist:crossdb": _BULK_TIER,
    "specialist:threatint": _BULK_TIER,
    # reasoning / planning
    "orchestration": _REASON_TIER,
    "planner": _REASON_TIER,
    "critic": _REASON_TIER,
    "agent_step": _REASON_TIER,
    "specialist:audit": _REASON_TIER,        # devil's advocate / hypothesis gen
    # heaviest reasoning
    "specialist:analyst": _HEAVY_TIER,       # ACH + synthesis + final narrative
    "synthesis:analyst": _HEAVY_TIER,
}


def _auto_tier(task_type: str) -> tuple[str, str]:
    """Default cost-aware classification. Returns (tier, reason)."""
    t = (task_type or "").strip()
    if t in _AUTO_TIERS:
        return _AUTO_TIERS[t], f"auto:{t}->{_AUTO_TIERS[t]}"
    # prefix heuristics so unknown specialists still route sanely
    if t.startswith("specialist:"):
        return _BULK_TIER, f"auto:{t}(specialist-default)->{_BULK_TIER}"
    if t.startswith(("synthesis", "analyst", "ach", "hypothes", "design", "gap")):
        return _HEAVY_TIER, f"auto:{t}(synthesis-like)->{_HEAVY_TIER}"
    if t.startswith(("plan", "reason", "critic", "investigat")):
        return _REASON_TIER, f"auto:{t}(reasoning-like)->{_REASON_TIER}"
    # default: cheapest reasonable model
    return _REASON_TIER, f"auto:{t or 'unknown'}(default)->{_REASON_TIER}"


# --- profiles ---------------------------------------------------------------
@dataclass(frozen=True)
class RoutingProfile:
    """A named routing profile: per-task_type tier overrides on top of auto."""

    name: str
    tier_overrides: dict[str, str] = field(default_factory=dict)

    def tier_for(self, task_type: str) -> tuple[str, str]:
        t = (task_type or "").strip()
        if t in self.tier_overrides:
            tier = self.tier_overrides[t]
            return tier, f"profile:{self.name}:{t}->{tier}"
        return _auto_tier(t)


# Hephaestus R&D: discovery/extraction cheap; research = reasoning;
# design + gap analysis = heaviest (novel design, complex gap analysis).
HEPHAESTUS_PROFILE = RoutingProfile(
    name="hephaestus",
    tier_overrides={
        "hephaestus:discovery": "haiku",
        "hephaestus:extract": "haiku",
        "hephaestus:research": "opus",
        "hephaestus:gap": "fable",
        "hephaestus:dossier_gap": "fable",
        "hephaestus:design": "fable",
        "hephaestus:decision": "opus",
    },
)

DEFAULT_PROFILE = RoutingProfile(name="default")

# Dossier "lethality": analysis steps escalate with the level; bulk stays Haiku.
# economy  -> analyst=opus, audit/planner/critic=opus, bulk=haiku
# balanced -> analyst=fable, audit/planner/critic=opus, bulk=haiku
# max      -> all core analysis (planner/critic/audit/analyst)=fable, bulk=haiku
_DOSSIER_BULK = {
    "specialist:socint": "haiku", "specialist:webint": "haiku",
    "specialist:geoint": "haiku", "specialist:socialint": "haiku",
    "specialist:crossdb": "haiku", "specialist:threatint": "haiku",
    "extract": "haiku", "normalize": "haiku", "enrich": "haiku",
    "collect": "haiku", "format": "haiku", "summarize": "haiku",
}
_DOSSIER_ANALYSIS_BY_LETHALITY: dict[str, dict[str, str]] = {
    "economy": {
        "specialist:analyst": "opus", "synthesis:analyst": "opus",
        "specialist:audit": "opus", "planner": "opus", "critic": "haiku",
    },
    "balanced": {
        "specialist:analyst": "fable", "synthesis:analyst": "fable",
        "specialist:audit": "opus", "planner": "opus", "critic": "opus",
    },
    "max": {
        "specialist:analyst": "fable", "synthesis:analyst": "fable",
        "specialist:audit": "fable", "planner": "fable", "critic": "fable",
    },
}


def _dossier_tier(task_type: str, lethality: str) -> tuple[str, str]:
    t = (task_type or "").strip()
    lvl = lethality if lethality in LETHALITY_LEVELS else "balanced"
    if t in _DOSSIER_BULK:
        return _DOSSIER_BULK[t], f"dossier[{lvl}]:bulk:{t}->haiku"
    analysis = _DOSSIER_ANALYSIS_BY_LETHALITY[lvl]
    if t in analysis:
        return analysis[t], f"dossier[{lvl}]:analysis:{t}->{analysis[t]}"
    return _auto_tier(t)


# --- the policy object ------------------------------------------------------
@dataclass
class ModelPolicy:
    """Resolved routing configuration for a run (from config + /model)."""

    mode: str = "auto"                 # "auto" | "pinned"
    pinned_model: str | None = None    # concrete id when mode == "pinned"
    profile: str = "default"           # default | hephaestus | dossier
    lethality: str = "balanced"        # economy | balanced | max (dossier only)
    overrides: dict[str, str] = field(default_factory=dict)  # task_type -> model id

    def resolve(self, task_type: str | None) -> tuple[str, str]:
        """Return (model_id, routing_reason) for a task_type. Precedence:
        global pin > per-phase override > profile/lethality > auto rule."""
        t = (task_type or "").strip()
        # 1) global pin
        if self.mode == "pinned" and self.pinned_model:
            mid = resolve_model_name(self.pinned_model)
            return mid, f"pinned:{mid}"
        # 2) per-phase override
        if t and t in self.overrides:
            mid = resolve_model_name(self.overrides[t])
            return mid, f"override:{t}->{mid}"
        # 3) profile / lethality
        if self.profile == "dossier":
            tier, reason = _dossier_tier(t, self.lethality)
        elif self.profile == "hephaestus":
            tier, reason = HEPHAESTUS_PROFILE.tier_for(t)
        else:
            tier, reason = DEFAULT_PROFILE.tier_for(t)
        return TIER_MODEL.get(tier, TIER_MODEL[_REASON_TIER]), reason

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "pinned_model": self.pinned_model,
            "profile": self.profile,
            "lethality": self.lethality,
            "overrides": dict(self.overrides),
        }


def policy_from_settings(settings) -> ModelPolicy:
    """Build a ModelPolicy from the settings singleton (ai.model_policy.*).

    Falls back to safe defaults when keys are absent. ``settings`` only needs a
    ``.get(dotted_key, default)`` method (config.settings.Settings satisfies it).
    """
    def g(key, default):
        try:
            val = settings.get(f"ai.model_policy.{key}", default)
            return val if val is not None else default
        except Exception:
            return default

    overrides = g("overrides", {}) or {}
    if not isinstance(overrides, dict):
        overrides = {}
    return ModelPolicy(
        mode=str(g("mode", "auto")),
        pinned_model=g("pinned_model", None) or None,
        profile=str(g("profile", "default")),
        lethality=str(g("lethality", "balanced")),
        overrides={str(k): str(v) for k, v in overrides.items()},
    )
