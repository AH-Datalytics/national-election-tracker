"""Race detail and geographic breakdown endpoints."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException

from api.db import get_readonly_db

router = APIRouter(prefix="/api", tags=["races"])


def _validate_state(db, state: str) -> str:
    code = state.upper()
    row = db.execute("SELECT code FROM states WHERE code = ?", (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "State not found"})
    return code


def _get_race(db, state_code: str, race_key: str):
    """Fetch a race row, validating it belongs to the given state."""
    race = db.execute(
        """
        SELECT r.*, e.state, e.election_key
        FROM races r
        JOIN elections e ON e.id = r.election_id
        WHERE r.race_key = ? AND e.state = ?
        """,
        (race_key, state_code),
    ).fetchone()
    if not race:
        raise HTTPException(status_code=404, detail={"error": "Race not found"})
    return race


@router.get("/{state}/races/{race_key}")
def get_race(state: str, race_key: str):
    """
    Full race detail.

    Returns race metadata, choices with totals, ballot measure flag,
    and whether precinct-level data is available.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)
    race = _get_race(db, code, race_key)

    # Choices
    choices = db.execute(
        """
        SELECT choice_key, choice_type, name, party, ballot_order,
               color_hex, outcome, vote_total
        FROM choices
        WHERE race_id = ?
        ORDER BY vote_total DESC
        """,
        (race["id"],),
    ).fetchall()

    # Check for precinct data
    has_precinct = db.execute(
        "SELECT 1 FROM votes_precinct WHERE race_id = ? LIMIT 1",
        (race["id"],),
    ).fetchone() is not None

    # Reporting info
    reporting = db.execute(
        """
        SELECT county_code, precincts_reporting, precincts_expected
        FROM race_reporting
        WHERE race_id = ?
        """,
        (race["id"],),
    ).fetchall()

    return {
        "race_key": race["race_key"],
        "election_key": race["election_key"],
        "state": race["state"],
        "title": race["title"],
        "office_category": race["office_category"],
        "office_name": race["office_name"],
        "district": race["district"],
        "county_code": race["county_code"],
        "num_to_elect": race["num_to_elect"],
        "is_ballot_measure": race["is_ballot_measure"],
        "has_precinct_data": has_precinct,
        "choices": [dict(c) for c in choices],
        "reporting": [dict(r) for r in reporting],
    }


@router.get("/{state}/races/{race_key}/counties")
def get_race_counties(state: str, race_key: str):
    """
    County-level results for a race.

    Returns an array of county objects, each with choice vote totals
    and reporting status.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)
    race = _get_race(db, code, race_key)

    # County votes with choice details
    rows = db.execute(
        """
        SELECT
            vc.county_code,
            co.name AS county_name,
            c.name AS choice_name,
            c.party,
            c.choice_key,
            vc.vote_total
        FROM votes_county vc
        JOIN choices c ON c.id = vc.choice_id
        LEFT JOIN counties co ON co.state = ? AND co.code = vc.county_code
        WHERE vc.race_id = ?
        ORDER BY vc.county_code, vc.vote_total DESC
        """,
        (code, race["id"]),
    ).fetchall()

    # Group by county
    counties_map: dict[str, dict] = {}
    for r in rows:
        cc = r["county_code"]
        if cc not in counties_map:
            counties_map[cc] = {
                "county_code": cc,
                "county_name": r["county_name"],
                "choices": [],
                "precincts_reporting": 0,
                "precincts_expected": 0,
            }
        counties_map[cc]["choices"].append({
            "name": r["choice_name"],
            "party": r["party"],
            "choice_key": r["choice_key"],
            "vote_total": r["vote_total"],
        })

    # Reporting data per county
    reporting = db.execute(
        """
        SELECT county_code, precincts_reporting, precincts_expected
        FROM race_reporting
        WHERE race_id = ? AND county_code IS NOT NULL
        """,
        (race["id"],),
    ).fetchall()
    for rp in reporting:
        cc = rp["county_code"]
        if cc in counties_map:
            counties_map[cc]["precincts_reporting"] = rp["precincts_reporting"]
            counties_map[cc]["precincts_expected"] = rp["precincts_expected"]

    return list(counties_map.values())


@router.get("/{state}/races/{race_key}/precincts/{county_code}")
def get_race_precincts(state: str, race_key: str, county_code: str):
    """
    Precinct-level results for a race in a specific county.

    Returns an array of precinct objects, each with choice vote totals.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)
    race = _get_race(db, code, race_key)

    rows = db.execute(
        """
        SELECT
            vp.precinct_id,
            c.name AS choice_name,
            c.party,
            c.choice_key,
            vp.vote_total
        FROM votes_precinct vp
        JOIN choices c ON c.id = vp.choice_id
        WHERE vp.race_id = ? AND vp.county_code = ?
        ORDER BY vp.precinct_id, vp.vote_total DESC
        """,
        (race["id"], county_code),
    ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "No precinct data found for this county"},
        )

    # Group by precinct
    precincts_map: dict[str, dict] = {}
    for r in rows:
        pid = r["precinct_id"]
        if pid not in precincts_map:
            precincts_map[pid] = {"precinct_id": pid, "choices": []}
        precincts_map[pid]["choices"].append({
            "name": r["choice_name"],
            "party": r["party"],
            "choice_key": r["choice_key"],
            "vote_total": r["vote_total"],
        })

    return list(precincts_map.values())
