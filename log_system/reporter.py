"""
Report generator for StrikeCore penetration-testing sessions.

Produces structured pentest reports from session audit data in Markdown,
HTML (via Jinja2), and JSON formats.

Usage::

    from log_system.reporter import generate_report, save_report

    md = generate_report("session-abc", format="markdown")
    save_report("session-abc", "/tmp/report.html", format="html")
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import BaseLoader, Environment

from log_system.audit import AuditEntry, AuditLogger, audit

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
    "informational": 4,
}

_SEVERITY_COLORS = {
    "critical": "#7b2d8e",
    "high": "#d32f2f",
    "medium": "#f57c00",
    "low": "#1976d2",
    "info": "#616161",
    "informational": "#616161",
}

_SEVERITY_BADGES_MD = {
    "critical": "**`CRITICAL`**",
    "high": "**`HIGH`**",
    "medium": "**`MEDIUM`**",
    "low": "**`LOW`**",
    "info": "`INFO`",
    "informational": "`INFO`",
}


def _severity_key(finding: Dict[str, Any]) -> int:
    """Return a sort key so findings are ordered critical -> info."""
    sev = str(finding.get("severity", "info")).lower()
    return _SEVERITY_ORDER.get(sev, 99)


# ---------------------------------------------------------------------------
# Session data extraction
# ---------------------------------------------------------------------------


def _collect_session_data(
    session_id: str,
    audit_logger: Optional[AuditLogger] = None,
) -> Dict[str, Any]:
    """Gather all audit entries for *session_id* and organise them.

    Returns a dict with keys:
        session_id, start_time, end_time, findings, tool_calls,
        ai_interactions, commands, provider_switches, raw_events.
    """
    al = audit_logger or audit
    events = al.get_events(session_id=session_id)

    data: Dict[str, Any] = {
        "session_id": session_id,
        "start_time": None,
        "end_time": None,
        "findings": [],
        "tool_calls": [],
        "ai_interactions": [],
        "commands": [],
        "provider_switches": [],
        "raw_events": [asdict(e) for e in events],
    }

    for ev in events:
        if ev.event_type == "SESSION_START":
            data["start_time"] = ev.timestamp
        elif ev.event_type == "SESSION_END":
            data["end_time"] = ev.timestamp
        elif ev.event_type == "FINDING":
            data["findings"].append(ev.details)
        elif ev.event_type == "TOOL_CALL":
            data["tool_calls"].append(ev.details)
        elif ev.event_type in ("AI_REQUEST", "AI_RESPONSE"):
            data["ai_interactions"].append(
                {"type": ev.event_type, "timestamp": ev.timestamp, **ev.details}
            )
        elif ev.event_type == "COMMAND_EXEC":
            data["commands"].append(ev.details)
        elif ev.event_type == "PROVIDER_SWITCH":
            data["provider_switches"].append(ev.details)

    # Sort findings by severity (critical first).
    data["findings"].sort(key=_severity_key)

    return data


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _render_markdown(data: Dict[str, Any]) -> str:
    lines: List[str] = []

    lines.append(f"# StrikeCore Penetration Test Report")
    lines.append("")
    lines.append(f"**Session ID:** `{data['session_id']}`  ")
    lines.append(f"**Start:** {data['start_time'] or 'N/A'}  ")
    lines.append(f"**End:** {data['end_time'] or 'N/A'}  ")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ")
    lines.append("")

    # -- Executive summary --------------------------------------------------
    lines.append("## Executive Summary")
    lines.append("")
    finding_count = len(data["findings"])
    severity_counts: Dict[str, int] = {}
    for f in data["findings"]:
        sev = str(f.get("severity", "info")).lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    if finding_count == 0:
        lines.append("No findings were recorded during this session.")
    else:
        lines.append(
            f"A total of **{finding_count}** finding(s) were identified during "
            f"the assessment:"
        )
        lines.append("")
        for sev in ("critical", "high", "medium", "low", "info"):
            count = severity_counts.get(sev, 0)
            if count:
                badge = _SEVERITY_BADGES_MD.get(sev, sev.upper())
                lines.append(f"- {badge}: {count}")
        lines.append("")

    # -- Methodology --------------------------------------------------------
    lines.append("## Methodology")
    lines.append("")
    tool_names = sorted({tc.get("tool", "unknown") for tc in data["tool_calls"]})
    if tool_names:
        lines.append("The following tools were employed during the engagement:")
        lines.append("")
        for t in tool_names:
            lines.append(f"- `{t}`")
        lines.append("")
    else:
        lines.append("No automated tools were recorded for this session.")
        lines.append("")

    if data["commands"]:
        lines.append(f"A total of **{len(data['commands'])}** commands were executed.")
        lines.append("")

    # -- Findings -----------------------------------------------------------
    lines.append("## Findings")
    lines.append("")

    if not data["findings"]:
        lines.append("_No findings recorded._")
        lines.append("")
    else:
        for idx, finding in enumerate(data["findings"], 1):
            sev = str(finding.get("severity", "info")).lower()
            badge = _SEVERITY_BADGES_MD.get(sev, f"`{sev.upper()}`")
            title = finding.get("title", finding.get("name", f"Finding {idx}"))
            lines.append(f"### {idx}. {title}  {badge}")
            lines.append("")
            if finding.get("description"):
                lines.append(finding["description"])
                lines.append("")
            if finding.get("evidence"):
                lines.append("**Evidence:**")
                lines.append("")
                lines.append(f"```\n{finding['evidence']}\n```")
                lines.append("")
            if finding.get("recommendation"):
                lines.append(f"**Recommendation:** {finding['recommendation']}")
                lines.append("")
            if finding.get("references"):
                lines.append("**References:**")
                for ref in finding["references"]:
                    lines.append(f"- {ref}")
                lines.append("")

    # -- Recommendations ----------------------------------------------------
    lines.append("## Recommendations")
    lines.append("")
    recommendations = [
        f.get("recommendation")
        for f in data["findings"]
        if f.get("recommendation")
    ]
    if recommendations:
        for idx, rec in enumerate(recommendations, 1):
            lines.append(f"{idx}. {rec}")
        lines.append("")
    else:
        lines.append("_No specific recommendations recorded._")
        lines.append("")

    # -- Tool output appendix -----------------------------------------------
    lines.append("## Appendix: Tool Output")
    lines.append("")

    if data["tool_calls"]:
        for tc in data["tool_calls"]:
            tool = tc.get("tool", "unknown")
            lines.append(f"### `{tool}`")
            lines.append("")
            if tc.get("args"):
                lines.append(f"**Arguments:** `{tc['args']}`")
                lines.append("")
            if tc.get("output"):
                lines.append("```")
                lines.append(str(tc["output"]))
                lines.append("```")
                lines.append("")
    else:
        lines.append("_No tool output recorded._")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML template (inline)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StrikeCore Report &mdash; {{ session_id }}</title>
<style>
  :root {
    --bg: #fafafa; --fg: #212121; --accent: #1565c0;
    --critical: #7b2d8e; --high: #d32f2f; --medium: #f57c00;
    --low: #1976d2; --info: #616161;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
         color: var(--fg); line-height: 1.6; max-width: 960px; margin: 0 auto;
         padding: 2rem 1rem; }
  h1 { color: var(--accent); border-bottom: 3px solid var(--accent);
       padding-bottom: .5rem; margin-bottom: 1.5rem; }
  h2 { color: var(--accent); margin-top: 2rem; margin-bottom: .75rem;
       border-bottom: 1px solid #ccc; padding-bottom: .3rem; }
  h3 { margin-top: 1.2rem; margin-bottom: .4rem; }
  .meta { background: #e3f2fd; padding: 1rem; border-radius: 6px;
          margin-bottom: 1.5rem; }
  .meta span { display: inline-block; margin-right: 2rem; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 4px;
           color: #fff; font-weight: 700; font-size: .85rem; }
  .badge-critical { background: var(--critical); }
  .badge-high { background: var(--high); }
  .badge-medium { background: var(--medium); }
  .badge-low { background: var(--low); }
  .badge-info { background: var(--info); }
  .finding { background: #fff; border: 1px solid #ddd; border-radius: 6px;
             padding: 1rem 1.25rem; margin-bottom: 1rem;
             border-left: 4px solid #ccc; }
  .finding-critical { border-left-color: var(--critical); }
  .finding-high { border-left-color: var(--high); }
  .finding-medium { border-left-color: var(--medium); }
  .finding-low { border-left-color: var(--low); }
  .finding-info { border-left-color: var(--info); }
  pre { background: #263238; color: #eeffff; padding: 1rem; border-radius: 4px;
        overflow-x: auto; margin: .5rem 0; font-size: .9rem; }
  code { font-family: 'Fira Code', 'Consolas', monospace; }
  ul, ol { padding-left: 1.5rem; margin: .5rem 0; }
  table { width: 100%; border-collapse: collapse; margin: .75rem 0; }
  th, td { text-align: left; padding: .4rem .6rem; border: 1px solid #ccc; }
  th { background: #e8eaf6; }
  .footer { margin-top: 3rem; text-align: center; color: #999;
            font-size: .85rem; }
</style>
</head>
<body>

<h1>StrikeCore Penetration Test Report</h1>

<div class="meta">
  <span><strong>Session:</strong> <code>{{ session_id }}</code></span>
  <span><strong>Start:</strong> {{ start_time or "N/A" }}</span>
  <span><strong>End:</strong> {{ end_time or "N/A" }}</span>
  <span><strong>Generated:</strong> {{ generated }}</span>
</div>

<h2>Executive Summary</h2>
{% if findings %}
<p>A total of <strong>{{ findings | length }}</strong> finding(s) were identified:</p>
<table>
  <tr><th>Severity</th><th>Count</th></tr>
  {% for sev, count in severity_counts.items() %}
  <tr>
    <td><span class="badge badge-{{ sev }}">{{ sev | upper }}</span></td>
    <td>{{ count }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No findings were recorded during this session.</p>
{% endif %}

<h2>Methodology</h2>
{% if tool_names %}
<p>The following tools were employed during the engagement:</p>
<ul>
  {% for t in tool_names %}<li><code>{{ t }}</code></li>{% endfor %}
</ul>
{% else %}
<p>No automated tools were recorded for this session.</p>
{% endif %}
{% if commands %}
<p>A total of <strong>{{ commands | length }}</strong> commands were executed.</p>
{% endif %}

<h2>Findings</h2>
{% if findings %}
{% for f in findings %}
{% set sev = (f.severity | default("info")) | lower %}
<div class="finding finding-{{ sev }}">
  <h3>{{ loop.index }}. {{ f.title or f.get("name", "Finding " ~ loop.index) }}
    <span class="badge badge-{{ sev }}">{{ sev | upper }}</span>
  </h3>
  {% if f.description %}<p>{{ f.description }}</p>{% endif %}
  {% if f.evidence %}<p><strong>Evidence:</strong></p><pre><code>{{ f.evidence }}</code></pre>{% endif %}
  {% if f.recommendation %}<p><strong>Recommendation:</strong> {{ f.recommendation }}</p>{% endif %}
  {% if f.references %}
  <p><strong>References:</strong></p>
  <ul>{% for ref in f.references %}<li>{{ ref }}</li>{% endfor %}</ul>
  {% endif %}
</div>
{% endfor %}
{% else %}
<p><em>No findings recorded.</em></p>
{% endif %}

<h2>Recommendations</h2>
{% if recommendations %}
<ol>
  {% for rec in recommendations %}<li>{{ rec }}</li>{% endfor %}
</ol>
{% else %}
<p><em>No specific recommendations recorded.</em></p>
{% endif %}

<h2>Appendix: Tool Output</h2>
{% if tool_calls %}
{% for tc in tool_calls %}
<h3><code>{{ tc.tool or "unknown" }}</code></h3>
{% if tc.args %}<p><strong>Arguments:</strong> <code>{{ tc.args }}</code></p>{% endif %}
{% if tc.output %}<pre><code>{{ tc.output }}</code></pre>{% endif %}
{% endfor %}
{% else %}
<p><em>No tool output recorded.</em></p>
{% endif %}

<div class="footer">
  Generated by StrikeCore &mdash; {{ generated }}
</div>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------


class _DictAccessor(dict):
    """Dict subclass that supports Jinja2 dot-access (``f.title``)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            return None


def _render_html(data: Dict[str, Any]) -> str:
    env = Environment(loader=BaseLoader(), autoescape=True)
    # Register a 'default' filter for Jinja2
    env.filters.setdefault("default", lambda v, d="": d if v is None else v)

    template = env.from_string(_HTML_TEMPLATE)

    # Build severity counts
    severity_counts: Dict[str, int] = {}
    for f in data["findings"]:
        sev = str(f.get("severity", "info")).lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    tool_names = sorted({tc.get("tool", "unknown") for tc in data["tool_calls"]})
    recommendations = [
        f.get("recommendation")
        for f in data["findings"]
        if f.get("recommendation")
    ]

    # Wrap findings so Jinja2 dot-access works
    findings = [_DictAccessor(f) for f in data["findings"]]

    return template.render(
        session_id=data["session_id"],
        start_time=data["start_time"],
        end_time=data["end_time"],
        generated=datetime.now(timezone.utc).isoformat(),
        findings=findings,
        severity_counts=severity_counts,
        tool_names=tool_names,
        tool_calls=[_DictAccessor(tc) for tc in data["tool_calls"]],
        commands=data["commands"],
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def _render_json(data: Dict[str, Any]) -> str:
    output = {
        "session_id": data["session_id"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "generated": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_findings": len(data["findings"]),
            "total_commands": len(data["commands"]),
            "total_tool_calls": len(data["tool_calls"]),
            "total_ai_interactions": len(data["ai_interactions"]),
        },
        "findings": data["findings"],
        "tool_calls": data["tool_calls"],
        "commands": data["commands"],
        "recommendations": [
            f.get("recommendation")
            for f in data["findings"]
            if f.get("recommendation")
        ],
    }
    return json.dumps(output, indent=2, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_RENDERERS = {
    "markdown": _render_markdown,
    "md": _render_markdown,
    "html": _render_html,
    "json": _render_json,
}


def generate_report(
    session_id: str,
    fmt: str = "markdown",
    *,
    audit_logger: Optional[AuditLogger] = None,
) -> str:
    """Generate a pentest report for *session_id*.

    Parameters
    ----------
    session_id:
        The session whose audit entries should be compiled.
    fmt:
        Output format -- ``'markdown'`` (default), ``'html'``, or ``'json'``.
    audit_logger:
        Optional :class:`AuditLogger` instance.  Defaults to the module-level
        singleton.

    Returns
    -------
    str
        The rendered report content.
    """
    renderer = _RENDERERS.get(fmt.lower())
    if renderer is None:
        raise ValueError(
            f"Unsupported report format: {fmt!r}. "
            f"Choose from: {', '.join(_RENDERERS)}"
        )

    data = _collect_session_data(session_id, audit_logger=audit_logger)
    return renderer(data)


def save_report(
    session_id: str,
    path: str | Path,
    fmt: str = "markdown",
    *,
    audit_logger: Optional[AuditLogger] = None,
) -> Path:
    """Generate a report and write it to *path*.

    Parameters
    ----------
    session_id:
        The session whose audit entries should be compiled.
    path:
        Destination file path.
    fmt:
        Output format -- ``'markdown'``, ``'html'``, or ``'json'``.
    audit_logger:
        Optional :class:`AuditLogger` instance.

    Returns
    -------
    Path
        The resolved path of the written file.
    """
    content = generate_report(session_id, fmt=fmt, audit_logger=audit_logger)
    dest = Path(path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest
