"""Map file serving endpoints."""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.db import DB_PATH

router = APIRouter(prefix="/api/maps", tags=["maps"])

# Maps directory — use MAPS_DIR env var if set, otherwise fall back to data/maps/
MAPS_DIR = os.environ.get(
    "MAPS_DIR",
    os.path.join(os.path.dirname(DB_PATH), "maps"),
)


@router.get("/us-states.json")
def us_states_map():
    """Serve the US states TopoJSON file."""
    path = os.path.join(MAPS_DIR, "us-states.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail={"error": "US states map not found"})
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{state}/counties.json")
def county_map(state: str):
    """Serve a state's county TopoJSON file."""
    code = state.upper()
    path = os.path.join(MAPS_DIR, code.lower(), "counties.json")
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail={"error": f"County map not found for {code}"},
        )
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{state}/precincts/{county_code}.json")
def precinct_map(state: str, county_code: str):
    """Serve precinct boundaries for a specific county."""
    code = state.upper()
    path = os.path.join(
        MAPS_DIR, code.lower(), "precincts", f"{county_code}.json"
    )
    if not os.path.isfile(path):
        raise HTTPException(
            status_code=404,
            detail={"error": f"Precinct map not found for {code} county {county_code}"},
        )
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )
