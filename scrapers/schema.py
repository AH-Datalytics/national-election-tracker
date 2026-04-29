"""
National Election Tracker — Database Schema

Creates all tables, indexes, and seed data for the national election tracker.
Single SQLite database with `state` as a first-class dimension.

Usage:
    python scrapers/schema.py                           # default: data/elections.db
    python scrapers/schema.py --db-path /some/other.db  # custom path
"""

import argparse
import os
import re
import sqlite3
import unicodedata


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.environ.get(
    "ELECTIONS_DB_PATH",
    os.path.join(REPO_ROOT, "data", "elections.db"),
)


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def generate_election_key(state: str, date: str, election_type: str) -> str:
    """
    Deterministic election key.
    E.g., generate_election_key('IN', '2024-11-05', 'general') -> 'IN-2024-11-05-general'
    """
    return f"{state.upper()}-{date}-{election_type.lower()}"


def generate_race_key(
    election_key: str,
    office: str,
    district: str | None = None,
    county: str | None = None,
) -> str:
    """
    Deterministic race key from components.
    E.g., 'IN-2024-11-05-general--us-senate'
          'IN-2024-11-05-general--us-house--d09'
          'IN-2024-11-05-general--county-sheriff--allen'
    """
    parts = [election_key, _slugify(office)]
    if district:
        parts.append(_slugify(district))
    if county:
        parts.append(_slugify(county))
    return "--".join(parts)


def generate_choice_key(
    race_key: str, name: str, party: str | None = None
) -> str:
    """
    Deterministic choice key.
    E.g., 'IN-2024-11-05-general--us-senate--jim-banks--rep'
    """
    parts = [race_key, _slugify(name)]
    if party:
        parts.append(_slugify(party))
    return "--".join(parts)


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- ==========================================================================
-- Dimension tables
-- ==========================================================================

CREATE TABLE IF NOT EXISTS states (
    code            TEXT PRIMARY KEY,          -- 2-letter: LA, IN, OH
    name            TEXT NOT NULL,
    fips            TEXT,
    county_label    TEXT NOT NULL,             -- parish / county / borough
    sos_base_url    TEXT,
    scraper_type    TEXT
);

CREATE TABLE IF NOT EXISTS counties (
    state           TEXT NOT NULL REFERENCES states(code),
    code            TEXT NOT NULL,             -- state-specific code
    name            TEXT NOT NULL,
    fips            TEXT,
    slug            TEXT NOT NULL,
    PRIMARY KEY (state, code)
);

-- ==========================================================================
-- Core election tables
-- ==========================================================================

CREATE TABLE IF NOT EXISTS elections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    election_key    TEXT NOT NULL UNIQUE,      -- e.g. IN-2024-11-05-general
    state           TEXT NOT NULL REFERENCES states(code),
    date            TEXT NOT NULL,             -- YYYY-MM-DD
    type            TEXT NOT NULL,             -- primary / general / runoff / special
    is_official     INTEGER NOT NULL DEFAULT 0,
    sos_election_id TEXT,
    UNIQUE(state, date, sos_election_id)
);

CREATE TABLE IF NOT EXISTS races (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_key        TEXT NOT NULL UNIQUE,
    election_id     INTEGER NOT NULL REFERENCES elections(id),
    sos_race_id     TEXT,
    title           TEXT NOT NULL,
    office_category TEXT NOT NULL,             -- us_senate, us_house, governor, etc.
    office_name     TEXT,                      -- raw from source
    district        TEXT,
    county_code     TEXT,                      -- null for statewide
    num_to_elect    INTEGER NOT NULL DEFAULT 1,
    is_ballot_measure INTEGER NOT NULL DEFAULT 0,
    UNIQUE(election_id, sos_race_id)
);

CREATE TABLE IF NOT EXISTS choices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    choice_key      TEXT NOT NULL UNIQUE,
    race_id         INTEGER NOT NULL REFERENCES races(id),
    sos_choice_id   TEXT,
    choice_type     TEXT NOT NULL,             -- 'candidate' or 'ballot_option'
    name            TEXT NOT NULL,
    party           TEXT,
    ballot_order    INTEGER,
    color_hex       TEXT,
    outcome         TEXT,
    vote_total      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(race_id, sos_choice_id)
);

-- ==========================================================================
-- Vote detail tables
-- ==========================================================================

CREATE TABLE IF NOT EXISTS votes_county (
    race_id         INTEGER NOT NULL REFERENCES races(id),
    county_code     TEXT NOT NULL,
    choice_id       INTEGER NOT NULL REFERENCES choices(id),
    vote_total      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (race_id, county_code, choice_id)
);

CREATE TABLE IF NOT EXISTS votes_precinct (
    race_id         INTEGER NOT NULL REFERENCES races(id),
    county_code     TEXT NOT NULL,
    precinct_id     TEXT NOT NULL,
    choice_id       INTEGER NOT NULL REFERENCES choices(id),
    vote_total      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (race_id, county_code, precinct_id, choice_id)
);

CREATE TABLE IF NOT EXISTS early_votes (
    race_id         INTEGER NOT NULL REFERENCES races(id),
    county_code     TEXT NOT NULL,
    choice_id       INTEGER NOT NULL REFERENCES choices(id),
    vote_total      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (race_id, county_code, choice_id)
);

-- ==========================================================================
-- Reporting & turnout
-- ==========================================================================

CREATE TABLE IF NOT EXISTS race_reporting (
    race_id             INTEGER NOT NULL REFERENCES races(id),
    county_code         TEXT,                  -- null for statewide aggregate
    precincts_reporting INTEGER NOT NULL DEFAULT 0,
    precincts_expected  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (race_id, county_code)
);

CREATE TABLE IF NOT EXISTS turnout (
    election_id     INTEGER NOT NULL REFERENCES elections(id),
    county_code     TEXT NOT NULL,
    qualified_voters INTEGER NOT NULL DEFAULT 0,
    voters_voted    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (election_id, county_code)
);

-- ==========================================================================
-- Extensibility
-- ==========================================================================

CREATE TABLE IF NOT EXISTS race_metadata (
    race_id         INTEGER PRIMARY KEY REFERENCES races(id),
    data            TEXT NOT NULL              -- JSON blob
);

-- ==========================================================================
-- Provenance tables
-- ==========================================================================

CREATE TABLE IF NOT EXISTS import_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    state           TEXT NOT NULL,
    election_key    TEXT,
    started_at      TEXT NOT NULL,             -- ISO 8601
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running', -- running / success / failed
    scraper_version TEXT,
    record_counts   TEXT,                      -- JSON
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id   INTEGER NOT NULL REFERENCES import_runs(id),
    url             TEXT,
    filename        TEXT,
    sha256          TEXT,
    size_bytes      INTEGER,
    fetched_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id   INTEGER NOT NULL REFERENCES import_runs(id),
    check_name      TEXT NOT NULL,
    passed          INTEGER NOT NULL,
    details         TEXT                       -- JSON
);

-- ==========================================================================
-- Indexes
-- ==========================================================================

CREATE INDEX IF NOT EXISTS idx_elections_state_date ON elections(state, date);
CREATE INDEX IF NOT EXISTS idx_races_election       ON races(election_id);
CREATE INDEX IF NOT EXISTS idx_races_category       ON races(office_category);
CREATE INDEX IF NOT EXISTS idx_choices_race          ON choices(race_id);
CREATE INDEX IF NOT EXISTS idx_votes_county_race     ON votes_county(race_id);
CREATE INDEX IF NOT EXISTS idx_votes_precinct_race   ON votes_precinct(race_id);
"""


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

STATES_SEED = [
    ("LA", "Louisiana", "22", "Parish",
     "https://voterportal.sos.la.gov/ElectionResults/ElectionResults/Data",
     "louisiana"),
    ("IN", "Indiana", "18", "County",
     "https://enr.indianavoters.in.gov",
     "indiana"),
    ("OH", "Ohio", "39", "County",
     "https://liveresults.ohiosos.gov",
     "ohio"),
]

# Louisiana: 64 parishes — codes 01-64, matching existing LA tracker
LOUISIANA_COUNTIES = [
    ("LA", "01", "Acadia",            "22001", "acadia"),
    ("LA", "02", "Allen",             "22003", "allen"),
    ("LA", "03", "Ascension",         "22005", "ascension"),
    ("LA", "04", "Assumption",        "22007", "assumption"),
    ("LA", "05", "Avoyelles",         "22009", "avoyelles"),
    ("LA", "06", "Beauregard",        "22011", "beauregard"),
    ("LA", "07", "Bienville",         "22013", "bienville"),
    ("LA", "08", "Bossier",           "22015", "bossier"),
    ("LA", "09", "Caddo",             "22017", "caddo"),
    ("LA", "10", "Calcasieu",         "22019", "calcasieu"),
    ("LA", "11", "Caldwell",          "22021", "caldwell"),
    ("LA", "12", "Cameron",           "22023", "cameron"),
    ("LA", "13", "Catahoula",         "22025", "catahoula"),
    ("LA", "14", "Claiborne",         "22027", "claiborne"),
    ("LA", "15", "Concordia",         "22029", "concordia"),
    ("LA", "16", "De Soto",           "22031", "de-soto"),
    ("LA", "17", "East Baton Rouge",  "22033", "east-baton-rouge"),
    ("LA", "18", "East Carroll",      "22035", "east-carroll"),
    ("LA", "19", "East Feliciana",    "22037", "east-feliciana"),
    ("LA", "20", "Evangeline",        "22039", "evangeline"),
    ("LA", "21", "Franklin",          "22041", "franklin"),
    ("LA", "22", "Grant",             "22043", "grant"),
    ("LA", "23", "Iberia",            "22045", "iberia"),
    ("LA", "24", "Iberville",         "22047", "iberville"),
    ("LA", "25", "Jackson",           "22049", "jackson"),
    ("LA", "26", "Jefferson",         "22051", "jefferson"),
    ("LA", "27", "Jefferson Davis",   "22053", "jefferson-davis"),
    ("LA", "28", "Lafayette",         "22055", "lafayette"),
    ("LA", "29", "Lafourche",         "22057", "lafourche"),
    ("LA", "30", "La Salle",          "22059", "la-salle"),
    ("LA", "31", "Lincoln",           "22061", "lincoln"),
    ("LA", "32", "Livingston",        "22063", "livingston"),
    ("LA", "33", "Madison",           "22065", "madison"),
    ("LA", "34", "Morehouse",         "22067", "morehouse"),
    ("LA", "35", "Natchitoches",      "22069", "natchitoches"),
    ("LA", "36", "Orleans",           "22071", "orleans"),
    ("LA", "37", "Ouachita",          "22073", "ouachita"),
    ("LA", "38", "Plaquemines",       "22075", "plaquemines"),
    ("LA", "39", "Pointe Coupee",     "22077", "pointe-coupee"),
    ("LA", "40", "Rapides",           "22079", "rapides"),
    ("LA", "41", "Red River",         "22081", "red-river"),
    ("LA", "42", "Richland",          "22083", "richland"),
    ("LA", "43", "Sabine",            "22085", "sabine"),
    ("LA", "44", "St. Bernard",       "22087", "st-bernard"),
    ("LA", "45", "St. Charles",       "22089", "st-charles"),
    ("LA", "46", "St. Helena",        "22091", "st-helena"),
    ("LA", "47", "St. James",         "22093", "st-james"),
    ("LA", "48", "St. John the Baptist", "22095", "st-john-the-baptist"),
    ("LA", "49", "St. Landry",        "22097", "st-landry"),
    ("LA", "50", "St. Martin",        "22099", "st-martin"),
    ("LA", "51", "St. Mary",          "22101", "st-mary"),
    ("LA", "52", "St. Tammany",       "22103", "st-tammany"),
    ("LA", "53", "Tangipahoa",        "22105", "tangipahoa"),
    ("LA", "54", "Tensas",            "22107", "tensas"),
    ("LA", "55", "Terrebonne",        "22109", "terrebonne"),
    ("LA", "56", "Union",             "22111", "union"),
    ("LA", "57", "Vermilion",         "22113", "vermilion"),
    ("LA", "58", "Vernon",            "22115", "vernon"),
    ("LA", "59", "Washington",        "22117", "washington"),
    ("LA", "60", "Webster",           "22119", "webster"),
    ("LA", "61", "West Baton Rouge",  "22121", "west-baton-rouge"),
    ("LA", "62", "West Carroll",      "22123", "west-carroll"),
    ("LA", "63", "West Feliciana",    "22125", "west-feliciana"),
    ("LA", "64", "Winn",              "22127", "winn"),
]

# Indiana: 92 counties — FIPS codes (3-digit county portion)
INDIANA_COUNTIES = [
    ("IN", "001", "Adams",       "18001", "adams"),
    ("IN", "003", "Allen",       "18003", "allen"),
    ("IN", "005", "Bartholomew", "18005", "bartholomew"),
    ("IN", "007", "Benton",      "18007", "benton"),
    ("IN", "009", "Blackford",   "18009", "blackford"),
    ("IN", "011", "Boone",       "18011", "boone"),
    ("IN", "013", "Brown",       "18013", "brown"),
    ("IN", "015", "Carroll",     "18015", "carroll"),
    ("IN", "017", "Cass",        "18017", "cass"),
    ("IN", "019", "Clark",       "18019", "clark"),
    ("IN", "021", "Clay",        "18021", "clay"),
    ("IN", "023", "Clinton",     "18023", "clinton"),
    ("IN", "025", "Crawford",    "18025", "crawford"),
    ("IN", "027", "Daviess",     "18027", "daviess"),
    ("IN", "029", "Dearborn",    "18029", "dearborn"),
    ("IN", "031", "Decatur",     "18031", "decatur"),
    ("IN", "033", "DeKalb",      "18033", "dekalb"),
    ("IN", "035", "Delaware",    "18035", "delaware"),
    ("IN", "037", "Dubois",      "18037", "dubois"),
    ("IN", "039", "Elkhart",     "18039", "elkhart"),
    ("IN", "041", "Fayette",     "18041", "fayette"),
    ("IN", "043", "Floyd",       "18043", "floyd"),
    ("IN", "045", "Fountain",    "18045", "fountain"),
    ("IN", "047", "Franklin",    "18047", "franklin"),
    ("IN", "049", "Fulton",      "18049", "fulton"),
    ("IN", "051", "Gibson",      "18051", "gibson"),
    ("IN", "053", "Grant",       "18053", "grant"),
    ("IN", "055", "Greene",      "18055", "greene"),
    ("IN", "057", "Hamilton",    "18057", "hamilton"),
    ("IN", "059", "Hancock",     "18059", "hancock"),
    ("IN", "061", "Harrison",    "18061", "harrison"),
    ("IN", "063", "Hendricks",   "18063", "hendricks"),
    ("IN", "065", "Henry",       "18065", "henry"),
    ("IN", "067", "Howard",      "18067", "howard"),
    ("IN", "069", "Huntington",  "18069", "huntington"),
    ("IN", "071", "Jackson",     "18071", "jackson"),
    ("IN", "073", "Jasper",      "18073", "jasper"),
    ("IN", "075", "Jay",         "18075", "jay"),
    ("IN", "077", "Jefferson",   "18077", "jefferson"),
    ("IN", "079", "Jennings",    "18079", "jennings"),
    ("IN", "081", "Johnson",     "18081", "johnson"),
    ("IN", "083", "Knox",        "18083", "knox"),
    ("IN", "085", "Kosciusko",   "18085", "kosciusko"),
    ("IN", "087", "LaGrange",    "18087", "lagrange"),
    ("IN", "089", "Lake",        "18089", "lake"),
    ("IN", "091", "LaPorte",     "18091", "laporte"),
    ("IN", "093", "Lawrence",    "18093", "lawrence"),
    ("IN", "095", "Madison",     "18095", "madison"),
    ("IN", "097", "Marion",      "18097", "marion"),
    ("IN", "099", "Marshall",    "18099", "marshall"),
    ("IN", "101", "Martin",      "18101", "martin"),
    ("IN", "103", "Miami",       "18103", "miami"),
    ("IN", "105", "Monroe",      "18105", "monroe"),
    ("IN", "107", "Montgomery",  "18107", "montgomery"),
    ("IN", "109", "Morgan",      "18109", "morgan"),
    ("IN", "111", "Newton",      "18111", "newton"),
    ("IN", "113", "Noble",       "18113", "noble"),
    ("IN", "115", "Ohio",        "18115", "ohio"),
    ("IN", "117", "Orange",      "18117", "orange"),
    ("IN", "119", "Owen",        "18119", "owen"),
    ("IN", "121", "Parke",       "18121", "parke"),
    ("IN", "123", "Perry",       "18123", "perry"),
    ("IN", "125", "Pike",        "18125", "pike"),
    ("IN", "127", "Porter",      "18127", "porter"),
    ("IN", "129", "Posey",       "18129", "posey"),
    ("IN", "131", "Pulaski",     "18131", "pulaski"),
    ("IN", "133", "Putnam",      "18133", "putnam"),
    ("IN", "135", "Randolph",    "18135", "randolph"),
    ("IN", "137", "Ripley",      "18137", "ripley"),
    ("IN", "139", "Rush",        "18139", "rush"),
    ("IN", "141", "St. Joseph",  "18141", "st-joseph"),
    ("IN", "143", "Scott",       "18143", "scott"),
    ("IN", "145", "Shelby",      "18145", "shelby"),
    ("IN", "147", "Spencer",     "18147", "spencer"),
    ("IN", "149", "Starke",      "18149", "starke"),
    ("IN", "151", "Steuben",     "18151", "steuben"),
    ("IN", "153", "Sullivan",    "18153", "sullivan"),
    ("IN", "155", "Switzerland",  "18155", "switzerland"),
    ("IN", "157", "Tippecanoe",  "18157", "tippecanoe"),
    ("IN", "159", "Tipton",      "18159", "tipton"),
    ("IN", "161", "Union",       "18161", "union"),
    ("IN", "163", "Vanderburgh", "18163", "vanderburgh"),
    ("IN", "165", "Vermillion",  "18165", "vermillion"),
    ("IN", "167", "Vigo",        "18167", "vigo"),
    ("IN", "169", "Wabash",      "18169", "wabash"),
    ("IN", "171", "Warren",      "18171", "warren"),
    ("IN", "173", "Warrick",     "18173", "warrick"),
    ("IN", "175", "Washington",  "18175", "washington"),
    ("IN", "177", "Wayne",       "18177", "wayne"),
    ("IN", "179", "Wells",       "18179", "wells"),
    ("IN", "181", "White",       "18181", "white"),
    ("IN", "183", "Whitley",     "18183", "whitley"),
]

# Ohio: 88 counties — FIPS codes (3-digit county portion)
OHIO_COUNTIES = [
    ("OH", "001", "Adams",       "39001", "adams"),
    ("OH", "003", "Allen",       "39003", "allen"),
    ("OH", "005", "Ashland",     "39005", "ashland"),
    ("OH", "007", "Ashtabula",   "39007", "ashtabula"),
    ("OH", "009", "Athens",      "39009", "athens"),
    ("OH", "011", "Auglaize",    "39011", "auglaize"),
    ("OH", "013", "Belmont",     "39013", "belmont"),
    ("OH", "015", "Brown",       "39015", "brown"),
    ("OH", "017", "Butler",      "39017", "butler"),
    ("OH", "019", "Carroll",     "39019", "carroll"),
    ("OH", "021", "Champaign",   "39021", "champaign"),
    ("OH", "023", "Clark",       "39023", "clark"),
    ("OH", "025", "Clermont",    "39025", "clermont"),
    ("OH", "027", "Clinton",     "39027", "clinton"),
    ("OH", "029", "Columbiana",  "39029", "columbiana"),
    ("OH", "031", "Coshocton",   "39031", "coshocton"),
    ("OH", "033", "Crawford",    "39033", "crawford"),
    ("OH", "035", "Cuyahoga",    "39035", "cuyahoga"),
    ("OH", "037", "Darke",       "39037", "darke"),
    ("OH", "039", "Defiance",    "39039", "defiance"),
    ("OH", "041", "Delaware",    "39041", "delaware"),
    ("OH", "043", "Erie",        "39043", "erie"),
    ("OH", "045", "Fairfield",   "39045", "fairfield"),
    ("OH", "047", "Fayette",     "39047", "fayette"),
    ("OH", "049", "Franklin",    "39049", "franklin"),
    ("OH", "051", "Fulton",      "39051", "fulton"),
    ("OH", "053", "Gallia",      "39053", "gallia"),
    ("OH", "055", "Geauga",      "39055", "geauga"),
    ("OH", "057", "Greene",      "39057", "greene"),
    ("OH", "059", "Guernsey",    "39059", "guernsey"),
    ("OH", "061", "Hamilton",    "39061", "hamilton"),
    ("OH", "063", "Hancock",     "39063", "hancock"),
    ("OH", "065", "Hardin",      "39065", "hardin"),
    ("OH", "067", "Harrison",    "39067", "harrison"),
    ("OH", "069", "Henry",       "39069", "henry"),
    ("OH", "071", "Highland",    "39071", "highland"),
    ("OH", "073", "Hocking",     "39073", "hocking"),
    ("OH", "075", "Holmes",      "39075", "holmes"),
    ("OH", "077", "Huron",       "39077", "huron"),
    ("OH", "079", "Jackson",     "39079", "jackson"),
    ("OH", "081", "Jefferson",   "39081", "jefferson"),
    ("OH", "083", "Knox",        "39083", "knox"),
    ("OH", "085", "Lake",        "39085", "lake"),
    ("OH", "087", "Lawrence",    "39087", "lawrence"),
    ("OH", "089", "Licking",     "39089", "licking"),
    ("OH", "091", "Logan",       "39091", "logan"),
    ("OH", "093", "Lorain",      "39093", "lorain"),
    ("OH", "095", "Lucas",       "39095", "lucas"),
    ("OH", "097", "Madison",     "39097", "madison"),
    ("OH", "099", "Mahoning",    "39099", "mahoning"),
    ("OH", "101", "Marion",      "39101", "marion"),
    ("OH", "103", "Medina",      "39103", "medina"),
    ("OH", "105", "Meigs",       "39105", "meigs"),
    ("OH", "107", "Mercer",      "39107", "mercer"),
    ("OH", "109", "Miami",       "39109", "miami"),
    ("OH", "111", "Monroe",      "39111", "monroe"),
    ("OH", "113", "Montgomery",  "39113", "montgomery"),
    ("OH", "115", "Morgan",      "39115", "morgan"),
    ("OH", "117", "Morrow",      "39117", "morrow"),
    ("OH", "119", "Muskingum",   "39119", "muskingum"),
    ("OH", "121", "Noble",       "39121", "noble"),
    ("OH", "123", "Ottawa",      "39123", "ottawa"),
    ("OH", "125", "Paulding",    "39125", "paulding"),
    ("OH", "127", "Perry",       "39127", "perry"),
    ("OH", "129", "Pickaway",    "39129", "pickaway"),
    ("OH", "131", "Pike",        "39131", "pike"),
    ("OH", "133", "Portage",     "39133", "portage"),
    ("OH", "135", "Preble",      "39135", "preble"),
    ("OH", "137", "Putnam",      "39137", "putnam"),
    ("OH", "139", "Richland",    "39139", "richland"),
    ("OH", "141", "Ross",        "39141", "ross"),
    ("OH", "143", "Sandusky",    "39143", "sandusky"),
    ("OH", "145", "Scioto",      "39145", "scioto"),
    ("OH", "147", "Seneca",      "39147", "seneca"),
    ("OH", "149", "Shelby",      "39149", "shelby"),
    ("OH", "151", "Stark",       "39151", "stark"),
    ("OH", "153", "Summit",      "39153", "summit"),
    ("OH", "155", "Trumbull",    "39155", "trumbull"),
    ("OH", "157", "Tuscarawas",  "39157", "tuscarawas"),
    ("OH", "159", "Union",       "39159", "union"),
    ("OH", "161", "Van Wert",    "39161", "van-wert"),
    ("OH", "163", "Vinton",      "39163", "vinton"),
    ("OH", "165", "Warren",      "39165", "warren"),
    ("OH", "167", "Washington",  "39167", "washington"),
    ("OH", "169", "Wayne",       "39169", "wayne"),
    ("OH", "171", "Williams",    "39171", "williams"),
    ("OH", "173", "Wood",        "39173", "wood"),
    ("OH", "175", "Wyandot",     "39175", "wyandot"),
]

ALL_COUNTIES = LOUISIANA_COUNTIES + INDIANA_COUNTIES + OHIO_COUNTIES


# ---------------------------------------------------------------------------
# Create / seed
# ---------------------------------------------------------------------------

def create_schema(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create all tables, indexes, and seed data."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # -- Tables & indexes -----------------------------------------------------
    conn.executescript(SCHEMA_SQL)

    # -- Seed states ----------------------------------------------------------
    conn.executemany(
        """INSERT OR IGNORE INTO states
           (code, name, fips, county_label, sos_base_url, scraper_type)
           VALUES (?, ?, ?, ?, ?, ?)""",
        STATES_SEED,
    )

    # -- Seed counties --------------------------------------------------------
    conn.executemany(
        """INSERT OR IGNORE INTO counties
           (state, code, name, fips, slug)
           VALUES (?, ?, ?, ?, ?)""",
        ALL_COUNTIES,
    )

    conn.commit()
    conn.close()

    # Summarize
    conn = sqlite3.connect(db_path)
    state_count = conn.execute("SELECT COUNT(*) FROM states").fetchone()[0]
    county_count = conn.execute("SELECT COUNT(*) FROM counties").fetchone()[0]
    conn.close()

    print(f"Schema created at {os.path.abspath(db_path)}")
    print(f"  {state_count} states seeded")
    print(f"  {county_count} counties seeded")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the National Election Tracker database schema."
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()
    create_schema(args.db_path)


if __name__ == "__main__":
    main()
