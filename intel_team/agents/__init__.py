"""Intel-team specialists (domain-constrained Claude sub-agents).

Each specialist is a thin layer over the existing ``core.provider_router``
``ProviderRouter`` — they do not duplicate LLM infrastructure, they only
constrain the system prompt and the tool surface to their domain.
"""

from intel_team.agents.analyst import AnalystAgent
from intel_team.agents.audit import AuditAgent
from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.agents.socint import SOCINTSpecialist

__all__ = [
    "AgentConfig",
    "AnalystAgent",
    "AuditAgent",
    "BaseSpecialist",
    "SOCINTSpecialist",
]
