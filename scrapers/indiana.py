"""
Indiana Historical Election Scraper

Ingests archived election results from the Indiana Civix ENR JSON API
(enr.indianavoters.in.gov).  Each archive exposes two flat JSON files:

  - AllOfficeResults.json   (one row per candidate per precinct)
  - AllRefResults.json      (one row per referendum per precinct)

This scraper downloads those files, groups records into races/choices,
aggregates precinct votes to county level, and loads everything into
the national election tracker database.

Usage:
    python scrapers/indiana.py --election 2024General
    python scrapers/indiana.py --all
    python scrapers/indiana.py --all --force
    python scrapers/indiana.py --election 2024General --db-path /some/other.db
"""

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
import yaml

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scrapers"))

from base import StateScraper
from schema import (
    DEFAULT_DB_PATH,
    generate_choice_key,
    generate_election_key,
    generate_race_key,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(REPO_ROOT, "scrapers", "configs", "indiana.yaml")

# ---------------------------------------------------------------------------
# Office category mapping (OfficeCategory -> normalized office_category)
# ---------------------------------------------------------------------------

CATEGORY_MAP = {
    # Federal
    "President": "presidential",
    "US Senator": "us_senate",
    "US Representative": "us_house",
    # Statewide executive
    "Governor": "governor",
    "Lieutenant Governor": "lieutenant_governor",
    "Superintendent of Public Instruction": "state_office",
    "Attorney General": "attorney_general",
    "Auditor of State": "state_office",
    "Secretary of State": "state_office",
    "Treasurer of State": "state_office",
    # State legislature
    "State Senator": "state_senate",
    "State Representative": "state_house",
    # Judicial
    "Judge": "judicial",
    "Supreme Court Justice": "judicial",
    "Court of Appeals Judge": "judicial",
    "Circuit Court Judge": "judicial",
    "Superior Court Judge": "judicial",
    # County
    "County Council": "county",
    "County Commissioner": "county",
    "County Assessor": "county",
    "County Auditor": "county",
    "County Clerk": "county",
    "County Coroner": "county",
    "County Recorder": "county",
    "County Sheriff": "county",
    "County Surveyor": "county",
    "County Treasurer": "county",
    "Prosecuting Attorney": "county",
    # Municipal / township
    "Township Trustee": "municipal",
    "Township Board": "municipal",
    "City Council": "municipal",
    "Town Council": "municipal",
    "Mayor": "municipal",
    # School
    "School Board": "school_board",
    # Additional Indiana-specific categories
    "City Clerk Or Clerk/treasurer": "municipal",
    "City-County Or City Common Council Member": "municipal",
    "Judge, City Court": "judicial",
    "Judge, Town Court": "judicial",
    "Town Clerk-Treasurer": "municipal",
    "Town Council Member": "municipal",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _district_from_office(office: str, jurisdiction: str) -> str | None:
    """
    Extract a district identifier from the office title.

    Examples:
        'United States Representative District 9' -> 'd09'
        'State Senator District 22'               -> 'd22'
        'County Council District 4'               -> 'd04'
    """
    import re

    m = re.search(r"District\s+(\d+)", office, re.IGNORECASE)
    if m:
        return f"d{int(m.group(1)):02d}"
    return None


def _county_for_race(jurisdiction: str) -> str | None:
    """
    If the jurisdiction is not 'Statewide', return a lowered county-ish hint.
    Actual county_code lookup happens against the counties table.
    """
    if jurisdiction and jurisdiction.lower() != "statewide":
        return jurisdiction
    return None


# ---------------------------------------------------------------------------
# Indiana Scraper
# ---------------------------------------------------------------------------


class IndianaScraper(StateScraper):
    """Scraper for Indiana archived election data (Civix ENR JSON)."""

    def __init__(self, db_path: str, config: dict):
        super().__init__(db_path, config)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.get("user_agent", "NationalElectionTracker/1.0")
        self.delay = config.get("scraping", {}).get("delay_seconds", 2.0)
        self._county_cache: dict[str, str] | None = None  # name_lower -> code

    # ------------------------------------------------------------------
    # County name -> code lookup
    # ------------------------------------------------------------------

    def _build_county_cache(self, conn) -> dict[str, str]:
        """Build a case-insensitive county name -> county code map from the DB."""
        if self._county_cache is not None:
            return self._county_cache

        rows = conn.execute(
            "SELECT code, name FROM counties WHERE state = 'IN'"
        ).fetchall()
        cache = {}
        for row in rows:
            code, name = row["code"], row["name"]
            cache[name.lower()] = code
            # Handle "St. Joseph" -> "st. joseph" and "st joseph"
            if "." in name:
                cache[name.replace(".", "").lower()] = code
        self._county_cache = cache
        return cache

    def _county_code(self, conn, county_name: str) -> str | None:
        """Look up county code by name (case-insensitive). Returns None if unmatched."""
        cache = self._build_county_cache(conn)
        return cache.get(county_name.lower()) or cache.get(county_name.replace(".", "").lower())

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def list_elections(self) -> list[dict]:
        """Return the list of archive entries from the YAML config."""
        return self.config.get("archives", [])

    def fetch_election(self, archive: dict, force: bool = False) -> dict:
        """
        Fetch and ingest one election archive.

        Parameters
        ----------
        archive : dict
            One entry from config['archives'] with keys: slug, date, type.
        force : bool
            If True, re-import even if already done.

        Returns
        -------
        dict with summary counts, or {'skipped': True} if already imported.
        """
        slug = archive["slug"]
        date = archive["date"]
        etype = archive["type"]
        election_key = generate_election_key("IN", date, etype)

        conn = self.get_db()
        try:
            # Check idempotency
            if not force and self.is_election_imported(conn, election_key):
                log.info(f"  {slug}: already imported (election_key={election_key}), skipping")
                return {"skipped": True, "election_key": election_key}

            run_id = self.create_import_run(conn, election_key)
            conn.commit()

            try:
                # ----- Fetch JSON files -----
                url_template = self.config["archive_url_template"]

                office_url = url_template.format(slug=slug) + "/AllOfficeResults.json"
                log.info(f"  Fetching {office_url} ...")
                office_resp = self.session.get(office_url, timeout=120)
                office_resp.raise_for_status()
                office_data = office_resp.content
                office_records = json.loads(office_data)
                self.log_source_file(conn, run_id, office_url, office_data, f"{slug}_AllOfficeResults.json")
                log.info(f"    AllOfficeResults: {len(office_records):,} records ({len(office_data):,} bytes)")
                conn.commit()

                time.sleep(self.delay)

                ref_url = url_template.format(slug=slug) + "/AllRefResults.json"
                log.info(f"  Fetching {ref_url} ...")
                ref_resp = self.session.get(ref_url, timeout=120)
                ref_records = []
                if ref_resp.status_code == 200:
                    ref_data = ref_resp.content
                    ref_records = json.loads(ref_data)
                    self.log_source_file(conn, run_id, ref_url, ref_data, f"{slug}_AllRefResults.json")
                    log.info(f"    AllRefResults: {len(ref_records):,} records ({len(ref_data):,} bytes)")
                elif ref_resp.status_code == 404:
                    log.info(f"    AllRefResults: not found (no referendums for this election)")
                else:
                    ref_resp.raise_for_status()
                conn.commit()

                # ----- Delete existing data for this election if re-importing -----
                self._clear_election(conn, election_key)

                # ----- Create election record -----
                conn.execute(
                    "INSERT INTO elections (election_key, state, date, type, is_official, sos_election_id) "
                    "VALUES (?, 'IN', ?, ?, 1, ?)",
                    (election_key, date, etype, slug),
                )
                election_id = conn.execute(
                    "SELECT id FROM elections WHERE election_key = ?", (election_key,)
                ).fetchone()["id"]

                # ----- Process office results -----
                office_counts = self._process_offices(conn, election_id, election_key, office_records)

                # ----- Process referendum results -----
                ref_counts = self._process_referendums(conn, election_id, election_key, ref_records)

                # ----- Totals -----
                counts = {
                    "races": office_counts["races"] + ref_counts["races"],
                    "choices": office_counts["choices"] + ref_counts["choices"],
                    "votes_county": office_counts["votes_county"] + ref_counts["votes_county"],
                    "votes_precinct": office_counts["votes_precinct"] + ref_counts["votes_precinct"],
                }

                # ----- Quality checks -----
                all_passed = self._run_quality_checks(conn, run_id, election_id)

                # ----- Finish -----
                status = "success" if all_passed else "success_with_warnings"
                self.finish_import_run(conn, run_id, status, record_counts=counts)
                conn.commit()

                log.info(f"  {slug}: {counts['races']} races, {counts['choices']} choices, "
                         f"{counts['votes_county']} county votes, {counts['votes_precinct']} precinct votes")

                return {"election_key": election_key, **counts}

            except Exception as e:
                self.finish_import_run(conn, run_id, "failed", error=str(e))
                conn.commit()
                raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Clear existing election data (for re-import)
    # ------------------------------------------------------------------

    def _clear_election(self, conn, election_key: str) -> None:
        """Remove all data for an election_key so we can re-import cleanly."""
        row = conn.execute(
            "SELECT id FROM elections WHERE election_key = ?", (election_key,)
        ).fetchone()
        if row is None:
            return

        election_id = row["id"]
        race_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM races WHERE election_id = ?", (election_id,)
            ).fetchall()
        ]
        if race_ids:
            ph = ",".join("?" * len(race_ids))
            choice_ids = [
                c["id"] for c in conn.execute(
                    f"SELECT id FROM choices WHERE race_id IN ({ph})", race_ids
                ).fetchall()
            ]
            if choice_ids:
                cph = ",".join("?" * len(choice_ids))
                conn.execute(f"DELETE FROM votes_precinct WHERE choice_id IN ({cph})", choice_ids)
                conn.execute(f"DELETE FROM votes_county WHERE choice_id IN ({cph})", choice_ids)
                conn.execute(f"DELETE FROM early_votes WHERE choice_id IN ({cph})", choice_ids)

            conn.execute(f"DELETE FROM race_reporting WHERE race_id IN ({ph})", race_ids)
            conn.execute(f"DELETE FROM race_metadata WHERE race_id IN ({ph})", race_ids)
            conn.execute(f"DELETE FROM choices WHERE race_id IN ({ph})", race_ids)
            conn.execute(f"DELETE FROM races WHERE election_id = ?", (election_id,))

        conn.execute("DELETE FROM turnout WHERE election_id = ?", (election_id,))
        conn.execute("DELETE FROM elections WHERE id = ?", (election_id,))
        log.info(f"    Cleared existing data for {election_key}")

    # ------------------------------------------------------------------
    # Office results processing
    # ------------------------------------------------------------------

    def _process_offices(self, conn, election_id: int, election_key: str, records: list[dict]) -> dict:
        """
        Process AllOfficeResults.json records.

        Groups by (Office, OfficeCategory, JurisdictionName) to build races,
        then inserts choices and vote records.
        """
        if not records:
            return {"races": 0, "choices": 0, "votes_county": 0, "votes_precinct": 0}

        # --- Group records by race ---
        # Key: (Office, OfficeCategory, JurisdictionName)
        race_groups: dict[tuple, list[dict]] = defaultdict(list)
        for rec in records:
            key = (rec["Office"], rec.get("OfficeCategory", ""), rec.get("JurisdictionName", ""))
            race_groups[key].append(rec)

        race_count = 0
        choice_count = 0
        county_vote_count = 0
        precinct_vote_count = 0
        seen_race_keys = set()
        unrecognized_categories = set()

        for (office, office_category, jurisdiction), recs in race_groups.items():
            # --- Map category ---
            normalized = CATEGORY_MAP.get(office_category)
            if normalized is None:
                if office_category not in unrecognized_categories:
                    log.warning(f"    Unrecognized OfficeCategory '{office_category}' for '{office}' -- using 'other'")
                    unrecognized_categories.add(office_category)
                normalized = "other"

            # --- District ---
            district = _district_from_office(office, jurisdiction)

            # --- County for local races ---
            county_hint = _county_for_race(jurisdiction)
            race_county_code = None
            if county_hint:
                race_county_code = self._county_code(conn, county_hint)

            # --- Race key ---
            race_key = generate_race_key(election_key, office, district, county_hint)
            base_key = race_key
            suffix = 0
            while race_key in seen_race_keys:
                suffix += 1
                race_key = f"{base_key}--{suffix}"
            seen_race_keys.add(race_key)

            # --- num_to_elect ---
            num_seats = 1
            for r in recs:
                if r.get("NumberofOfficeSeats"):
                    num_seats = int(r["NumberofOfficeSeats"])
                    break

            # --- Insert race ---
            conn.execute(
                "INSERT INTO races (race_key, election_id, sos_race_id, title, office_category, "
                "office_name, district, county_code, num_to_elect, is_ballot_measure) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (race_key, election_id, None, office, normalized, office_category,
                 district, race_county_code, num_seats),
            )
            race_id = conn.execute(
                "SELECT id FROM races WHERE race_key = ?", (race_key,)
            ).fetchone()["id"]
            race_count += 1

            # --- Group records by candidate ---
            # Key: (NameonBallot, PoliticalParty)
            candidate_groups: dict[tuple, list[dict]] = defaultdict(list)
            for rec in recs:
                cand_key = (rec.get("NameonBallot", "Unknown"), rec.get("PoliticalParty"))
                candidate_groups[cand_key].append(rec)

            seen_choice_keys = set()

            for (name, party), cand_recs in candidate_groups.items():
                # --- Choice key ---
                choice_key = generate_choice_key(race_key, name, party)
                base_ck = choice_key
                ck_suffix = 0
                while choice_key in seen_choice_keys:
                    ck_suffix += 1
                    choice_key = f"{base_ck}--{ck_suffix}"
                seen_choice_keys.add(choice_key)

                # --- Ballot order ---
                ballot_order = None
                for r in cand_recs:
                    if r.get("BallotOrder") is not None:
                        ballot_order = int(r["BallotOrder"])
                        break

                # --- Winner / outcome ---
                outcome = None
                for r in cand_recs:
                    if r.get("Winner", "").lower() == "yes":
                        outcome = "Elected"
                        break

                # --- Vote total (sum all precinct records) ---
                vote_total = sum(int(r.get("TotalVotes", 0)) for r in cand_recs)

                # --- Insert choice ---
                conn.execute(
                    "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                    "name, party, ballot_order, color_hex, outcome, vote_total) "
                    "VALUES (?, ?, ?, 'candidate', ?, ?, ?, NULL, ?, ?)",
                    (choice_key, race_id, None, name, party, ballot_order, outcome, vote_total),
                )
                choice_id = conn.execute(
                    "SELECT id FROM choices WHERE choice_key = ?", (choice_key,)
                ).fetchone()["id"]
                choice_count += 1

                # --- Precinct votes ---
                for rec in cand_recs:
                    county_name = rec.get("ReportingCountyName", "")
                    cc = self._county_code(conn, county_name) if county_name else None
                    if cc is None:
                        continue
                    precinct = rec.get("DataEntryJurisdictionName", "Unknown")
                    votes = int(rec.get("TotalVotes", 0))
                    conn.execute(
                        "INSERT OR IGNORE INTO votes_precinct "
                        "(race_id, county_code, precinct_id, choice_id, vote_total) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (race_id, cc, precinct, choice_id, votes),
                    )
                    precinct_vote_count += 1

                # --- County-level aggregation ---
                county_totals: dict[str, int] = defaultdict(int)
                for rec in cand_recs:
                    county_name = rec.get("ReportingCountyName", "")
                    cc = self._county_code(conn, county_name) if county_name else None
                    if cc is None:
                        continue
                    county_totals[cc] += int(rec.get("TotalVotes", 0))

                for cc, vtotal in county_totals.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO votes_county "
                        "(race_id, county_code, choice_id, vote_total) "
                        "VALUES (?, ?, ?, ?)",
                        (race_id, cc, choice_id, vtotal),
                    )
                    county_vote_count += 1

        if unrecognized_categories:
            log.info(f"    Unrecognized categories: {sorted(unrecognized_categories)}")

        return {
            "races": race_count,
            "choices": choice_count,
            "votes_county": county_vote_count,
            "votes_precinct": precinct_vote_count,
        }

    # ------------------------------------------------------------------
    # Referendum results processing
    # ------------------------------------------------------------------

    def _process_referendums(self, conn, election_id: int, election_key: str, records: list[dict]) -> dict:
        """
        Process AllRefResults.json records.

        Each referendum becomes a race with two choices (Yes / No).
        """
        if not records:
            return {"races": 0, "choices": 0, "votes_county": 0, "votes_precinct": 0}

        # --- Group by referendum ---
        # Key: (ReferendumTitle, ReportingJurisdiction or TypeofReferendum)
        ref_groups: dict[tuple, list[dict]] = defaultdict(list)
        for rec in records:
            title = rec.get("ReferendumTitle", "Unknown Referendum")
            jurisdiction = rec.get("ReportingJurisdiction", "")
            ref_groups[(title, jurisdiction)].append(rec)

        race_count = 0
        choice_count = 0
        county_vote_count = 0
        precinct_vote_count = 0
        seen_race_keys = set()

        for (title, jurisdiction), recs in ref_groups.items():
            # --- County hint ---
            county_hint = None
            if jurisdiction and jurisdiction.lower() != "statewide":
                county_hint = jurisdiction

            # --- Race key ---
            race_key = generate_race_key(election_key, title, None, county_hint)
            base_key = race_key
            suffix = 0
            while race_key in seen_race_keys:
                suffix += 1
                race_key = f"{base_key}--{suffix}"
            seen_race_keys.add(race_key)

            # --- Insert race ---
            race_county_code = self._county_code(conn, county_hint) if county_hint else None
            conn.execute(
                "INSERT INTO races (race_key, election_id, sos_race_id, title, office_category, "
                "office_name, district, county_code, num_to_elect, is_ballot_measure) "
                "VALUES (?, ?, ?, ?, 'referendum', ?, NULL, ?, 1, 1)",
                (race_key, election_id, None, title,
                 recs[0].get("TypeofReferendum", "Referendum"), race_county_code),
            )
            race_id = conn.execute(
                "SELECT id FROM races WHERE race_key = ?", (race_key,)
            ).fetchone()["id"]
            race_count += 1

            # --- Yes choice ---
            yes_key = generate_choice_key(race_key, "Yes")
            conn.execute(
                "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                "name, party, ballot_order, color_hex, outcome, vote_total) "
                "VALUES (?, ?, NULL, 'ballot_option', 'Yes', NULL, 1, NULL, NULL, 0)",
                (yes_key, race_id),
            )
            yes_id = conn.execute(
                "SELECT id FROM choices WHERE choice_key = ?", (yes_key,)
            ).fetchone()["id"]

            # --- No choice ---
            no_key = generate_choice_key(race_key, "No")
            conn.execute(
                "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                "name, party, ballot_order, color_hex, outcome, vote_total) "
                "VALUES (?, ?, NULL, 'ballot_option', 'No', NULL, 2, NULL, NULL, 0)",
                (no_key, race_id),
            )
            no_id = conn.execute(
                "SELECT id FROM choices WHERE choice_key = ?", (no_key,)
            ).fetchone()["id"]
            choice_count += 2

            # --- Precinct votes + county aggregation ---
            # Referendum records may use ReportingCountyName OR
            # ReportingJurisdiction for the county name (the former is
            # sometimes empty).  DataEntryJurisdictionName may be the
            # county itself (Locality level) or a precinct name.
            yes_county: dict[str, int] = defaultdict(int)
            no_county: dict[str, int] = defaultdict(int)
            yes_total = 0
            no_total = 0

            for rec in recs:
                county_name = (
                    rec.get("ReportingCountyName")
                    or rec.get("ReportingJurisdiction")
                    or ""
                )
                cc = self._county_code(conn, county_name) if county_name else None
                precinct = rec.get("DataEntryJurisdictionName", "Unknown")
                y_votes = int(rec.get("YesVotes", 0))
                n_votes = int(rec.get("NoVotes", 0))
                yes_total += y_votes
                no_total += n_votes

                if cc:
                    yes_county[cc] += y_votes
                    no_county[cc] += n_votes

                    conn.execute(
                        "INSERT OR IGNORE INTO votes_precinct "
                        "(race_id, county_code, precinct_id, choice_id, vote_total) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (race_id, cc, precinct, yes_id, y_votes),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO votes_precinct "
                        "(race_id, county_code, precinct_id, choice_id, vote_total) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (race_id, cc, precinct, no_id, n_votes),
                    )
                    precinct_vote_count += 2

            # --- County vote records ---
            for cc, vtotal in yes_county.items():
                conn.execute(
                    "INSERT OR IGNORE INTO votes_county "
                    "(race_id, county_code, choice_id, vote_total) VALUES (?, ?, ?, ?)",
                    (race_id, cc, yes_id, vtotal),
                )
                county_vote_count += 1

            for cc, vtotal in no_county.items():
                conn.execute(
                    "INSERT OR IGNORE INTO votes_county "
                    "(race_id, county_code, choice_id, vote_total) VALUES (?, ?, ?, ?)",
                    (race_id, cc, no_id, vtotal),
                )
                county_vote_count += 1

            # --- Update choice vote totals ---
            conn.execute("UPDATE choices SET vote_total = ? WHERE id = ?", (yes_total, yes_id))
            conn.execute("UPDATE choices SET vote_total = ? WHERE id = ?", (no_total, no_id))

            # --- Determine outcome ---
            if yes_total > no_total:
                conn.execute("UPDATE choices SET outcome = 'Passed' WHERE id = ?", (yes_id,))
                conn.execute("UPDATE choices SET outcome = 'Failed' WHERE id = ?", (no_id,))
            elif no_total > yes_total:
                conn.execute("UPDATE choices SET outcome = 'Failed' WHERE id = ?", (yes_id,))
                conn.execute("UPDATE choices SET outcome = 'Passed' WHERE id = ?", (no_id,))

        return {
            "races": race_count,
            "choices": choice_count,
            "votes_county": county_vote_count,
            "votes_precinct": precinct_vote_count,
        }

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def _run_quality_checks(self, conn, run_id: int, election_id: int) -> bool:
        """Run post-import quality checks. Returns True if all pass."""
        all_passed = True

        # 1. county_totals_reconcile
        # For each race: sum of county vote totals for each choice should equal choice.vote_total
        mismatches = conn.execute("""
            SELECT c.id, c.name, c.vote_total,
                   COALESCE(SUM(vc.vote_total), 0) as county_sum
            FROM choices c
            JOIN races r ON c.race_id = r.id
            LEFT JOIN votes_county vc ON vc.choice_id = c.id AND vc.race_id = r.id
            WHERE r.election_id = ?
            GROUP BY c.id
            HAVING c.vote_total != COALESCE(SUM(vc.vote_total), 0)
        """, (election_id,)).fetchall()

        passed = len(mismatches) == 0
        details = {"mismatched_choices": len(mismatches)}
        if mismatches:
            details["examples"] = [
                {"choice": m["name"], "vote_total": m["vote_total"], "county_sum": m["county_sum"]}
                for m in mismatches[:5]
            ]
        self.log_quality_check(conn, run_id, "county_totals_reconcile", passed, details)
        if not passed:
            log.warning(f"    QC FAIL county_totals_reconcile: {len(mismatches)} mismatches")
            all_passed = False

        # 2. no_negative_votes
        neg_county = conn.execute("""
            SELECT COUNT(*) FROM votes_county vc
            JOIN races r ON vc.race_id = r.id
            WHERE r.election_id = ? AND vc.vote_total < 0
        """, (election_id,)).fetchone()[0]

        neg_precinct = conn.execute("""
            SELECT COUNT(*) FROM votes_precinct vp
            JOIN races r ON vp.race_id = r.id
            WHERE r.election_id = ? AND vp.vote_total < 0
        """, (election_id,)).fetchone()[0]

        neg_total = neg_county + neg_precinct
        passed = neg_total == 0
        self.log_quality_check(conn, run_id, "no_negative_votes", passed,
                               {"negative_county": neg_county, "negative_precinct": neg_precinct})
        if not passed:
            log.warning(f"    QC FAIL no_negative_votes: {neg_total} negative records")
            all_passed = False

        # 3. all_races_have_choices
        empty_races = conn.execute("""
            SELECT r.id, r.title FROM races r
            LEFT JOIN choices c ON c.race_id = r.id
            WHERE r.election_id = ?
            GROUP BY r.id
            HAVING COUNT(c.id) = 0
        """, (election_id,)).fetchall()

        passed = len(empty_races) == 0
        details = {"empty_races": len(empty_races)}
        if empty_races:
            details["examples"] = [r["title"] for r in empty_races[:5]]
        self.log_quality_check(conn, run_id, "all_races_have_choices", passed, details)
        if not passed:
            log.warning(f"    QC FAIL all_races_have_choices: {len(empty_races)} empty races")
            all_passed = False

        return all_passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_config(path: str = CONFIG_PATH) -> dict:
    """Load the Indiana YAML config."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Indiana historical election scraper (Civix ENR JSON).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--election", help="Single election slug (e.g. 2024General)")
    group.add_argument("--all", action="store_true", help="Import all archives in config")
    parser.add_argument("--force", action="store_true", help="Re-import even if already done")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to indiana.yaml config")
    args = parser.parse_args()

    config = load_config(args.config)
    scraper = IndianaScraper(args.db_path, config)

    archives = scraper.list_elections()

    if args.election:
        # Find the matching archive
        match = [a for a in archives if a["slug"] == args.election]
        if not match:
            slugs = [a["slug"] for a in archives]
            log.error(f"Election '{args.election}' not found in config. Available: {slugs}")
            sys.exit(1)
        targets = match
    else:
        targets = archives

    # --- Run ---
    total = len(targets)
    log.info(f"Indiana scraper: {total} election(s) to process")
    log.info(f"Database: {args.db_path}")
    log.info("=" * 60)

    results = []
    errors = []

    for i, archive in enumerate(targets, 1):
        slug = archive["slug"]
        log.info(f"[{i}/{total}] {slug} ({archive['date']} {archive['type']})")
        try:
            result = scraper.fetch_election(archive, force=args.force)
            results.append(result)
        except Exception as e:
            log.error(f"  FAILED: {e}")
            errors.append((slug, str(e)))
            results.append({"error": str(e), "election_key": f"IN-{archive['date']}-{archive['type']}"})

        # Rate-limit between elections
        if i < total:
            time.sleep(scraper.delay)

    # --- Summary ---
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)

    imported = [r for r in results if not r.get("skipped") and not r.get("error")]
    skipped = [r for r in results if r.get("skipped")]

    total_races = sum(r.get("races", 0) for r in imported)
    total_choices = sum(r.get("choices", 0) for r in imported)
    total_county = sum(r.get("votes_county", 0) for r in imported)
    total_precinct = sum(r.get("votes_precinct", 0) for r in imported)

    log.info(f"  Elections imported: {len(imported)}")
    log.info(f"  Elections skipped:  {len(skipped)}")
    log.info(f"  Errors:             {len(errors)}")
    log.info(f"  Total races:        {total_races:,}")
    log.info(f"  Total choices:      {total_choices:,}")
    log.info(f"  Total county votes: {total_county:,}")
    log.info(f"  Total precinct votes: {total_precinct:,}")

    if errors:
        log.info("  Failed elections:")
        for slug, err in errors:
            log.info(f"    - {slug}: {err}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
