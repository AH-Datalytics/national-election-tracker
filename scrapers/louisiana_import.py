"""
Louisiana Data Import — Imports LA election data from the existing LA tracker
database into the national election tracker schema.

Source: louisiana_elections.db (from louisiana-election-tracker project)
Target: data/elections.db (national schema created by schema.py)

The source DB is treated as READ-ONLY. A working copy is made first.

Usage:
    python scrapers/louisiana_import.py                           # default paths
    python scrapers/louisiana_import.py --source /path/to/la.db   # custom source
    python scrapers/louisiana_import.py --target /path/to/nat.db  # custom target
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scrapers"))

from schema import generate_election_key, generate_race_key, generate_choice_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

DEFAULT_SOURCE = os.path.join(
    os.path.dirname(REPO_ROOT),
    "louisiana-election-tracker",
    "louisiana_elections.db",
)
DEFAULT_TARGET = os.path.join(REPO_ROOT, "data", "elections.db")
WORKING_COPY = os.path.join(REPO_ROOT, "data", "louisiana_source.db")

# ---------------------------------------------------------------------------
# Office level code mapping
# ---------------------------------------------------------------------------

OFFICE_LEVEL_MAP = {
    "010": "presidential",
    "100": "governor",
    "105": "lieutenant_governor",
    "110": "secretary_of_state",
    "115": "attorney_general",
    "120": "treasurer",
    "140": "us_senate",
    "142": "us_senate",
    "145": "us_house",
    "147": "us_house",
    "150": "judicial",
    "151": "judicial",
    "155": "judicial",
    "160": "state_commission",
    "161": "state_commission",
    "165": "state_senate",
    "166": "state_senate",
    "200": "state_house",
    "205": "state_house",
    "210": "judicial",
    "215": "judicial",
    "235": "county",
    "250": "judicial",
    "255": "school_board",
    "300": "municipal",
    "305": "municipal",
    "308": "municipal",
    "310": "municipal",
    "998": "constitutional_amendment",
    "999": "referendum",
}

BALLOT_MEASURE_CODES = {"998", "999"}

# ---------------------------------------------------------------------------
# Election type classification
# ---------------------------------------------------------------------------


def classify_election_type(iso_date: str) -> str:
    """
    Classify a Louisiana election date as 'primary', 'general', 'runoff', or 'special'.

    Louisiana uses a jungle primary system. Heuristic:
    - Fall dates (Oct-Nov) -> 'general'
    - Spring/summer dates (Mar-Sep) -> 'primary'
    - Dec-Feb dates (likely runoffs after fall elections) -> 'runoff'
    """
    month = int(iso_date[5:7])
    if month in (10, 11):
        return "general"
    elif 3 <= month <= 9:
        return "primary"
    elif month == 12 or month <= 2:
        return "runoff"
    return "general"


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------


def sha256_file(path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


def copy_source_db(source_path: str) -> str:
    """Copy the source DB to a working copy. Returns the working copy path."""
    os.makedirs(os.path.dirname(WORKING_COPY), exist_ok=True)
    shutil.copy2(source_path, WORKING_COPY)
    log.info(f"Copied source DB to {WORKING_COPY}")
    return WORKING_COPY


def validate_source(src_conn: sqlite3.Connection) -> dict:
    """Validate the source DB has the expected tables and return counts."""
    expected_tables = [
        "elections", "races", "candidates", "votes_parish",
        "votes_precinct", "early_votes", "turnout", "parishes",
    ]
    counts = {}
    for table in expected_tables:
        try:
            row = src_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()
            counts[table] = row[0]
        except sqlite3.OperationalError:
            raise RuntimeError(f"Source DB missing expected table: {table}")
    return counts


def clear_la_data(tgt_conn: sqlite3.Connection) -> None:
    """Delete all existing LA data from the target DB for idempotent re-import."""
    log.info("Clearing existing LA data from target...")

    # Get all LA election IDs first
    la_election_ids = [
        row[0]
        for row in tgt_conn.execute(
            "SELECT id FROM elections WHERE state = 'LA'"
        ).fetchall()
    ]

    if not la_election_ids:
        log.info("  No existing LA data found.")
        return

    # Get all race IDs for LA elections
    placeholders = ",".join("?" * len(la_election_ids))
    la_race_ids = [
        row[0]
        for row in tgt_conn.execute(
            f"SELECT id FROM races WHERE election_id IN ({placeholders})",
            la_election_ids,
        ).fetchall()
    ]

    if la_race_ids:
        race_ph = ",".join("?" * len(la_race_ids))

        # Delete in dependency order (children first)
        # Get choice IDs for foreign key cleanup
        la_choice_ids = [
            row[0]
            for row in tgt_conn.execute(
                f"SELECT id FROM choices WHERE race_id IN ({race_ph})",
                la_race_ids,
            ).fetchall()
        ]

        if la_choice_ids:
            choice_ph = ",".join("?" * len(la_choice_ids))
            tgt_conn.execute(
                f"DELETE FROM votes_precinct WHERE choice_id IN ({choice_ph})",
                la_choice_ids,
            )
            tgt_conn.execute(
                f"DELETE FROM votes_county WHERE choice_id IN ({choice_ph})",
                la_choice_ids,
            )
            tgt_conn.execute(
                f"DELETE FROM early_votes WHERE choice_id IN ({choice_ph})",
                la_choice_ids,
            )

        tgt_conn.execute(
            f"DELETE FROM race_reporting WHERE race_id IN ({race_ph})",
            la_race_ids,
        )
        tgt_conn.execute(
            f"DELETE FROM race_metadata WHERE race_id IN ({race_ph})",
            la_race_ids,
        )
        tgt_conn.execute(
            f"DELETE FROM choices WHERE race_id IN ({race_ph})",
            la_race_ids,
        )
        tgt_conn.execute(
            f"DELETE FROM races WHERE id IN ({race_ph})",
            la_race_ids,
        )

    # Delete turnout and elections
    tgt_conn.execute(
        f"DELETE FROM turnout WHERE election_id IN ({placeholders})",
        la_election_ids,
    )
    tgt_conn.execute("DELETE FROM elections WHERE state = 'LA'")

    # Delete LA import provenance
    la_run_ids = [
        row[0]
        for row in tgt_conn.execute(
            "SELECT id FROM import_runs WHERE state = 'LA'"
        ).fetchall()
    ]
    if la_run_ids:
        run_ph = ",".join("?" * len(la_run_ids))
        tgt_conn.execute(
            f"DELETE FROM data_quality_checks WHERE import_run_id IN ({run_ph})",
            la_run_ids,
        )
        tgt_conn.execute(
            f"DELETE FROM source_files WHERE import_run_id IN ({run_ph})",
            la_run_ids,
        )
        tgt_conn.execute("DELETE FROM import_runs WHERE state = 'LA'")

    log.info(
        f"  Cleared {len(la_election_ids)} elections, "
        f"{len(la_race_ids)} races."
    )


def import_elections(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
) -> dict:
    """
    Import elections from source to target.
    Returns {old_election_id: (new_election_id, election_key)}.
    """
    rows = src_conn.execute(
        "SELECT id, date, sos_election_id, is_official FROM elections ORDER BY date"
    ).fetchall()

    election_map = {}  # old_id -> (new_id, election_key)
    batch = []

    for old_id, date, sos_election_id, is_official in rows:
        etype = classify_election_type(date)
        election_key = generate_election_key("LA", date, etype)

        # Handle duplicate keys (multiple elections on same date with same type)
        # Append the SOS election ID to disambiguate
        base_key = election_key
        suffix = 0
        while any(ek == election_key for _, ek in election_map.values()):
            suffix += 1
            election_key = f"{base_key}-{suffix}"

        batch.append((
            election_key, "LA", date, etype, is_official, str(sos_election_id),
        ))
        election_map[old_id] = (None, election_key)  # new_id filled after insert

    tgt_conn.executemany(
        """INSERT INTO elections
           (election_key, state, date, type, is_official, sos_election_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        batch,
    )

    # Fetch new IDs by election_key
    for old_id, (_, ekey) in list(election_map.items()):
        new_id = tgt_conn.execute(
            "SELECT id FROM elections WHERE election_key = ?", (ekey,)
        ).fetchone()[0]
        election_map[old_id] = (new_id, ekey)

    log.info(f"Importing elections... {len(election_map):,} done")
    return election_map


def import_races(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    election_map: dict,
) -> dict:
    """
    Import races from source to target.
    Returns {old_race_id: (new_race_id, race_key, office_level_code)}.
    """
    rows = src_conn.execute(
        """SELECT id, election_id, sos_race_id, specific_title, general_title,
                  office_level_code, is_multi_parish, num_to_elect, can_have_runoff
           FROM races ORDER BY id"""
    ).fetchall()

    race_map = {}  # old_race_id -> (new_race_id, race_key, office_level_code)
    race_batch = []
    meta_batch = []
    seen_race_keys = set()

    for (
        old_id, old_election_id, sos_race_id, specific_title, general_title,
        office_level_code, is_multi_parish, num_to_elect, can_have_runoff,
    ) in rows:
        if old_election_id not in election_map:
            log.warning(f"Race {old_id} references unknown election {old_election_id}, skipping")
            continue

        new_election_id, election_key = election_map[old_election_id]
        office_category = OFFICE_LEVEL_MAP.get(office_level_code, "other")
        is_ballot_measure = 1 if office_level_code in BALLOT_MEASURE_CODES else 0

        # Use specific_title as the primary title, general_title as office_name
        title = specific_title or general_title or "Unknown Race"

        # Generate race key: election_key + title (specific_title is unique within election)
        race_key = generate_race_key(election_key, title)

        # Deduplicate race keys (rare but possible with identical titles)
        base_key = race_key
        suffix = 0
        while race_key in seen_race_keys:
            suffix += 1
            race_key = f"{base_key}--{suffix}"
        seen_race_keys.add(race_key)

        # Determine county_code for parish-level races
        county_code = None  # Multi-parish races are statewide-ish

        race_batch.append((
            race_key, new_election_id, str(sos_race_id), title,
            office_category, general_title, None, county_code,
            num_to_elect, is_ballot_measure,
        ))

        # Metadata JSON
        meta = {
            "specific_title": specific_title,
            "general_title": general_title,
            "office_level_code": office_level_code,
            "can_have_runoff": can_have_runoff,
            "is_multi_parish": is_multi_parish,
        }
        meta_batch.append((race_key, json.dumps(meta)))

        race_map[old_id] = (None, race_key, office_level_code)  # new_id filled after insert

    # Batch insert races
    tgt_conn.executemany(
        """INSERT INTO races
           (race_key, election_id, sos_race_id, title, office_category,
            office_name, district, county_code, num_to_elect, is_ballot_measure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        race_batch,
    )

    # Fetch new race IDs and insert metadata
    meta_inserts = []
    for old_id, (_, rkey, olc) in list(race_map.items()):
        new_id = tgt_conn.execute(
            "SELECT id FROM races WHERE race_key = ?", (rkey,)
        ).fetchone()[0]
        race_map[old_id] = (new_id, rkey, olc)

    # Now build metadata batch with new race IDs
    for rkey, meta_json in meta_batch:
        new_id = tgt_conn.execute(
            "SELECT id FROM races WHERE race_key = ?", (rkey,)
        ).fetchone()[0]
        meta_inserts.append((new_id, meta_json))

    tgt_conn.executemany(
        "INSERT INTO race_metadata (race_id, data) VALUES (?, ?)",
        meta_inserts,
    )

    log.info(f"Importing races... {len(race_map):,} done")
    return race_map


def import_choices(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    race_map: dict,
) -> dict:
    """
    Import candidates -> choices.
    Returns {old_candidate_id: new_choice_id}.
    """
    rows = src_conn.execute(
        """SELECT id, race_id, sos_choice_id, description, party,
                  color_hex, outcome, vote_total
           FROM candidates ORDER BY id"""
    ).fetchall()

    candidate_map = {}  # old_candidate_id -> new_choice_id
    batch = []
    seen_choice_keys = set()

    for (
        old_id, old_race_id, sos_choice_id, description, party,
        color_hex, outcome, vote_total,
    ) in rows:
        if old_race_id not in race_map:
            log.warning(f"Candidate {old_id} references unknown race {old_race_id}, skipping")
            continue

        new_race_id, race_key, office_level_code = race_map[old_race_id]
        is_ballot_measure = office_level_code in BALLOT_MEASURE_CODES
        choice_type = "ballot_option" if is_ballot_measure else "candidate"

        name = description or "Unknown"
        choice_key = generate_choice_key(race_key, name, party)

        # Deduplicate choice keys
        base_key = choice_key
        suffix = 0
        while choice_key in seen_choice_keys:
            suffix += 1
            choice_key = f"{base_key}--{suffix}"
        seen_choice_keys.add(choice_key)

        batch.append((
            choice_key, new_race_id, str(sos_choice_id), choice_type,
            name, party, None, color_hex, outcome, vote_total or 0,
        ))

        candidate_map[old_id] = (None, choice_key)  # new_id filled after insert

    tgt_conn.executemany(
        """INSERT INTO choices
           (choice_key, race_id, sos_choice_id, choice_type, name,
            party, ballot_order, color_hex, outcome, vote_total)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        batch,
    )

    # Fetch new choice IDs
    for old_id, (_, ckey) in list(candidate_map.items()):
        new_id = tgt_conn.execute(
            "SELECT id FROM choices WHERE choice_key = ?", (ckey,)
        ).fetchone()[0]
        candidate_map[old_id] = new_id

    log.info(f"Importing choices... {len(candidate_map):,} done")
    return candidate_map


def import_votes_county(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    race_map: dict,
    candidate_map: dict,
) -> int:
    """Import votes_parish -> votes_county. Returns row count."""
    rows = src_conn.execute(
        "SELECT race_id, parish_code, candidate_id, vote_total FROM votes_parish"
    ).fetchall()

    batch = []
    skipped = 0
    for old_race_id, parish_code, old_candidate_id, vote_total in rows:
        if old_race_id not in race_map:
            skipped += 1
            continue
        new_race_id = race_map[old_race_id][0]
        new_choice_id = candidate_map.get(old_candidate_id)
        if new_choice_id is None:
            skipped += 1
            continue
        batch.append((new_race_id, parish_code, new_choice_id, vote_total or 0))

    tgt_conn.executemany(
        """INSERT INTO votes_county (race_id, county_code, choice_id, vote_total)
           VALUES (?, ?, ?, ?)""",
        batch,
    )

    if skipped:
        log.warning(f"  votes_county: skipped {skipped:,} rows with unmapped IDs")
    log.info(f"Importing votes_county... {len(batch):,} done")
    return len(batch)


def import_votes_precinct(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    race_map: dict,
    candidate_map: dict,
) -> int:
    """Import votes_precinct -> votes_precinct. Returns row count."""
    # Stream in chunks to handle millions of rows
    CHUNK_SIZE = 50000
    cursor = src_conn.execute(
        "SELECT race_id, parish_code, precinct_label, candidate_id, vote_total FROM votes_precinct"
    )

    total = 0
    skipped = 0
    while True:
        rows = cursor.fetchmany(CHUNK_SIZE)
        if not rows:
            break

        batch = []
        for old_race_id, parish_code, precinct_label, old_candidate_id, vote_total in rows:
            if old_race_id not in race_map:
                skipped += 1
                continue
            new_race_id = race_map[old_race_id][0]
            new_choice_id = candidate_map.get(old_candidate_id)
            if new_choice_id is None:
                skipped += 1
                continue
            batch.append((
                new_race_id, parish_code, precinct_label, new_choice_id, vote_total or 0,
            ))

        if batch:
            tgt_conn.executemany(
                """INSERT INTO votes_precinct
                   (race_id, county_code, precinct_id, choice_id, vote_total)
                   VALUES (?, ?, ?, ?, ?)""",
                batch,
            )
        total += len(batch)

        if total % 200000 == 0 and total > 0:
            log.info(f"  votes_precinct progress: {total:,} rows...")

    if skipped:
        log.warning(f"  votes_precinct: skipped {skipped:,} rows with unmapped IDs")
    log.info(f"Importing votes_precinct... {total:,} done")
    return total


def import_early_votes(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    race_map: dict,
    candidate_map: dict,
) -> int:
    """Import early_votes -> early_votes. Returns row count."""
    rows = src_conn.execute(
        "SELECT race_id, parish_code, candidate_id, vote_total FROM early_votes"
    ).fetchall()

    batch = []
    skipped = 0
    for old_race_id, parish_code, old_candidate_id, vote_total in rows:
        if old_race_id not in race_map:
            skipped += 1
            continue
        new_race_id = race_map[old_race_id][0]
        new_choice_id = candidate_map.get(old_candidate_id)
        if new_choice_id is None:
            skipped += 1
            continue
        batch.append((new_race_id, parish_code, new_choice_id, vote_total or 0))

    tgt_conn.executemany(
        """INSERT INTO early_votes (race_id, county_code, choice_id, vote_total)
           VALUES (?, ?, ?, ?)""",
        batch,
    )

    if skipped:
        log.warning(f"  early_votes: skipped {skipped:,} rows with unmapped IDs")
    log.info(f"Importing early_votes... {len(batch):,} done")
    return len(batch)


def import_turnout_and_reporting(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    election_map: dict,
    race_map: dict,
) -> tuple:
    """
    Import LA turnout table -> race_reporting + turnout.

    LA has turnout per race per parish:
      race_id, parish_code, precincts_reporting, precincts_expected, qualified_voters, voters_voted

    We split into:
      - race_reporting: race_id + county_code + precincts_reporting/expected
      - turnout: election_id + county_code + qualified_voters/voters_voted (deduplicated)
    """
    rows = src_conn.execute(
        """SELECT race_id, parish_code, precincts_reporting, precincts_expected,
                  qualified_voters, voters_voted
           FROM turnout"""
    ).fetchall()

    # Build race_id -> election_id lookup
    race_to_election = {}
    for old_race_id, (new_race_id, _, _) in race_map.items():
        # Find election_id for this race
        old_election_id = src_conn.execute(
            "SELECT election_id FROM races WHERE id = ?", (old_race_id,)
        ).fetchone()
        if old_election_id and old_election_id[0] in election_map:
            race_to_election[old_race_id] = election_map[old_election_id[0]][0]

    reporting_batch = []
    turnout_seen = {}  # (new_election_id, parish_code) -> (qualified, voted)
    skipped = 0

    for old_race_id, parish_code, prec_reporting, prec_expected, qualified, voted in rows:
        if old_race_id not in race_map:
            skipped += 1
            continue
        new_race_id = race_map[old_race_id][0]

        # Race reporting (all rows)
        reporting_batch.append((
            new_race_id, parish_code,
            prec_reporting or 0, prec_expected or 0,
        ))

        # Turnout (deduplicate by election+parish, take first non-zero)
        new_election_id = race_to_election.get(old_race_id)
        if new_election_id and parish_code:
            key = (new_election_id, parish_code)
            if key not in turnout_seen:
                if (qualified or 0) > 0 or (voted or 0) > 0:
                    turnout_seen[key] = (qualified or 0, voted or 0)
            else:
                # Keep the larger values (more complete data)
                old_q, old_v = turnout_seen[key]
                turnout_seen[key] = (
                    max(old_q, qualified or 0),
                    max(old_v, voted or 0),
                )

    tgt_conn.executemany(
        """INSERT INTO race_reporting
           (race_id, county_code, precincts_reporting, precincts_expected)
           VALUES (?, ?, ?, ?)""",
        reporting_batch,
    )

    turnout_batch = [
        (eid, pcode, q, v)
        for (eid, pcode), (q, v) in turnout_seen.items()
    ]
    tgt_conn.executemany(
        """INSERT INTO turnout
           (election_id, county_code, qualified_voters, voters_voted)
           VALUES (?, ?, ?, ?)""",
        turnout_batch,
    )

    if skipped:
        log.warning(f"  turnout: skipped {skipped:,} rows with unmapped IDs")
    log.info(f"Importing race_reporting... {len(reporting_batch):,} done")
    log.info(f"Importing turnout... {len(turnout_batch):,} done")
    return len(reporting_batch), len(turnout_batch)


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------


def run_quality_checks(
    src_conn: sqlite3.Connection,
    tgt_conn: sqlite3.Connection,
    import_run_id: int,
) -> list:
    """Run quality checks and log results. Returns list of (name, passed, details)."""
    checks = []

    # 1. Election count match
    src_count = src_conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0]
    tgt_count = tgt_conn.execute(
        "SELECT COUNT(*) FROM elections WHERE state = 'LA'"
    ).fetchone()[0]
    checks.append((
        "election_count_match",
        1 if src_count == tgt_count else 0,
        json.dumps({"source": src_count, "target": tgt_count}),
    ))

    # 2. Race count match
    src_count = src_conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    tgt_count = tgt_conn.execute(
        """SELECT COUNT(*) FROM races r
           JOIN elections e ON r.election_id = e.id
           WHERE e.state = 'LA'"""
    ).fetchone()[0]
    checks.append((
        "race_count_match",
        1 if src_count == tgt_count else 0,
        json.dumps({"source": src_count, "target": tgt_count}),
    ))

    # 3. Total votes match (candidate vote_totals)
    src_votes = src_conn.execute(
        "SELECT COALESCE(SUM(vote_total), 0) FROM candidates"
    ).fetchone()[0]
    tgt_votes = tgt_conn.execute(
        """SELECT COALESCE(SUM(c.vote_total), 0) FROM choices c
           JOIN races r ON c.race_id = r.id
           JOIN elections e ON r.election_id = e.id
           WHERE e.state = 'LA'"""
    ).fetchone()[0]
    checks.append((
        "total_votes_match",
        1 if src_votes == tgt_votes else 0,
        json.dumps({"source": src_votes, "target": tgt_votes}),
    ))

    # 4. No negative votes
    neg_county = tgt_conn.execute(
        """SELECT COUNT(*) FROM votes_county vc
           JOIN races r ON vc.race_id = r.id
           JOIN elections e ON r.election_id = e.id
           WHERE e.state = 'LA' AND vc.vote_total < 0"""
    ).fetchone()[0]
    neg_precinct = tgt_conn.execute(
        """SELECT COUNT(*) FROM votes_precinct vp
           JOIN races r ON vp.race_id = r.id
           JOIN elections e ON r.election_id = e.id
           WHERE e.state = 'LA' AND vp.vote_total < 0"""
    ).fetchone()[0]
    neg_early = tgt_conn.execute(
        """SELECT COUNT(*) FROM early_votes ev
           JOIN races r ON ev.race_id = r.id
           JOIN elections e ON r.election_id = e.id
           WHERE e.state = 'LA' AND ev.vote_total < 0"""
    ).fetchone()[0]
    neg_total = neg_county + neg_precinct + neg_early
    checks.append((
        "no_negative_votes",
        1 if neg_total == 0 else 0,
        json.dumps({
            "negative_county": neg_county,
            "negative_precinct": neg_precinct,
            "negative_early": neg_early,
        }),
    ))

    # Log all checks
    for name, passed, details in checks:
        tgt_conn.execute(
            """INSERT INTO data_quality_checks
               (import_run_id, check_name, passed, details)
               VALUES (?, ?, ?, ?)""",
            (import_run_id, name, passed, details),
        )
        status = "PASS" if passed else "FAIL"
        log.info(f"  Quality check [{status}] {name}: {details}")

    return checks


# ---------------------------------------------------------------------------
# Main import orchestrator
# ---------------------------------------------------------------------------


def run_import(source_path: str, target_path: str) -> None:
    """Run the full Louisiana data import."""
    started_at = datetime.now(timezone.utc).isoformat()

    # Validate source exists and has data
    if not os.path.exists(source_path):
        log.error(f"Source database not found: {source_path}")
        sys.exit(1)

    source_size = os.path.getsize(source_path)
    if source_size == 0:
        log.error(
            f"Source database is empty (0 bytes): {source_path}\n"
            "  The LA database must be populated first. On Hetzner, run:\n"
            "    cd /opt/louisiana-election-tracker && python scripts/scrape_historical.py\n"
            "  Then copy the database locally or run this import on the server."
        )
        sys.exit(1)

    # Validate target exists
    if not os.path.exists(target_path):
        log.error(
            f"Target database not found: {target_path}\n"
            "  Run 'python scrapers/schema.py' first to create the national schema."
        )
        sys.exit(1)

    # Copy source to working copy
    working_path = copy_source_db(source_path)
    source_hash = sha256_file(source_path)
    log.info(f"Source DB: {source_path} ({source_size:,} bytes, SHA-256: {source_hash[:16]}...)")

    # Open connections
    src_conn = sqlite3.connect(f"file:{working_path}?mode=ro", uri=True)
    tgt_conn = sqlite3.connect(target_path)
    tgt_conn.execute("PRAGMA journal_mode=WAL")
    tgt_conn.execute("PRAGMA foreign_keys=ON")
    import_run_id = None

    try:
        # Validate source
        src_counts = validate_source(src_conn)
        log.info(f"Source DB validated: {src_counts}")

        # Clear existing LA data (idempotent) — must happen BEFORE
        # creating the new import_run so the clear doesn't delete it
        clear_la_data(tgt_conn)
        tgt_conn.commit()

        # Create import run record
        tgt_conn.execute(
            """INSERT INTO import_runs (state, started_at, status, scraper_version)
               VALUES ('LA', ?, 'running', 'louisiana_import.py v1.0')""",
            (started_at,),
        )
        import_run_id = tgt_conn.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        # Log source file
        tgt_conn.execute(
            """INSERT INTO source_files
               (import_run_id, filename, sha256, size_bytes, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (import_run_id, os.path.basename(source_path), source_hash,
             source_size, started_at),
        )
        tgt_conn.commit()

        # --- Import in a single transaction ---
        log.info("=" * 60)
        log.info("Starting Louisiana data import...")
        log.info("=" * 60)

        # Step 1: Elections
        election_map = import_elections(src_conn, tgt_conn)

        # Step 2: Races
        race_map = import_races(src_conn, tgt_conn, election_map)

        # Step 3: Choices (candidates)
        candidate_map = import_choices(src_conn, tgt_conn, race_map)

        # Step 4: Votes — county level
        county_vote_count = import_votes_county(src_conn, tgt_conn, race_map, candidate_map)

        # Step 5: Votes — precinct level
        precinct_vote_count = import_votes_precinct(src_conn, tgt_conn, race_map, candidate_map)

        # Step 6: Early votes
        early_vote_count = import_early_votes(src_conn, tgt_conn, race_map, candidate_map)

        # Step 7: Turnout + reporting
        reporting_count, turnout_count = import_turnout_and_reporting(
            src_conn, tgt_conn, election_map, race_map,
        )

        # Commit all data
        tgt_conn.commit()

        # Step 8: Quality checks
        log.info("Running quality checks...")
        checks = run_quality_checks(src_conn, tgt_conn, import_run_id)

        # Step 9: Update import run
        record_counts = {
            "elections": len(election_map),
            "races": len(race_map),
            "choices": len(candidate_map),
            "votes_county": county_vote_count,
            "votes_precinct": precinct_vote_count,
            "early_votes": early_vote_count,
            "race_reporting": reporting_count,
            "turnout": turnout_count,
        }
        finished_at = datetime.now(timezone.utc).isoformat()
        all_passed = all(passed for _, passed, _ in checks)

        tgt_conn.execute(
            """UPDATE import_runs
               SET status = ?, record_counts = ?, finished_at = ?
               WHERE id = ?""",
            (
                "success" if all_passed else "success_with_warnings",
                json.dumps(record_counts),
                finished_at,
                import_run_id,
            ),
        )
        tgt_conn.commit()

        # Summary
        log.info("=" * 60)
        log.info("IMPORT COMPLETE")
        log.info("=" * 60)
        for key, count in record_counts.items():
            log.info(f"  {key}: {count:,}")
        check_status = "ALL PASSED" if all_passed else "SOME FAILED"
        log.info(f"  Quality checks: {check_status}")
        log.info(f"  Target DB: {target_path}")

    except Exception as e:
        log.error(f"Import failed: {e}", exc_info=True)
        # Try to update import run status if it was created
        if import_run_id is not None:
            try:
                tgt_conn.execute(
                    """UPDATE import_runs
                       SET status = 'failed', error_message = ?, finished_at = ?
                       WHERE id = ?""",
                    (str(e), datetime.now(timezone.utc).isoformat(), import_run_id),
                )
                tgt_conn.commit()
            except Exception:
                pass
        raise
    finally:
        src_conn.close()
        tgt_conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Import Louisiana election data into the national tracker."
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Path to source LA database (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"Path to target national database (default: {DEFAULT_TARGET})",
    )
    args = parser.parse_args()
    run_import(args.source, args.target)


if __name__ == "__main__":
    main()
