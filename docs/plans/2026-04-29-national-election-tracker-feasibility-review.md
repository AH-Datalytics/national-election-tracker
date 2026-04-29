# National Election Tracker Feasibility Review

Date: 2026-04-29

## Summary

The design is directionally sound for a 3-state MVP, but it overstates how turnkey the national scale and Ohio historical path are. Indiana is the strongest new-state candidate. Ohio live results are well supported by the current public feed. Ohio historical ingestion should be treated as exploratory rather than a May 4 blocker.

Recommended MVP scope:

- Import Louisiana into the new generalized model.
- Build Indiana historical import and May 5 live polling.
- Build Ohio live polling from the NIST XML feed.
- Ship county-level maps and result views.
- Defer Indiana/Ohio precinct maps, Ohio historical deep ingest, and national trend analysis.

## Architecture Review

The proposed stack can work for an MVP:

- Next.js on Vercel for the frontend.
- FastAPI for the read API.
- SQLite for the first shared election database.
- Vercel Blob or object storage for map assets.
- Per-state scraper adapters.

This is a reasonable architecture for Louisiana, Indiana, and Ohio as a public portfolio tool. It is not yet a fully mature national-scale architecture for every race, every state, multi-year precinct-level results, live snapshots, and long-term auditability.

### Main Scalability Gaps

1. **Storage headroom is probably understated.**

   A 20GB Hetzner volume is enough for the first three states and likely enough for a lightweight 50-state summary database. It is probably not enough if the system keeps raw source files, repeated live snapshots, full precinct geometries, generated vector tiles, import logs, and multi-cycle local-race results.

2. **SQLite is fine for MVP reads, but has a write-concurrency ceiling.**

   SQLite with WAL mode is acceptable for read-heavy traffic and periodic scraper writes. It becomes a constraint if multiple scrapers, live polling jobs, imports, and API reads happen at once. The schema/API should be written so the backend can later move to Postgres or a Postgres-plus-object-storage model without changing the frontend contract.

3. **Raw GeoJSON/TopoJSON is not the right final precinct-map format.**

   For county maps, per-state TopoJSON is fine. For national precinct-level maps, use generated vector tiles or PMTiles, likely built with Tippecanoe. Raw precinct GeoJSON will get too large and slow.

4. **The plan lacks provenance and audit tables.**

   A national election data system needs to know where every row came from and whether it reconciles with source totals. Add:

   - `import_runs`
   - `source_files`
   - `raw_payloads` or archived file paths
   - `live_snapshots`
   - `data_quality_checks`

5. **Public URLs need stable IDs.**

   Do not expose SQLite integer IDs as permanent route params. Rebuilds or reimports can change them. Use deterministic state/source-derived IDs and slugs for elections, races, candidates, and ballot measures.

## Schema Recommendations

The proposed schema is close, but it should be adjusted before implementation.

### Preserve Race-Level Reporting

The existing Louisiana schema stores reporting and turnout by `race_id`. The proposed national schema stores turnout by `election_id + county_code`, which may lose race-specific reporting state. Some sources report participating precincts or contest reporting by race, not only by election.

Recommended split:

- `votes_county`: vote totals only.
- `votes_precinct`: vote totals only.
- `race_reporting`: precincts reporting/expected by race and geography.
- `turnout`: voter registration/ballots cast where the source actually provides it.

### Add Source-Derived IDs

Add stable IDs such as:

- `election_key`: `IN-2024-general`
- `race_key`: deterministic hash or normalized source composite.
- `candidate_key`: deterministic hash from race key, candidate name, party, ballot order, and source choice ID when present.
- `measure_key`: separate deterministic key for referenda/questions.

### Model Ballot Measures Explicitly

Do not force every ballot measure into the candidate table without a clear convention. Indiana referenda provide `YesVotes` and `NoVotes`, not candidate records. Either:

- represent Yes/No as choices in a generalized `choices` table, or
- keep `candidates` but rename it to `choices` so ballot options and candidates share a neutral model.

## Louisiana

Louisiana should be mostly a port from the existing standalone tracker, but not a blind copy.

Existing strengths:

- Mature scraper.
- Known SOS JSON API shape.
- Existing database and map assets.
- Live routes already proved the election-night flow.

Porting considerations:

- Preserve Louisiana's race-level turnout/reporting fields.
- Add `state = 'LA'` across imported rows.
- Convert `parish_code` to the generalized `county_code` naming at the API/model boundary.
- Keep Louisiana-specific source fields where needed instead of over-normalizing away useful details such as `specific_title`, `general_title`, `office_level_code`, `can_have_runoff`, and `is_multi_parish`.

## Indiana

Indiana is the strongest new state in the plan.

### Verified

The following endpoint pattern works for historical office results:

```text
https://enr.indianavoters.in.gov/archive/{Year}{Type}/download/AllOfficeResults.json
```

Verified examples:

```text
https://enr.indianavoters.in.gov/archive/2024General/download/AllOfficeResults.json
https://enr.indianavoters.in.gov/archive/2022General/download/AllOfficeResults.json
```

The field shape matches the design:

- `Election`
- `JurisdictionName`
- `ReportingCountyName`
- `DataEntryJurisdictionName`
- `DataEntryLevelName`
- `Office`
- `OfficeCategory`
- `BallotOrder`
- `NameonBallot`
- `PoliticalParty`
- `Winner`
- `NumberofOfficeSeats`
- `TotalVotes`

Referendum endpoint verified:

```text
https://enr.indianavoters.in.gov/archive/2024General/download/AllRefResults.json
```

### Caveats

1. **No stable source IDs in the flat office feed.**

   The scraper must synthesize deterministic election, race, candidate, precinct, and result keys.

2. **Referenda are shaped differently.**

   `AllRefResults.json` includes fields like:

   - `ReportingJurisdiction`
   - `TypeofReferendum`
   - `ReferendumTitle`
   - `ReferendumText`
   - `DataEntryJurisdictionName`
   - `DataEntryLevelName`
   - `YesVotes`
   - `NoVotes`

   This needs a ballot-measure import path.

3. **Live current-path assumption needs discovery.**

   The current non-archive path checked on 2026-04-29 returned 404:

   ```text
   https://enr.indianavoters.in.gov/download/AllOfficeResults.json
   ```

   The live scraper should discover links from the active ENR page or configure the exact election slug before election night.

4. **Precinct labels need normalization.**

   `DataEntryJurisdictionName` appears to carry precinct/locality names. These are usable for result tables, but not guaranteed to match Census VTD geometry labels.

### Indiana Verdict

The Indiana approach is correct for historical result ingestion and likely good for live results, with these required additions:

- deterministic IDs,
- explicit referendum handling,
- live URL discovery/configuration,
- precinct label normalization and quality reporting.

## Ohio

Ohio live results are correctly described. Ohio historical results are less certain and should not be treated as a fast, reliable Phase 1 task.

### Verified Live Feed

Ohio's live results site is:

```text
https://liveresults.ohiosos.gov/
```

The page states that election results are available in standardized NIST 1500-100 XML and that the feed updates every three minutes during election night.

The actual XML download endpoint is:

```text
https://liveresults.ohiosos.gov/Api/v1/download?filename=VSSC1622XmlFileBlob
```

This returned an XML payload beginning with `ElectionReport` and `Format="SummaryContest"` on 2026-04-29. The payload was marked `IsTest="true"` before election night, which is expected.

The site exposes this through JavaScript:

```javascript
downloadReport('VSSC1622XmlFileBlob')
```

The scraper should call the API download endpoint directly.

### Historical Caveats

The design currently says Ohio historical XLSX files are available at a predictable `globalassets/elections/{YEAR}/{TYPE}/official/...` path. That should be weakened.

Current Ohio results pages redirect toward the Ohio data portal, and local results are also distributed through county board of elections websites. Some official XLSX files are visible in search snippets and historical pages, but the naming/path pattern should be treated as inconsistent and discovery-based.

For Phase 1, Ohio should be:

- live XML parser,
- county-level live result display,
- maybe official statewide/county historical import if a file is easy to obtain,
- not full historical precinct ETL.

### Ohio Verdict

Ohio live is solid. Ohio historical is a Phase 2 exploration item unless a concrete file manifest is built first.

## Map Data

County boundaries are straightforward:

- Use Census county boundaries.
- Generate one simplified TopoJSON/GeoJSON per state.
- Key counties by state FIPS + county FIPS.

Precinct boundaries are the hard part:

- Louisiana is already solved.
- Indiana Census VTDs may be good enough for visual approximation, but may not match live precinct labels.
- Ohio precinct/VTD matching likely needs state/county-specific handling.

Recommendation:

- Phase 1: county maps only for IN/OH.
- Phase 2: precinct result tables.
- Phase 3: precinct geometry matching and vector tiles.

## Revised Phase 1

For a May 4 live test, scope should be:

1. Create new repo and deploy skeleton.
2. Build generalized schema with provenance fields.
3. Import Louisiana data.
4. Build Indiana historical scraper for `AllOfficeResults.json` plus `AllRefResults.json`.
5. Build Indiana live URL discovery/config and polling.
6. Build Ohio NIST XML live parser using the direct download endpoint.
7. Build FastAPI read endpoints for states, elections, races, county results, and live status.
8. Build frontend routes for national map, state pages, election pages, and live pages.
9. Build county maps for LA/IN/OH.
10. Add data-quality checks and an operator checklist for election night.

Explicitly defer:

- Ohio historical XLSX deep ingest.
- Indiana/Ohio precinct maps.
- national shift maps.
- cross-state candidate matching.
- full 50-state storage optimization.

## Recommended Acceptance Criteria

MVP is ready when:

- `/` national map loads and links to LA, IN, OH.
- `/la`, `/in`, and `/oh` state pages load.
- Louisiana imported data matches existing known counts.
- Indiana 2024 General import reconciles candidate totals to source totals.
- Indiana referenda import as ballot measures.
- Ohio live XML endpoint can be fetched and parsed.
- Live API records source timestamp, import timestamp, and `IsTest`/unofficial status.
- County-level result view renders for at least one Indiana race and one Ohio live/test race.
- Scrapers are idempotent.
- Database backup procedure exists before each import.
- API health endpoint exists.

## Final Recommendation

Proceed with the national tracker, but revise the design before implementation. The architecture is good enough for a first public build, but it should be described as an MVP architecture, not the final 50-state architecture.

The most important changes are:

- make Ohio historical data Phase 2,
- add provenance/audit schema now,
- use stable source-derived IDs,
- model ballot measures explicitly,
- keep IN/OH precinct maps out of the May 4 critical path,
- plan vector tiles/PMTiles for true national precinct mapping.

