"""
StrikeCore Report Builder — Structured Markdown + HTML intelligence reports.

Reads from InvestigationStore and generates professional reports.
"""
from __future__ import annotations
import json, os, time
from datetime import datetime
from pathlib import Path
from typing import Any

REPORTS_DIR = Path.home() / "strikecore-data" / "reports"

def build_report(store_data: dict, format: str = "markdown") -> str:
    """Generate a structured report from investigation store data."""
    d = store_data
    target = d["identity"]["names"][0] if d["identity"]["names"] else d["target_id"]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    total_findings = len(d["emails"]) + len(d["phones"]) + len(d["profiles"])
    confirmed = sum(1 for e in d["emails"].values() if e["confidence"] == "CONFIRMED")
    
    md = f"""# OSINT INVESTIGATION REPORT
**Target:** {target}  
**Classification:** CONFIDENTIAL  
**Date:** {ts}  
**Analyst:** StrikeCore AI  
**Findings:** {total_findings} total, {confirmed} confirmed  

---

## 1. EXECUTIVE SUMMARY

Target **{target}** (usernames: {', '.join(d['identity']['usernames'])}) investigated across {len(d.get('phase_log', []))} phases using automated OSINT tools. 
{'**' + str(len(d['emails'])) + ' email addresses** identified' if d['emails'] else 'No emails identified'}, \
{'**' + str(len(d['phones'])) + ' phone numbers** identified' if d['phones'] else 'no phone numbers found'}. \
Digital footprint spans **{len(d['profiles'])} platforms**. \
{'Associated with **' + ', '.join(d['organizations'].keys()) + '**.' if d['organizations'] else ''}

---

## 2. TARGET PROFILE

| Field | Value |
|-------|-------|
| **Full Name** | {', '.join(d['identity']['names']) or 'Unknown'} |
| **Usernames** | {', '.join(d['identity']['usernames']) or 'N/A'} |
| **DOB/Age** | {d['identity'].get('dob') or 'Unknown'} |
| **Nationality** | {d['identity'].get('nationality') or 'Unknown'} |
| **Location** | {', '.join(l['name'] for l in d['locations']) or 'Unknown'} |

"""
    # Notes
    if d.get("notes"):
        md += "**Analyst Notes:**\n"
        for n in d["notes"]:
            md += f"- {n['text']}\n"
        md += "\n"

    # Emails
    md += """---

## 3. DIGITAL FOOTPRINT

### 3.1 Email Addresses

| Email | Confidence | Sources |
|-------|-----------|---------|
"""
    for email, info in sorted(d["emails"].items(), key=lambda x: (0 if x[1]["confidence"]=="CONFIRMED" else 1)):
        sources = ', '.join(info["sources"][:3])
        md += f"| `{email}` | **{info['confidence']}** | {sources} |\n"

    # Phones
    md += """\n### 3.2 Phone Numbers

| Number | Confidence | Carrier | Sources |
|--------|-----------|---------|---------|
"""
    if d["phones"]:
        for phone, info in d["phones"].items():
            sources = ', '.join(info["sources"][:3])
            md += f"| `{phone}` | **{info['confidence']}** | {info.get('carrier', 'N/A')} | {sources} |\n"
    else:
        md += "| *None identified* | — | — | — |\n"

    # Profiles
    md += """\n### 3.3 Online Profiles

| Platform | URL | Confidence | Notes |
|----------|-----|-----------|-------|
"""
    for platform, info in d["profiles"].items():
        md += f"| **{platform}** | {info['url']} | {info['confidence']} | {info.get('notes', '')[:50]} |\n"

    # Organizations
    if d["organizations"]:
        md += """\n---

## 4. ORGANIZATIONAL INTELLIGENCE

| Organization | Role | Source |
|-------------|------|--------|
"""
        for name, info in d["organizations"].items():
            md += f"| **{name}** | {info.get('role', 'N/A')} | {info.get('source', 'N/A')} |\n"

    # Social graph
    if d["social_graph"]:
        md += f"""\n---

## 5. HUMAN INTELLIGENCE — Social Graph

| Connection | Relation | Platform |
|-----------|----------|----------|
"""
        for c in d["social_graph"][:20]:
            md += f"| {c['name']} | {c['relation']} | {c.get('platform', 'N/A')} |\n"

    # Breach exposure
    if d.get("breaches"):
        md += """\n---

## 6. BREACH EXPOSURE

| Breach | Data Types | Date |
|--------|-----------|------|
"""
        for b in d["breaches"]:
            md += f"| {b['breach_name']} | {b['data_types']} | {b['date']} |\n"

    # Timeline
    md += f"""\n---

## 7. INVESTIGATION TIMELINE

| Phase | Date | Tools | Findings |
|-------|------|-------|----------|
"""
    for phase in d.get("phase_log", []):
        tools = ', '.join(phase.get("tools_used", [])[:4])
        md += f"| {phase['phase']} | {phase['timestamp'][:10]} | {tools} | {phase['findings_count']} |\n"

    # Recommendations
    md += """\n---

## 8. RECOMMENDATIONS

"""
    if not d["phones"]:
        md += "- **Phone discovery:** Investigate breach databases with confirmed emails, check Italian business registries (Registro Imprese) for P.IVA\n"
    if not any("linkedin" in p.lower() for p in d["profiles"]):
        md += "- **LinkedIn:** Search by confirmed emails or use CrossLinked with known organizations\n"
    if d["organizations"]:
        md += f"- **Corporate investigation:** Deeper recon on {', '.join(list(d['organizations'].keys())[:2])} for additional contact vectors\n"
    md += "- **Continuous monitoring:** Set up alerts for target username and email appearances in new breaches\n"

    # Raw evidence summary
    if d.get("raw_evidence"):
        md += f"""\n---

## 9. RAW EVIDENCE

<details>
<summary>Click to expand ({len(d['raw_evidence'])} tool outputs)</summary>

"""
        for tool, evidences in d["raw_evidence"].items():
            md += f"### {tool}\n```\n"
            md += evidences[-1]["output"][:1000] if evidences else "(empty)"
            md += "\n```\n\n"
        md += "</details>\n"

    md += f"""\n---

*Report generated by StrikeCore v1.0 — {ts}*  
*Classification: CONFIDENTIAL — Authorized distribution only*
"""
    return md


def save_report(store_data: dict, target_id: str) -> tuple[str, str]:
    """Save report as both .md and .html. Returns (md_path, html_path)."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    md_content = build_report(store_data)
    md_path = REPORTS_DIR / f"{target_id}_report.md"
    md_path.write_text(md_content)
    
    # Convert to HTML with dark theme
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Report: {target_id}</title>
<style>
body {{ background: #0a0a1a; color: #d0d0d0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace; max-width: 900px; margin: 0 auto; padding: 40px; line-height: 1.6; }}
h1 {{ color: #ff3333; border-bottom: 2px solid #ff3333; padding-bottom: 10px; }}
h2 {{ color: #00cccc; border-bottom: 1px solid #333; padding-bottom: 5px; margin-top: 30px; }}
h3 {{ color: #ffcc00; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th {{ background: #1a1a3a; color: #00cccc; padding: 8px 12px; text-align: left; border: 1px solid #333; }}
td {{ padding: 6px 12px; border: 1px solid #222; }}
tr:nth-child(even) {{ background: #0d0d2b; }}
code {{ background: #1a1a3a; padding: 2px 6px; border-radius: 3px; color: #3399ff; }}
a {{ color: #3399ff; }}
details {{ margin: 10px 0; padding: 10px; background: #0d0d2b; border-radius: 6px; }}
summary {{ cursor: pointer; color: #ffcc00; font-weight: bold; }}
pre {{ background: #0d0d2b; padding: 15px; border-radius: 6px; overflow-x: auto; border: 1px solid #333; }}
strong {{ color: #ffffff; }}
hr {{ border: none; border-top: 1px solid #333; margin: 20px 0; }}
</style></head><body>"""
    
    # Simple markdown to HTML conversion
    import re
    lines = md_content.split('\n')
    in_table = False
    in_code = False
    in_details = False
    
    for line in lines:
        if line.startswith('```'):
            if in_code:
                html += '</code></pre>\n'
                in_code = False
            else:
                html += '<pre><code>'
                in_code = True
            continue
        if in_code:
            html += line.replace('<', '&lt;').replace('>', '&gt;') + '\n'
            continue
        if line.startswith('<details>') or line.startswith('<summary>') or line.startswith('</details>') or line.startswith('</summary>'):
            html += line + '\n'
            continue
        if line.startswith('# '):
            html += f'<h1>{line[2:]}</h1>\n'
        elif line.startswith('## '):
            html += f'<h2>{line[3:]}</h2>\n'
        elif line.startswith('### '):
            html += f'<h3>{line[4:]}</h3>\n'
        elif line.startswith('| ') and '---' in line:
            continue
        elif line.startswith('| '):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if not in_table:
                html += '<table><thead><tr>' + ''.join(f'<th>{c}</th>' for c in cells) + '</tr></thead><tbody>\n'
                in_table = True
            else:
                # Bold and code in cells
                processed = []
                for c in cells:
                    c = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', c)
                    c = re.sub(r'`([^`]+)`', r'<code>\1</code>', c)
                    processed.append(c)
                html += '<tr>' + ''.join(f'<td>{c}</td>' for c in processed) + '</tr>\n'
        else:
            if in_table:
                html += '</tbody></table>\n'
                in_table = False
            line = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', line)
            line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
            if line.startswith('- '):
                html += f'<li>{line[2:]}</li>\n'
            elif line.startswith('---'):
                html += '<hr>\n'
            elif line.strip():
                html += f'<p>{line}</p>\n'
    
    if in_table:
        html += '</tbody></table>\n'
    html += '</body></html>'
    
    html_path = REPORTS_DIR / f"{target_id}_report.html"
    html_path.write_text(html)
    
    return str(md_path), str(html_path)
