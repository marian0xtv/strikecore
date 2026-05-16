"""Strikecore FastAPI backend — Phase C.

Surface:
    REST     /api/health, /api/agents, /api/dossiers, /api/dossiers/{id},
             /api/runs, /api/runs/{id}, /api/traces, /api/improvements,
             /api/tokens/summary, /api/settings, /api/console/dossier
    WS       /ws/traces — live stream from Postgres LISTEN/NOTIFY trace_channel

Reads directly from Postgres (Phase A schema). Writes only via /api/console.
"""
