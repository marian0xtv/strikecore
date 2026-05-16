"""Intel-team specialists (domain-constrained Claude sub-agents).

Each specialist is a thin layer over the existing ``core.provider_router``
``ProviderRouter`` — they do not duplicate LLM infrastructure, they only
constrain the system prompt and the tool surface to their domain.

Standard domain specialists (SOCINT, WEBINT, GEOINT, SOCIALINT) extend
``BaseSpecialist`` and inherit the canonical
*call → parse JSON → coerce findings* pipeline (``_standard_analyze``).
Audit and Analyst override ``analyze`` directly because their pipeline
diverges (they consume specialist reports, not raw tool output).
"""

from intel_team.agents.analyst import AnalystAgent
from intel_team.agents.audit import AuditAgent
from intel_team.agents.base import AgentConfig, BaseSpecialist
from intel_team.agents.geoint import GEOINTSpecialist
from intel_team.agents.socialint import SOCIALINTSpecialist
from intel_team.agents.socint import SOCINTSpecialist
from intel_team.agents.webint import WEBINTSpecialist

__all__ = [
    "AgentConfig",
    "AnalystAgent",
    "AuditAgent",
    "BaseSpecialist",
    "GEOINTSpecialist",
    "SOCIALINTSpecialist",
    "SOCINTSpecialist",
    "WEBINTSpecialist",
]
