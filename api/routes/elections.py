"""Election listing and detail endpoints."""

from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query

from api.db import get_readonly_db

router = APIRouter(prefix="/api", tags=["elections"])


def _validate_state(db, state: str) -> str:
    """Validate and normalize a state code. Raises 404 if not found."""
    code = state.upper()
    row = db.execute("SELECT code FROM states WHERE code = ?", (code,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "State not found"})
    return code


@router.get("/{state}/elections")
def list_elections(
    state: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    year: int | None = Query(None),
    type: str | None = Query(None),
):
    """
    Paginated election list for a state.

    Optional filters: year (YYYY), type (general/primary/runoff/special).
    """
    db = get_readonly_db()
    code = _validate_state(db, state)

    conditions = ["e.state = ?"]
    params: list = [code]

    if year:
        conditions.append("e.date LIKE ?")
        params.append(f"{year}-%")

    if type:
        conditions.append("e.type = ?")
        params.append(type.lower())

    where = " AND ".join(conditions)

    rows = db.execute(
        f"""
        SELECT
            e.election_key,
            e.date,
            e.type,
            e.is_official,
            COUNT(r.id) AS race_count
        FROM elections e
        LEFT JOIN races r ON r.election_id = e.id
        WHERE {where}
        GROUP BY e.id
        ORDER BY e.date DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    return [dict(r) for r in rows]


@router.get("/{state}/elections/{election_key}")
def get_election(state: str, election_key: str):
    """
    Single election with all races grouped by office_category.

    Each race includes its choices with vote totals.
    """
    db = get_readonly_db()
    code = _validate_state(db, state)

    election = db.execute(
        "SELECT * FROM elections WHERE election_key = ? AND state = ?",
        (election_key, code),
    ).fetchone()
    if not election:
        raise HTTPException(status_code=404, detail={"error": "Election not found"})

    # Fetch all races for this election
    races = db.execute(
        """
        SELECT
            r.race_key,
            r.title,
            r.office_category,
            r.office_name,
            r.district,
            r.county_code,
            r.num_to_elect,
            r.is_ballot_measure,
            r.id AS _race_id
        FROM races r
        WHERE r.election_id = ?
        ORDER BY r.office_category, r.title
        """,
        (election["id"],),
    ).fetchall()

    # Fetch choices for all races in one query
    race_ids = [r["_race_id"] for r in races]
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
                c.ballot_order,
                c.outcome,
                c.vote_total
            FROM choices c
            WHERE c.race_id IN ({placeholders})
            ORDER BY c.vote_total DESC
            """,
            race_ids,
        ).fetchall()
    else:
        choices = []

    # Group choices by race_id
    choices_by_race: dict[int, list[dict]] = defaultdict(list)
    for c in choices:
        c_dict = dict(c)
        race_id = c_dict.pop("race_id")
        choices_by_race[race_id].append(c_dict)

    # Build flat races list with choices
    races_list = []
    for r in races:
        r_dict = dict(r)
        race_id = r_dict.pop("_race_id")
        r_dict["choices"] = choices_by_race.get(race_id, [])
        races_list.append(r_dict)

    return {
        "election_key": election["election_key"],
        "state": election["state"],
        "date": election["date"],
        "type": election["type"],
        "is_official": election["is_official"],
        "race_count": len(races_list),
        "races": races_list,
    }
