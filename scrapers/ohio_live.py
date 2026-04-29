"""
Ohio Live Election Results Parser (NIST 1500-100 XML)

Fetches and parses live election results from the Ohio Secretary of State's
NIST 1500-100 XML feed.  This is a Phase 1 live-only parser -- no historical
XLSX support.

The NIST XML uses ObjectId cross-references extensively.  We build lookup
dicts (id -> object) for GpUnit, Party, Person, Candidate, and Contest
before processing vote counts.

Endpoint:
    https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob

Usage:
    python scrapers/ohio_live.py --once                  # fetch once and exit
    python scrapers/ohio_live.py --once --db-path /path   # custom DB
    python scrapers/ohio_live.py --poll                   # poll every 3 minutes until Ctrl-C
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
import yaml
from lxml import etree

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

CONFIG_PATH = os.path.join(REPO_ROOT, "scrapers", "configs", "ohio.yaml")

# ---------------------------------------------------------------------------
# NIST Election Type -> our type mapping
# ---------------------------------------------------------------------------

NIST_TYPE_MAP = {
    "general": "general",
    "partisan-primary-closed": "primary",
    "partisan-primary-open": "primary",
    "primary": "primary",
    "runoff": "runoff",
    "special": "special",
}

# ---------------------------------------------------------------------------
# Office category classification from contest name
# ---------------------------------------------------------------------------

OFFICE_PATTERNS = [
    # Federal
    (r"\b(president|presidential)\b", "presidential"),
    (r"\bu\.?s\.?\s*senat", "us_senate"),
    (r"\bunited\s+states\s+senat", "us_senate"),
    (r"\bu\.?s\.?\s*represent", "us_house"),
    (r"\bunited\s+states\s+represent", "us_house"),
    (r"\bcongressional\b", "us_house"),
    (r"\bmember\s+of\s+congress\b", "us_house"),
    # Statewide executive
    (r"\bgovernor\b", "governor"),
    (r"\blieutenant\s+governor\b", "lieutenant_governor"),
    (r"\battorney\s+general\b", "attorney_general"),
    (r"\bsecretary\s+of\s+state\b", "state_office"),
    (r"\bauditor\s+of\s+state\b", "state_office"),
    (r"\btreasurer\s+of\s+state\b", "state_office"),
    (r"\bchief\s+justice\b", "judicial"),
    (r"\bjustice\s+of\s+(the\s+)?supreme\s+court\b", "judicial"),
    # State legislature
    (r"\bstate\s+senat", "state_senate"),
    (r"\bstate\s+represent", "state_house"),
    # Judicial
    (r"\bjudge\b", "judicial"),
    (r"\bjustice\b", "judicial"),
    (r"\bcourt\s+of\s+appeals?\b", "judicial"),
    (r"\bcourt\s+of\s+common\s+pleas\b", "judicial"),
    (r"\bmunicipal\s+court\b", "judicial"),
    (r"\bdomestic\s+relations\b", "judicial"),
    (r"\bjuvenile\s+court\b", "judicial"),
    (r"\bprobate\s+court\b", "judicial"),
    # County
    (r"\bcounty\s+commission", "county"),
    (r"\bcounty\s+council", "county"),
    (r"\bcounty\s+auditor\b", "county"),
    (r"\bcounty\s+clerk\b", "county"),
    (r"\bcounty\s+engineer\b", "county"),
    (r"\bcounty\s+recorder\b", "county"),
    (r"\bcounty\s+treasurer\b", "county"),
    (r"\bcounty\s+sheriff\b", "county"),
    (r"\bcoroner\b", "county"),
    (r"\bprosecuting\s+attorney\b", "county"),
    # Municipal / township
    (r"\bmayor\b", "municipal"),
    (r"\bcity\s+council\b", "municipal"),
    (r"\btownship\b", "municipal"),
    (r"\bvillage\b", "municipal"),
    # School
    (r"\bschool\s+board\b", "school_board"),
    (r"\bboard\s+of\s+education\b", "school_board"),
]


def classify_office(contest_name: str) -> str:
    """Classify a contest name into an office_category."""
    name_lower = contest_name.lower()
    for pattern, category in OFFICE_PATTERNS:
        if re.search(pattern, name_lower):
            return category
    return "other"


def _extract_district(contest_name: str) -> str | None:
    """Extract a district identifier from a contest name, if present."""
    m = re.search(r"District\s+(\d+)", contest_name, re.IGNORECASE)
    if m:
        return f"d{int(m.group(1)):02d}"
    return None


# ---------------------------------------------------------------------------
# XML namespace helpers
# ---------------------------------------------------------------------------

# The NIST 1500-100 XML may use a default namespace.  We detect it at parse
# time and build a prefix map so all XPath queries work.

def _ns(tree):
    """Return the namespace prefix map for the root element, or empty dict."""
    root = tree.getroot() if hasattr(tree, "getroot") else tree
    nsmap = root.nsmap.copy() if root.nsmap else {}
    # lxml stores the default namespace under None key
    if None in nsmap:
        nsmap["ns"] = nsmap.pop(None)
    return nsmap


def _tag(nsmap, local_name):
    """Build a Clark-notation {namespace}localName tag, or plain localName."""
    if "ns" in nsmap:
        return f"{{{nsmap['ns']}}}{local_name}"
    return local_name


# ---------------------------------------------------------------------------
# Ohio Scraper
# ---------------------------------------------------------------------------


class OhioLiveScraper(StateScraper):
    """Scraper for Ohio live election results (NIST 1500-100 XML)."""

    def __init__(self, db_path: str, config: dict):
        super().__init__(db_path, config)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.get(
            "user_agent", "NationalElectionTracker/1.0"
        )
        self.delay = config.get("scraping", {}).get("delay_seconds", 5.0)
        self.poll_interval = config.get("scraping", {}).get(
            "poll_interval_seconds", 180
        )
        self._county_cache: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # County name -> code lookup
    # ------------------------------------------------------------------

    def _build_county_cache(self, conn) -> dict[str, str]:
        """Build a case-insensitive county name -> county code map."""
        if self._county_cache is not None:
            return self._county_cache

        rows = conn.execute(
            "SELECT code, name FROM counties WHERE state = 'OH'"
        ).fetchall()
        cache = {}
        for row in rows:
            code, name = row["code"], row["name"]
            cache[name.lower()] = code
            # Also store without "county" suffix and with period variants
            stripped = re.sub(r"\s+county$", "", name, flags=re.IGNORECASE).lower()
            cache[stripped] = code
            if "." in name:
                cache[name.replace(".", "").lower()] = code
        self._county_cache = cache
        return cache

    def _county_code(self, conn, county_name: str) -> str | None:
        """Look up county code by name (case-insensitive)."""
        cache = self._build_county_cache(conn)
        name_lower = county_name.lower().strip()
        # Try exact match
        if name_lower in cache:
            return cache[name_lower]
        # Try without " county" suffix
        stripped = re.sub(r"\s+county$", "", name_lower)
        if stripped in cache:
            return cache[stripped]
        # Try without periods
        no_dots = name_lower.replace(".", "")
        if no_dots in cache:
            return cache[no_dots]
        return None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    def list_elections(self) -> list[dict]:
        """
        For live scraping there is no static list.  We parse the XML to
        discover the current election.  Return an empty list; the actual
        election discovery happens inside fetch_live().
        """
        return []

    def fetch_election(self, election_id: str) -> dict:
        """Not used for live -- see fetch_live()."""
        return self.fetch_live()

    # ------------------------------------------------------------------
    # Live fetch
    # ------------------------------------------------------------------

    def fetch_live(self) -> dict:
        """
        Fetch the NIST XML, parse it, and load into the database.
        Returns a summary dict with counts.
        """
        url = self.config["live_url"]
        log.info(f"Fetching Ohio live results from {url}")

        resp = self.session.get(url, timeout=120)
        resp.raise_for_status()
        raw_data = resp.content
        log.info(f"  Received {len(raw_data):,} bytes")

        # Parse the XML
        tree = etree.fromstring(raw_data)
        nsmap = _ns(tree)

        # Detect test data
        is_test = tree.get("IsTest", "false").lower() == "true"
        if is_test:
            log.warning("  XML has IsTest='true' -- this is test/placeholder data")

        # Extract election metadata
        election_el = tree.find(_tag(nsmap, "Election"), nsmap)
        if election_el is None:
            log.error("  No <Election> element found in XML")
            return {"error": "No Election element"}

        election_name = self._text(election_el, "Name", nsmap) or "Ohio Election"
        start_date = self._text(election_el, "StartDate", nsmap)
        end_date = self._text(election_el, "EndDate", nsmap)
        nist_type_el = election_el.find(_tag(nsmap, "Type"), nsmap)
        nist_type = (nist_type_el.text.strip().lower() if nist_type_el is not None and nist_type_el.text else "general")

        # Map to our election type
        election_type = NIST_TYPE_MAP.get(nist_type, "general")
        election_date = start_date or end_date or datetime.now().strftime("%Y-%m-%d")

        election_key = generate_election_key("OH", election_date, election_type)
        log.info(f"  Election: {election_name} ({election_key})")
        log.info(f"  Date: {election_date}, Type: {election_type}, Test: {is_test}")

        # Open DB and process
        conn = self.get_db()
        try:
            run_id = self.create_import_run(conn, election_key)
            self.log_source_file(conn, run_id, url, raw_data, "VSSC1622XmlFileBlob.xml")
            conn.commit()

            try:
                # Build lookup dicts from XML
                lookups = self._build_lookups(tree, nsmap)

                # Clear existing data for this election (UPSERT behavior)
                self._clear_election(conn, election_key)

                # Create election record
                conn.execute(
                    "INSERT INTO elections (election_key, state, date, type, is_official, sos_election_id) "
                    "VALUES (?, 'OH', ?, ?, ?, ?)",
                    (election_key, election_date, election_type, 0 if is_test else 1, election_name),
                )
                election_id = conn.execute(
                    "SELECT id FROM elections WHERE election_key = ?", (election_key,)
                ).fetchone()["id"]

                # Store test flag in race_metadata for the election
                if is_test:
                    # We will store it as election-level metadata through import_runs
                    pass

                # Process contests and votes
                counts = self._process_contests(
                    conn, election_id, election_key, tree, nsmap, lookups
                )

                # Quality checks
                all_passed = self._run_quality_checks(conn, run_id, election_id)

                # Record metadata about test status
                record_counts = {
                    **counts,
                    "is_test": is_test,
                }
                status = "success" if all_passed else "success_with_warnings"
                self.finish_import_run(conn, run_id, status, record_counts=record_counts)
                conn.commit()

                log.info(
                    f"  Result: {counts['races']} races, {counts['choices']} choices, "
                    f"{counts['votes_county']} county vote rows"
                )

                return {"election_key": election_key, **counts, "is_test": is_test}

            except Exception as e:
                self.finish_import_run(conn, run_id, "failed", error=str(e))
                conn.commit()
                raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # XML helpers
    # ------------------------------------------------------------------

    def _text(self, el, child_name: str, nsmap: dict) -> str | None:
        """Get text content of a child element, or None."""
        child = el.find(_tag(nsmap, child_name), nsmap)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def _attr(self, el, attr_name: str) -> str | None:
        """Get an attribute value, checking with and without namespace."""
        val = el.get(attr_name)
        if val is not None:
            return val
        # Try with xsi: namespace prefix
        for key, value in el.attrib.items():
            if key.endswith(attr_name) or key.split("}")[-1] == attr_name:
                return value
        return None

    # ------------------------------------------------------------------
    # Build lookup dicts
    # ------------------------------------------------------------------

    def _build_lookups(self, tree, nsmap: dict) -> dict:
        """
        Build lookup dicts from the NIST XML for cross-referencing.

        Returns a dict with keys:
            gpunits: {ObjectId: element}
            parties: {ObjectId: {name, abbreviation, color}}
            persons: {ObjectId: full_name}
            candidates: {ObjectId: {person_id, party_id, ballot_name}}
            gpunit_type: {ObjectId: type_str}  (state/county/precinct)
            gpunit_name: {ObjectId: name_str}
        """
        lookups = {
            "gpunits": {},
            "gpunit_type": {},
            "gpunit_name": {},
            "gpunit_composing": {},
            "parties": {},
            "persons": {},
            "candidates": {},
        }

        # -- GpUnit --
        for gpu in tree.iter(_tag(nsmap, "GpUnit")):
            oid = gpu.get("ObjectId")
            if oid is None:
                continue
            lookups["gpunits"][oid] = gpu

            gpu_type = self._text(gpu, "Type", nsmap) or ""
            lookups["gpunit_type"][oid] = gpu_type.lower()

            gpu_name = self._text(gpu, "Name", nsmap) or ""
            lookups["gpunit_name"][oid] = gpu_name

            composing = self._text(gpu, "ComposingGpUnitIds", nsmap)
            if composing:
                lookups["gpunit_composing"][oid] = composing.split()

        # -- Party --
        for party in tree.iter(_tag(nsmap, "Party")):
            oid = party.get("ObjectId")
            if oid is None:
                continue
            lookups["parties"][oid] = {
                "name": self._text(party, "Name", nsmap) or "",
                "abbreviation": self._text(party, "Abbreviation", nsmap) or "",
                "color": self._text(party, "Color", nsmap),
            }

        # -- Person --
        for person in tree.iter(_tag(nsmap, "Person")):
            oid = person.get("ObjectId")
            if oid is None:
                continue
            full_name = self._text(person, "FullName", nsmap) or ""
            # Also try FirstName + LastName if FullName is empty
            if not full_name:
                fn = self._text(person, "FirstName", nsmap) or ""
                ln = self._text(person, "LastName", nsmap) or ""
                full_name = f"{fn} {ln}".strip()
            lookups["persons"][oid] = full_name

        # -- Candidate --
        for cand in tree.iter(_tag(nsmap, "Candidate")):
            oid = cand.get("ObjectId")
            if oid is None:
                continue
            person_id = self._text(cand, "PersonId", nsmap)
            party_id = self._text(cand, "PartyId", nsmap)
            ballot_name_el = cand.find(_tag(nsmap, "BallotName"), nsmap)
            ballot_name = ""
            if ballot_name_el is not None:
                # BallotName may contain a Text child
                text_el = ballot_name_el.find(_tag(nsmap, "Text"), nsmap)
                if text_el is not None and text_el.text:
                    ballot_name = text_el.text.strip()
                elif ballot_name_el.text:
                    ballot_name = ballot_name_el.text.strip()

            # Fall back to Person FullName
            if not ballot_name and person_id:
                ballot_name = lookups["persons"].get(person_id, "")

            lookups["candidates"][oid] = {
                "person_id": person_id,
                "party_id": party_id,
                "ballot_name": ballot_name,
            }

        log.info(
            f"  Lookups: {len(lookups['gpunits'])} GpUnits, "
            f"{len(lookups['parties'])} Parties, "
            f"{len(lookups['persons'])} Persons, "
            f"{len(lookups['candidates'])} Candidates"
        )

        return lookups

    # ------------------------------------------------------------------
    # Identify county GpUnits
    # ------------------------------------------------------------------

    def _county_gpunits(self, lookups: dict) -> dict[str, str]:
        """
        Return {gpunit_object_id: county_name} for all county-type GpUnits.
        """
        result = {}
        for oid, gtype in lookups["gpunit_type"].items():
            if gtype == "county":
                result[oid] = lookups["gpunit_name"].get(oid, "")
        return result

    # ------------------------------------------------------------------
    # Process contests
    # ------------------------------------------------------------------

    def _process_contests(
        self,
        conn,
        election_id: int,
        election_key: str,
        tree,
        nsmap: dict,
        lookups: dict,
    ) -> dict:
        """
        Process all Contest elements (CandidateContest, BallotMeasureContest,
        RetentionContest) and their vote counts.
        """
        race_count = 0
        choice_count = 0
        county_vote_count = 0
        seen_race_keys = set()

        # Map county GpUnit ObjectId -> our county_code in DB
        county_gpunits = self._county_gpunits(lookups)
        county_gpunit_to_code = {}
        for gpu_oid, county_name in county_gpunits.items():
            cc = self._county_code(conn, county_name)
            if cc:
                county_gpunit_to_code[gpu_oid] = cc
            else:
                log.debug(f"    Could not match county GpUnit '{county_name}' (id={gpu_oid})")

        log.info(f"  Matched {len(county_gpunit_to_code)}/{len(county_gpunits)} county GpUnits to DB")

        # Iterate all Contest elements
        # The NIST XML uses xsi:type to distinguish CandidateContest, BallotMeasureContest, etc.
        # We look for the xsi:type attribute, or fall back to child element detection.

        contest_tag = _tag(nsmap, "Contest")
        for contest in tree.iter(contest_tag):
            contest_oid = contest.get("ObjectId") or ""

            # Determine contest type
            xsi_type = self._get_xsi_type(contest)
            contest_name = self._text(contest, "Name", nsmap) or "Unknown Contest"

            if xsi_type == "BallotMeasureContest" or contest.find(_tag(nsmap, "FullText"), nsmap) is not None:
                result = self._process_ballot_measure(
                    conn, election_id, election_key, contest, nsmap, lookups,
                    county_gpunit_to_code, seen_race_keys,
                )
            elif xsi_type == "RetentionContest":
                result = self._process_retention(
                    conn, election_id, election_key, contest, nsmap, lookups,
                    county_gpunit_to_code, seen_race_keys,
                )
            else:
                # Default: CandidateContest (or unknown type treated as candidate)
                result = self._process_candidate_contest(
                    conn, election_id, election_key, contest, nsmap, lookups,
                    county_gpunit_to_code, seen_race_keys,
                )

            race_count += result["races"]
            choice_count += result["choices"]
            county_vote_count += result["votes_county"]

        return {
            "races": race_count,
            "choices": choice_count,
            "votes_county": county_vote_count,
        }

    def _get_xsi_type(self, el) -> str:
        """Extract the xsi:type attribute value (e.g. 'CandidateContest')."""
        # Check for {http://www.w3.org/2001/XMLSchema-instance}type
        for key, val in el.attrib.items():
            if key.endswith("}type") or key == "type":
                # Value may be prefixed like "ns:CandidateContest"
                return val.split(":")[-1] if ":" in val else val
        return ""

    # ------------------------------------------------------------------
    # Process CandidateContest
    # ------------------------------------------------------------------

    def _process_candidate_contest(
        self, conn, election_id, election_key, contest, nsmap, lookups,
        county_gpunit_to_code, seen_race_keys,
    ) -> dict:
        """Process a single CandidateContest element."""
        contest_name = self._text(contest, "Name", nsmap) or "Unknown Race"
        votes_allowed = self._text(contest, "VotesAllowed", nsmap)
        num_to_elect = int(votes_allowed) if votes_allowed else 1

        office_category = classify_office(contest_name)
        district = _extract_district(contest_name)

        # Build race key
        race_key = generate_race_key(election_key, contest_name, district)
        race_key = self._unique_race_key(race_key, seen_race_keys)

        # Insert race
        conn.execute(
            "INSERT INTO races (race_key, election_id, sos_race_id, title, office_category, "
            "office_name, district, county_code, num_to_elect, is_ballot_measure) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0)",
            (race_key, election_id, contest.get("ObjectId"), contest_name,
             office_category, contest_name, district, num_to_elect),
        )
        race_id = conn.execute(
            "SELECT id FROM races WHERE race_key = ?", (race_key,)
        ).fetchone()["id"]

        # Process selections (ContestSelection / CandidateSelection)
        choice_count = 0
        county_vote_count = 0

        selection_tag = _tag(nsmap, "ContestSelection")
        for selection in contest.iter(selection_tag):
            sel_type = self._get_xsi_type(selection)

            # Get candidate info
            candidate_ids_el = selection.find(_tag(nsmap, "CandidateIds"), nsmap)
            candidate_ids_text = ""
            if candidate_ids_el is not None and candidate_ids_el.text:
                candidate_ids_text = candidate_ids_el.text.strip()

            candidate_id = candidate_ids_text.split()[0] if candidate_ids_text else None
            cand_info = lookups["candidates"].get(candidate_id, {}) if candidate_id else {}

            name = cand_info.get("ballot_name", "")
            if not name:
                # Try sequence number or any identifying text
                name = self._text(selection, "SequenceOrder", nsmap) or "Unknown"

            party_id = cand_info.get("party_id")
            party_info = lookups["parties"].get(party_id, {}) if party_id else {}
            party_name = party_info.get("name") or party_info.get("abbreviation")
            party_color = party_info.get("color")

            # Ballot order
            seq = self._text(selection, "SequenceOrder", nsmap)
            ballot_order = int(seq) if seq else None

            # Aggregate votes
            vote_total, county_votes = self._extract_votes(
                selection, nsmap, county_gpunit_to_code
            )

            # Choice key
            choice_key = generate_choice_key(race_key, name, party_name)

            # Insert choice
            conn.execute(
                "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                "name, party, ballot_order, color_hex, outcome, vote_total) "
                "VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?, NULL, ?)",
                (choice_key, race_id, selection.get("ObjectId"), name,
                 party_name, ballot_order, party_color, vote_total),
            )
            choice_id = conn.execute(
                "SELECT id FROM choices WHERE choice_key = ?", (choice_key,)
            ).fetchone()["id"]
            choice_count += 1

            # Insert county votes
            for cc, vtotal in county_votes.items():
                conn.execute(
                    "INSERT OR REPLACE INTO votes_county "
                    "(race_id, county_code, choice_id, vote_total) "
                    "VALUES (?, ?, ?, ?)",
                    (race_id, cc, choice_id, vtotal),
                )
                county_vote_count += 1

        return {"races": 1, "choices": choice_count, "votes_county": county_vote_count}

    # ------------------------------------------------------------------
    # Process BallotMeasureContest
    # ------------------------------------------------------------------

    def _process_ballot_measure(
        self, conn, election_id, election_key, contest, nsmap, lookups,
        county_gpunit_to_code, seen_race_keys,
    ) -> dict:
        """Process a single BallotMeasureContest element."""
        contest_name = self._text(contest, "Name", nsmap) or "Unknown Ballot Measure"
        full_text_el = contest.find(_tag(nsmap, "FullText"), nsmap)
        full_text = ""
        if full_text_el is not None:
            text_el = full_text_el.find(_tag(nsmap, "Text"), nsmap)
            if text_el is not None and text_el.text:
                full_text = text_el.text.strip()
            elif full_text_el.text:
                full_text = full_text_el.text.strip()

        # Build race key
        race_key = generate_race_key(election_key, contest_name)
        race_key = self._unique_race_key(race_key, seen_race_keys)

        # Insert race
        conn.execute(
            "INSERT INTO races (race_key, election_id, sos_race_id, title, office_category, "
            "office_name, district, county_code, num_to_elect, is_ballot_measure) "
            "VALUES (?, ?, ?, ?, 'referendum', ?, NULL, NULL, 1, 1)",
            (race_key, election_id, contest.get("ObjectId"), contest_name, contest_name),
        )
        race_id = conn.execute(
            "SELECT id FROM races WHERE race_key = ?", (race_key,)
        ).fetchone()["id"]

        # Store full text as metadata
        if full_text:
            conn.execute(
                "INSERT OR REPLACE INTO race_metadata (race_id, data) VALUES (?, ?)",
                (race_id, json.dumps({"full_text": full_text})),
            )

        # Process ballot measure selections
        choice_count = 0
        county_vote_count = 0

        selection_tag = _tag(nsmap, "ContestSelection")
        for selection in contest.iter(selection_tag):
            # Determine Yes/No from the Selection text
            sel_text = self._text(selection, "Selection", nsmap)
            if sel_text is None:
                # Try BallotMeasureSelection type detection
                text_el = selection.find(_tag(nsmap, "Selection"), nsmap)
                if text_el is not None:
                    inner = text_el.find(_tag(nsmap, "Text"), nsmap)
                    if inner is not None and inner.text:
                        sel_text = inner.text.strip()
                    elif text_el.text:
                        sel_text = text_el.text.strip()

            if not sel_text:
                sel_text = "Unknown"

            # Normalize: capitalize first letter
            name = sel_text.strip().capitalize() if sel_text else "Unknown"
            # Map common values
            if name.lower() in ("yes", "for"):
                name = "Yes"
            elif name.lower() in ("no", "against"):
                name = "No"

            # Ballot order
            seq = self._text(selection, "SequenceOrder", nsmap)
            ballot_order = int(seq) if seq else None

            # Aggregate votes
            vote_total, county_votes = self._extract_votes(
                selection, nsmap, county_gpunit_to_code
            )

            # Choice key
            choice_key = generate_choice_key(race_key, name)

            conn.execute(
                "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                "name, party, ballot_order, color_hex, outcome, vote_total) "
                "VALUES (?, ?, ?, 'ballot_option', ?, NULL, ?, NULL, NULL, ?)",
                (choice_key, race_id, selection.get("ObjectId"), name,
                 ballot_order, vote_total),
            )
            choice_id = conn.execute(
                "SELECT id FROM choices WHERE choice_key = ?", (choice_key,)
            ).fetchone()["id"]
            choice_count += 1

            # County votes
            for cc, vtotal in county_votes.items():
                conn.execute(
                    "INSERT OR REPLACE INTO votes_county "
                    "(race_id, county_code, choice_id, vote_total) "
                    "VALUES (?, ?, ?, ?)",
                    (race_id, cc, choice_id, vtotal),
                )
                county_vote_count += 1

        return {"races": 1, "choices": choice_count, "votes_county": county_vote_count}

    # ------------------------------------------------------------------
    # Process RetentionContest
    # ------------------------------------------------------------------

    def _process_retention(
        self, conn, election_id, election_key, contest, nsmap, lookups,
        county_gpunit_to_code, seen_race_keys,
    ) -> dict:
        """
        Process a RetentionContest.  These are judicial retention votes
        (Yes/No for a specific candidate).
        """
        contest_name = self._text(contest, "Name", nsmap) or "Unknown Retention"

        # RetentionContest has a CandidateId for the judge
        candidate_id = self._text(contest, "CandidateId", nsmap)
        cand_info = lookups["candidates"].get(candidate_id, {}) if candidate_id else {}
        judge_name = cand_info.get("ballot_name", "")
        if judge_name and judge_name not in contest_name:
            contest_name = f"{contest_name} - {judge_name}"

        # Build race key
        race_key = generate_race_key(election_key, contest_name)
        race_key = self._unique_race_key(race_key, seen_race_keys)

        # Insert race (modeled as ballot measure)
        conn.execute(
            "INSERT INTO races (race_key, election_id, sos_race_id, title, office_category, "
            "office_name, district, county_code, num_to_elect, is_ballot_measure) "
            "VALUES (?, ?, ?, ?, 'judicial', ?, NULL, NULL, 1, 1)",
            (race_key, election_id, contest.get("ObjectId"), contest_name, contest_name),
        )
        race_id = conn.execute(
            "SELECT id FROM races WHERE race_key = ?", (race_key,)
        ).fetchone()["id"]

        # Process Yes/No selections
        choice_count = 0
        county_vote_count = 0

        selection_tag = _tag(nsmap, "ContestSelection")
        for selection in contest.iter(selection_tag):
            sel_text = self._text(selection, "Selection", nsmap)
            if not sel_text:
                text_el = selection.find(_tag(nsmap, "Selection"), nsmap)
                if text_el is not None:
                    inner = text_el.find(_tag(nsmap, "Text"), nsmap)
                    if inner is not None and inner.text:
                        sel_text = inner.text.strip()
                    elif text_el.text:
                        sel_text = text_el.text.strip()

            name = (sel_text or "Unknown").strip().capitalize()
            if name.lower() in ("yes", "for"):
                name = "Yes"
            elif name.lower() in ("no", "against"):
                name = "No"

            seq = self._text(selection, "SequenceOrder", nsmap)
            ballot_order = int(seq) if seq else None

            vote_total, county_votes = self._extract_votes(
                selection, nsmap, county_gpunit_to_code
            )

            choice_key = generate_choice_key(race_key, name)

            conn.execute(
                "INSERT INTO choices (choice_key, race_id, sos_choice_id, choice_type, "
                "name, party, ballot_order, color_hex, outcome, vote_total) "
                "VALUES (?, ?, ?, 'ballot_option', ?, NULL, ?, NULL, NULL, ?)",
                (choice_key, race_id, selection.get("ObjectId"), name,
                 ballot_order, vote_total),
            )
            choice_id = conn.execute(
                "SELECT id FROM choices WHERE choice_key = ?", (choice_key,)
            ).fetchone()["id"]
            choice_count += 1

            for cc, vtotal in county_votes.items():
                conn.execute(
                    "INSERT OR REPLACE INTO votes_county "
                    "(race_id, county_code, choice_id, vote_total) "
                    "VALUES (?, ?, ?, ?)",
                    (race_id, cc, choice_id, vtotal),
                )
                county_vote_count += 1

        return {"races": 1, "choices": choice_count, "votes_county": county_vote_count}

    # ------------------------------------------------------------------
    # Vote extraction
    # ------------------------------------------------------------------

    def _extract_votes(
        self, selection_el, nsmap: dict, county_gpunit_to_code: dict
    ) -> tuple[int, dict[str, int]]:
        """
        Extract vote counts from a ContestSelection element.

        The NIST XML nests VoteCounts inside the selection.  Each VoteCounts
        has a GpUnitId and Count.  We aggregate to county level.

        Returns (total_votes, {county_code: vote_count}).
        """
        total = 0
        county_votes: dict[str, int] = defaultdict(int)

        for vc in selection_el.iter(_tag(nsmap, "VoteCounts")):
            gpu_id = self._text(vc, "GpUnitId", nsmap) or ""
            count_text = self._text(vc, "Count", nsmap) or "0"
            try:
                count = int(float(count_text))
            except (ValueError, TypeError):
                count = 0

            # Determine vote type (total / election-day / absentee / etc.)
            vote_type_el = vc.find(_tag(nsmap, "Type"), nsmap)
            vote_type = vote_type_el.text.strip().lower() if vote_type_el is not None and vote_type_el.text else "total"

            # We aggregate "total" type votes.  If the feed only provides
            # breakdowns (election-day, absentee), we sum them all.
            # The state-level GpUnit gives the grand total; county GpUnits
            # give per-county.

            if gpu_id in county_gpunit_to_code:
                county_votes[county_gpunit_to_code[gpu_id]] += count
            # If the GpUnit is the state or we can't resolve it, still add to total
            total += count

        # If we got county-level data, compute total from counties
        # (to avoid double-counting state + county)
        if county_votes:
            total = sum(county_votes.values())

        return total, dict(county_votes)

    # ------------------------------------------------------------------
    # Clear existing election data (for re-import / UPSERT)
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
            r["id"]
            for r in conn.execute(
                "SELECT id FROM races WHERE election_id = ?", (election_id,)
            ).fetchall()
        ]
        if race_ids:
            ph = ",".join("?" * len(race_ids))
            choice_ids = [
                c["id"]
                for c in conn.execute(
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
            conn.execute("DELETE FROM races WHERE election_id = ?", (election_id,))

        conn.execute("DELETE FROM turnout WHERE election_id = ?", (election_id,))
        conn.execute("DELETE FROM elections WHERE id = ?", (election_id,))
        log.info(f"    Cleared existing data for {election_key}")

    # ------------------------------------------------------------------
    # Unique race key helper
    # ------------------------------------------------------------------

    def _unique_race_key(self, race_key: str, seen: set) -> str:
        """Ensure race_key is unique by appending a suffix if needed."""
        base = race_key
        suffix = 0
        while race_key in seen:
            suffix += 1
            race_key = f"{base}--{suffix}"
        seen.add(race_key)
        return race_key

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def _run_quality_checks(self, conn, run_id: int, election_id: int) -> bool:
        """Run post-import quality checks. Returns True if all pass."""
        all_passed = True

        # 1. county_totals_reconcile
        mismatches = conn.execute(
            """
            SELECT c.id, c.name, c.vote_total,
                   COALESCE(SUM(vc.vote_total), 0) as county_sum
            FROM choices c
            JOIN races r ON c.race_id = r.id
            LEFT JOIN votes_county vc ON vc.choice_id = c.id AND vc.race_id = r.id
            WHERE r.election_id = ?
            GROUP BY c.id
            HAVING c.vote_total != COALESCE(SUM(vc.vote_total), 0)
            """,
            (election_id,),
        ).fetchall()

        passed = len(mismatches) == 0
        details = {"mismatched_choices": len(mismatches)}
        if mismatches:
            details["examples"] = [
                {"choice": m["name"], "vote_total": m["vote_total"], "county_sum": m["county_sum"]}
                for m in mismatches[:5]
            ]
        self.log_quality_check(conn, run_id, "county_totals_reconcile", passed, details)
        if not passed:
            log.warning(f"    QC WARN county_totals_reconcile: {len(mismatches)} mismatches")
            all_passed = False

        # 2. no_negative_votes
        neg_county = conn.execute(
            """
            SELECT COUNT(*) FROM votes_county vc
            JOIN races r ON vc.race_id = r.id
            WHERE r.election_id = ? AND vc.vote_total < 0
            """,
            (election_id,),
        ).fetchone()[0]

        passed = neg_county == 0
        self.log_quality_check(
            conn, run_id, "no_negative_votes", passed, {"negative_county": neg_county}
        )
        if not passed:
            log.warning(f"    QC FAIL no_negative_votes: {neg_county} negative records")
            all_passed = False

        # 3. all_races_have_choices
        empty_races = conn.execute(
            """
            SELECT r.id, r.title FROM races r
            LEFT JOIN choices c ON c.race_id = r.id
            WHERE r.election_id = ?
            GROUP BY r.id
            HAVING COUNT(c.id) = 0
            """,
            (election_id,),
        ).fetchall()

        passed = len(empty_races) == 0
        details = {"empty_races": len(empty_races)}
        if empty_races:
            details["examples"] = [r["title"] for r in empty_races[:5]]
        self.log_quality_check(conn, run_id, "all_races_have_choices", passed, details)
        if not passed:
            log.warning(f"    QC WARN all_races_have_choices: {len(empty_races)} empty races")
            all_passed = False

        return all_passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_config(path: str = CONFIG_PATH) -> dict:
    """Load the Ohio YAML config."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Ohio live election results parser (NIST 1500-100 XML).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--once", action="store_true", help="Fetch once and exit"
    )
    group.add_argument(
        "--poll", action="store_true", help="Poll every 3 minutes until Ctrl-C"
    )
    parser.add_argument(
        "--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database"
    )
    parser.add_argument(
        "--config", default=CONFIG_PATH, help="Path to ohio.yaml config"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    scraper = OhioLiveScraper(args.db_path, config)

    if args.once:
        log.info("Ohio live scraper: single fetch")
        log.info(f"Database: {args.db_path}")
        log.info("=" * 60)
        try:
            result = scraper.fetch_live()
            if result.get("error"):
                log.error(f"  Error: {result['error']}")
                sys.exit(1)
            log.info("=" * 60)
            log.info("Done.")
        except requests.exceptions.HTTPError as e:
            log.error(f"HTTP error: {e}")
            log.info("The endpoint may not have active election data.")
            sys.exit(1)
        except etree.XMLSyntaxError as e:
            log.error(f"XML parse error: {e}")
            log.info("The endpoint returned invalid XML (may not have active election data).")
            sys.exit(1)
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            sys.exit(1)

    elif args.poll:
        interval = config.get("scraping", {}).get("poll_interval_seconds", 180)
        log.info(f"Ohio live scraper: polling every {interval}s (Ctrl-C to stop)")
        log.info(f"Database: {args.db_path}")
        log.info("=" * 60)

        # Graceful shutdown on Ctrl-C
        running = True

        def _signal_handler(sig, frame):
            nonlocal running
            log.info("Received shutdown signal, finishing current cycle...")
            running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        cycle = 0
        while running:
            cycle += 1
            log.info(f"--- Poll cycle {cycle} ---")
            try:
                result = scraper.fetch_live()
                if result.get("is_test"):
                    log.info("  (Test data -- no active election)")
                log.info(f"  Races: {result.get('races', 0)}, "
                         f"Choices: {result.get('choices', 0)}, "
                         f"County votes: {result.get('votes_county', 0)}")
            except requests.exceptions.HTTPError as e:
                log.warning(f"  HTTP error (will retry): {e}")
            except etree.XMLSyntaxError as e:
                log.warning(f"  XML parse error (will retry): {e}")
            except Exception as e:
                log.error(f"  Unexpected error (will retry): {e}")

            # Wait for next cycle
            if running:
                log.info(f"  Sleeping {interval}s until next poll...")
                for _ in range(interval):
                    if not running:
                        break
                    time.sleep(1)

        log.info("Polling stopped.")


if __name__ == "__main__":
    main()
