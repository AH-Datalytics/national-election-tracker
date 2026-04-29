"""
End-to-end test for the Louisiana data import.

Creates a synthetic LA source database, runs the import, and verifies
all data landed correctly in the national schema.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scrapers"))

from schema import create_schema
from louisiana_import import run_import


def build_source_db(path):
    """Create a synthetic LA source database with known data."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE elections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            sos_election_id TEXT NOT NULL UNIQUE,
            is_official INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE races (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL,
            sos_race_id TEXT NOT NULL,
            specific_title TEXT NOT NULL,
            general_title TEXT NOT NULL,
            office_level_code TEXT NOT NULL,
            is_multi_parish INTEGER NOT NULL DEFAULT 1,
            num_to_elect INTEGER NOT NULL DEFAULT 1,
            can_have_runoff INTEGER NOT NULL DEFAULT 0,
            UNIQUE(election_id, sos_race_id)
        );
        CREATE TABLE candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id INTEGER NOT NULL,
            sos_choice_id TEXT NOT NULL,
            description TEXT NOT NULL,
            party TEXT,
            color_hex TEXT,
            outcome TEXT,
            vote_total INTEGER NOT NULL DEFAULT 0,
            UNIQUE(race_id, sos_choice_id)
        );
        CREATE TABLE votes_parish (
            race_id INTEGER NOT NULL,
            parish_code TEXT NOT NULL,
            candidate_id INTEGER NOT NULL,
            vote_total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (race_id, parish_code, candidate_id)
        );
        CREATE TABLE votes_precinct (
            race_id INTEGER NOT NULL,
            parish_code TEXT NOT NULL,
            precinct_label TEXT NOT NULL,
            candidate_id INTEGER NOT NULL,
            vote_total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (race_id, parish_code, precinct_label, candidate_id)
        );
        CREATE TABLE early_votes (
            race_id INTEGER NOT NULL,
            parish_code TEXT NOT NULL,
            candidate_id INTEGER NOT NULL,
            vote_total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (race_id, parish_code, candidate_id)
        );
        CREATE TABLE turnout (
            race_id INTEGER NOT NULL,
            parish_code TEXT,
            precincts_reporting INTEGER NOT NULL DEFAULT 0,
            precincts_expected INTEGER NOT NULL DEFAULT 0,
            qualified_voters INTEGER NOT NULL DEFAULT 0,
            voters_voted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (race_id, parish_code)
        );
        CREATE TABLE parishes (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE
        );
        CREATE TABLE candidate_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_normalized TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            party TEXT,
            first_seen_date TEXT,
            last_seen_date TEXT,
            race_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE candidate_appearances (
            candidate_index_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            PRIMARY KEY (candidate_index_id, candidate_id)
        );
    """)

    # 2 elections: one general (Nov), one primary (Mar)
    conn.execute("INSERT INTO elections VALUES (1, '2024-11-05', '1001', 1)")
    conn.execute("INSERT INTO elections VALUES (2, '2024-03-23', '1002', 1)")

    # 3 races: President (010), Amendment (998), Governor (100)
    conn.execute(
        "INSERT INTO races VALUES (1, 1, 'R1', 'President', 'Presidential', '010', 1, 1, 0)"
    )
    conn.execute(
        "INSERT INTO races VALUES (2, 1, 'R2', 'Amendment 1', 'Constitutional Amendment', '998', 1, 1, 0)"
    )
    conn.execute(
        "INSERT INTO races VALUES (3, 2, 'R3', 'Governor', 'Governor', '100', 1, 1, 1)"
    )

    # 6 candidates
    conn.execute(
        "INSERT INTO candidates VALUES (1, 1, 'C1', 'John Smith (REP)', 'REP', '#FF0000', 'W', 50000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES (2, 1, 'C2', 'Jane Doe (DEM)', 'DEM', '#0000FF', 'L', 45000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES (3, 2, 'C3', 'For', NULL, '#00FF00', 'W', 60000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES (4, 2, 'C4', 'Against', NULL, '#FF0000', 'L', 30000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES (5, 3, 'C5', 'Bob Wilson (REP)', 'REP', '#FF0000', 'W', 80000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES (6, 3, 'C6', 'Alice Brown (DEM)', 'DEM', '#0000FF', 'L', 70000)"
    )

    # votes_parish
    conn.execute("INSERT INTO votes_parish VALUES (1, '36', 1, 20000)")
    conn.execute("INSERT INTO votes_parish VALUES (1, '36', 2, 25000)")
    conn.execute("INSERT INTO votes_parish VALUES (1, '26', 1, 30000)")
    conn.execute("INSERT INTO votes_parish VALUES (1, '26', 2, 20000)")

    # votes_precinct
    conn.execute("INSERT INTO votes_precinct VALUES (1, '36', 'PCT-001', 1, 5000)")
    conn.execute("INSERT INTO votes_precinct VALUES (1, '36', 'PCT-001', 2, 6000)")
    conn.execute("INSERT INTO votes_precinct VALUES (1, '36', 'PCT-002', 1, 7000)")
    conn.execute("INSERT INTO votes_precinct VALUES (1, '36', 'PCT-002', 2, 8000)")

    # early_votes
    conn.execute("INSERT INTO early_votes VALUES (1, '36', 1, 3000)")
    conn.execute("INSERT INTO early_votes VALUES (1, '36', 2, 4000)")

    # turnout (race_id, parish_code, prec_reporting, prec_expected, qualified, voted)
    conn.execute("INSERT INTO turnout VALUES (1, '36', 50, 50, 100000, 45000)")
    conn.execute("INSERT INTO turnout VALUES (1, '26', 100, 100, 200000, 90000)")
    conn.execute("INSERT INTO turnout VALUES (2, '36', 30, 30, 100000, 40000)")
    conn.execute("INSERT INTO turnout VALUES (3, '36', 50, 50, 100000, 55000)")

    # parishes
    conn.execute("INSERT INTO parishes VALUES ('36', 'Orleans', 'orleans')")
    conn.execute("INSERT INTO parishes VALUES ('26', 'Jefferson', 'jefferson')")

    conn.commit()
    conn.close()


def verify(tgt_path):
    """Verify the import results and print summary."""
    conn = sqlite3.connect(tgt_path)
    errors = []

    # --- Elections ---
    elections = conn.execute(
        "SELECT election_key, date, type, is_official FROM elections WHERE state = 'LA' ORDER BY date"
    ).fetchall()
    print(f"\nElections ({len(elections)}):")
    for e in elections:
        print(f"  {e}")
    if len(elections) != 2:
        errors.append(f"Expected 2 elections, got {len(elections)}")

    # Check types: Nov -> general, Mar -> primary
    types = {e[1]: e[2] for e in elections}
    if types.get("2024-11-05") != "general":
        errors.append(f"Nov election type: expected 'general', got '{types.get('2024-11-05')}'")
    if types.get("2024-03-23") != "primary":
        errors.append(f"Mar election type: expected 'primary', got '{types.get('2024-03-23')}'")

    # --- Races ---
    races = conn.execute("""
        SELECT r.race_key, r.title, r.office_category, r.is_ballot_measure
        FROM races r JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA' ORDER BY r.id
    """).fetchall()
    print(f"\nRaces ({len(races)}):")
    for r in races:
        print(f"  {r}")
    if len(races) != 3:
        errors.append(f"Expected 3 races, got {len(races)}")

    # Check office categories
    categories = {r[1]: r[2] for r in races}
    if categories.get("President") != "presidential":
        errors.append(f"President category: expected 'presidential', got '{categories.get('President')}'")
    if categories.get("Amendment 1") != "constitutional_amendment":
        errors.append(f"Amendment category: expected 'constitutional_amendment', got '{categories.get('Amendment 1')}'")
    if categories.get("Governor") != "governor":
        errors.append(f"Governor category: expected 'governor', got '{categories.get('Governor')}'")

    # Check ballot measure flag
    ballot_measures = {r[1]: r[3] for r in races}
    if ballot_measures.get("Amendment 1") != 1:
        errors.append("Amendment 1 should be is_ballot_measure=1")
    if ballot_measures.get("President") != 0:
        errors.append("President should be is_ballot_measure=0")

    # --- Choices ---
    choices = conn.execute("""
        SELECT c.name, c.party, c.choice_type, c.outcome, c.vote_total
        FROM choices c JOIN races r ON c.race_id = r.id JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA' ORDER BY c.id
    """).fetchall()
    print(f"\nChoices ({len(choices)}):")
    for c in choices:
        print(f"  {c}")
    if len(choices) != 6:
        errors.append(f"Expected 6 choices, got {len(choices)}")

    # Check choice types
    choice_types = {c[0]: c[2] for c in choices}
    if choice_types.get("For") != "ballot_option":
        errors.append("'For' should be choice_type='ballot_option'")
    if choice_types.get("John Smith (REP)") != "candidate":
        errors.append("'John Smith (REP)' should be choice_type='candidate'")

    # Check vote totals preserved
    vote_totals = {c[0]: c[4] for c in choices}
    if vote_totals.get("John Smith (REP)") != 50000:
        errors.append(f"John Smith vote_total: expected 50000, got {vote_totals.get('John Smith (REP)')}")

    # --- Votes county ---
    vc_count = conn.execute("""
        SELECT COUNT(*) FROM votes_county vc
        JOIN races r ON vc.race_id = r.id JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA'
    """).fetchone()[0]
    print(f"\nVotes county: {vc_count}")
    if vc_count != 4:
        errors.append(f"Expected 4 votes_county rows, got {vc_count}")

    # --- Votes precinct ---
    vp_count = conn.execute("""
        SELECT COUNT(*) FROM votes_precinct vp
        JOIN races r ON vp.race_id = r.id JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA'
    """).fetchone()[0]
    print(f"Votes precinct: {vp_count}")
    if vp_count != 4:
        errors.append(f"Expected 4 votes_precinct rows, got {vp_count}")

    # --- Early votes ---
    ev_count = conn.execute("""
        SELECT COUNT(*) FROM early_votes ev
        JOIN races r ON ev.race_id = r.id JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA'
    """).fetchone()[0]
    print(f"Early votes: {ev_count}")
    if ev_count != 2:
        errors.append(f"Expected 2 early_votes rows, got {ev_count}")

    # --- Race reporting ---
    rr_count = conn.execute("""
        SELECT COUNT(*) FROM race_reporting rr
        JOIN races r ON rr.race_id = r.id JOIN elections e ON r.election_id = e.id
        WHERE e.state = 'LA'
    """).fetchone()[0]
    print(f"Race reporting: {rr_count}")
    if rr_count != 4:
        errors.append(f"Expected 4 race_reporting rows, got {rr_count}")

    # --- Turnout ---
    turnout_count = conn.execute("SELECT COUNT(*) FROM turnout").fetchone()[0]
    print(f"Turnout: {turnout_count}")

    # --- Race metadata ---
    meta = conn.execute("""
        SELECT r.title, rm.data FROM race_metadata rm
        JOIN races r ON rm.race_id = r.id
        JOIN elections e ON r.election_id = e.id WHERE e.state = 'LA'
    """).fetchall()
    print(f"\nRace metadata ({len(meta)}):")
    for m in meta:
        d = json.loads(m[1])
        print(f"  {m[0]}: office_level_code={d['office_level_code']}, can_have_runoff={d['can_have_runoff']}")
    if len(meta) != 3:
        errors.append(f"Expected 3 race_metadata rows, got {len(meta)}")

    # --- Quality checks ---
    checks = conn.execute(
        "SELECT check_name, passed, details FROM data_quality_checks"
    ).fetchall()
    print(f"\nQuality checks ({len(checks)}):")
    for c in checks:
        status = "PASS" if c[1] else "FAIL"
        print(f"  [{status}] {c[0]}: {c[1]}")
    if len(checks) != 4:
        errors.append(f"Expected 4 quality checks, got {len(checks)}")

    all_passed = all(c[1] for c in checks)
    if not all_passed:
        errors.append("Not all quality checks passed")

    # --- Import run ---
    run = conn.execute(
        "SELECT state, status, record_counts FROM import_runs"
    ).fetchone()
    print(f"\nImport run: state={run[0]}, status={run[1]}")
    counts = json.loads(run[2])
    for k, v in counts.items():
        print(f"  {k}: {v:,}")

    conn.close()

    # --- Idempotent re-run ---
    print("\n" + "=" * 60)
    print("Testing idempotent re-import...")
    print("=" * 60)

    return errors


def main():
    test_dir = tempfile.mkdtemp(prefix="la_import_test_")
    src_path = os.path.join(test_dir, "louisiana_elections.db")
    tgt_path = os.path.join(test_dir, "national.db")

    # Point WORKING_COPY to test dir
    import louisiana_import
    louisiana_import.WORKING_COPY = os.path.join(test_dir, "louisiana_source.db")

    try:
        print("Building synthetic source DB...")
        build_source_db(src_path)

        print("Creating target schema...")
        create_schema(tgt_path)

        print("\n" + "=" * 60)
        print("FIRST IMPORT")
        print("=" * 60)
        run_import(src_path, tgt_path)

        errors = verify(tgt_path)

        # Idempotent re-run
        run_import(src_path, tgt_path)
        tgt = sqlite3.connect(tgt_path)
        election_count = tgt.execute(
            "SELECT COUNT(*) FROM elections WHERE state = 'LA'"
        ).fetchone()[0]
        tgt.close()
        if election_count != 2:
            errors.append(
                f"After re-import, expected 2 elections, got {election_count} (not idempotent)"
            )
        else:
            print("  Idempotent re-import OK: still 2 elections")

        # Final result
        print("\n" + "=" * 60)
        if errors:
            print(f"TEST FAILED ({len(errors)} errors):")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        else:
            print("ALL TESTS PASSED!")
        print("=" * 60)

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
        print("Test directory cleaned up.")


if __name__ == "__main__":
    main()
