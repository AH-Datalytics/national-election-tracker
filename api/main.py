"""
National Election Tracker — FastAPI Application

Read-only REST API serving election data from a single SQLite database.
Runs on Hetzner alongside the database; the Next.js frontend on Vercel
calls these endpoints.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import elections, health, live, maps, races, states

app = FastAPI(
    title="National Election Tracker",
    description="Election results API — every race, every state, precinct-level.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow Vercel frontend (configurable via env)
# ---------------------------------------------------------------------------
cors_origins_raw = os.environ.get("CORS_ORIGINS", "*")
if cors_origins_raw == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(states.router)
app.include_router(elections.router)
app.include_router(races.router)
app.include_router(live.router)
app.include_router(maps.router)
