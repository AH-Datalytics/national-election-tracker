"""State listing and detail endpoints."""

from fastapi import APIRouter, HTTPException

from api.db import get_readonly_db

router = APIRouter(prefix="/api", tags=["states"])


def _state_summary(db, code: str) -> dict | None:
    """Build a state summary dict, or None if the state doesn't exist."""
    state = db.execute("SELECT * FROM states WHERE code = ?", (code.upper(),)).fetchone()
    if not state:
        return None

    stats = db.execute(
        """
        SELECT
            COUNT(DISTINCT e.id) AS election_count,
            COUNT(DISTINCT r.id) AS race_count,
            MIN(e.date) AS earliest,
            MAX(e.date) AS latest
        FROM elections e
        LEFT JOIN races r ON r.election_id = e.id
        WHERE e.state = ?
        """,
        (code.upper(),),
    ).fetchone()

    return {
        "code": state["code"],
        "name": state["name"],
        "fips": state["fips"],
        "county_label": state["county_label"],
        "election_count": stats["election_count"] or 0,
        "race_count": stats["race_count"] or 0,
        "earliest": stats["earliest"],
        "latest": stats["latest"],
    }


@router.get("/states")
def list_states():
    """List all states with election counts, race counts, and date range."""
    db = get_readonly_db()
    rows = db.execute("SELECT code FROM states ORDER BY code").fetchall()
    results = []
    for row in rows:
        summary = _state_summary(db, row["code"])
        if summary:
            results.append(summary)
    return results


@router.get("/states/{code}")
def get_state(code: str):
    """
    Single state detail.

    Returns the same shape as the list endpoint plus a counties array.
    """
    db = get_readonly_db()
    summary = _state_summary(db, code)
    if not summary:
        raise HTTPException(status_code=404, detail={"error": "State not found"})

    counties = db.execute(
        "SELECT code, name, fips, slug FROM counties WHERE state = ? ORDER BY name",
        (code.upper(),),
    ).fetchall()
    summary["counties"] = [dict(c) for c in counties]
    return summary
