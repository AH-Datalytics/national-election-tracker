# National Election Tracker

## What is this?

A year-round election results platform that tracks every race in every state — from president and governor down to county commissioner and school board — with precinct-level results, interactive maps, and real-time election night dashboards. An AH Datalytics portfolio piece and public data tool.

Self-hosted, open-data alternative to AP election results or NYT election maps, built incrementally state by state.

## Architecture

```
Vercel (Next.js frontend)  →  Hetzner (FastAPI + SQLite)  →  State SOS APIs
```

- **Frontend:** Next.js 16 on Vercel (separate Vercel project from everything else)
- **Backend:** FastAPI + single SQLite database on Hetzner (volume ID: 105552283)
- **DB path on Hetzner:** `/opt/national-elections/data/elections.db`
- **Systemd service:** `national-elections-api.service`

## Tech Stack

- **Python 3.12:** FastAPI, uvicorn, requests, lxml, openpyxl, pyyaml
- **Frontend:** Next.js 16, Tailwind CSS v4, D3, MapLibre GL, Recharts
- **Maps:** topojson, shapely, fiona (Census TIGER shapefiles → TopoJSON)
- **Database:** SQLite (single file, `state` column on all tables)

## Critical Constraint

**DO NOT modify the Louisiana Election Tracker repo or deployment.** The existing `AH-Datalytics/louisiana-election-tracker` is a completely separate project with its own repo, Vercel deployment, database, and scraper scripts. This national tracker:
- Is a separate GitHub repo (`AH-Datalytics/national-election-tracker`)
- Has its own Vercel project and domain
- Has its own Hetzner directory, volume, and systemd service
- Copies Louisiana data (never moves or modifies the original)
- Has no shared dependencies, no symlinks, no monorepo connection

## States

| State | Source | Status |
|-------|--------|--------|
| **LA** | Import from existing `louisiana_elections.db` (317 elections, 1982-present) | Imported |
| **IN** | Civix ENR JSON (`enr.indianavoters.in.gov`), precinct-level, 2019+ | Historical + Live |
| **OH** | NIST 1500-100 XML (`liveresults.ohiosos.gov`), live only Phase 1 | Live only |

## Key Commands

```bash
# Scrapers (run on Hetzner, not locally)
python scrapers/runner.py scrape --state IN           # Scrape one state
python scrapers/runner.py scrape --all                # Scrape all states
python scrapers/runner.py scrape --state IN --election 2024General  # Single election
python scrapers/runner.py live --state IN             # Start live polling
python scrapers/runner.py backup                      # Snapshot DB

# API (Hetzner)
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Frontend (local dev)
cd web && npm run dev
```

## Project Structure

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
├── web/                         # Next.js 16 frontend (deployed to Vercel)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx             # National US map
│   │   └── [state]/
│   │       ├── page.tsx         # State homepage
│   │       ├── live/page.tsx    # Election night dashboard
│   │       └── elections/...
│   ├── components/
│   │   ├── USMap.tsx
│   │   ├── CountyMap.tsx
│   │   ├── RaceCard.tsx
│   │   └── ElectionExplorer.tsx
│   └── lib/
│       ├── api-client.ts
│       ├── types.ts
│       ├── constants.ts
│       └── utils.ts
├── maps/
│   ├── build_county_maps.py     # Census TIGER → TopoJSON
│   └── requirements.txt
├── deploy/
│   ├── hetzner-setup.sh
│   └── national-elections-api.service
├── data/                        # .gitignored — on Hetzner volume
│   ├── elections.db
│   └── backups/
├── docs/plans/
│   ├── 2026-04-29-national-election-tracker-design.md
│   ├── 2026-04-29-national-election-tracker-implementation.md
│   └── 2026-04-29-national-election-tracker-feasibility-review.md
├── .gitignore
└── CLAUDE.md                    # This file
```

## Database Design

Single SQLite database. Every table has a `state` column. Uses **stable source-derived keys** for all public-facing IDs (not autoincrement integers).

### Naming Conventions
- **`choices`** not `candidates` — holds both candidate records and ballot measure options (Yes/No)
- **`counties`** not `parishes` — generic term; `county_label` in `states` table handles display (parish/county/borough)
- **`election_key`** format: `{STATE}-{YYYY}-{type}` (e.g., `IN-2024-general`)
- **`race_key`**: deterministic from election_key + office + district + county
- **`choice_key`**: deterministic from race_key + name + party + ballot_order

### Core Tables
- `states` — 2-letter code PK, name, FIPS, county_label, scraper_type
- `counties` — PK (state, code), name, FIPS, slug
- `elections` — election_key (used in URLs), state, date, type, is_official
- `races` — race_key (used in URLs), office_category, office_name, district, is_ballot_measure
- `choices` — choice_key, choice_type (candidate/ballot_option), name, party, outcome, vote_total
- `votes_county` — per-county vote totals per choice per race
- `votes_precinct` — per-precinct vote totals (where available)
- `early_votes` — early/absentee vote totals
- `race_reporting` — precincts reporting/expected per race per county
- `turnout` — qualified voters and voters voted per election per county
- `import_runs` — provenance: every import logged with timestamps, status, record counts
- `source_files` — provenance: URL, filename, SHA-256, fetch timestamp per import
- `data_quality_checks` — reconciliation results per import

### Design Principles
1. **Source-derived stable IDs** — URLs use deterministic keys, not SQLite rowids
2. **Ballot measures modeled explicitly** — `choices` table with `choice_type` field
3. **Race-level reporting** — precincts reporting tracked per race per geography
4. **Provenance tracking** — every import records source, timestamp, file hash
5. **Idempotent imports** — re-running a scraper replaces data cleanly (UPSERT on stable keys)

## URL Convention

All public URLs use stable keys, never database integer IDs:
- `/` — National US map
- `/[state]` — State homepage (e.g., `/in`)
- `/[state]/live` — Election night dashboard
- `/[state]/elections` — All elections for state
- `/[state]/elections/[electionKey]` — Single election (e.g., `/in/elections/IN-2024-general`)
- `/[state]/elections/[electionKey]/[raceKey]` — Race detail

## Execution Strategy

All scraping and data processing runs on Hetzner, not locally. Code is developed locally, pushed to GitHub, pulled on Hetzner, and executed there. This saves bandwidth, keeps DB writes local to the server, and leverages Hetzner's connectivity to SOS APIs.

Pattern: push code → SSH to Hetzner → git pull → run scripts → tail logs → verify.

## API Endpoints (Hetzner FastAPI)

- `GET /api/health` — API status + DB accessibility
- `GET /api/states` — All states with coverage stats
- `GET /api/{state}/elections` — Elections for a state
- `GET /api/{state}/elections/{electionKey}` — Single election with races
- `GET /api/{state}/elections/{electionKey}/races/{raceKey}` — Race detail with county results
- `GET /api/{state}/live/status` — Is election night active?
- `GET /api/{state}/live/races` — All races with current totals
- `GET /api/{state}/live/race/{raceKey}/counties` — County breakdown
- `GET /api/maps/{state}/counties.json` — County TopoJSON

## Design Doc

Full design specification: `docs/plans/2026-04-29-national-election-tracker-design.md`
Implementation plan: `docs/plans/2026-04-29-national-election-tracker-implementation.md`
Feasibility review: `docs/plans/2026-04-29-national-election-tracker-feasibility-review.md`
