"""SOCIALINT specialist — social-graph analysis.

Distinct from :class:`SOCINTSpecialist` (which *discovers* accounts on
platforms), SOCIALINT analyses the **graph between identified accounts**:

* Mutual connections / followers ∩ following intersections
* Comment graphs (who talks to whom, how often, with what tone)
* Like / mention graphs
* Tagged-in patterns (who appears in whose photos / posts)
* Sockpuppet detection: temporal correlation, stylometric similarity,
  posting-time clustering, identical handles across platforms
* Cross-platform identity linkage via the social graph (same network of
  friends on Instagram + Facebook + Telegram = strong identity binding)
* Relationship-type inference (family / work / romantic / transactional)
  with explicit caveats — never assert intimate relationships from
  observational data alone
* Network centrality, community detection, ego-network shape

The specialist operates over **pre-collected tool output** — followers/
following dumps, comment threads, like records — and applies social-network
tradecraft to surface defensible findings about the target's *position in
the graph*, not their account identifiers.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.types import Domain, PIR

logger = logging.getLogger("intel_team.agents.socialint")


class SOCIALINTSpecialist(BaseSpecialist):
    """Social-graph specialist (separate from SOCINT account-discovery)."""

    config = AgentConfig(
        name="socialint_specialist",
        domain=Domain.SOCIALINT,
        system_prompt_file="socialint.md",
        allowed_tool_categories=["socint"],   # reuses SOCINT tool wrappers
        model_tier="specialist",
        max_tokens=6000,
        temperature=0.20,
    )

    _ALLOWED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "connection",            # an inferred relationship between two accounts
            "mutual_count",          # cardinality of mutual followers
            "sockpuppet_cluster",    # set of accounts likely controlled by the same person
            "alias_link",            # two handles inferred to belong to the same person
            "community",             # named community / cluster the target belongs to
            "centrality_signal",     # high-centrality role in the local graph
            "ego_network_shape",
            "relationship_type",     # family / work / romantic / transactional / other
            "interaction_pattern",   # frequency / direction / tone summary
            "tag_co_occurrence",
            "comment_graph_edge",
            "post_time_cluster",
            "cross_platform_overlap",
            "other",
        }
    )

    # _FORBIDDEN_TYPES inherited (forbids phone — phones come only from
    # phone-specific tools per CLAUDE.md §3.4)

    # Override to surface graph-specific context fields
    def _build_user_message(self, pir: PIR, context: dict[str, Any]) -> str:
        import json

        payload = {
            "pir": {
                "id": pir.id,
                "question": pir.question,
                "target": pir.target,
                "constraints": pir.constraints,
            },
            "investigation_store_summary": context.get("store_summary", ""),
            "recent_tool_outputs": context.get("tool_outputs", {}),
            # SOCIALINT-specific context — populated by ig-social-circle, etc.
            "followers": context.get("followers", []),
            "following": context.get("following", []),
            "mutuals": context.get("mutuals", []),
            "comment_threads": context.get("comment_threads", []),
            "like_records": context.get("like_records", []),
            "tag_records": context.get("tag_records", []),
            "post_timestamps": context.get("post_timestamps", []),
            "candidate_aliases": context.get("candidate_aliases", []),
            "operator_notes": context.get("operator_notes", ""),
        }
        return (
            "Analyse the social graph below and produce a SOCIALINT report per "
            "the JSON schema in your system prompt. Return ONLY the JSON object.\n\n"
            + json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )
