"""Live election night status and results endpoints."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException

from api.db import get_readonly_db

router = APIRouter(prefix="/api", tags=["live"])


def _validate_state(db, state: str) -> str:
    code = state.upper()
    row = db.execute("SELECT code FROM states WHERE code = ?", (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "State not found"})
    return code


def _get_live_election(db, state_code: str):
    """
    Find the most recent unofficial election for a state.

    An election is considered 'live' if:
    1. It is not yet marked official (is_official = 0), OR
    2. There is a recent import_run (within last hour) with status 'running' or 'success'.

    Falls back to the most recent election if none are unofficial.
    """
    # First: check for any import_runs in 'running' state within last hour
    active_run = db.execute(
        """
        SELECT ir.election_key, ir.started_at
        FROM import_runs ir
        WHERE ir.state = ?
          AND ir.status = 'running'
          AND ir.started_at > datetime('now', '-1 hour')
        ORDER BY ir.started_at DESC
        LIMIT 1
        """,
        (state_code,),
    ).fetchone()

    if active_run and active_run["election_key"]:
        election = db.execute(
            "SELECT * FROM elections WHERE election_key = ? AND state = ?",
            (active_run["election_key"], state_code),
        ).fetchone()
        if election:
            return election, True

    # Second: find most recent unofficial election
    election = db.execute(
        """
        SELECT * FROM elections
        WHERE state = ? AND is_official = 0
        ORDER BY date DESC
        LIMIT 1
        """,
        (state_code,),
    ).fetchone()
    if election:
        return election, True

    # Third: most recent election (even if official -- just not "active")
    election = db.execute(
        """
        SELECT * FROM elections
        WHERE state = ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (state_code,),
    ).fetchone()
    if election:
        return election, False

    return None, False


@router.get("/{state}/live/status")
def live_status(state: str):
    """
    Is an election currently active for this state?

    Checks import_runs for recent activity and unofficial elections.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)

    election, is_active = _get_live_election(db, code)

    # Last successful import
    last_import = db.execute(
        """
        SELECT finished_at FROM import_runs
        WHERE state = ? AND status IN ('success', 'success_with_warnings')
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (code,),
    ).fetchone()

    return {
        "active": is_active,
        "last_updated": last_import["finished_at"] if last_import else None,
        "election_key": election["election_key"] if election else None,
    }


@router.get("/{state}/live/races")
def live_races(state: str):
    """
    All races for the current live/most-recent election.

    Same structure as the election detail endpoint but for the live election.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)

    election, is_active = _get_live_election(db, code)
    if not election:
        raise HTTPException(status_code=404, detail={"error": "No election found"})

    # Races
    races = db.execute(
        """
        SELECT
            r.id AS _race_id,
            r.race_key,
            r.title,
            r.office_category,
            r.office_name,
            r.district,
            r.county_code,
            r.num_to_elect,
            r.is_ballot_measure
        FROM races r
        WHERE r.election_id = ?
        ORDER BY r.office_category, r.title
        """,
        (election["id"],),
    ).fetchall()

    # Choices in bulk
    race_ids = [r["_race_id"] for r in races]
    choices_by_race: dict[int, list[dict]] = defaultdict(list)
    if race_ids:
        placeholders = ",".join("?" * len(race_ids))
        choices = db.execute(
            f"""
            SELECT
                c.race_id,
                c.choice_key,
                c.choice_type,
                c.name,
                c.party,
                c.outcome,
                c.vote_total
            FROM choices c
            WHERE c.race_id IN ({placeholders})
            ORDER BY c.vote_total DESC
            """,
            race_ids,
        ).fetchall()
        for c in choices:
            c_dict = dict(c)
            rid = c_dict.pop("race_id")
            choices_by_race[rid].append(c_dict)

    # Reporting in bulk
    reporting_by_race: dict[int, dict] = {}
    if race_ids:
        placeholders = ",".join("?" * len(race_ids))
        reporting = db.execute(
            f"""
            SELECT race_id, SUM(precincts_reporting) AS precincts_reporting,
                   SUM(precincts_expected) AS precincts_expected
            FROM race_reporting
            WHERE race_id IN ({placeholders})
            GROUP BY race_id
            """,
            race_ids,
        ).fetchall()
        for rp in reporting:
            reporting_by_race[rp["race_id"]] = {
                "precincts_reporting": rp["precincts_reporting"] or 0,
                "precincts_expected": rp["precincts_expected"] or 0,
            }

    # Build grouped response
    races_by_category: dict[str, list[dict]] = defaultdict(list)
    for r in races:
        r_dict = dict(r)
        race_id = r_dict.pop("_race_id")
        r_dict["choices"] = choices_by_race.get(race_id, [])
        r_dict["reporting"] = reporting_by_race.get(race_id, {
            "precincts_reporting": 0,
            "precincts_expected": 0,
        })
        races_by_category[r_dict["office_category"]].append(r_dict)

    return {
        "active": is_active,
        "election_key": election["election_key"],
        "date": election["date"],
        "type": election["type"],
        "is_official": election["is_official"],
        "race_count": len(races),
        "races_by_category": dict(races_by_category),
    }


@router.get("/{state}/live/races/{race_key}/counties")
def live_race_counties(state: str, race_key: str):
    """
    County breakdown for a live race.

    Same as the races county endpoint but validates against the live election.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)

    race = db.execute(
        """
        SELECT r.*, e.state
        FROM races r
        JOIN elections e ON e.id = r.election_id
        WHERE r.race_key = ? AND e.state = ?
        """,
        (race_key, code),
    ).fetchone()
    if not race:
        raise HTTPException(status_code=404, detail={"error": "Race not found"})

    # County votes
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

    # Reporting
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
