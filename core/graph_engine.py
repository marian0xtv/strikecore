"""
StrikeCore Graph Engine — networkx + pyvis interactive intelligence graphs.

Reads from InvestigationStore and generates weighted, typed network graphs.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any

import networkx as nx
from pyvis.network import Network

GRAPHS_DIR = Path.home() / "strikecore-data" / "reports" / "graphs"

# Node type → color + shape
NODE_STYLES = {
    "target":   {"color": "#ff3333", "shape": "dot",      "size": 45},
    "email":    {"color": "#3399ff", "shape": "dot",      "size": 22},
    "phone":    {"color": "#cc66ff", "shape": "dot",      "size": 22},
    "profile":  {"color": "#00cc66", "shape": "dot",      "size": 18},
    "org":      {"color": "#ff9933", "shape": "diamond",  "size": 28},
    "location": {"color": "#00cccc", "shape": "triangle", "size": 20},
    "person":   {"color": "#ff6699", "shape": "dot",      "size": 16},
    "alias":    {"color": "#ffcc00", "shape": "dot",      "size": 15},
    "domain":   {"color": "#6699ff", "shape": "square",   "size": 18},
    "ip":       {"color": "#ff4444", "shape": "square",   "size": 18},
}

CONF_BORDER = {"CONFIRMED": "#00ff00", "PROBABLE": "#ffcc00", "UNVERIFIED": "#ff6600"}


def build_graph(store_data: dict) -> tuple[nx.Graph, str]:
    """Build a networkx graph from investigation store data and export as interactive HTML."""
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    
    d = store_data
    G = nx.Graph()
    target_name = d["identity"]["names"][0] if d["identity"]["names"] else d["target_id"]
    target_id = d["target_id"]
    
    # Central target node
    G.add_node(target_name, ntype="target", title=f"Target: {target_name}",
               **NODE_STYLES["target"])
    
    # Aliases
    for alias in d["identity"]["usernames"]:
        G.add_node(alias, ntype="alias", title=f"Alias: {alias}", **NODE_STYLES["alias"])
        G.add_edge(target_name, alias, label="alias", weight=1, color="#555")
    
    # Emails
    for email, info in d["emails"].items():
        conf = info["confidence"]
        border = CONF_BORDER.get(conf, "#666")
        G.add_node(email, ntype="email", title=f"Email [{conf}]\nSources: {', '.join(info['sources'])}",
                   color={"background": NODE_STYLES["email"]["color"], "border": border},
                   shape="dot", size=22 if conf == "CONFIRMED" else 18,
                   borderWidth=3 if conf == "CONFIRMED" else 1)
        G.add_edge(target_name, email, label="email", weight=3 if conf == "CONFIRMED" else 1,
                   color="#3399ff" if conf == "CONFIRMED" else "#555")
    
    # Phones
    for phone, info in d["phones"].items():
        conf = info["confidence"]
        G.add_node(phone, ntype="phone", title=f"Phone [{conf}]\nCarrier: {info.get('carrier', 'N/A')}",
                   **NODE_STYLES["phone"])
        G.add_edge(target_name, phone, label="phone", weight=3, color="#cc66ff")
    
    # Profiles
    for platform, info in d["profiles"].items():
        label = platform
        G.add_node(label, ntype="profile", title=f"{platform}: {info['url']}\n{info.get('notes', '')}",
                   **NODE_STYLES["profile"])
        G.add_edge(target_name, label, label="profile", weight=2, color="#00cc66")
    
    # Organizations
    for org_name, info in d["organizations"].items():
        G.add_node(org_name, ntype="org", title=f"Org: {org_name}\nRole: {info.get('role', 'N/A')}",
                   **NODE_STYLES["org"])
        G.add_edge(target_name, org_name, label=info.get("role", "org"), weight=2, color="#ff9933")
        
        # Link org emails
        for email in d["emails"]:
            org_lower = org_name.lower().replace(" ", "").replace("/", "")
            if any(part in email for part in [org_lower[:5], "telecom", "bip", "mail-bip", "guest.telecom"]):
                if G.has_node(email):
                    G.add_edge(org_name, email, label="work_email", weight=2, color="#ff993380", dashes=True)
    
    # Locations
    for loc in d["locations"]:
        name = loc["name"] if isinstance(loc, dict) else loc
        G.add_node(name, ntype="location", title=f"Location: {name}", **NODE_STYLES["location"])
        G.add_edge(target_name, name, label="location", weight=1, color="#00cccc")
    
    # Social graph
    for conn in d["social_graph"][:25]:
        cname = conn["name"]
        if not G.has_node(cname):
            G.add_node(cname, ntype="person", title=f"{cname}\n{conn['relation']}",
                       **NODE_STYLES["person"])
        G.add_edge(target_name, cname, label=conn["relation"], weight=1, color="#44444480", dashes=True)
    
    # Export with pyvis
    net = Network(height="100vh", width="100%", bgcolor="#0a0a1a", font_color="#e0e0e0",
                  directed=False, select_menu=False, filter_menu=False)
    net.from_nx(G)
    
    net.set_options(json.dumps({
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -100,
                "centralGravity": 0.008,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.5
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 200}
        },
        "edges": {
            "smooth": {"type": "continuous"},
            "font": {"size": 9, "color": "#666", "face": "monospace"}
        },
        "interaction": {"hover": True, "navigationButtons": True, "keyboard": True}
    }))
    
    html_path = str(GRAPHS_DIR / f"{target_id}_graph.html")
    net.save_graph(html_path)
    
    # Inject dark header
    content = Path(html_path).read_text()
    header = f'''<div style="position:fixed;top:0;left:0;right:0;z-index:999;background:linear-gradient(135deg,#1a0a2e,#0a1a3e);
    padding:12px 20px;border-bottom:2px solid #ff3333;font-family:monospace;">
    <span style="color:#ff3333;font-size:18px;font-weight:bold;">&#9760; STRIKECORE</span>
    <span style="color:#888;margin-left:15px;">{target_name} — Intelligence Graph — {len(G.nodes)} nodes, {len(G.edges)} edges</span></div>'''
    content = content.replace('<body>', f'<body>{header}<div style="margin-top:50px">', 1)
    content = content.replace('</body>', '</div></body>')
    Path(html_path).write_text(content)
    
    # Save graph JSON for API/dashboard
    graph_json = nx.node_link_data(G)
    json_path = GRAPHS_DIR / f"{target_id}_graph.json"
    json_path.write_text(json.dumps(graph_json, indent=2, default=str))
    
    return G, html_path
