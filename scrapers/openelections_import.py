"""
OpenElections Historical Data Importer

Imports historical election results from the OpenElections GitHub repositories
for Indiana and Ohio into the national election tracker database.

Data Sources:
  - Indiana: https://github.com/openelections/openelections-data-in
    County-level CSVs: 2002-2024
    Precinct-level CSVs: 2012, 2014, 2016, 2018, 2020, 2024

  - Ohio: https://github.com/openelections/openelections-data-oh
    County-level CSVs: 2000-2020
    Precinct-level CSVs: 2006, 2010-2020

CSV schemas vary by state and year.  This importer uses flexible column
mapping to handle all known variants.

Usage:
    python scrapers/openelections_import.py --state IN             # All Indiana
    python scrapers/openelections_import.py --state OH             # All Ohio
    python scrapers/openelections_import.py --state IN --year 2020 # Single year
    python scrapers/openelections_import.py --all                  # Both states
    python scrapers/openelections_import.py --all --force          # Re-import all
"""

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scrapers"))

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

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# GitHub Configuration
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

REPOS = {
    "IN": "openelections/openelections-data-in",
    "OH": "openelections/openelections-data-oh",
}

# Years to scan per state
YEARS = {
    "IN": list(range(2002, 2025, 2)),  # Even years: 2002, 2004, ..., 2024
    "OH": [2000] + list(range(2002, 2021, 2)) + [2007],  # Even years + 2007 special
}

# Standard election dates by year (month-day). Used to build election_key.
# We derive the full date from the CSV filename: YYYYMMDD__state__type...
# These are fallbacks if we can't parse the date from the filename.
ELECTION_DATES = {}  # populated dynamically from filenames

# Rate limit delay between GitHub API calls (seconds)
API_DELAY = 1.0

# Rate limit delay between raw file downloads (seconds)
DOWNLOAD_DELAY = 0.5


# ---------------------------------------------------------------------------
# Office category mapping
# ---------------------------------------------------------------------------

OFFICE_CATEGORY_MAP = {
    # Federal
    "president": "presidential",
    "u.s. president": "presidential",
    "us president": "presidential",
    "governor/lieutenant governor": "presidential",  # OH 2006 uses this for presidential-style race
    # US Senate
    "u.s. senate": "us_senate",
    "us senate": "us_senate",
    "united states senator": "us_senate",
    "u.s. senator": "us_senate",
    # US House
    "u.s. house": "us_house",
    "us house": "us_house",
    "u.s. representative": "us_house",
    "united states representative": "us_house",
    # Governor
    "governor": "governor",
    "governor/lieutenant governor": "governor",
    # State executive
    "lieutenant governor": "lieutenant_governor",
    "attorney general": "attorney_general",
    "secretary of state": "state_office",
    "auditor of state": "state_office",
    "treasurer of state": "state_office",
    "state auditor": "state_office",
    "state treasurer": "state_office",
    "chief justice": "judicial",
    "justice of the supreme court": "judicial",
    "supreme court justice": "judicial",
    # State legislature
    "state senate": "state_senate",
    "state senator": "state_senate",
    "state house": "state_house",
    "state representative": "state_house",
    # Judicial
    "judge": "judicial",
    "court of appeals": "judicial",
    "supreme court": "judicial",
    # County
    "county commissioner": "county",
    "county council": "county",
    "county auditor": "county",
    "county clerk": "county",
    "county coroner": "county",
    "county engineer": "county",
    "county recorder": "county",
    "county sheriff": "county",
    "county surveyor": "county",
    "county treasurer": "county",
    "prosecuting attorney": "county",
    "prosecutor": "county",
    # Municipal
    "mayor": "municipal",
    "city council": "municipal",
    "town council": "municipal",
    "township trustee": "municipal",
    "township board": "municipal",
    # School
    "school board": "school_board",
    # Ballot measures
    "issue": "referendum",
    "amendment": "referendum",
    "public question": "referendum",
    "ballot measure": "referendum",
}


def classify_office(office_raw: str) -> str:
    """
    Map a raw office string to our normalized office_category.
    Uses prefix matching against OFFICE_CATEGORY_MAP.
    """
    if not office_raw:
        return "other"
    lower = office_raw.strip().lower()

    # Direct match
    if lower in OFFICE_CATEGORY_MAP:
        return OFFICE_CATEGORY_MAP[lower]

    # Prefix match (longest first)
    for prefix in sorted(OFFICE_CATEGORY_MAP.keys(), key=len, reverse=True):
        if lower.startswith(prefix):
            return OFFICE_CATEGORY_MAP[prefix]

    # Pattern-based heuristics
    if "president" in lower:
        return "presidential"
    if "senate" in lower and ("u.s." in lower or "us " in lower or "united states" in lower):
        return "us_senate"
    if ("house" in lower or "representative" in lower) and (
        "u.s." in lower or "us " in lower or "united states" in lower
    ):
        return "us_house"
    if "governor" in lower:
        return "governor"
    if "state sen" in lower:
        return "state_senate"
    if "state rep" in lower or "state house" in lower:
        return "state_house"
    if "judge" in lower or "justice" in lower or "court" in lower:
        return "judicial"
    if "sheriff" in lower or "commissioner" in lower or "county" in lower:
        return "county"
    if "council" in lower or "mayor" in lower or "township" in lower:
        return "municipal"
    if "school" in lower:
        return "school_board"
    if "issue" in lower or "amendment" in lower or "question" in lower or "levy" in lower:
        return "referendum"
    if lower in ("registered voters", "ballots cast", "voters"):
        return "_meta"  # skip these rows

    return "other"


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

# Pattern: YYYYMMDD__state__type[__party][__office][__district][__county]__level.csv
# Examples:
#   20241105__in__general__precinct.csv
#   20201103__oh__general__county.csv
#   20160315__oh__primary__democratic.csv
#   20161108__in__general__adams__precinct.csv
#   20060502__OH__primary.csv  (county-level, no level suffix)
FILENAME_RE = re.compile(
    r"^(\d{8})__(\w{2})__(\w+?)(?:__(?:precinct|county))?\.csv$",
    re.IGNORECASE,
)

# More lenient pattern that captures everything
FILENAME_FULL_RE = re.compile(
    r"^(\d{8})__(\w{2})__(.+)\.csv$",
    re.IGNORECASE,
)


def parse_filename(filename: str) -> dict | None:
    """
    Parse an OpenElections filename into its components.

    Returns dict with keys: date, state, election_type, level, party, county_filter
    or None if not a recognized format.
    """
    basename = os.path.basename(filename)

    # Skip non-election files (QC findings, parser scripts, etc.)
    lower_base = basename.lower()
    if any(skip in lower_base for skip in ("_qc_", "qc_findings", "parser", "crosswalk", ".py")):
        return None

    m = FILENAME_FULL_RE.match(basename)
    if not m:
        return None

    date_str = m.group(1)  # YYYYMMDD
    state = m.group(2).upper()
    remainder = m.group(3).lower()  # everything between state and .csv

    # Parse the date
    try:
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        iso_date = f"{year:04d}-{month:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None

    # Handle files with single-underscore variants (e.g., madison_precinct instead of madison__precinct)
    # Normalize: if the remainder contains a single _ adjacent to 'precinct' or 'county',
    # treat it as a double-underscore separator
    remainder = re.sub(r"(?<=[a-z])_precinct$", "__precinct", remainder)
    remainder = re.sub(r"(?<=[a-z])_county$", "__county", remainder)

    # Split remainder by double-underscore
    parts = remainder.split("__")
    # First part is always the election type
    election_type = parts[0]  # general, primary, special, etc.

    level = "county"  # default
    party = None
    county_filter = None

    remaining = parts[1:]

    # Check if last part is 'precinct' or 'county'
    if remaining and remaining[-1] in ("precinct", "county"):
        level = remaining[-1]
        remaining = remaining[:-1]

    # Check for party-specific files (OH primaries)
    if remaining and remaining[0] in ("democratic", "republican", "libertarian", "natural_law", "green"):
        party = remaining[0]
        remaining = remaining[1:]

    # Check for special election subtypes: special__general__office__district
    if election_type == "special" and remaining:
        # e.g., special__general__house__8  -> election_type = "special"
        # Keep election_type as "special"
        # Remaining parts describe the specific race (we'll handle in parsing)
        pass

    # Check for county-specific precinct files (IN 2016/2020/2024)
    # e.g., general__adams__precinct -> county_filter = 'adams', level = 'precinct'
    if remaining and len(remaining) == 1:
        # Could be a county name or office type
        candidate = remaining[0]
        # If it's a known office shorthand, skip. Otherwise treat as county.
        if candidate not in ("house", "senate", "president", "state_house",
                             "state_senate", "general"):
            county_filter = candidate

    return {
        "date_str": date_str,
        "iso_date": iso_date,
        "year": year,
        "state": state,
        "election_type": election_type,
        "level": level,
        "party": party,
        "county_filter": county_filter,
        "filename": basename,
    }


# ---------------------------------------------------------------------------
# CSV Column Mapping
# ---------------------------------------------------------------------------

# All known column names across years/states, mapped to canonical names
COLUMN_ALIASES = {
    # County
    "county": "county",
    # Precinct — various naming conventions across years
    "precinct": "precinct",
    "precinct name": "precinct",
    "precinct_name": "precinct",
    "precinct_code": "precinct_code",
    "precinct code": "precinct_code",
    # Office
    "office": "office",
    # District
    "district": "district",
    # Seats
    "seats": "seats",
    # Candidate
    "candidate": "candidate",
    # Party
    "party": "party",
    # Votes
    "votes": "votes",
    # Vote breakdowns
    "absentee": "absentee",
    "election_day": "election_day",
    "provisional": "provisional",
    "early_voting": "early_voting",
    # Ohio 2020 extra columns
    "region": "region",
    "media_market": "media_market",
}


def normalize_columns(headers: list[str]) -> dict[str, str]:
    """
    Map CSV column headers to canonical names.
    Returns {original_header: canonical_name} for recognized columns.
    """
    mapping = {}
    for h in headers:
        canonical = COLUMN_ALIASES.get(h.strip().lower())
        if canonical:
            mapping[h] = canonical
    return mapping


def extract_row(row: dict, col_map: dict[str, str]) -> dict:
    """
    Extract a row using the column mapping, returning a dict with canonical keys.
    """
    result = {}
    for orig, canonical in col_map.items():
        val = row.get(orig, "").strip() if row.get(orig) is not None else ""
        result[canonical] = val
    return result


# ---------------------------------------------------------------------------
# District extraction
# ---------------------------------------------------------------------------

def extract_district(office: str, district_col: str | None) -> str | None:
    """
    Extract a normalized district identifier.
    Checks the explicit district column first, then parses from the office name.

    Returns e.g., 'd09' or None.
    """
    # Check explicit district column
    if district_col and district_col.strip():
        d = district_col.strip()
        # It might be just a number
        try:
            num = int(d)
            return f"d{num:02d}"
        except ValueError:
            pass
        # Or "District 9" style
        m = re.search(r"(\d+)", d)
        if m:
            return f"d{int(m.group(1)):02d}"
        # Non-numeric district (e.g., "At Large")
        return d.lower().replace(" ", "-")

    # Parse from office name
    if office:
        m = re.search(r"District\s+(\d+)", office, re.IGNORECASE)
        if m:
            return f"d{int(m.group(1)):02d}"

    return None


# ---------------------------------------------------------------------------
# OpenElections Importer
# ---------------------------------------------------------------------------

class OpenElectionsImporter:
    """
    Imports historical election data from OpenElections GitHub repositories.
    """

    def __init__(self, db_path: str, force: bool = False):
        self.db_path = db_path
        self.force = force
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "NationalElectionTracker/1.0 (openelections-import)"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"

        # Use GitHub token if available (higher rate limits)
        gh_token = os.environ.get("GITHUB_TOKEN")
        if gh_token:
            self.session.headers["Authorization"] = f"token {gh_token}"
            log.info("Using GitHub token for API authentication")

        # County caches: state -> {name_lower: code}
        self._county_caches: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _build_county_cache(self, conn: sqlite3.Connection, state: str) -> dict[str, str]:
        """Build case-insensitive county name -> code map."""
        if state in self._county_caches:
            return self._county_caches[state]

        rows = conn.execute(
            "SELECT code, name, slug FROM counties WHERE state = ?", (state,)
        ).fetchall()
        cache = {}
        for row in rows:
            code, name, slug = row["code"], row["name"], row["slug"]
            cache[name.lower()] = code
            cache[slug] = code
            # Handle "St. Joseph" -> "st joseph" / "st. joseph"
            if "." in name:
                cache[name.replace(".", "").lower()] = code
            # Handle "De Soto" -> "desoto" and "de soto"
            if " " in name:
                cache[name.replace(" ", "").lower()] = code
            # Handle "Van Wert" -> "van wert" / "vanwert"
            cache[name.lower().replace(" ", "")] = code
        self._county_caches[state] = cache
        return cache

    def county_code(self, conn: sqlite3.Connection, state: str, county_name: str) -> str | None:
        """Look up county code by name. Returns None if unmatched."""
        if not county_name:
            return None
        cache = self._build_county_cache(conn, state)
        name = county_name.strip().lower()
        return (
            cache.get(name)
            or cache.get(name.replace(".", ""))
            or cache.get(name.replace(" ", ""))
            or cache.get(name.replace(".", "").replace(" ", ""))
        )

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def create_import_run(self, conn: sqlite3.Connection, state: str, election_key: str | None = None) -> int:
        c = conn.execute(
            "INSERT INTO import_runs (state, election_key, started_at, status, scraper_version) "
            "VALUES (?, ?, ?, 'running', ?)",
            (state, election_key, datetime.now(timezone.utc).isoformat(), f"openelections-import/{VERSION}"),
        )
        return c.lastrowid

    def log_source_file(self, conn: sqlite3.Connection, run_id: int, url: str, data: bytes, filename: str) -> None:
        sha = hashlib.sha256(data).hexdigest()
        conn.execute(
            "INSERT INTO source_files (import_run_id, url, filename, sha256, size_bytes, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, url, filename, sha, len(data), datetime.now(timezone.utc).isoformat()),
        )

    def finish_import_run(
        self, conn: sqlite3.Connection, run_id: int, status: str,
        record_counts: dict | None = None, error: str | None = None
    ) -> None:
        conn.execute(
            "UPDATE import_runs SET finished_at=?, status=?, record_counts=?, error_message=? WHERE id=?",
            (
                datetime.now(timezone.utc).isoformat(),
                status,
                json.dumps(record_counts) if record_counts else None,
                error,
                run_id,
            ),
        )

    def is_election_imported(self, conn: sqlite3.Connection, election_key: str) -> bool:
        row = conn.execute(
            "SELECT id FROM import_runs WHERE election_key = ? AND status IN ('success', 'success_with_warnings')",
            (election_key,),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Clear existing election data (for re-import)
    # ------------------------------------------------------------------

    def _clear_election(self, conn: sqlite3.Connection, election_key: str) -> None:
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
    # GitHub API helpers
    # ------------------------------------------------------------------

    def _api_get(self, url: str) -> requests.Response:
        """GET with rate-limit delay and error handling."""
        time.sleep(API_DELAY)
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 403:
            # Rate limited
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(int(reset) - int(time.time()), 1)
                log.warning(f"GitHub rate limit hit. Waiting {wait}s...")
                time.sleep(wait + 1)
                resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp

    def _download_csv(self, repo: str, path: str) -> bytes:
        """Download a raw CSV file from GitHub."""
        url = f"{RAW_BASE}/{repo}/master/{path}"
        time.sleep(DOWNLOAD_DELAY)
        resp = self.session.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content

    def _list_directory(self, repo: str, path: str) -> list[dict]:
        """List contents of a GitHub directory."""
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
        resp = self._api_get(url)
        items = resp.json()
        if not isinstance(items, list):
            return []
        return items

    # ------------------------------------------------------------------
    # Discover CSV files for a state/year
    # ------------------------------------------------------------------

    def discover_files(self, state: str, year: int) -> list[dict]:
        """
        Discover all CSV files for a state and year from GitHub.
        Returns list of parsed file info dicts.
        """
        repo = REPOS[state]
        files = []

        try:
            items = self._list_directory(repo, str(year))
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                log.info(f"  No directory for {state}/{year}")
                return []
            raise

        for item in items:
            name = item["name"]
            item_type = item.get("type", "file")

            if item_type == "dir":
                # Recurse into subdirectories (e.g., 2024/counties/)
                try:
                    sub_items = self._list_directory(repo, f"{year}/{name}")
                    for sub in sub_items:
                        if sub["name"].lower().endswith(".csv"):
                            info = parse_filename(sub["name"])
                            if info:
                                info["path"] = f"{year}/{name}/{sub['name']}"
                                info["size"] = sub.get("size", 0)
                                files.append(info)
                except requests.HTTPError:
                    log.warning(f"  Could not list {year}/{name}/")
                continue

            if not name.lower().endswith(".csv"):
                continue

            info = parse_filename(name)
            if info:
                info["path"] = f"{year}/{name}"
                info["size"] = item.get("size", 0)
                files.append(info)

        return files

    # ------------------------------------------------------------------
    # Group files into elections
    # ------------------------------------------------------------------

    def group_files_into_elections(self, files: list[dict], state: str) -> dict[str, list[dict]]:
        """
        Group discovered files by election_key.
        Returns {election_key: [file_info, ...]}.
        """
        elections: dict[str, list[dict]] = defaultdict(list)

        for f in files:
            # Build election key from date + type
            # For party-specific primaries (OH), group under the same election
            etype = f["election_type"]
            if etype == "special":
                etype = "special"  # keep as-is
            election_key = generate_election_key(state, f["iso_date"], etype)
            elections[election_key].append(f)

        return dict(elections)

    # ------------------------------------------------------------------
    # Parse CSV data
    # ------------------------------------------------------------------

    def _parse_csv(self, data: bytes, file_info: dict) -> list[dict]:
        """
        Parse a CSV file into a list of normalized row dicts.
        Handles encoding issues, various column layouts, and mixed line endings.
        """
        # Try UTF-8 first, fall back to latin-1
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")

        # Normalize line endings: replace \r\n and \r with \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove any null bytes
        text = text.replace("\x00", "")

        # Parse CSV
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []

        col_map = normalize_columns(list(reader.fieldnames))
        if not col_map:
            log.warning(f"    No recognized columns in {file_info['filename']}: {reader.fieldnames}")
            return []

        rows = []
        for raw_row in reader:
            row = extract_row(raw_row, col_map)

            # Inject metadata from file info
            row["_level"] = file_info["level"]
            row["_party_file"] = file_info.get("party")  # for OH party-specific primaries
            row["_county_filter"] = file_info.get("county_filter")

            # Skip meta rows (Registered Voters, Ballots Cast)
            office = row.get("office", "")
            if classify_office(office) == "_meta":
                continue

            # Skip rows with no candidate
            if not row.get("candidate"):
                continue

            # Parse votes to int
            votes_str = row.get("votes", "0")
            try:
                row["votes_int"] = int(votes_str.replace(",", "")) if votes_str else 0
            except ValueError:
                row["votes_int"] = 0

            # If party comes from the filename (OH party-specific primary files),
            # and the row has no party column, inject it
            if row["_party_file"] and not row.get("party"):
                party_map = {
                    "democratic": "D", "republican": "R", "libertarian": "L",
                    "green": "G", "natural_law": "NL",
                }
                row["party"] = party_map.get(row["_party_file"], row["_party_file"][0].upper())

            rows.append(row)

        return rows

    # ------------------------------------------------------------------
    # Import one election
    # ------------------------------------------------------------------

    def import_election(
        self, state: str, election_key: str, files: list[dict]
    ) -> dict:
        """
        Import all files for a single election into the database.
        Returns summary dict.
        """
        conn = self.get_db()
        try:
            # Check idempotency
            if not self.force and self.is_election_imported(conn, election_key):
                log.info(f"  {election_key}: already imported, skipping (use --force to re-import)")
                return {"skipped": True, "election_key": election_key}

            # Check for overlap with existing Civix data (IN 2019+)
            if state == "IN":
                existing = conn.execute(
                    "SELECT election_key FROM elections WHERE election_key = ?",
                    (election_key,),
                ).fetchone()
                if existing and not self.force:
                    # Check if it came from the Civix scraper
                    civix_run = conn.execute(
                        "SELECT id FROM import_runs WHERE election_key = ? AND scraper_version NOT LIKE 'openelections%'",
                        (election_key,),
                    ).fetchone()
                    if civix_run:
                        log.info(f"  {election_key}: already has Civix ENR data, skipping OpenElections")
                        return {"skipped": True, "election_key": election_key, "reason": "civix_precedence"}

            run_id = self.create_import_run(conn, state, election_key)
            conn.commit()

            try:
                # Separate files by level
                county_files = [f for f in files if f["level"] == "county"]
                precinct_files = [f for f in files if f["level"] == "precinct"]

                # Download and parse all files
                all_county_rows = []
                all_precinct_rows = []
                repo = REPOS[state]

                for f in county_files:
                    log.info(f"    Downloading {f['path']} ({f.get('size', '?')} bytes)")
                    data = self._download_csv(repo, f["path"])
                    self.log_source_file(conn, run_id, f"{RAW_BASE}/{repo}/master/{f['path']}", data, f["filename"])
                    rows = self._parse_csv(data, f)
                    log.info(f"      Parsed {len(rows):,} data rows")
                    all_county_rows.extend(rows)

                for f in precinct_files:
                    log.info(f"    Downloading {f['path']} ({f.get('size', '?')} bytes)")
                    data = self._download_csv(repo, f["path"])
                    self.log_source_file(conn, run_id, f"{RAW_BASE}/{repo}/master/{f['path']}", data, f["filename"])
                    rows = self._parse_csv(data, f)
                    log.info(f"      Parsed {len(rows):,} data rows")
                    all_precinct_rows.extend(rows)

                conn.commit()

                if not all_county_rows and not all_precinct_rows:
                    log.warning(f"  {election_key}: no data rows parsed from any file")
                    self.finish_import_run(conn, run_id, "failed", error="No data rows parsed")
                    conn.commit()
                    return {"error": "no_data", "election_key": election_key}

                # Clear existing data if re-importing
                self._clear_election(conn, election_key)

                # Parse election metadata from key
                # election_key format: STATE-YYYY-MM-DD-type
                parts = election_key.split("-")
                e_state = parts[0]
                e_date = "-".join(parts[1:4])
                e_type = parts[4] if len(parts) > 4 else parts[-1]

                # Create election record
                conn.execute(
                    "INSERT INTO elections (election_key, state, date, type, is_official) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (election_key, state, e_date, e_type),
                )
                election_id = conn.execute(
                    "SELECT id FROM elections WHERE election_key = ?", (election_key,)
                ).fetchone()["id"]

                # Process rows into races, choices, votes
                counts = self._process_rows(
                    conn, state, election_id, election_key,
                    all_county_rows, all_precinct_rows,
                )

                # Finish
                self.finish_import_run(conn, run_id, "success", record_counts=counts)
                conn.commit()

                log.info(
                    f"  {election_key}: {counts['races']} races, "
                    f"{counts['choices']} choices, "
                    f"{counts['votes_county']} county votes, "
                    f"{counts['votes_precinct']} precinct votes"
                )
                return {"election_key": election_key, **counts}

            except Exception as e:
                self.finish_import_run(conn, run_id, "failed", error=str(e))
                conn.commit()
                raise

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Process parsed rows into DB records
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_candidate_name(name: str) -> str:
        """
        Normalize a candidate name for matching between county/precinct files.
        Handles "Last, First" vs "First Last" formats.
        Returns a lowercase, punctuation-stripped canonical form.
        """
        name = name.strip().lower()
        # Remove punctuation except spaces/commas
        name = re.sub(r"[^\w\s,]", "", name)
        # If "Last, First Middle" -> "first middle last"
        if "," in name:
            parts = [p.strip() for p in name.split(",", 1)]
            name = f"{parts[1]} {parts[0]}".strip()
        # Collapse whitespace
        name = re.sub(r"\s+", " ", name)
        return name

    def _process_rows(
        self,
        conn: sqlite3.Connection,
        state: str,
        election_id: int,
        election_key: str,
        county_rows: list[dict],
        precinct_rows: list[dict],
    ) -> dict:
        """
        Process parsed CSV rows into races, choices, and vote records.

        Strategy:
        - If county-level data exists for a race, use it as authoritative for
          race/choice creation and vote totals.
        - Precinct data adds granular vote records, matched to existing choices
          by normalized candidate name + party.
        - If only precinct data exists (no county file), use it for everything.
        """
        have_county = len(county_rows) > 0
        have_precinct = len(precinct_rows) > 0

        # Choose primary data source for race/choice creation
        if have_county:
            primary_rows = county_rows
        else:
            primary_rows = precinct_rows

        # ---------- Group primary rows by race ----------
        race_groups: dict[tuple, list[dict]] = defaultdict(list)
        for row in primary_rows:
            office = row.get("office", "Unknown").strip()
            district = extract_district(office, row.get("district"))
            category = classify_office(office)
            if category == "_meta":
                continue
            race_groups[(office, district)].append(row)

        # ---------- Group precinct rows by race (for matching later) ----------
        precinct_race_groups: dict[tuple, list[dict]] = defaultdict(list)
        if have_precinct:
            for row in precinct_rows:
                office = row.get("office", "Unknown").strip()
                district = extract_district(office, row.get("district"))
                category = classify_office(office)
                if category == "_meta":
                    continue
                precinct_race_groups[(office, district)].append(row)

        # ---------- Create races, choices, votes ----------
        race_count = 0
        choice_count = 0
        county_vote_count = 0
        precinct_vote_count = 0
        seen_race_keys = set()

        for (office, district), rows in race_groups.items():
            category = classify_office(office)
            if category == "_meta":
                continue

            # Generate race key
            race_key = generate_race_key(election_key, office, district)
            base_key = race_key
            suffix = 0
            while race_key in seen_race_keys:
                suffix += 1
                race_key = f"{base_key}--{suffix}"
            seen_race_keys.add(race_key)

            # Determine num_to_elect from seats column
            num_seats = 1
            for r in rows:
                seats_str = r.get("seats", "")
                if seats_str:
                    try:
                        num_seats = int(seats_str)
                        break
                    except ValueError:
                        pass

            is_ballot = 1 if category == "referendum" else 0

            # Insert race
            conn.execute(
                "INSERT INTO races (race_key, election_id, title, office_category, "
                "office_name, district, num_to_elect, is_ballot_measure) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (race_key, election_id, office, category, office, district, num_seats, is_ballot),
            )
            race_id = conn.execute(
                "SELECT id FROM races WHERE race_key = ?", (race_key,)
            ).fetchone()["id"]
            race_count += 1

            # ---------- Group primary rows by candidate ----------
            candidate_groups: dict[tuple, list[dict]] = defaultdict(list)
            for row in rows:
                name = row.get("candidate", "Unknown").strip()
                party = row.get("party", "").strip() or None
                candidate_groups[(name, party)].append(row)

            seen_choice_keys = set()

            # Build a lookup for matching precinct rows to choices:
            # normalized_name + party -> choice_id
            choice_lookup: dict[tuple, int] = {}

            for (name, party), cand_rows in candidate_groups.items():
                choice_key = generate_choice_key(race_key, name, party)
                base_ck = choice_key
                ck_suffix = 0
                while choice_key in seen_choice_keys:
                    ck_suffix += 1
                    choice_key = f"{base_ck}--{ck_suffix}"
                seen_choice_keys.add(choice_key)

                choice_type = "ballot_option" if is_ballot else "candidate"

                # Compute total votes
                if have_county:
                    vote_total = sum(r["votes_int"] for r in cand_rows)
                else:
                    vote_total = sum(r["votes_int"] for r in cand_rows)

                # Insert choice
                conn.execute(
                    "INSERT INTO choices (choice_key, race_id, choice_type, "
                    "name, party, vote_total) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (choice_key, race_id, choice_type, name, party, vote_total),
                )
                choice_id = conn.execute(
                    "SELECT id FROM choices WHERE choice_key = ?", (choice_key,)
                ).fetchone()["id"]
                choice_count += 1

                # Register in lookup for precinct matching
                norm_name = self._normalize_candidate_name(name)
                norm_party = (party or "").strip().upper()
                choice_lookup[(norm_name, norm_party)] = choice_id
                # Also register without party for fallback matching
                if (norm_name, "") not in choice_lookup:
                    choice_lookup[(norm_name, "")] = choice_id

                # ---------- County-level votes ----------
                if have_county:
                    # Primary rows are county rows
                    county_totals: dict[str, int] = defaultdict(int)
                    for row in cand_rows:
                        county_name = row.get("county", "")
                        cc = self.county_code(conn, state, county_name)
                        if cc:
                            county_totals[cc] += row["votes_int"]

                    for cc, vtotal in county_totals.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO votes_county "
                            "(race_id, county_code, choice_id, vote_total) "
                            "VALUES (?, ?, ?, ?)",
                            (race_id, cc, choice_id, vtotal),
                        )
                        county_vote_count += 1

                else:
                    # Primary rows are precinct rows — aggregate to county level
                    county_totals: dict[str, int] = defaultdict(int)
                    for row in cand_rows:
                        county_name = row.get("county", "")
                        if not county_name and row.get("_county_filter"):
                            county_name = row["_county_filter"]
                        cc = self.county_code(conn, state, county_name)
                        if cc:
                            county_totals[cc] += row["votes_int"]

                    for cc, vtotal in county_totals.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO votes_county "
                            "(race_id, county_code, choice_id, vote_total) "
                            "VALUES (?, ?, ?, ?)",
                            (race_id, cc, choice_id, vtotal),
                        )
                        county_vote_count += 1

                    # Insert precinct votes directly (primary is precinct data)
                    for row in cand_rows:
                        county_name = row.get("county", "")
                        if not county_name and row.get("_county_filter"):
                            county_name = row["_county_filter"]
                        cc = self.county_code(conn, state, county_name)
                        if not cc:
                            continue
                        precinct = row.get("precinct", "")
                        if not precinct:
                            continue
                        conn.execute(
                            "INSERT OR REPLACE INTO votes_precinct "
                            "(race_id, county_code, precinct_id, choice_id, vote_total) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (race_id, cc, precinct, choice_id, row["votes_int"]),
                        )
                        precinct_vote_count += 1

            # ---------- Match precinct data to existing choices (when county is primary) ----------
            if have_county and have_precinct and (office, district) in precinct_race_groups:
                prec_rows = precinct_race_groups[(office, district)]
                unmatched = 0
                for row in prec_rows:
                    pname = row.get("candidate", "").strip()
                    pparty = (row.get("party", "") or "").strip().upper()
                    norm_pname = self._normalize_candidate_name(pname)

                    # Try exact match (name + party)
                    cid = choice_lookup.get((norm_pname, pparty))
                    if cid is None:
                        # Try name-only match
                        cid = choice_lookup.get((norm_pname, ""))
                    if cid is None:
                        # Fallback: try matching by party only if there's exactly one
                        # candidate with that party in this race
                        party_matches = [
                            v for (n, p), v in choice_lookup.items()
                            if p == pparty and p != ""
                        ]
                        if len(party_matches) == 1:
                            cid = party_matches[0]
                    if cid is None:
                        unmatched += 1
                        continue

                    county_name = row.get("county", "")
                    if not county_name and row.get("_county_filter"):
                        county_name = row["_county_filter"]
                    cc = self.county_code(conn, state, county_name)
                    if not cc:
                        continue
                    precinct = row.get("precinct", "")
                    if not precinct:
                        continue

                    conn.execute(
                        "INSERT OR REPLACE INTO votes_precinct "
                        "(race_id, county_code, precinct_id, choice_id, vote_total) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (race_id, cc, precinct, cid, row["votes_int"]),
                    )
                    precinct_vote_count += 1

                if unmatched > 0:
                    log.debug(
                        f"    {office}: {unmatched} precinct rows couldn't be matched to county choices"
                    )

        # ---------- Handle precinct-only races not in county data ----------
        if have_county and have_precinct:
            for (office, district), prec_rows in precinct_race_groups.items():
                if (office, district) in race_groups:
                    continue  # already handled above

                category = classify_office(office)
                if category == "_meta":
                    continue

                # This race only exists in precinct data
                race_key = generate_race_key(election_key, office, district)
                base_key = race_key
                suffix = 0
                while race_key in seen_race_keys:
                    suffix += 1
                    race_key = f"{base_key}--{suffix}"
                seen_race_keys.add(race_key)

                num_seats = 1
                for r in prec_rows:
                    seats_str = r.get("seats", "")
                    if seats_str:
                        try:
                            num_seats = int(seats_str)
                            break
                        except ValueError:
                            pass

                is_ballot = 1 if category == "referendum" else 0

                conn.execute(
                    "INSERT INTO races (race_key, election_id, title, office_category, "
                    "office_name, district, num_to_elect, is_ballot_measure) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (race_key, election_id, office, category, office, district, num_seats, is_ballot),
                )
                race_id = conn.execute(
                    "SELECT id FROM races WHERE race_key = ?", (race_key,)
                ).fetchone()["id"]
                race_count += 1

                # Group by candidate
                cand_groups: dict[tuple, list[dict]] = defaultdict(list)
                for row in prec_rows:
                    name = row.get("candidate", "Unknown").strip()
                    party = row.get("party", "").strip() or None
                    cand_groups[(name, party)].append(row)

                seen_ck = set()
                for (name, party), cand_rows in cand_groups.items():
                    ck = generate_choice_key(race_key, name, party)
                    base_ck = ck
                    ck_suf = 0
                    while ck in seen_ck:
                        ck_suf += 1
                        ck = f"{base_ck}--{ck_suf}"
                    seen_ck.add(ck)

                    vote_total = sum(r["votes_int"] for r in cand_rows)
                    choice_type = "ballot_option" if is_ballot else "candidate"

                    conn.execute(
                        "INSERT INTO choices (choice_key, race_id, choice_type, "
                        "name, party, vote_total) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (ck, race_id, choice_type, name, party, vote_total),
                    )
                    cid = conn.execute(
                        "SELECT id FROM choices WHERE choice_key = ?", (ck,)
                    ).fetchone()["id"]
                    choice_count += 1

                    # Aggregate to county + insert precinct
                    county_totals: dict[str, int] = defaultdict(int)
                    for row in cand_rows:
                        county_name = row.get("county", "")
                        if not county_name and row.get("_county_filter"):
                            county_name = row["_county_filter"]
                        cc = self.county_code(conn, state, county_name)
                        if cc:
                            county_totals[cc] += row["votes_int"]
                        precinct = row.get("precinct", "")
                        if cc and precinct:
                            conn.execute(
                                "INSERT OR REPLACE INTO votes_precinct "
                                "(race_id, county_code, precinct_id, choice_id, vote_total) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (race_id, cc, precinct, cid, row["votes_int"]),
                            )
                            precinct_vote_count += 1

                    for cc, vtotal in county_totals.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO votes_county "
                            "(race_id, county_code, choice_id, vote_total) "
                            "VALUES (?, ?, ?, ?)",
                            (race_id, cc, cid, vtotal),
                        )
                        county_vote_count += 1

        return {
            "races": race_count,
            "choices": choice_count,
            "votes_county": county_vote_count,
            "votes_precinct": precinct_vote_count,
        }

    # ------------------------------------------------------------------
    # Import all elections for a state/year
    # ------------------------------------------------------------------

    def import_state_year(self, state: str, year: int) -> list[dict]:
        """Import all elections for a state and year."""
        log.info(f"Discovering {state} {year} files...")
        files = self.discover_files(state, year)
        if not files:
            log.info(f"  No CSV files found for {state} {year}")
            return []

        log.info(f"  Found {len(files)} CSV files")

        # Group into elections
        elections = self.group_files_into_elections(files, state)
        log.info(f"  {len(elections)} election(s) identified")

        results = []
        for election_key, election_files in sorted(elections.items()):
            level_summary = defaultdict(int)
            for f in election_files:
                level_summary[f["level"]] += 1
            log.info(
                f"  Importing {election_key} "
                f"({sum(level_summary.values())} files: "
                f"{', '.join(f'{v} {k}' for k, v in level_summary.items())})"
            )

            try:
                result = self.import_election(state, election_key, election_files)
                results.append(result)
            except Exception as e:
                log.error(f"  FAILED {election_key}: {e}")
                results.append({"error": str(e), "election_key": election_key})

        return results

    def import_state(self, state: str, year: int | None = None) -> list[dict]:
        """Import all data for a state (or a specific year)."""
        if year:
            return self.import_state_year(state, year)

        results = []
        years = YEARS.get(state, [])
        for y in sorted(years):
            year_results = self.import_state_year(state, y)
            results.extend(year_results)
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import historical election data from OpenElections GitHub repos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --state IN                  Import all Indiana data
  %(prog)s --state OH                  Import all Ohio data
  %(prog)s --state IN --year 2020      Single year
  %(prog)s --all                       Both states
  %(prog)s --all --force               Re-import everything
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--state",
        choices=["IN", "OH"],
        help="Import data for a single state",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Import data for all supported states (IN + OH)",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Import only a specific election year",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-import even if election already exists",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Only list available files (do not import)",
    )
    args = parser.parse_args()

    importer = OpenElectionsImporter(args.db_path, force=args.force)

    if args.all:
        states = ["IN", "OH"]
    else:
        states = [args.state]

    # List-only mode
    if args.list_files:
        for state in states:
            years = [args.year] if args.year else YEARS.get(state, [])
            for year in sorted(years):
                files = importer.discover_files(state, year)
                elections = importer.group_files_into_elections(files, state)
                for ek, efs in sorted(elections.items()):
                    print(f"\n{ek}:")
                    for f in efs:
                        print(f"  {f['level']:8s}  {f['path']}")
        return

    # Import mode
    log.info(f"OpenElections Importer v{VERSION}")
    log.info(f"Database: {args.db_path}")
    log.info(f"States: {', '.join(states)}")
    if args.year:
        log.info(f"Year: {args.year}")
    if args.force:
        log.info("Force mode: will re-import existing elections")
    log.info("=" * 60)

    all_results = []
    all_errors = []

    for state in states:
        log.info(f"\n{'='*60}")
        log.info(f"  {state}")
        log.info(f"{'='*60}")

        results = importer.import_state(state, year=args.year)
        for r in results:
            if r.get("error"):
                all_errors.append((r["election_key"], r["error"]))
        all_results.extend(results)

    # Summary
    log.info("\n" + "=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)

    imported = [r for r in all_results if not r.get("skipped") and not r.get("error")]
    skipped = [r for r in all_results if r.get("skipped")]

    total_races = sum(r.get("races", 0) for r in imported)
    total_choices = sum(r.get("choices", 0) for r in imported)
    total_county = sum(r.get("votes_county", 0) for r in imported)
    total_precinct = sum(r.get("votes_precinct", 0) for r in imported)

    log.info(f"  Elections imported:  {len(imported)}")
    log.info(f"  Elections skipped:   {len(skipped)}")
    log.info(f"  Errors:              {len(all_errors)}")
    log.info(f"  Total races:         {total_races:,}")
    log.info(f"  Total choices:       {total_choices:,}")
    log.info(f"  Total county votes:  {total_county:,}")
    log.info(f"  Total precinct votes:{total_precinct:,}")

    if all_errors:
        log.info("\n  Failed elections:")
        for ek, err in all_errors:
            log.info(f"    - {ek}: {err}")

    if all_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
