# National Election Tracker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a national election tracker MVP with LA (imported), IN (historical + live), and OH (live) — ready for May 5 primaries by May 4.

**Architecture:** New repo + Hetzner (FastAPI + SQLite on volume 105552283) + Vercel (Next.js frontend). Louisiana data imported from existing DB. Indiana scraped from Civix ENR JSON. Ohio live from NIST XML. County-level maps from Census TIGER.

**Tech Stack:** Python 3.12 (FastAPI, uvicorn, requests, lxml, openpyxl), Next.js 16, Tailwind CSS v4, D3, MapLibre GL, Recharts

**Design:** `docs/plans/2026-04-29-national-election-tracker-design.md`

**Critical constraint:** The existing Louisiana Election Tracker repo and deployment must not be modified or disrupted.

**Execution strategy:** All scraping and data processing runs directly on Hetzner — not locally. Code is developed locally, pushed to GitHub, pulled on Hetzner, and executed there. This saves Claude API costs (no large data transfers through the conversation), leverages Hetzner's bandwidth for SOS API calls, and keeps the DB writes local to the server. Claude monitors remotely via SSH. Pattern learned from SwimPulse: push code → SSH → run on server → tail logs → verify.

---

## File Structure

```
national-election-tracker/
├── scrapers/
│   ├── base.py                  # Abstract scraper interface
│   ├── schema.py                # Create all DB tables
│   ├── louisiana_import.py      # One-time: LA DB → national schema
│   ├── indiana.py               # IN Civix ENR JSON scraper
│   ├── ohio_live.py             # OH NIST XML live parser
│   ├── runner.py                # CLI orchestrator
│   ├── requirements.txt
│   └── configs/
│       ├── louisiana.yaml
│       ├── indiana.yaml
│       └── ohio.yaml
├── api/
│   ├── main.py                  # FastAPI app
│   ├── db.py                    # DB connection singleton
│   ├── routes/
│   │   ├── health.py
│   │   ├── states.py
│   │   ├── elections.py
│   │   ├── races.py
│   │   ├── live.py
│   │   └── maps.py
│   └── requirements.txt
├── web/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx             # National US map
│   │   └── [state]/
│   │       ├── page.tsx         # State homepage
│   │       ├── live/page.tsx
│   │       └── elections/
│   │           ├── page.tsx
│   │           └── [electionKey]/
│   │               ├── page.tsx
│   │               └── [raceKey]/page.tsx
│   ├── components/
│   │   ├── USMap.tsx
│   │   ├── CountyMap.tsx
│   │   ├── RaceCard.tsx
│   │   └── ElectionExplorer.tsx
│   ├── lib/
│   │   ├── api-client.ts
│   │   ├── types.ts
│   │   ├── constants.ts
│   │   └── utils.ts
│   ├── next.config.ts
│   ├── package.json
│   └── tsconfig.json
├── maps/
│   ├── build_county_maps.py     # Census TIGER → TopoJSON
│   └── requirements.txt
├── deploy/
│   ├── hetzner-setup.sh
│   └── national-elections-api.service
├── data/                        # .gitignored
│   ├── elections.db
│   └── backups/
├── .gitignore
├── CLAUDE.md
└── docs/plans/
```

---

## Task 1: Create Repo + Project Skeleton

**Files:**
- Create: `CLAUDE.md`, `.gitignore`, `scrapers/requirements.txt`, `api/requirements.txt`, `maps/requirements.txt`

- [ ] **Step 1: Create GitHub repo**

```bash
cd C:/Users/bhorw/projects
gh repo create AH-Datalytics/national-election-tracker --private --clone
cd national-election-tracker
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
# Database
*.db
*.db-wal
*.db-shm
*.db-journal
data/

# Python
__pycache__/
*.pyc
venv/
.venv/

# Shapefiles (large)
*.shp
*.shx
*.dbf
*.prj
*.cpg
_shapefile_cache/

# Node
node_modules/
.next/
.vercel/

# Environment
.env
.env.local
```

- [ ] **Step 3: Create `CLAUDE.md`**

Include: project overview, architecture, key commands, file structure, tech stack, design constraint (do not touch LA tracker).

- [ ] **Step 4: Create Python requirements files**

`scrapers/requirements.txt`:
```
requests>=2.31
pyyaml>=6.0
```

`api/requirements.txt`:
```
fastapi>=0.115
uvicorn>=0.34
```

`maps/requirements.txt`:
```
topojson>=1.9
shapely>=2.0
fiona>=1.10
```

- [ ] **Step 5: Create directory structure**

```bash
mkdir -p scrapers/configs api/routes web maps deploy data/backups docs/plans
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: project skeleton with directory structure and requirements"
git push -u origin master
```

---

## Task 2: Database Schema

**Files:**
- Create: `scrapers/schema.py`

- [ ] **Step 1: Write `scrapers/schema.py`**

Full schema creation script with all tables from design doc:
- `states` — with county_label, sos_base_url, scraper_type
- `counties` — state + code PK, fips, slug
- `elections` — with `election_key` TEXT UNIQUE (e.g., `LA-2024-11-05-general`)
- `races` — with `race_key` TEXT UNIQUE, `is_ballot_measure` flag
- `choices` — renamed from candidates, with `choice_type` (candidate/ballot_option), `choice_key` TEXT UNIQUE
- `votes_county` — choice_id FK
- `votes_precinct` — choice_id FK
- `early_votes` — choice_id FK
- `race_reporting` — per-race precincts reporting/expected
- `turnout` — per-election voter registration/ballots cast
- `import_runs` — provenance tracking
- `source_files` — file hashes and URLs
- `data_quality_checks` — reconciliation results
- `race_metadata` — JSON blob for state-specific fields (LA office_level_code, can_have_runoff, etc.)

Seed `states` with LA (64 parishes), IN (92 counties), OH (88 counties).

Key function: `generate_election_key(state, date, type) → "IN-2024-11-05-general"`

Key function: `generate_race_key(election_key, office, district, county) → deterministic hash or slug`

Key function: `generate_choice_key(race_key, name, party, ballot_order) → deterministic`

- [ ] **Step 2: Run schema creation**

```bash
cd C:/Users/bhorw/projects/national-election-tracker
python scrapers/schema.py
```

Verify: `sqlite3 data/elections.db ".tables"` shows all tables. `SELECT COUNT(*) FROM states` returns 3. `SELECT COUNT(*) FROM counties` returns 244 (64+92+88).

- [ ] **Step 3: Commit**

```bash
git add scrapers/schema.py
git commit -m "feat: generalized schema with provenance tables and stable keys"
```

---

## Task 3: Louisiana Data Import

**Files:**
- Create: `scrapers/louisiana_import.py`

**Prerequisite:** Copy `louisiana_elections.db` from the LA tracker project to a temp location. Do NOT modify the original.

- [ ] **Step 1: Copy the LA database**

```bash
cp C:/Users/bhorw/projects/louisiana-election-tracker/louisiana_elections.db C:/Users/bhorw/projects/national-election-tracker/data/louisiana_source.db
```

- [ ] **Step 2: Write `scrapers/louisiana_import.py`**

Script that:
1. Opens `data/louisiana_source.db` as read-only source
2. Opens `data/elections.db` as destination
3. Creates an `import_runs` record
4. For each LA election:
   - Generates `election_key` (e.g., `LA-2024-11-05-general`)
   - Inserts into `elections` with `state = 'LA'`
5. For each LA race:
   - Generates `race_key`
   - Maps `parish_code` → `county_code`
   - Maps `office_level_code` to normalized `office_category`
   - Stores LA-specific fields (`specific_title`, `general_title`, `office_level_code`, `can_have_runoff`, `is_multi_parish`) in `race_metadata`
   - Sets `is_ballot_measure = 1` for codes 998, 999
6. For each LA candidate → `choices` with `choice_type = 'candidate'` (or `'ballot_option'` for amendments/propositions)
7. Copies `votes_parish` → `votes_county`, `votes_precinct`, `early_votes`
8. Copies `turnout` data, splits into `turnout` + `race_reporting`
9. Logs `source_files` record for the LA DB
10. Runs reconciliation: verify election count, race count, total votes match source
11. Logs `data_quality_checks` results

Field mapping:
- `parishes.code` → `counties.code` (same values, just table rename)
- `parishes.name` → `counties.name`
- `candidates.description` → `choices.name`
- `candidates.sos_choice_id` → `choices.sos_choice_id`

Election type inference from LA data: LA doesn't have an explicit type field. Use date patterns:
- Elections with "Primary" races → `primary`
- Elections with "General" or "Runoff" → `general` or `runoff`
- Default to `general` if unclear (can refine later)

- [ ] **Step 3: Run the import**

```bash
python scrapers/louisiana_import.py
```

- [ ] **Step 4: Verify**

```bash
sqlite3 data/elections.db "SELECT COUNT(*) FROM elections WHERE state = 'LA'"
# Expected: ~317

sqlite3 data/elections.db "SELECT COUNT(*) FROM races r JOIN elections e ON r.election_id = e.id WHERE e.state = 'LA'"
# Expected: matches LA source

sqlite3 data/elections.db "SELECT COUNT(*) FROM import_runs WHERE state = 'LA'"
# Expected: 1

sqlite3 data/elections.db "SELECT check_name, passed FROM data_quality_checks ORDER BY id"
# Expected: all passed = 1
```

- [ ] **Step 5: Commit**

```bash
git add scrapers/louisiana_import.py
git commit -m "feat: Louisiana data import with provenance and reconciliation"
```

---

## Task 4: Indiana Historical Scraper

**Files:**
- Create: `scrapers/base.py`, `scrapers/indiana.py`, `scrapers/configs/indiana.yaml`

- [ ] **Step 1: Write `scrapers/base.py`**

Abstract base class:
```python
class StateScraper(ABC):
    def __init__(self, db_path: str, config: dict): ...
    @abstractmethod
    def list_elections(self) -> list[dict]: ...
    @abstractmethod
    def fetch_election(self, election_id: str) -> dict: ...

    # Shared helpers
    def create_import_run(self, election_key: str) -> int: ...
    def log_source_file(self, run_id: int, url: str, data: bytes) -> None: ...
    def run_quality_checks(self, run_id: int, election_id: int) -> None: ...
    def backup_db(self) -> str: ...
```

- [ ] **Step 2: Write `scrapers/configs/indiana.yaml`**

```yaml
state: IN
name: Indiana
base_url: https://enr.indianavoters.in.gov
archive_url: https://enr.indianavoters.in.gov/archive/{slug}/download
delay_seconds: 2.0
user_agent: NationalElectionTracker/1.0

archives:
  - slug: 2024General
    date: "2024-11-05"
    type: general
  - slug: 2024Primary
    date: "2024-05-07"
    type: primary
  - slug: 2023General
    date: "2023-11-07"
    type: general
  - slug: 2023Primary
    date: "2023-05-02"
    type: primary
  - slug: 2022General
    date: "2022-11-08"
    type: general
  - slug: 2022Primary
    date: "2022-05-03"
    type: primary
  - slug: 2020General
    date: "2020-11-03"
    type: general
  - slug: 2020Primary
    date: "2020-06-02"
    type: primary
  - slug: 2019General
    date: "2019-11-05"
    type: general
  - slug: 2019Primary
    date: "2019-05-07"
    type: primary
```

- [ ] **Step 3: Write `scrapers/indiana.py`**

Indiana scraper that:
1. Reads config from `configs/indiana.yaml`
2. For each archive in config:
   - Downloads `{archive_url}/AllOfficeResults.json` (offices)
   - Downloads `{archive_url}/AllRefResults.json` (referendums)
   - Creates `import_runs` record
   - Logs both files in `source_files` with SHA-256 hash
3. Parses office results JSON:
   - Groups records by `(ReportingCountyName, Office, OfficeCategory)` to identify unique races
   - Generates deterministic `race_key` from election_key + office + district
   - Generates `choice_key` from race_key + candidate name + party
   - For each record:
     - `ReportingCountyName` → look up county code from `counties` table
     - `Office` → `races.title`
     - `OfficeCategory` → map to normalized `office_category`
     - `NameonBallot` → `choices.name`
     - `PoliticalParty` → `choices.party`
     - `TotalVotes` → `votes_precinct.vote_total` (precinct level) and aggregated to `votes_county`
     - `Winner` = "Yes" → `choices.outcome` = "Elected"
     - `DataEntryJurisdictionName` → `votes_precinct.precinct_id`
   - Aggregate precinct votes to county level for `votes_county`
4. Parses referendum results JSON:
   - Creates race with `is_ballot_measure = 1`, `office_category = 'referendum'`
   - Creates two choices: Yes (`choice_type = 'ballot_option'`) and No (`choice_type = 'ballot_option'`)
   - `YesVotes` → Yes choice vote_total, `NoVotes` → No choice vote_total
5. Runs quality checks:
   - County vote totals sum to statewide totals
   - No negative vote counts
   - Every race has at least one choice
6. Logs results to `data_quality_checks`

`OfficeCategory` mapping:
```python
CATEGORY_MAP = {
    'US Senator': 'us_senate',
    'US Representative': 'us_house',
    'Governor': 'governor',
    'State Senator': 'state_senate',
    'State Representative': 'state_house',
    'Judge': 'judicial',
    # ... add more as encountered
}
```

- [ ] **Step 4: Test with one election**

```bash
python scrapers/indiana.py --election 2024General
```

Verify:
```bash
sqlite3 data/elections.db "SELECT election_key, date, type FROM elections WHERE state = 'IN'"
sqlite3 data/elections.db "SELECT COUNT(*) FROM races r JOIN elections e ON r.election_id = e.id WHERE e.state = 'IN'"
sqlite3 data/elections.db "SELECT COUNT(*) FROM votes_precinct vp JOIN races r ON vp.race_id = r.id JOIN elections e ON r.election_id = e.id WHERE e.state = 'IN'"
sqlite3 data/elections.db "SELECT check_name, passed, details FROM data_quality_checks WHERE import_run_id = (SELECT MAX(id) FROM import_runs WHERE state = 'IN')"
```

- [ ] **Step 5: Scrape all Indiana archives**

```bash
python scrapers/indiana.py --all
```

- [ ] **Step 6: Commit**

```bash
git add scrapers/base.py scrapers/indiana.py scrapers/configs/indiana.yaml
git commit -m "feat: Indiana historical scraper with offices and referendums"
```

---

## Task 5: Ohio Live XML Parser

**Files:**
- Create: `scrapers/ohio_live.py`, `scrapers/configs/ohio.yaml`

- [ ] **Step 1: Write `scrapers/configs/ohio.yaml`**

```yaml
state: OH
name: Ohio
live_url: https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob
delay_seconds: 180  # 3-minute updates
user_agent: NationalElectionTracker/1.0
```

- [ ] **Step 2: Write `scrapers/ohio_live.py`**

Ohio live scraper that:
1. Fetches the NIST 1500-100 XML from the download endpoint
2. Parses `ElectionReport` XML:
   - `Election` element → election metadata (date, type)
   - `GpUnit` elements → counties (state FIPS + county FIPS matching)
   - `Contest` / `CandidateContest` → races
   - `BallotMeasureContest` → ballot measures
   - `CandidateSelection` → choices
   - `VoteCounts` per `GpUnit` → `votes_county`
3. Creates/updates election record with `is_official = 0`
4. Records `IsTest` flag from XML in import_runs metadata
5. Tracks source timestamp from XML
6. Quality checks: vote totals, contest counts

This is a live poller — designed to be called repeatedly during election night. Uses UPSERT logic.

CLI:
- `python scrapers/ohio_live.py --once` — fetch once and exit
- `python scrapers/ohio_live.py --poll` — poll every 3 minutes until stopped

- [ ] **Step 3: Test with current test data**

```bash
python scrapers/ohio_live.py --once
```

The endpoint currently returns `IsTest="true"` data. Verify it parses without error and inserts records.

- [ ] **Step 4: Commit**

```bash
git add scrapers/ohio_live.py scrapers/configs/ohio.yaml
git commit -m "feat: Ohio NIST XML live parser"
```

---

## Task 6: Runner CLI with Adaptive Workers

**Files:**
- Create: `scrapers/runner.py`

Lessons from SwimPulse scraping: start slow, ramp up if healthy, back off on errors, pause between batches, always resume-safe.

- [ ] **Step 1: Write `scrapers/runner.py`**

Unified CLI using argparse:

```
python scrapers/runner.py scrape --state IN                              # all IN archives
python scrapers/runner.py scrape --state IN --election 2024General       # single election
python scrapers/runner.py scrape --state IN --workers 3 --ramp           # multi-worker with ramp-up
python scrapers/runner.py scrape --all --workers 2                       # all states, 2 workers
python scrapers/runner.py live --state OH                                # poll OH live
python scrapers/runner.py live --state IN                                # poll IN live
python scrapers/runner.py import-la                                      # one-time LA import
python scrapers/runner.py backup                                         # snapshot DB
python scrapers/runner.py status                                         # show import_runs summary
```

### Worker/Concurrency Model

```python
class AdaptiveWorkerPool:
    """
    Manages concurrent scraper workers with adaptive scaling.
    Pattern from SwimPulse: start conservative, scale up on success, back off on errors.
    """
    def __init__(self, max_workers=4, initial_workers=1, ramp_up=True):
        self.max_workers = max_workers
        self.active_workers = initial_workers
        self.consecutive_successes = 0
        self.consecutive_errors = 0
        self.pause_until = None

    def on_success(self):
        """Ramp up: after 5 consecutive successes, add a worker (up to max)."""
        self.consecutive_successes += 1
        self.consecutive_errors = 0
        if self.ramp_up and self.consecutive_successes >= 5:
            if self.active_workers < self.max_workers:
                self.active_workers += 1
                log.info(f"Ramping up to {self.active_workers} workers")
            self.consecutive_successes = 0

    def on_error(self, status_code=None):
        """Back off: reduce workers, pause if rate limited."""
        self.consecutive_successes = 0
        self.consecutive_errors += 1
        if status_code == 429 or self.consecutive_errors >= 3:
            self.active_workers = max(1, self.active_workers - 1)
            pause_seconds = min(60 * self.consecutive_errors, 300)  # max 5 min
            self.pause_until = time.time() + pause_seconds
            log.warning(f"Backing off: {self.active_workers} workers, pausing {pause_seconds}s")

    def should_pause(self) -> bool:
        if self.pause_until and time.time() < self.pause_until:
            return True
        self.pause_until = None
        return False
```

### Key behaviors:
- **Start with 1 worker** by default. `--ramp` enables auto-scaling up to `--workers N`.
- **Ramp up** after 5 consecutive successful fetches: add 1 worker.
- **Back off** on HTTP 429 or 3 consecutive errors: drop 1 worker + pause (exponential, max 5 min).
- **Pause between elections** (configurable per state in YAML: `batch_pause_seconds`).
- **Resume-safe**: before fetching, check `import_runs` — skip elections already successfully imported. `--force` to re-import.
- **Graceful shutdown**: Ctrl-C finishes current election, writes partial progress, exits cleanly.
- **Progress logging**: `[3/10] Fetching 2022Primary... 2 workers, 0 errors`
- **Batch pause**: after every N elections (default 3), pause for `batch_pause_seconds` (default 10s) to be respectful.

### Monitoring output format:
```
14:32:01 [1/10] IN 2024General — fetching AllOfficeResults.json (41.2 MB)...
14:32:08 [1/10] IN 2024General — fetching AllRefResults.json (2.1 MB)...
14:32:10 [1/10] IN 2024General — 847 races, 12,431 choices, 1,247,832 precinct votes — OK
14:32:10 [1/10] IN 2024General — quality checks: 3/3 passed
14:32:12 [2/10] IN 2024Primary — fetching AllOfficeResults.json...
14:32:15 Ramping up to 2 workers
...
14:35:40 [10/10] IN 2019Primary — complete
14:35:40 === Indiana scrape complete: 10 elections, 0 errors, 4m28s ===
```

Backup creates `data/backups/elections-YYYYMMDD-HHMMSS.db`.

- [ ] **Step 2: Add worker config to YAML files**

`scrapers/configs/indiana.yaml` additions:
```yaml
scraping:
  max_workers: 3
  initial_workers: 1
  delay_seconds: 2.0
  batch_size: 3
  batch_pause_seconds: 10
  ramp_after_successes: 5
```

- [ ] **Step 3: Commit**

```bash
git add scrapers/runner.py scrapers/configs/
git commit -m "feat: unified runner CLI with adaptive worker pool and resume capability"
```

---

## Task 7: FastAPI Backend

**Files:**
- Create: `api/main.py`, `api/db.py`, `api/routes/health.py`, `api/routes/states.py`, `api/routes/elections.py`, `api/routes/races.py`, `api/routes/live.py`, `api/routes/maps.py`

- [ ] **Step 1: Write `api/db.py`**

SQLite connection singleton (read-only, WAL mode, mmap enabled):
```python
import sqlite3
DB_PATH = "/opt/national-elections/data/elections.db"  # Hetzner path
# For local dev, override via ELECTIONS_DB_PATH env var
```

- [ ] **Step 2: Write `api/main.py`**

FastAPI app with CORS (allow Vercel origin), includes all route modules.

- [ ] **Step 3: Write `api/routes/health.py`**

`GET /api/health` — returns `{"status": "ok", "db_size_mb": N, "states": ["LA","IN","OH"], "elections_count": N}`

- [ ] **Step 4: Write `api/routes/states.py`**

- `GET /api/states` — list all states with election counts
- `GET /api/states/{code}` — single state detail with stats

- [ ] **Step 5: Write `api/routes/elections.py`**

- `GET /api/{state}/elections` — list elections for state (paginated, filterable by year/type)
- `GET /api/{state}/elections/{electionKey}` — single election with race list

- [ ] **Step 6: Write `api/routes/races.py`**

- `GET /api/{state}/races/{raceKey}` — race detail with all choices and vote totals
- `GET /api/{state}/races/{raceKey}/counties` — county-level results
- `GET /api/{state}/races/{raceKey}/precincts/{countyCode}` — precinct-level results (where available)

- [ ] **Step 7: Write `api/routes/live.py`**

- `GET /api/{state}/live/status` — is election night active? Last update timestamp.
- `GET /api/{state}/live/races` — all live races with current totals
- `GET /api/{state}/live/races/{raceKey}/counties` — live county breakdown

- [ ] **Step 8: Write `api/routes/maps.py`**

- `GET /api/maps/us-states.json` — US state boundaries TopoJSON
- `GET /api/maps/{state}/counties.json` — county boundaries for a state

- [ ] **Step 9: Test locally**

```bash
cd C:/Users/bhorw/projects/national-election-tracker
ELECTIONS_DB_PATH=data/elections.db uvicorn api.main:app --reload --port 8200
```

Test endpoints:
```bash
curl http://localhost:8200/api/health
curl http://localhost:8200/api/states
curl http://localhost:8200/api/la/elections
curl http://localhost:8200/api/in/elections
```

- [ ] **Step 10: Commit**

```bash
git add api/
git commit -m "feat: FastAPI backend with all read endpoints"
```

---

## Task 8: County Map Generation

**Files:**
- Create: `maps/build_county_maps.py`

- [ ] **Step 1: Download Census TIGER county shapefile**

```bash
cd C:/Users/bhorw/projects/national-election-tracker/maps
curl -O https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip
unzip cb_2024_us_county_500k.zip -d _census_counties
```

- [ ] **Step 2: Download US state boundaries**

```bash
curl -O https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip
unzip cb_2024_us_state_500k.zip -d _census_states
```

- [ ] **Step 3: Write `maps/build_county_maps.py`**

Script that:
1. Reads the national county shapefile
2. For each target state (LA, IN, OH):
   - Filters counties by state FIPS
   - Simplifies geometry (target <200KB per state)
   - Outputs TopoJSON to `data/maps/{state}/counties.json`
3. For US states map:
   - Simplifies all state boundaries
   - Outputs to `data/maps/us-states.json`
   - Includes `has_data` property (true for LA, IN, OH)

- [ ] **Step 4: Run map generation**

```bash
python maps/build_county_maps.py
```

Verify files exist and are reasonable size (<500KB each).

- [ ] **Step 5: Commit**

```bash
git add maps/build_county_maps.py
git commit -m "feat: county and state boundary map generation from Census TIGER"
```

---

## Task 9: Next.js Frontend Scaffold

**Files:**
- Create: `web/` directory with Next.js app

- [ ] **Step 1: Create Next.js app**

```bash
cd C:/Users/bhorw/projects/national-election-tracker
npx create-next-app@latest web --typescript --tailwind --app --src-dir=false --import-alias="@/*" --use-npm
```

- [ ] **Step 2: Write `web/lib/api-client.ts`**

Typed fetch client that calls the Hetzner FastAPI backend:
```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8200';

export async function fetchApi<T>(path: string, revalidate?: number): Promise<T> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    next: { revalidate: revalidate ?? 3600 },
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Write `web/lib/types.ts`**

TypeScript interfaces matching API response shapes:
- `State`, `Election`, `Race`, `Choice`, `CountyResult`, `PrecinctResult`, `LiveStatus`

- [ ] **Step 4: Write `web/lib/constants.ts`**

State metadata, party colors, office category labels. Port PARTY_COLORS from LA tracker.

- [ ] **Step 5: Write `web/lib/utils.ts`**

Port formatting helpers from LA tracker: `formatNumber`, `formatPercent`, `formatDate`, `outcomeLabel`, `partyLabel`.

- [ ] **Step 6: Update `web/app/layout.tsx`**

Root layout with:
- Title: "National Election Tracker"
- Subtitle: "by AH Datalytics"
- Nav: Home, States, Live
- Footer: "Built by AH Datalytics"
- AHD analytics tracking script

Same editorial/newsroom aesthetic as LA tracker. Serif titles, clean borders, white background.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/bhorw/projects/national-election-tracker
git add web/
git commit -m "feat: Next.js frontend scaffold with API client and types"
```

---

## Task 10: National Homepage (US Map)

**Files:**
- Create: `web/components/USMap.tsx`, `web/app/page.tsx`

- [ ] **Step 1: Write `web/components/USMap.tsx`**

D3-based US map component (client component):
- Fetch `us-states.json` TopoJSON from API
- Render all 50 states + DC
- States with data: filled blue/dark, clickable, hover tooltip with state name + election count
- States without data: light gray fill, no interaction
- Click navigates to `/[state]`
- Responsive (SVG viewBox)
- Clean, minimal — no gradients, no drop shadows

- [ ] **Step 2: Write `web/app/page.tsx`**

Homepage (server component):
- Fetch stats from `/api/states`
- Hero: "National Election Tracker" heading + "Tracking X elections across Y states" subtitle
- US Map component
- Stats bar: X states, Y elections, Z races
- Next upcoming election banner (if any state has one)

- [ ] **Step 3: Commit**

```bash
git add web/components/USMap.tsx web/app/page.tsx
git commit -m "feat: national homepage with interactive US map"
```

---

## Task 11: State Pages

**Files:**
- Create: `web/app/[state]/page.tsx`, `web/app/[state]/layout.tsx`

- [ ] **Step 1: Write `web/app/[state]/layout.tsx`**

State-level layout:
- State name in header (e.g., "Louisiana", "Indiana", "Ohio")
- Sub-nav: Overview, Elections, Live
- Validate `[state]` param against known states; 404 if unknown

- [ ] **Step 2: Write `web/app/[state]/page.tsx`**

State homepage (server component):
- Fetch from `/api/states/{code}` and `/api/{state}/elections?limit=5`
- State stats: election count, race count, coverage dates
- Recent elections list (cards with date, type, race count)
- Link to full election list

- [ ] **Step 3: Write `web/app/[state]/elections/page.tsx`**

Elections list (server component):
- Fetch from `/api/{state}/elections`
- Filterable by year range and type
- Cards: date, type, race count, turnout if available

- [ ] **Step 4: Commit**

```bash
git add web/app/\[state\]/
git commit -m "feat: state homepage and election list pages"
```

---

## Task 12: Election + Race Detail Pages

**Files:**
- Create: `web/app/[state]/elections/[electionKey]/page.tsx`, `web/app/[state]/elections/[electionKey]/[raceKey]/page.tsx`
- Create: `web/components/CountyMap.tsx`, update `web/components/RaceCard.tsx`

- [ ] **Step 1: Write `web/components/RaceCard.tsx`**

Port from LA tracker's `RaceCard.tsx`. Adapt:
- `candidates` prop → `choices` prop
- Support `choice_type` — show "Yes/No" differently than candidate names
- Keep party dots, vote bars, outcome badges
- Use `choice_key` as React key instead of `id`

- [ ] **Step 2: Write `web/components/CountyMap.tsx`**

D3 or MapLibre choropleth (client component):
- Fetch county TopoJSON from `/api/maps/{state}/counties.json`
- Color by winner, margin, or turnout (configurable)
- Hover tooltip: county name + lead candidate + margin
- Click: future drill-down (Phase 2)
- Responsive

- [ ] **Step 3: Write election detail page**

`web/app/[state]/elections/[electionKey]/page.tsx`:
- Fetch election + races from API
- Group races by `office_category` (Federal, State, Judicial, Local, Ballot Measures)
- RaceCard for each race (compact mode)
- CountyMap for selected race
- Toggle between races to update map

- [ ] **Step 4: Write race detail page**

`web/app/[state]/elections/[electionKey]/[raceKey]/page.tsx`:
- Fetch race detail + county results from API
- Full RaceCard (expanded)
- County breakdown table (sortable: county name, votes, margin)
- CountyMap colored by winner
- Early vote breakdown if available

- [ ] **Step 5: Commit**

```bash
git add web/components/ web/app/\[state\]/elections/
git commit -m "feat: election detail, race detail pages with county map"
```

---

## Task 13: Live Dashboard

**Files:**
- Create: `web/app/[state]/live/page.tsx`

- [ ] **Step 1: Write live dashboard page**

`web/app/[state]/live/page.tsx` (client component for auto-refresh):
- Polls `/api/{state}/live/status` every 30 seconds
- If active: shows all live races grouped by office category
- Each race: RaceCard with updating vote counts
- CountyMap for selected race
- Header: "Election Night — [State]", precincts reporting, last updated timestamp
- If not active: "No active election" message with countdown to next election + link to historical

- [ ] **Step 2: Commit**

```bash
git add web/app/\[state\]/live/
git commit -m "feat: live election night dashboard with auto-refresh"
```

---

## Task 14: Hetzner Deployment + Server-Side Execution

**This is where all scraping happens.** Code is pushed to GitHub, pulled on Hetzner, and run there. Claude monitors via SSH.

**Files:**
- Create: `deploy/hetzner-setup.sh`, `deploy/national-elections-api.service`, `deploy/pull-and-run.sh`

- [ ] **Step 1: Write `deploy/national-elections-api.service`**

```ini
[Unit]
Description=National Elections Tracker API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/national-elections
ExecStart=/opt/national-elections/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8200
Restart=always
RestartSec=5
Environment=ELECTIONS_DB_PATH=/opt/national-elections/data/elections.db

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `deploy/hetzner-setup.sh`**

Setup script that:
1. Mounts volume 105552283 to `/mnt/HC_Volume_105552283`
2. Creates directory structure:
   ```
   /opt/national-elections/
   ├── repo/          # git clone of the repo
   ├── data/          # → symlink to volume
   │   ├── elections.db
   │   ├── maps/
   │   ├── backups/
   │   └── logs/
   └── venv/          # Python 3.12 venv
   ```
3. Clones repo: `gh repo clone AH-Datalytics/national-election-tracker /opt/national-elections/repo`
4. Creates Python venv, installs requirements
5. Creates symlink: `/opt/national-elections/data` → volume mount
6. Runs schema creation
7. Installs systemd service
8. Starts API

- [ ] **Step 3: Write `deploy/pull-and-run.sh`**

Quick deploy script for iterative development:
```bash
#!/bin/bash
# Pull latest code and restart API
cd /opt/national-elections/repo
git pull
pip install -r scrapers/requirements.txt -r api/requirements.txt --quiet
systemctl restart national-elections-api
echo "Deployed $(git log --oneline -1)"
```

- [ ] **Step 4: SSH to Hetzner and deploy**

```bash
ssh root@178.156.243.51  # or whatever the server IP is

# Mount volume
mkdir -p /mnt/HC_Volume_105552283
mount -o discard,defaults /dev/disk/by-id/scsi-0HC_Volume_105552283 /mnt/HC_Volume_105552283
echo '/dev/disk/by-id/scsi-0HC_Volume_105552283 /mnt/HC_Volume_105552283 ext4 discard,nofail,defaults 0 0' >> /etc/fstab

# Run setup script
bash /opt/national-elections/repo/deploy/hetzner-setup.sh
```

- [ ] **Step 5: Run LA import on Hetzner**

First, upload the LA source DB (one-time, ~100MB):
```bash
scp C:/Users/bhorw/projects/louisiana-election-tracker/louisiana_elections.db root@178.156.243.51:/opt/national-elections/data/louisiana_source.db
```

Then run the import on the server:
```bash
ssh root@178.156.243.51 "cd /opt/national-elections/repo && python scrapers/louisiana_import.py"
```

Monitor:
```bash
ssh root@178.156.243.51 "sqlite3 /opt/national-elections/data/elections.db 'SELECT state, COUNT(*) FROM elections GROUP BY state'"
```

- [ ] **Step 6: Run Indiana historical scrape on Hetzner**

This is the big one — 10 elections × ~41MB each. Run directly on Hetzner with progress monitoring:

```bash
# Start the scrape in a tmux session (survives SSH disconnect)
ssh root@178.156.243.51
tmux new -s indiana-scrape
cd /opt/national-elections/repo
python scrapers/indiana.py --all 2>&1 | tee /opt/national-elections/data/logs/indiana-scrape.log
# Ctrl-B D to detach
```

Monitor from Claude:
```bash
# Check progress
ssh root@178.156.243.51 "tail -20 /opt/national-elections/data/logs/indiana-scrape.log"

# Check row counts
ssh root@178.156.243.51 "sqlite3 /opt/national-elections/data/elections.db 'SELECT e.election_key, COUNT(DISTINCT r.id), COUNT(DISTINCT c.id) FROM elections e LEFT JOIN races r ON r.election_id = e.id LEFT JOIN choices c ON c.race_id = r.id WHERE e.state = \"IN\" GROUP BY e.id'"
```

Indiana scraper should have:
- Rate limiting: 2s between downloads (configurable in YAML)
- Progress logging: "Fetching 2024General... 3 of 10 elections"
- Resume on failure: skip elections already fully imported (check import_runs)
- Backup before start: `python scrapers/runner.py backup`

- [ ] **Step 7: Run Ohio live test on Hetzner**

```bash
ssh root@178.156.243.51 "cd /opt/national-elections/repo && python scrapers/ohio_live.py --once 2>&1 | tee /opt/national-elections/data/logs/ohio-live.log"
```

- [ ] **Step 8: Generate maps on Hetzner**

```bash
ssh root@178.156.243.51 "cd /opt/national-elections/repo && python maps/build_county_maps.py"
```

- [ ] **Step 9: Verify API is running**

```bash
curl http://178.156.243.51:8200/api/health
curl http://178.156.243.51:8200/api/states
curl http://178.156.243.51:8200/api/in/elections
```

- [ ] **Step 10: Commit deploy scripts**

```bash
git add deploy/
git commit -m "feat: Hetzner deployment config, setup, and pull-and-run scripts"
```

### Ongoing Deploy Workflow

After any code change:
```bash
# Local: commit and push
git add -A && git commit -m "fix: ..." && git push

# Hetzner: pull and restart
ssh root@178.156.243.51 "bash /opt/national-elections/repo/deploy/pull-and-run.sh"
```

---

## Task 15: Vercel Deployment

- [ ] **Step 1: Set up Vercel project**

```bash
cd C:/Users/bhorw/projects/national-election-tracker/web
npx vercel link
```

Create new Vercel project: `national-election-tracker`

- [ ] **Step 2: Set environment variables**

In Vercel dashboard or CLI:
```bash
npx vercel env add NEXT_PUBLIC_API_URL production
# Value: http://178.156.243.51:8200  (or domain if set up)
```

- [ ] **Step 3: Deploy**

```bash
npx next build
npx vercel --prod
```

- [ ] **Step 4: Verify**

Visit the Vercel URL. Confirm:
- National map loads with LA, IN, OH colored
- State pages load
- Election lists show data

---

## Task 16: Indiana Live Discovery + Election Night Prep

**Files:**
- Modify: `scrapers/indiana.py` (add live polling mode)

- [ ] **Step 1: Discover Indiana's active election URL**

Before May 5, check what URL the ENR site uses for the active election:
```bash
curl -s "https://enr.indianavoters.in.gov/site/index.html" | grep -i "election\|archive\|2026"
```

Also check: `https://enr.indianavoters.in.gov/download/AllOfficeResults.json` (may go live on election day).

Update `configs/indiana.yaml` with the discovered live URL.

- [ ] **Step 2: Add live polling to Indiana scraper**

Add `--live` mode to `indiana.py`:
- Polls the active election URL every 60 seconds
- Parses same JSON format as historical
- UPSERTs results (idempotent)
- Logs each poll as an `import_runs` record with status

- [ ] **Step 3: Test with historical data as dry run**

```bash
python scrapers/indiana.py --live --dry-run --url "https://enr.indianavoters.in.gov/archive/2024General/download/AllOfficeResults.json"
```

- [ ] **Step 4: Commit**

```bash
git add scrapers/indiana.py scrapers/configs/indiana.yaml
git commit -m "feat: Indiana live polling mode for election night"
```

---

## Task 17: Pre-Launch Checklist

- [ ] **Step 1: Database backup**

```bash
python scrapers/runner.py backup
```

Verify backup exists in `data/backups/`.

- [ ] **Step 2: Verify all acceptance criteria**

Run through the acceptance criteria from the design doc:
- [ ] National map loads with LA, IN, OH colored
- [ ] State pages load for `/la`, `/in`, `/oh`
- [ ] LA data matches expected counts
- [ ] IN 2024 General county totals reconcile
- [ ] IN referenda appear as ballot measures
- [ ] OH live XML parses successfully
- [ ] Live API records timestamps and test status
- [ ] County choropleth renders for at least one IN race
- [ ] County results render for at least one OH test race
- [ ] Scrapers are idempotent
- [ ] DB backup procedure works
- [ ] `/api/health` returns OK
- [ ] `import_runs` has records
- [ ] `data_quality_checks` has results
- [ ] LA tracker is untouched (verify: `cd louisiana-election-tracker && git status` shows clean)

- [ ] **Step 3: Election night operator prep**

Document in `CLAUDE.md` or `docs/election-night.md`:
1. Start OH live poller: `python scrapers/ohio_live.py --poll`
2. Start IN live poller: `python scrapers/indiana.py --live`
3. Monitor: `tail -f logs/*.log`
4. Verify API: `curl /api/health`
5. After results certified: re-run scrapers with `--official` flag

- [ ] **Step 4: Final commit and push**

```bash
git add -A
git commit -m "chore: pre-launch checklist and election night docs"
git push
```
