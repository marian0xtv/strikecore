"""Uniform Tool registry over intel_team specialists + legacy agents + binaries.

Single dispatch surface for the Executor. Every callable in the system is
exposed as a :class:`Tool` with the same interface:

    name           — registry key (e.g. ``specialist:socint``, ``legacy:osint``, ``bin:sherlock``)
    description    — operator-facing one-liner
    input_schema   — JSON schema for the params dict
    output_schema  — JSON schema describing the expected result shape
    invoke()       — async callable returning a dict (or any JSON-serialisable)
    cost_estimate  — rough USD micros estimate (used by planner)
    health_check() — fast probe (importable, binary present, …)

Three families today:
  * ``specialist:*``  — intel_team specialists (SOCINT, SOCIALINT, GEOINT, WEBINT,
                        AUDIT, ANALYST). Re-uses their existing ``analyze`` method.
  * ``legacy:*``      — agents/*_agent.py (recon, osint, github_scanner, …).
                        Re-uses their existing ``run`` method.
  * ``bin:*``         — entries from core/tool_registry.py invoked via
                        core/executor.py. Kept minimal in Phase B; binary
                        execution is a heavier concern (Tor, sudo, rate-limit)
                        that lives in core/executor.py.

The gateway exposes :func:`default_gateway` returning a process-wide singleton
populated lazily.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar, Optional

logger = logging.getLogger("agent.tool_gateway")


@dataclass
class Tool:
    """Uniform Tool definition."""

    name: str
    description: str
    invoke: Callable[..., Awaitable[Any]]
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    output_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    family: str = "specialist"                            # specialist | legacy | binary | synthesis
    cost_estimate_micros: int = 0                         # rough; planner uses to budget
    domain: str | None = None
    health_check: Callable[[], bool] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolGateway:
    """Process-wide registry. Populate via :meth:`autodiscover`."""

    _INSTANCE: ClassVar[Optional["ToolGateway"]] = None

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.debug("Tool %s already registered — overwriting", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self, family: str | None = None) -> list[Tool]:
        if family is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.family == family]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # ------------------------------------------------------------------
    # Auto-discovery
    # ------------------------------------------------------------------

    def autodiscover(self, *, intel_team: bool = True, legacy_agents: bool = True,
                     binaries: bool = True) -> dict[str, int]:
        """Walk modules and register every tool we find.

        Returns a count summary keyed by family.
        """
        summary = {"specialist": 0, "legacy": 0, "binary": 0, "synthesis": 0}

        if intel_team:
            summary["specialist"] += self._register_intel_team_specialists()

        if legacy_agents:
            summary["legacy"] += self._register_legacy_agents()

        if binaries:
            summary["binary"] += self._register_binary_tools()

        return summary

    # ------------------------------------------------------------------
    # Families
    # ------------------------------------------------------------------

    def _register_intel_team_specialists(self) -> int:
        """Register every BaseSpecialist subclass in intel_team.agents."""
        try:
            from intel_team.agents.base import BaseSpecialist  # noqa: F401
            import intel_team.agents as it_pkg
        except Exception as exc:  # noqa: BLE001
            logger.warning("intel_team.agents unavailable: %s", exc)
            return 0

        count = 0
        for _finder, mod_name, _ispkg in pkgutil.iter_modules(it_pkg.__path__):
            if mod_name in ("__init__", "base"):
                continue
            try:
                mod = importlib.import_module(f"intel_team.agents.{mod_name}")
            except Exception as exc:  # noqa: BLE001
                logger.debug("skip intel_team.agents.%s: %s", mod_name, exc)
                continue
            for attr_name in dir(mod):
                cls = getattr(mod, attr_name)
                if not (inspect.isclass(cls) and attr_name.endswith(("Specialist", "Agent"))
                        and cls.__module__ == mod.__name__):
                    continue
                # config is a class-level AgentConfig
                cfg = getattr(cls, "config", None)
                if cfg is None or not hasattr(cfg, "name"):
                    continue
                family = "synthesis" if attr_name.lower() in ("analystagent", "analyst") else "specialist"
                tool = self._wrap_specialist(cls, family=family)
                if tool is not None:
                    self.register(tool)
                    count += 1
        return count

    def _wrap_specialist(self, cls: type, *, family: str) -> Tool | None:
        """Wrap an intel_team specialist class as a Tool."""
        try:
            cfg = cls.config
        except Exception:  # noqa: BLE001
            return None

        domain_value = getattr(cfg.domain, "value", str(getattr(cfg, "domain", "unknown")))
        name = f"{family}:{domain_value}" if family == "specialist" else f"synthesis:{cfg.name}"

        async def invoke(*, router: Any, pir: Any, context: dict[str, Any],
                         store: Any = None) -> dict[str, Any]:
            instance = cls(router, store)
            # Specialists implement async ``analyze``; AnalystAgent has ``synthesize``
            if hasattr(instance, "synthesize") and family == "synthesis":
                dossier = await instance.synthesize(
                    pir,
                    specialist_reports=context.get("specialist_reports", []),
                    audit_reports=context.get("audit_reports", []),
                    store_summary=context.get("store_summary", ""),
                    operator_notes=context.get("operator_notes", ""),
                )
                # AnalystAgent.synthesize returns a Dossier; tolerate the rare path
                # where a downstream fallback already returned a plain dict.
                return {"dossier": dossier.to_dict() if hasattr(dossier, "to_dict") else dossier}
            report = await instance.analyze(pir, context)
            return report.to_dict() if hasattr(report, "to_dict") else {"raw": str(report)}

        return Tool(
            name=name,
            description=f"intel_team {family} agent for domain {domain_value}",
            invoke=invoke,
            family=family,
            domain=domain_value,
            input_schema={
                "type": "object",
                "properties": {
                    "pir": {"type": "object"},
                    "context": {"type": "object"},
                },
                "required": ["pir"],
            },
            output_schema={"type": "object", "properties": {"findings": {"type": "array"}, "gaps": {"type": "array"}}},
            cost_estimate_micros=20_000 if family == "synthesis" else 8_000,
            metadata={"class": f"{cls.__module__}.{cls.__name__}"},
        )

    def _register_legacy_agents(self) -> int:
        """Register every legacy ``agents/*_agent.py`` class with an async ``run`` method."""
        try:
            import agents as agents_pkg
        except Exception as exc:  # noqa: BLE001
            logger.warning("legacy agents/ unavailable: %s", exc)
            return 0

        count = 0
        for _finder, mod_name, _ispkg in pkgutil.iter_modules(agents_pkg.__path__):
            if mod_name in ("__init__",):
                continue
            try:
                mod = importlib.import_module(f"agents.{mod_name}")
            except Exception as exc:  # noqa: BLE001
                logger.debug("skip agents.%s: %s", mod_name, exc)
                continue
            for attr_name in dir(mod):
                cls = getattr(mod, attr_name)
                if not (inspect.isclass(cls) and attr_name.endswith("Agent")
                        and cls.__module__ == mod.__name__):
                    continue
                if not hasattr(cls, "run"):
                    continue
                name = f"legacy:{attr_name.removesuffix('Agent').lower()}"
                desc = (getattr(cls, "description", None) or
                        getattr(cls, "__doc__", "") or attr_name).strip().split("\n")[0]
                count += 1
                self.register(self._wrap_legacy_agent(name, cls, desc))
        return count

    def _wrap_legacy_agent(self, name: str, cls: type, desc: str) -> Tool:
        async def invoke(*, target: str, agent_core: Any = None, **_: Any) -> dict[str, Any]:
            instance = cls()
            run = getattr(instance, "run")
            if inspect.iscoroutinefunction(run):
                result = await run(target, agent_core)
            else:
                result = await asyncio.to_thread(run, target, agent_core)
            return result if isinstance(result, dict) else {"raw": str(result)}

        return Tool(
            name=name,
            description=desc[:280],
            invoke=invoke,
            family="legacy",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
            output_schema={"type": "object"},
            cost_estimate_micros=2_000,
            metadata={"class": f"{cls.__module__}.{cls.__name__}"},
        )

    def _register_binary_tools(self) -> int:
        """Surface binary tools from core/tool_registry.py.

        Phase B keeps this surface read-only: the planner sees the catalogue
        and can mention binaries in its rationale, but actual invocation goes
        through ``core/executor.py`` and is wired in Phase D / via a follow-up
        commit. Returns 0 until that wiring exists.
        """
        try:
            from core.tool_registry import ToolRegistry  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            logger.debug("core.tool_registry unavailable: %s", exc)
            return 0

        # NOTE: binary tools are catalogued in ToolRegistry but invocation
        # requires more plumbing (sudo gates, proxy routing, output truncation)
        # than the Phase B scope allows. Phase D opens this surface up.
        return 0


def default_gateway() -> ToolGateway:
    """Lazy process-wide gateway. Auto-discovers on first access."""
    if ToolGateway._INSTANCE is None:
        gw = ToolGateway()
        summary = gw.autodiscover()
        logger.info("ToolGateway autodiscover: %s", summary)
        ToolGateway._INSTANCE = gw
    return ToolGateway._INSTANCE
