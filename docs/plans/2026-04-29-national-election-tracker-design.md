# National Election Tracker — Design Spec

## Overview

### What is this?

A year-round election results platform that tracks every race in every state — from president and governor down to county commissioner and school board — with precinct-level results, interactive maps, and real-time election night dashboards. An AH Datalytics portfolio piece and public data tool.

Think of it as a self-hosted, open-data alternative to the AP election results pages or NYT election maps, built incrementally state by state.

### Why build it?

1. **No free, open, precinct-level election tracker exists.** AP charges for access. NYT/FiveThirtyEight only cover marquee races. State SOS websites are hard to navigate and don't support cross-election analysis.
2. **AHD portfolio piece** — demonstrates data engineering, real-time systems, and editorial data visualization at scale.
3. **Scalable architecture** — each state is an independent scraper adapter. Once the pattern works for 3 states, expanding to 50 is a matter of writing adapters, not redesigning the system.

### Where did this come from?

AH Datalytics already built a [Louisiana Election Tracker](https://github.com/AH-Datalytics/louisiana-election-tracker) with 317 elections (1982–present), precinct-level MapLibre maps, and a live election night dashboard powered by the Louisiana SOS JSON API. That project is fully functional and deployed on Vercel.

This design expands that single-state tracker into a national platform. The Louisiana tracker remains as-is (separate repo, separate deployment). The national tracker is a new project that:
- Imports Louisiana's existing data as its first state
- Adds Indiana and Ohio as the first new states
- Provides a national-level US map showing coverage
- Is architected to scale to all 50 states over time

### Isolation from the Louisiana Tracker

**The existing Louisiana Election Tracker (`AH-Datalytics/louisiana-election-tracker`) must not be modified, broken, or disrupted by any work on this project.** It remains an independent repo with its own Vercel deployment, its own database, and its own scraper scripts.

Specifically:
- **Separate GitHub repo.** The national tracker is `AH-Datalytics/national-election-tracker`. No changes to the LA tracker repo.
- **Separate Vercel project.** Different Vercel app, different domain. The LA tracker continues running at its current URL.
- **Separate Hetzner deployment.** The national tracker gets its own Hetzner directory, volume, systemd service, and FastAPI instance. It does not share resources with any other project.
- **Data is copied, not moved.** Louisiana data is imported into the national DB by copying from the existing `louisiana_elections.db`. The original DB is never modified.
- **No shared dependencies.** The national tracker has its own `package.json`, `requirements.txt`, and config. No monorepo, no shared packages, no symlinks to the LA tracker.
- **LA tracker scraper remains canonical.** If Louisiana needs a scraper fix, it happens in the LA tracker repo. The national tracker's Louisiana adapter is a separate port.

### Key facts

| | |
|---|---|
| **New repo** | `AH-Datalytics/national-election-tracker` (separate from LA tracker) |
| **Frontend** | Next.js on Vercel (new Vercel project) |
| **Backend** | FastAPI + SQLite on Hetzner (20GB volume, resizable) |
| **MVP states** | Louisiana, Indiana, Ohio |
| **MVP deadline** | May 4, 2026 (live test for IN + OH May 5 primaries) |
| **Long-term target** | All 50 states |

---

## Data Sources

### Louisiana (existing — import from `louisiana-election-tracker`)
- **API:** `voterportal.sos.la.gov` JSON blob API (unauthenticated, 10s cache)
- **Coverage:** 317 elections, 1982–present
- **Granularity:** Precinct-level votes, 64 parishes
- **Live:** ISR-cached API routes poll SOS every ~30s on election night
- **Format:** JSON
- **Import strategy:** Copy existing `louisiana_elections.db`, transform schema to add `state = 'LA'` and generalized column names. Do not re-scrape.

### Indiana (new — strongest new-state candidate)
- **API:** `enr.indianavoters.in.gov` — Civix IVIS-ENR platform
- **Downloads:** `archive/{Year}{Type}/download/AllOfficeResults.json` (also CSV/XML)
- **Coverage:** 2019–2024+ confirmed (General + Primary). Historical CSV at `indianavoters.in.gov/ENRHistorical/`
- **Granularity:** **Precinct-level** — flat JSON with fields: `Election`, `JurisdictionName`, `ReportingCountyName`, `DataEntryJurisdictionName` (precinct), `DataEntryLevelName`, `Office`, `OfficeCategory`, `BallotOrder`, `NameonBallot`, `PoliticalParty`, `Winner`, `NumberofOfficeSeats`, `TotalVotes`
- **Live:** Same ENR system serves election night. JSON/CSV/XML download links available during live results. **Note:** the non-archive path (`enr.indianavoters.in.gov/download/AllOfficeResults.json`) returned 404 on 2026-04-29. The live scraper must discover the active election slug or configure it before election night.
- **Size:** ~41MB per election (2022 General)
- **Referendums:** Separate file: `AllRefResults.json` — different schema with `YesVotes`, `NoVotes`, `ReferendumTitle`, `ReferendumText`, `TypeofReferendum`
- **92 counties**
- **No stable source IDs** — scraper must synthesize deterministic keys from election + office + candidate + precinct

### Ohio (new — live excellent, historical ETL-heavy)
- **Live:** `liveresults.ohiosos.gov` — NIST 1500-100 XML feed, auto-updates every 3 minutes
  - Direct download endpoint: `https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob`
  - Returns `ElectionReport` XML with `Format="SummaryContest"`. Marked `IsTest="true"` before election night.
- **Historical:** XLSX files at `ohiosos.gov/globalassets/elections/{YEAR}/{TYPE}/official/...`
  - Coverage: 2016–2025, county + precinct level
  - **File naming is inconsistent across years** — not a reliable predictable pattern
  - Historical deep ingest is Phase 2, not Phase 1
- **88 counties**

### Data Source Quality Ranking
1. **Louisiana** — Best: clean JSON API, every endpoint documented, 40+ years
2. **Indiana** — Very good: structured JSON/CSV/XML downloads, precinct-level, 2019+
3. **Ohio** — Live is excellent (NIST XML). Historical is usable but ETL-heavy (inconsistent XLSX). Treat Ohio historical as "official bulk data feeds", not a drop-in API.

---

## Infrastructure

### Hetzner Server
- **Purpose:** SQLite database + FastAPI REST API + map file serving
- **Volume:** 20GB ($0.96/mo) — sufficient for MVP and early 50-state expansion. Hetzner volumes can be resized without downtime; upgrade when needed rather than over-provisioning.
- **Path:** `/opt/national-elections/data/elections.db`
- **FastAPI:** Serves all read queries, county/precinct results, map data, live status
- **Systemd service:** `national-elections-api.service`
- **Health endpoint:** `GET /api/health` — confirms API is running and DB is accessible

### Volume Sizing Rationale
| Component | 3 states | 50 states (projected) |
|-----------|----------|----------------------|
| Election results DB | ~250 MB | ~3–5 GB |
| County TopoJSON | ~10 MB | ~200 MB |
| Precinct geometries (Phase 2+) | ~200 MB | ~3–5 GB |
| Provenance/raw archives | ~100 MB | ~2 GB |
| Indexes + overhead | ~50 MB | ~1 GB |
| **Total** | **~600 MB** | **~8–13 GB** |

At full 50-state scale with raw source archives, vector tiles, and live snapshots, may need 40–50GB. Resize then.

### Vercel
- **Purpose:** Next.js frontend only
- **Calls Hetzner API** for all data (no bundled DB)
- **Vercel Blob CDN** for large GeoJSON files (precinct shapefiles) — same pattern as LA tracker
- **Separate Vercel project** from the LA tracker — different app, different domain

---

## Generalized Database Schema

Single SQLite database with `state` as a first-class dimension. Uses stable source-derived keys for all public-facing IDs (not autoincrement integers).

### Design Principles

1. **Source-derived stable IDs.** Public URLs use deterministic keys like `IN-2024-general`, not SQLite rowids that break on reimport. Internal integer PKs exist for joins but are never exposed in URLs or API responses.
2. **Ballot measures modeled explicitly.** The `choices` table (not `candidates`) holds both candidate records and ballot measure options (Yes/No). A `choice_type` field distinguishes them.
3. **Race-level reporting.** Precincts reporting/expected is tracked per race per geography (not collapsed to election level), because some sources report by contest.
4. **Provenance tracking.** Every import records its source, timestamp, and file hash. Reconciliation checks run after import.
5. **Idempotent imports.** Re-running a scraper for the same election replaces data cleanly (UPSERT on stable keys).

### Core Tables

#### `states`
- `code` TEXT PRIMARY KEY (2-letter: LA, IN, OH)
- `name` TEXT
- `fips` TEXT
- `county_label` TEXT (parish/county/borough — for display)
- `sos_base_url` TEXT
- `scraper_type` TEXT (louisiana/indiana/ohio)

#### `counties`
- `state` TEXT FK → states
- `code` TEXT (state-specific code)
- `name` TEXT
- `fips` TEXT
- `slug` TEXT
- PRIMARY KEY (state, code)

#### `elections`
- `id` INTEGER PRIMARY KEY
- `election_key` TEXT UNIQUE (e.g., `IN-2024-general`) — **used in URLs**
- `state` TEXT FK → states
- `date` TEXT (YYYY-MM-DD)
- `type` TEXT (primary/general/runoff/special)
- `is_official` INTEGER
- `sos_election_id` TEXT (state-specific identifier)
- UNIQUE(state, date, sos_election_id)

#### `races`
- `id` INTEGER PRIMARY KEY
- `race_key` TEXT UNIQUE — deterministic from election_key + office + district + county
- `election_id` INTEGER FK → elections
- `sos_race_id` TEXT
- `title` TEXT
- `office_category` TEXT (normalized: us_senate, us_house, governor, state_senate, state_house, judicial, county, municipal, ballot_measure, referendum, constitutional_amendment)
- `office_name` TEXT (raw from source)
- `district` TEXT
- `county_code` TEXT (null for statewide)
- `num_to_elect` INTEGER
- `is_ballot_measure` INTEGER DEFAULT 0
- UNIQUE(election_id, sos_race_id)

#### `choices` (candidates + ballot measure options)
- `id` INTEGER PRIMARY KEY
- `choice_key` TEXT UNIQUE — deterministic from race_key + name + party + ballot_order
- `race_id` INTEGER FK → races
- `sos_choice_id` TEXT
- `choice_type` TEXT ('candidate' | 'ballot_option')
- `name` TEXT (candidate name, or 'Yes'/'No'/'For'/'Against')
- `party` TEXT (null for ballot options)
- `ballot_order` INTEGER
- `color_hex` TEXT
- `outcome` TEXT (Elected/Defeated/Runoff/Approved/Rejected)
- `vote_total` INTEGER
- UNIQUE(race_id, sos_choice_id)

#### `votes_county`
- `race_id` INTEGER FK
- `county_code` TEXT
- `choice_id` INTEGER FK
- `vote_total` INTEGER
- PRIMARY KEY (race_id, county_code, choice_id)

#### `votes_precinct`
- `race_id` INTEGER FK
- `county_code` TEXT
- `precinct_id` TEXT
- `choice_id` INTEGER FK
- `vote_total` INTEGER
- PRIMARY KEY (race_id, county_code, precinct_id, choice_id)

#### `early_votes`
- `race_id` INTEGER FK
- `county_code` TEXT
- `choice_id` INTEGER FK
- `vote_total` INTEGER
- PRIMARY KEY (race_id, county_code, choice_id)

### Reporting & Turnout Tables (split per feasibility review)

#### `race_reporting`
- `race_id` INTEGER FK
- `county_code` TEXT (null for statewide aggregate)
- `precincts_reporting` INTEGER
- `precincts_expected` INTEGER
- PRIMARY KEY (race_id, county_code)

#### `turnout`
- `election_id` INTEGER FK
- `county_code` TEXT
- `qualified_voters` INTEGER
- `voters_voted` INTEGER
- PRIMARY KEY (election_id, county_code)

### Provenance Tables

#### `import_runs`
- `id` INTEGER PRIMARY KEY
- `state` TEXT
- `election_key` TEXT
- `started_at` TEXT (ISO 8601)
- `finished_at` TEXT
- `status` TEXT (running/success/failed)
- `scraper_version` TEXT
- `record_counts` TEXT (JSON: tables → row counts)
- `error_message` TEXT

#### `source_files`
- `id` INTEGER PRIMARY KEY
- `import_run_id` INTEGER FK → import_runs
- `url` TEXT
- `filename` TEXT
- `sha256` TEXT
- `size_bytes` INTEGER
- `fetched_at` TEXT

#### `data_quality_checks`
- `id` INTEGER PRIMARY KEY
- `import_run_id` INTEGER FK → import_runs
- `check_name` TEXT (e.g., 'county_totals_match_statewide', 'no_negative_votes')
- `passed` INTEGER
- `details` TEXT (JSON)

### Candidate Index (deferred)
- Same concept as LA tracker but with `state` column for state-specific dedup
- Cross-state matching deferred to Phase 2

### Louisiana-Specific Source Fields

When importing Louisiana data, preserve useful LA-specific fields in a `race_metadata` JSON column or separate table rather than discarding them:
- `specific_title`, `general_title` (LA's two-level race naming)
- `office_level_code` (LA's numeric office classification)
- `can_have_runoff` (Louisiana jungle primary system)
- `is_multi_parish` (LA's multi-parish race flag)

---

## Scraper Architecture

```
scrapers/
├── base.py                  # Abstract base: list_elections(), fetch_election(), fetch_live()
├── louisiana.py             # Port from existing LA scraper (SOS JSON API)
├── indiana.py               # Civix ENR JSON downloads + referendums
├── ohio.py                  # NIST XML (live only for Phase 1)
├── runner.py                # Multi-state orchestrator
├── import_louisiana.py      # One-time: transform existing LA DB → national schema
├── requirements.txt
└── configs/
    ├── louisiana.yaml       # State-specific config (URLs, archive list, rate limits)
    ├── indiana.yaml
    └── ohio.yaml
```

### Base Scraper Interface
```python
class StateScraper(ABC):
    @abstractmethod
    def list_elections(self) -> list[ElectionMeta]: ...
    @abstractmethod
    def fetch_election(self, election_id: str) -> ElectionData: ...
    @abstractmethod
    def fetch_live_status(self) -> LiveStatus: ...
    @abstractmethod
    def fetch_live_results(self) -> LiveResults: ...
```

### Key Scraper Requirements
- **Idempotent.** Re-running for the same election replaces data cleanly.
- **Provenance.** Every run creates an `import_runs` record and logs source files with hashes.
- **Reconciliation.** After import, verify county totals sum to statewide totals. Log mismatches to `data_quality_checks`.
- **Backup before import.** Copy the DB before any write operation.
- **Rate limiting.** Per-state configurable delay between API calls (in YAML config).

### Runner (`runner.py`)
- `python runner.py scrape --state IN` — scrape one state
- `python runner.py scrape --all` — scrape all configured states
- `python runner.py scrape --state IN --election 2024General` — single election
- `python runner.py live --state IN` — start live polling for active election
- `python runner.py backup` — snapshot the DB before operations
- Progress logging, resume on failure
- Workers: sequential by default, `--parallel N` for multi-state

### Indiana Scraper Details
- Archive URL pattern: `https://enr.indianavoters.in.gov/archive/{Year}{Type}/download/AllOfficeResults.json`
- Confirmed archives: 2019General, 2019Primary, 2020General, 2020Primary, 2022General, 2022Primary, 2023General, 2023Primary, 2024General, 2024Primary
- Each JSON file is a flat array — one record per candidate per precinct per office
- Map fields: `ReportingCountyName` → county, `DataEntryJurisdictionName` → precinct, `Office` → race title, `OfficeCategory` → office_category, `NameonBallot` → candidate name, `PoliticalParty` → party, `TotalVotes` → votes, `Winner` → outcome
- Referendums from `AllRefResults.json`: `ReferendumTitle` → race title, `YesVotes`/`NoVotes` → two choice records with `choice_type = 'ballot_option'`
- **Live URL discovery:** Before May 5, probe the ENR site to find the active election slug. Fallback: manually configure in `indiana.yaml`.

### Ohio Scraper Details
- **Phase 1 (live only):** Parse NIST 1500-100 XML from `liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob`
- **Phase 2 (historical):** Download XLSX from `ohiosos.gov/globalassets/elections/` — requires building a per-year file manifest first due to inconsistent naming

---

## Frontend

### Route Structure

URLs use stable `election_key` and `race_key` values, not database integer IDs.

#### National Level
- `/` — US map (D3). States with data colored, others gray. Click to drill into state. Hero stats (X states, Y elections, Z races tracked). Next upcoming election banner.
- `/states` — Grid of all 50 states showing coverage status

#### State Level (reuse LA tracker patterns)
- `/[state]` — State homepage: next election countdown, recent results, coverage stats
- `/[state]/live` — Election night dashboard (polling Hetzner API)
- `/[state]/elections` — Browse all elections for this state
- `/[state]/elections/[electionKey]` — Single election with race list + county choropleth
- `/[state]/elections/[electionKey]/[raceKey]` — Race detail with county breakdown
- `/[state]/candidates/[slug]` — Candidate cross-election profile (Phase 2)
- `/[state]/counties/[slug]` — County profile with turnout trends (Phase 2)

### Shared Components (port from LA tracker)
- **USMap** — New: D3 US map with state fill colors + click interaction
- **CountyMap** — Generalized from ParishMap: county-level choropleth per state
- **RaceCard** — Adapted from LA tracker, supports both candidates and ballot measures
- **ElectionExplorer** — Port from LA with state awareness
- **PrecinctMap** — Deferred to Phase 2 for IN/OH (LA precinct maps work via existing tracker)

### Design Direction
Same editorial/newsroom aesthetic as the LA tracker. Typography-forward, data-dense, maps first-class. No gradient mesh, no icon spam, no AI-typical color palettes.

---

## Map Data

### County Boundaries (Phase 1)
- Source: US Census TIGER/Line shapefiles (`cb_2024_us_county_500k`)
- One simplified TopoJSON per state: `maps/{state}/counties.json`
- Key counties by state FIPS + county FIPS
- Stored on Hetzner, served via FastAPI or Vercel Blob CDN

### Precinct Boundaries (Phase 2+)
- **Louisiana:** Already built in the LA tracker (1999–2026). Import as-is.
- **Indiana:** Census VTD shapefiles. Label matching `DataEntryJurisdictionName` → VTD geometry ID needs investigation.
- **Ohio:** Census VTD or state redistricting shapefiles. County-specific handling likely needed.
- **Long-term format:** PMTiles or vector tiles (via Tippecanoe) for national precinct maps. Raw GeoJSON/TopoJSON won't scale to 50 states.

---

## Election Night Live Architecture

```
Vercel Frontend  →  Hetzner FastAPI  →  State SOS APIs
    (ISR ~30s)       (polls per state)    (LA JSON, IN JSON, OH XML)
```

- FastAPI on Hetzner polls each state's live feed on a configurable interval
- Caches results in SQLite (same DB, flagged as unofficial via `is_official = 0`)
- Vercel calls Hetzner API with ISR revalidation (~30s)
- After election certified: re-import as official, stop polling
- **Operator checklist** for election night: verify live URLs, confirm DB backup, test API health, monitor scraper logs

### Per-State Live Endpoints on Hetzner
- `GET /api/health` — API status + DB accessibility
- `GET /api/{state}/live/status` — is election night active?
- `GET /api/{state}/live/races` — all races with current totals
- `GET /api/{state}/live/race/{raceKey}/counties` — county breakdown
- `GET /api/{state}/live/race/{raceKey}/precincts/{countyCode}` — precinct detail (where available)

---

## Phasing

### Phase 1: MVP by May 4, 2026

**Goal:** National map with LA/IN/OH, county-level results, live election night polling for IN + OH May 5 primaries.

1. Create new repo `AH-Datalytics/national-election-tracker`
2. Hetzner setup: 20GB volume, FastAPI skeleton, systemd service, health endpoint
3. Generalized schema with provenance tables, stable keys, choices model
4. Import Louisiana data from existing `louisiana_elections.db`
5. Build Indiana historical scraper — ingest all archives (2019–2024) + referendums
6. Build Ohio NIST XML live parser (live only — no historical XLSX ingest)
7. Build Indiana live URL discovery/config + polling
8. Build FastAPI read endpoints: states, elections, races, county results, live status
9. Build county TopoJSON maps for LA, IN, OH (Census TIGER)
10. Build frontend: national US map, state pages, election pages, race detail, live dashboard
11. Data quality checks: verify LA import counts, IN county-to-statewide reconciliation
12. Deploy to Vercel + Hetzner
13. Operator election night checklist

**Explicitly deferred from Phase 1:**
- Ohio historical XLSX deep ingest
- Indiana/Ohio precinct-level maps
- National shift maps and trend analysis
- Cross-state candidate matching
- Candidate profile pages
- County profile pages
- Full 50-state storage optimization

### Phase 2: Depth (post-May 6)
- Ohio historical import (build file manifest first, then ETL)
- Precinct result tables for IN and OH (data in DB, no geometry yet)
- Precinct geometry matching for IN/OH (Census VTD)
- Candidate profile + county profile pages
- More states (prioritize those with clean APIs)
- Vector tiles / PMTiles for precinct maps (Tippecanoe)

### Phase 3: Scale to 50 (ongoing)
- State-by-state scraper buildout with parallel workers
- Automated scraper discovery (test known URL patterns per state)
- Quality dashboard showing coverage per state
- Full precinct geometry pipeline
- Cross-state candidate matching
- National trend analysis and shift maps
- Migrate to Postgres if SQLite write-concurrency becomes a bottleneck

---

## Acceptance Criteria

MVP is ready when:

- [ ] `/` national map loads and links to LA, IN, OH (colored states). All other states gray.
- [ ] `/la`, `/in`, `/oh` state pages load with election lists.
- [ ] Louisiana imported data matches existing known row counts from the LA tracker DB.
- [ ] Indiana 2024 General import reconciles: county totals sum to statewide totals per race.
- [ ] Indiana referenda import as ballot measures with Yes/No choices.
- [ ] Ohio live XML endpoint can be fetched and parsed into the schema.
- [ ] Live API records source timestamp, import timestamp, and `IsTest`/unofficial status.
- [ ] County-level choropleth map renders for at least one Indiana historical race.
- [ ] County-level results render for at least one Ohio live/test race.
- [ ] All scrapers are idempotent (re-run produces same result).
- [ ] Database backup procedure exists and is documented.
- [ ] `GET /api/health` returns OK.
- [ ] `import_runs` table has records for every completed import.
- [ ] `data_quality_checks` table has reconciliation results.
- [ ] LA tracker (`louisiana-election-tracker`) is completely untouched and still deploys independently.

---

## Project Structure

```
national-election-tracker/
├── scrapers/
│   ├── base.py                  # Abstract scraper interface
│   ├── louisiana.py             # LA SOS JSON API adapter
│   ├── indiana.py               # IN Civix ENR JSON adapter
│   ├── ohio.py                  # OH NIST XML adapter (live only Phase 1)
│   ├── import_louisiana.py      # One-time LA DB → national schema transform
│   ├── runner.py                # CLI: scrape, live, backup
│   ├── requirements.txt
│   └── configs/
│       ├── louisiana.yaml
│       ├── indiana.yaml
│       └── ohio.yaml
├── api/
│   ├── main.py                  # FastAPI app
│   ├── routes/
│   │   ├── health.py
│   │   ├── elections.py
│   │   ├── races.py
│   │   ├── live.py
│   │   └── maps.py
│   └── requirements.txt
├── web/
│   ├── app/
│   │   ├── page.tsx             # National US map
│   │   ├── states/page.tsx      # All states grid
│   │   └── [state]/
│   │       ├── page.tsx         # State homepage
│   │       ├── live/page.tsx    # Election night dashboard
│   │       └── elections/
│   │           ├── page.tsx     # Browse elections
│   │           ├── [electionKey]/
│   │           │   ├── page.tsx # Single election
│   │           │   └── [raceKey]/
│   │           │       └── page.tsx  # Race detail
│   ├── components/
│   │   ├── USMap.tsx
│   │   ├── CountyMap.tsx
│   │   ├── RaceCard.tsx
│   │   └── ElectionExplorer.tsx
│   ├── lib/
│   │   ├── api-client.ts       # Fetch from Hetzner API
│   │   ├── constants.ts
│   │   └── utils.ts
│   ├── next.config.ts
│   └── package.json
├── data/                        # .gitignored, on Hetzner volume
│   ├── elections.db
│   └── backups/
├── deploy/
│   ├── hetzner-setup.sh
│   └── national-elections-api.service
├── CLAUDE.md
└── docs/
    └── plans/
```
