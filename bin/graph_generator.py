#!/usr/bin/env python3
"""
StrikeCore Intelligence Graph Generator.

Generates an interactive HTML network graph of OSINT connections
using vis.js. No external dependencies — pure HTML/JS output.

Usage:
  graph_generator.py OUTPUT.html [--data JSON_FILE]
  
Or import and call: generate_graph(data_dict, output_path)
"""

import json
import os
import sys
import html as html_mod
from datetime import datetime


TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>StrikeCore Intelligence Graph — {target}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a1a; color: #e0e0e0; font-family: 'Courier New', monospace; }}
  #header {{
    background: linear-gradient(135deg, #1a0a2e, #0a1a3e);
    padding: 20px 30px;
    border-bottom: 2px solid #ff3333;
  }}
  #header h1 {{ color: #ff3333; font-size: 24px; }}
  #header .meta {{ color: #888; font-size: 12px; margin-top: 5px; }}
  #container {{ display: flex; height: calc(100vh - 80px); }}
  #graph {{ flex: 1; background: #0d0d2b; }}
  #sidebar {{
    width: 380px; background: #0f0f2f; border-left: 1px solid #333;
    overflow-y: auto; padding: 15px;
  }}
  #sidebar h2 {{ color: #00cccc; font-size: 16px; margin: 15px 0 8px 0; border-bottom: 1px solid #333; padding-bottom: 5px; }}
  #sidebar .item {{ padding: 6px 10px; margin: 3px 0; background: #1a1a3a; border-radius: 4px; font-size: 12px; word-break: break-all; }}
  .conf-confirmed {{ border-left: 3px solid #00ff00; }}
  .conf-probable {{ border-left: 3px solid #ffcc00; }}
  .conf-unverified {{ border-left: 3px solid #ff6600; }}
  .tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-left: 5px; }}
  .tag-confirmed {{ background: #003300; color: #00ff00; }}
  .tag-probable {{ background: #332200; color: #ffcc00; }}
  .tag-email {{ background: #001a33; color: #3399ff; }}
  .tag-phone {{ background: #1a0033; color: #cc66ff; }}
  .tag-social {{ background: #330011; color: #ff3366; }}
  .tag-org {{ background: #002233; color: #00cccc; }}
  #node-info {{
    position: fixed; bottom: 20px; left: 20px; background: #1a1a3a;
    border: 1px solid #444; padding: 12px; border-radius: 6px;
    max-width: 400px; display: none; font-size: 12px;
  }}
  #legend {{
    position: fixed; top: 90px; right: 400px; background: rgba(15,15,47,0.9);
    padding: 10px; border-radius: 6px; font-size: 11px; border: 1px solid #333;
  }}
  #legend div {{ margin: 3px 0; }}
  #legend span {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}
</style>
</head>
<body>
<div id="header">
  <h1>&#9760; STRIKECORE INTELLIGENCE GRAPH</h1>
  <div class="meta">Target: {target} | Generated: {timestamp} | Classification: CONFIDENTIAL</div>
</div>
<div id="container">
  <div id="graph"></div>
  <div id="sidebar">
    <h2>&#128100; TARGET</h2>
    <div class="item">{target}</div>
    {sidebar_html}
  </div>
</div>
<div id="node-info"></div>
<div id="legend">
  <div><span style="background:#ff3333"></span> Target</div>
  <div><span style="background:#3399ff"></span> Email</div>
  <div><span style="background:#cc66ff"></span> Phone</div>
  <div><span style="background:#00cc66"></span> Social Profile</div>
  <div><span style="background:#ff9933"></span> Organization</div>
  <div><span style="background:#00cccc"></span> Location</div>
  <div><span style="background:#ffcc00"></span> Alias</div>
  <div><span style="background:#ff6699"></span> Person</div>
</div>
<script>
var nodes = new vis.DataSet({nodes_json});
var edges = new vis.DataSet({edges_json});
var container = document.getElementById('graph');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  physics: {{
    forceAtlas2Based: {{ gravitationalConstant: -120, centralGravity: 0.008, springLength: 150, springConstant: 0.02, damping: 0.5 }},
    solver: 'forceAtlas2Based',
    stabilization: {{ iterations: 200 }}
  }},
  nodes: {{
    font: {{ color: '#e0e0e0', size: 12, face: 'Courier New' }},
    borderWidth: 2,
    shadow: {{ enabled: true, color: 'rgba(0,0,0,0.5)', size: 10 }}
  }},
  edges: {{
    color: {{ color: '#444', highlight: '#888' }},
    font: {{ color: '#666', size: 9, face: 'Courier New', align: 'middle' }},
    smooth: {{ type: 'continuous' }}
  }},
  interaction: {{ hover: true, tooltipDelay: 200, navigationButtons: true }},
}};
var network = new vis.Network(container, data, options);
var nodeInfo = document.getElementById('node-info');
network.on('click', function(params) {{
  if (params.nodes.length > 0) {{
    var node = nodes.get(params.nodes[0]);
    nodeInfo.style.display = 'block';
    nodeInfo.innerHTML = '<b>' + node.label + '</b><br>' + (node.title || '');
  }} else {{
    nodeInfo.style.display = 'none';
  }}
}});
</script>
</body>
</html>'''


def generate_graph(data: dict, output_path: str) -> str:
    """Generate an HTML intelligence graph from OSINT data."""
    nodes = []
    edges = []
    node_id = 0
    
    target_name = data.get("target", "Unknown")
    
    # Central target node
    nodes.append({
        "id": node_id, "label": target_name,
        "color": {"background": "#ff3333", "border": "#ff0000"},
        "size": 40, "shape": "dot",
        "title": f"Primary target: {target_name}",
        "font": {"size": 16, "color": "#ffffff"}
    })
    target_id = node_id
    node_id += 1
    
    # Aliases / usernames
    for alias in data.get("aliases", []):
        nodes.append({
            "id": node_id, "label": alias,
            "color": {"background": "#ffcc00", "border": "#cc9900"},
            "size": 20, "shape": "dot",
            "title": f"Alias: {alias}"
        })
        edges.append({"from": target_id, "to": node_id, "label": "alias", "dashes": True})
        node_id += 1
    
    # Emails
    for email_data in data.get("emails", []):
        email = email_data if isinstance(email_data, str) else email_data.get("email", "")
        source = "" if isinstance(email_data, str) else email_data.get("source", "")
        confidence = "CONFIRMED" if isinstance(email_data, str) else email_data.get("confidence", "PROBABLE")
        
        border = "#00ff00" if confidence == "CONFIRMED" else "#ffcc00"
        nodes.append({
            "id": node_id, "label": email,
            "color": {"background": "#3399ff", "border": border},
            "size": 25, "shape": "dot",
            "title": f"Email: {email}\nSource: {source}\nConfidence: {confidence}"
        })
        edges.append({"from": target_id, "to": node_id, "label": "email"})
        node_id += 1
    
    # Phones
    for phone_data in data.get("phones", []):
        phone = phone_data if isinstance(phone_data, str) else phone_data.get("number", "")
        carrier = "" if isinstance(phone_data, str) else phone_data.get("carrier", "")
        
        nodes.append({
            "id": node_id, "label": phone,
            "color": {"background": "#cc66ff", "border": "#9933cc"},
            "size": 22, "shape": "dot",
            "title": f"Phone: {phone}\nCarrier: {carrier}"
        })
        edges.append({"from": target_id, "to": node_id, "label": "phone"})
        node_id += 1
    
    # Social profiles
    for profile in data.get("profiles", []):
        platform = profile.get("platform", "?")
        url = profile.get("url", "")
        
        nodes.append({
            "id": node_id, "label": platform,
            "color": {"background": "#00cc66", "border": "#009944"},
            "size": 18, "shape": "dot",
            "title": f"{platform}: {url}"
        })
        edges.append({"from": target_id, "to": node_id, "label": "profile"})
        node_id += 1
    
    # Organizations
    for org in data.get("organizations", []):
        org_name = org if isinstance(org, str) else org.get("name", "")
        role = "" if isinstance(org, str) else org.get("role", "")
        
        nodes.append({
            "id": node_id, "label": org_name,
            "color": {"background": "#ff9933", "border": "#cc6600"},
            "size": 25, "shape": "diamond",
            "title": f"Organization: {org_name}\nRole: {role}"
        })
        edges.append({"from": target_id, "to": node_id, "label": role or "org"})
        
        org_id = node_id
        node_id += 1
        
        # Link org emails to org
        for email_data in data.get("emails", []):
            email = email_data if isinstance(email_data, str) else email_data.get("email", "")
            if isinstance(org_name, str) and org_name.lower().replace(" ", "") in email.lower().replace(".", "").replace("-", ""):
                # Find the email node and add edge from org
                for n in nodes:
                    if n.get("label") == email:
                        edges.append({"from": org_id, "to": n["id"], "label": "work email", "dashes": True})
                        break
        node_id  # just in case
    
    # Locations
    for loc in data.get("locations", []):
        loc_name = loc if isinstance(loc, str) else loc.get("name", "")
        
        nodes.append({
            "id": node_id, "label": loc_name,
            "color": {"background": "#00cccc", "border": "#009999"},
            "size": 18, "shape": "triangle",
            "title": f"Location: {loc_name}"
        })
        edges.append({"from": target_id, "to": node_id, "label": "location"})
        node_id += 1
    
    # Connections (other people)
    for conn in data.get("connections", []):
        conn_name = conn if isinstance(conn, str) else conn.get("name", "")
        relation = "" if isinstance(conn, str) else conn.get("relation", "")
        
        nodes.append({
            "id": node_id, "label": conn_name,
            "color": {"background": "#ff6699", "border": "#cc3366"},
            "size": 16, "shape": "dot",
            "title": f"Connection: {conn_name}\nRelation: {relation}"
        })
        edges.append({"from": target_id, "to": node_id, "label": relation or "connection", "dashes": True})
        node_id += 1
    
    # Build sidebar HTML
    sidebar_parts = []
    
    if data.get("emails"):
        sidebar_parts.append('<h2>&#9993; EMAILS</h2>')
        for e in data["emails"]:
            email = e if isinstance(e, str) else e.get("email", "")
            source = "" if isinstance(e, str) else e.get("source", "")
            conf = "confirmed" if isinstance(e, str) else e.get("confidence", "probable").lower()
            sidebar_parts.append(f'<div class="item conf-{conf}">{email}<span class="tag tag-{conf}">{conf.upper()}</span><br><small>{source}</small></div>')
    
    if data.get("phones"):
        sidebar_parts.append('<h2>&#128222; PHONES</h2>')
        for p in data["phones"]:
            phone = p if isinstance(p, str) else p.get("number", "")
            carrier = "" if isinstance(p, str) else p.get("carrier", "")
            sidebar_parts.append(f'<div class="item conf-probable">{phone}<span class="tag tag-phone">PHONE</span><br><small>{carrier}</small></div>')
    
    if data.get("profiles"):
        sidebar_parts.append('<h2>&#127760; PROFILES</h2>')
        for p in data["profiles"]:
            platform = p.get("platform", "")
            url = p.get("url", "")
            sidebar_parts.append(f'<div class="item conf-confirmed"><a href="{url}" style="color:#3399ff" target="_blank">{platform}</a><span class="tag tag-social">SOCIAL</span></div>')
    
    if data.get("organizations"):
        sidebar_parts.append('<h2>&#127970; ORGANIZATIONS</h2>')
        for o in data["organizations"]:
            name = o if isinstance(o, str) else o.get("name", "")
            role = "" if isinstance(o, str) else o.get("role", "")
            sidebar_parts.append(f'<div class="item conf-probable">{name}<span class="tag tag-org">ORG</span><br><small>{role}</small></div>')
    
    if data.get("locations"):
        sidebar_parts.append('<h2>&#128205; LOCATIONS</h2>')
        for l in data["locations"]:
            loc = l if isinstance(l, str) else l.get("name", "")
            sidebar_parts.append(f'<div class="item conf-probable">{loc}</div>')
    
    # Generate HTML
    output = TEMPLATE.format(
        target=html_mod.escape(target_name),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        nodes_json=json.dumps(nodes),
        edges_json=json.dumps(edges),
        sidebar_html="\n".join(sidebar_parts),
    )
    
    with open(output_path, 'w') as f:
        f.write(output)
    
    return output_path


def main():
    if len(sys.argv) < 2:
        print("Usage: graph_generator.py OUTPUT.html [--data JSON_FILE]")
        print("       graph_generator.py OUTPUT.html --target NAME --emails e1,e2 --usernames u1,u2")
        print("       graph_generator.py OUTPUT.html (reads from stdin)")
        print()
        print("JSON format:")
        print(json.dumps({
            "target": "Luigi Savino",
            "aliases": ["luigisav", "LuigiSavino", "luxdj95"],
            "emails": [
                {"email": "luigi.savino.95@gmail.com", "source": "github_commit", "confidence": "CONFIRMED"},
            ],
            "phones": [{"number": "+393401234567", "carrier": "TIM"}],
            "profiles": [{"platform": "Instagram", "url": "https://instagram.com/luigisav"}],
            "organizations": [{"name": "Telecom Italia", "role": "Developer"}],
            "locations": ["Rome, Italy"],
            "connections": [{"name": "John Doe", "relation": "colleague"}],
        }, indent=2))
        sys.exit(0 if "--help" in sys.argv else 1)
    
    output_path = sys.argv[1]
    
    # Load data
    if "--data" in sys.argv:
        idx = sys.argv.index("--data")
        with open(sys.argv[idx + 1]) as f:
            data = json.load(f)
    elif "--target" in sys.argv:
        # Build data from CLI flags
        data = {"target": "", "aliases": [], "emails": [], "phones": [], "profiles": [], "organizations": [], "locations": [], "connections": []}
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--target" and i+1 < len(args):
                data["target"] = args[i+1]; i += 2
            elif args[i] == "--emails" and i+1 < len(args):
                data["emails"] = [{"email": e, "source": "cli", "confidence": "CONFIRMED"} for e in args[i+1].split(",")]; i += 2
            elif args[i] == "--usernames" and i+1 < len(args):
                data["aliases"] = args[i+1].split(","); i += 2
            elif args[i] == "--platforms" and i+1 < len(args):
                data["profiles"] = [{"platform": p, "url": f"https://{p.lower()}.com"} for p in args[i+1].split(",")]; i += 2
            elif args[i] == "--connections" and i+1 < len(args):
                data["connections"] = [{"name": c.replace("_", " "), "relation": "connection"} for c in args[i+1].split(",")]; i += 2
            elif args[i] == "--phones" and i+1 < len(args):
                data["phones"] = [{"number": p, "carrier": ""} for p in args[i+1].split(",")]; i += 2
            elif args[i] == "--orgs" and i+1 < len(args):
                data["organizations"] = [{"name": o, "role": ""} for o in args[i+1].split(",")]; i += 2
            elif args[i] == "--locations" and i+1 < len(args):
                data["locations"] = args[i+1].split(","); i += 2
            else:
                i += 1
    else:
        print("Reading JSON from stdin...")
        data = json.load(sys.stdin)
    
    path = generate_graph(data, output_path)
    print(f"Graph generated: {path}")
    print(f"Open in browser: file://{os.path.abspath(path)}")


if __name__ == "__main__":
    main()
