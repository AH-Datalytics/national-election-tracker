"""
Build precinct (VTD) boundary TopoJSON maps from Census TIGER shapefiles.

Downloads Census TIGER 2024 (or 2020) Voting Tabulation District shapefiles,
splits them by county, simplifies geometries, and outputs per-county and
statewide TopoJSON files for the frontend map components.

Usage:
    python maps/build_precinct_maps.py                            # Build all
    python maps/build_precinct_maps.py --state IN                 # Indiana only
    python maps/build_precinct_maps.py --state IN --county 049    # Single county

Output:
    data/maps/in/precincts/001.json       - Per-county precinct boundaries
    data/maps/in/precincts-all.json        - Statewide precinct overview
    data/maps/oh/precincts/001.json
    data/maps/oh/precincts-all.json
"""

import argparse
import json
import sqlite3
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlretrieve

import geopandas as gpd
import topojson

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data")))
MAPS_DIR = Path(os.environ.get("MAPS_DIR", str(DATA_DIR / "maps")))
DB_PATH = Path(os.environ.get("ELECTIONS_DB_PATH", str(DATA_DIR / "elections.db")))

# Cache downloaded shapefiles (gitignored)
CACHE_DIR = PROJECT_ROOT / "_shapefile_cache"

# States we build precinct maps for (FIPS -> (2-letter code, name))
TARGET_STATES = {
    "18": ("IN", "Indiana"),
    "39": ("OH", "Ohio"),
}

# Census TIGER VTD download URLs — try in order until one succeeds
VTD_URL_TEMPLATES = [
    "https://www2.census.gov/geo/tiger/TIGER2024/VTD/tl_2024_{fips}_vtd20.zip",
    "https://www2.census.gov/geo/tiger/TIGER2020PL/LAYER/VTD/2020/tl_2020_{fips}_vtd20.zip",
    "https://www2.census.gov/geo/tiger/TIGER2020/VTD/tl_2020_{fips}_vtd20.zip",
]

# Simplification tolerances (degrees; smaller = more detail)
# Per-county: minimal simplification for high detail
COUNTY_PRECINCT_TOLERANCE = 0.0005
# Statewide overview: aggressive simplification to keep file size small
STATEWIDE_PRECINCT_TOLERANCE = 0.003

# TopoJSON quantization and simplification
COUNTY_TOPOSIMPLIFY = 0.00001   # very little additional topo simplification
STATEWIDE_TOPOSIMPLIFY = 0.001  # more aggressive for statewide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def download_vtd_shapefile(state_fips: str, state_code: str) -> Path:
    """
    Download and extract a Census TIGER VTD shapefile zip.
    Tries multiple URL patterns (2024, then 2020 variants).
    Returns the directory containing extracted .shp files.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_name = f"vtd_{state_code.lower()}_{state_fips}"
    extract_dir = CACHE_DIR / cache_name

    # Check cache first
    if extract_dir.exists() and any(extract_dir.glob("*.shp")):
        print(f"  Using cached VTD shapefile for {state_code}")
        return extract_dir

    # Try each URL template
    zip_path = CACHE_DIR / f"{cache_name}.zip"
    for url_template in VTD_URL_TEMPLATES:
        url = url_template.format(fips=state_fips)
        print(f"  Trying {url} ...")
        try:
            urlretrieve(url, zip_path)
            print(f"  Downloaded successfully.")
            break
        except HTTPError as e:
            print(f"  HTTP {e.code} — trying next URL...")
            continue
    else:
        raise RuntimeError(
            f"Could not download VTD shapefile for {state_code} (FIPS {state_fips}). "
            f"Tried all URL patterns."
        )

    # Extract
    print(f"  Extracting to {extract_dir} ...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    return extract_dir


def load_county_code_lookup(state_code: str) -> tuple[dict[str, str], dict[str, str]]:
    """
    Build mappings from 3-digit county FIPS (COUNTYFP20) to:
      1. The county `code` used in the elections database
      2. The county `name` for display

    For IN and OH, the DB county code IS the 3-digit FIPS code (e.g., '001'),
    so the code mapping is a pass-through. But we still load from DB to be
    safe and to get county names.

    Returns (code_lookup, name_lookup) dicts keyed by 3-digit county FIPS.
    Returns ({}, {}) if the database is not available.
    """
    if not DB_PATH.exists():
        print(f"  WARNING: Database not found at {DB_PATH}, using FIPS county codes")
        return {}, {}

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT fips, code, name FROM counties WHERE state = ?",
        (state_code,),
    )
    # fips is 5-digit (e.g., '18001'), we need county portion (last 3 digits)
    lookup = {}
    names = {}
    for fips5, code, name in cursor.fetchall():
        county_fips_3 = fips5[2:]  # strip state FIPS prefix
        lookup[county_fips_3] = code
        names[county_fips_3] = name
    conn.close()
    return lookup, names


def detect_vtd_columns(gdf: gpd.GeoDataFrame) -> dict:
    """
    Detect the correct column names for VTD fields.
    Census TIGER files may use '20' or '10' suffixes depending on vintage.
    Returns a dict mapping our standard names to actual column names.
    """
    cols = set(gdf.columns)
    mapping = {}

    # VTD code
    for candidate in ["VTDST20", "VTDST10", "VTDST"]:
        if candidate in cols:
            mapping["vtd_code"] = candidate
            break

    # County FIPS
    for candidate in ["COUNTYFP20", "COUNTYFP10", "COUNTYFP"]:
        if candidate in cols:
            mapping["county_fips"] = candidate
            break

    # Name
    for candidate in ["NAMELSAD20", "NAMELSAD10", "NAME20", "NAME10", "NAMELSAD", "NAME"]:
        if candidate in cols:
            mapping["name"] = candidate
            break

    # GEOID
    for candidate in ["GEOID20", "GEOID10", "GEOID"]:
        if candidate in cols:
            mapping["geoid"] = candidate
            break

    # Validate we found everything
    required = ["vtd_code", "county_fips", "name", "geoid"]
    missing = [k for k in required if k not in mapping]
    if missing:
        print(f"  WARNING: Could not detect columns for: {missing}")
        print(f"  Available columns: {sorted(cols)}")
        raise RuntimeError(f"Missing required VTD columns: {missing}")

    print(f"  Column mapping: {mapping}")
    return mapping


def build_county_precinct_topojson(
    county_gdf: gpd.GeoDataFrame,
    col_map: dict,
    county_code: str,
    county_name: str,
) -> dict | None:
    """
    Build a TopoJSON for all precincts in a single county.
    Minimal simplification for high detail.
    """
    if county_gdf.empty:
        return None

    gdf = county_gdf.copy()

    # Simplify geometries (minimal for per-county detail)
    gdf["geometry"] = gdf["geometry"].simplify(
        COUNTY_PRECINCT_TOLERANCE, preserve_topology=True
    )

    # Remove any empty geometries after simplification
    gdf = gdf[~gdf["geometry"].is_empty].copy()

    if gdf.empty:
        return None

    # Build output properties
    result_gdf = gpd.GeoDataFrame(
        {
            "vtd_code": gdf[col_map["vtd_code"]].values,
            "name": gdf[col_map["name"]].values,
            "geoid": gdf[col_map["geoid"]].values,
            "county_code": county_code,
        },
        geometry=gdf["geometry"].values,
        crs=gdf.crs,
    )

    # Convert to TopoJSON
    topo = topojson.Topology(
        result_gdf,
        prequantize=1e5,
        toposimplify=COUNTY_TOPOSIMPLIFY,
        object_name="precincts",
    )

    return json.loads(topo.to_json())


def build_statewide_precinct_topojson(
    state_gdf: gpd.GeoDataFrame,
    col_map: dict,
    code_lookup: dict,
) -> dict | None:
    """
    Build a simplified statewide TopoJSON with all precincts.
    Aggressive simplification to keep file size reasonable.
    """
    if state_gdf.empty:
        return None

    gdf = state_gdf.copy()

    # Aggressive simplification for statewide overview
    gdf["geometry"] = gdf["geometry"].simplify(
        STATEWIDE_PRECINCT_TOLERANCE, preserve_topology=True
    )

    # Remove empty geometries
    gdf = gdf[~gdf["geometry"].is_empty].copy()

    if gdf.empty:
        return None

    # Map county FIPS to DB county codes
    county_fips_col = col_map["county_fips"]
    if code_lookup:
        county_codes = gdf[county_fips_col].map(
            lambda f: code_lookup.get(f, f)
        )
    else:
        county_codes = gdf[county_fips_col]

    result_gdf = gpd.GeoDataFrame(
        {
            "vtd_code": gdf[col_map["vtd_code"]].values,
            "county_fips": gdf[county_fips_col].values,
            "county_code": county_codes.values,
            "name": gdf[col_map["name"]].values,
            "geoid": gdf[col_map["geoid"]].values,
        },
        geometry=gdf["geometry"].values,
        crs=gdf.crs,
    )

    # Convert to TopoJSON
    topo = topojson.Topology(
        result_gdf,
        prequantize=1e5,
        toposimplify=STATEWIDE_TOPOSIMPLIFY,
        object_name="precincts",
    )

    return json.loads(topo.to_json())


def write_json(data: dict, path: Path) -> None:
    """Write JSON to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact output
    size_kb = path.stat().st_size / 1024
    print(f"  Wrote {path.relative_to(PROJECT_ROOT)} ({size_kb:.1f} KB)")


# ---------------------------------------------------------------------------
# Main build logic
# ---------------------------------------------------------------------------


def build_state_precincts(
    state_fips: str,
    state_code: str,
    state_name: str,
    county_filter: str | None = None,
) -> None:
    """
    Build all precinct TopoJSON files for one state.
    If county_filter is set, only build that county.
    """
    print(f"\n{'=' * 60}")
    print(f"  {state_name} ({state_code}) — FIPS {state_fips}")
    print(f"{'=' * 60}")

    # Step 1: Download VTD shapefile
    print("\n  [1/4] Downloading VTD shapefile...")
    vtd_dir = download_vtd_shapefile(state_fips, state_code)

    # Step 2: Load into GeoDataFrame
    print("\n  [2/4] Loading shapefile...")
    shp_file = next(vtd_dir.glob("*.shp"))
    gdf = gpd.read_file(shp_file)
    print(f"  Loaded {len(gdf)} VTD features")
    print(f"  Columns: {list(gdf.columns)}")

    # Detect column names
    col_map = detect_vtd_columns(gdf)
    county_fips_col = col_map["county_fips"]

    # Step 3: Load county code mapping from DB
    print("\n  [3/4] Loading county code mapping...")
    code_lookup, name_lookup = load_county_code_lookup(state_code)

    if code_lookup:
        print(f"  Loaded {len(code_lookup)} county mappings from database")
    else:
        print("  No database — using FIPS codes directly")

    # Get unique counties in the VTD data
    all_county_fips = sorted(gdf[county_fips_col].unique())
    print(f"  Found {len(all_county_fips)} counties in VTD data")

    # Filter to specific county if requested
    if county_filter:
        # county_filter could be a FIPS code or a DB code — check both
        matching_fips = []
        for fips3 in all_county_fips:
            db_code = code_lookup.get(fips3, fips3) if code_lookup else fips3
            if fips3 == county_filter or db_code == county_filter:
                matching_fips.append(fips3)
        if not matching_fips:
            print(f"  ERROR: County '{county_filter}' not found in VTD data")
            print(f"  Available county FIPS: {all_county_fips[:10]}...")
            return
        all_county_fips = matching_fips
        print(f"  Filtered to county: {county_filter}")

    # Step 4: Build per-county and statewide files
    print(f"\n  [4/4] Building TopoJSON files...")
    state_lower = state_code.lower()
    precincts_dir = MAPS_DIR / state_lower / "precincts"
    total_features = 0
    county_count = 0

    for county_fips_3 in all_county_fips:
        # Get county code for filename
        county_code = code_lookup.get(county_fips_3, county_fips_3) if code_lookup else county_fips_3
        county_name = name_lookup.get(county_fips_3, county_fips_3) if name_lookup else county_fips_3

        # Filter VTDs for this county
        county_gdf = gdf[gdf[county_fips_col] == county_fips_3]
        n_precincts = len(county_gdf)

        if n_precincts == 0:
            continue

        # Build per-county TopoJSON
        topo_data = build_county_precinct_topojson(
            county_gdf, col_map, county_code, county_name
        )

        if topo_data:
            out_path = precincts_dir / f"{county_code}.json"
            write_json(topo_data, out_path)
            total_features += n_precincts
            county_count += 1
            print(f"    {county_code} ({county_name}): {n_precincts} precincts")

    print(f"\n  Per-county summary: {county_count} counties, {total_features} total precincts")

    # Build statewide overview (skip if only building one county)
    if not county_filter:
        print(f"\n  Building statewide overview...")
        statewide_topo = build_statewide_precinct_topojson(gdf, col_map, code_lookup)
        if statewide_topo:
            statewide_path = MAPS_DIR / state_lower / "precincts-all.json"
            write_json(statewide_topo, statewide_path)
    else:
        print(f"\n  Skipping statewide file (--county filter active)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build precinct (VTD) boundary TopoJSON maps from Census TIGER shapefiles."
    )
    parser.add_argument(
        "--state",
        type=str,
        help="2-letter state code to build (e.g., IN, OH). Omit to build all.",
    )
    parser.add_argument(
        "--county",
        type=str,
        help="3-digit county FIPS/code to build (e.g., 049). Requires --state.",
    )
    args = parser.parse_args()

    if args.county and not args.state:
        parser.error("--county requires --state")

    # Normalize state code
    state_filter = args.state.upper() if args.state else None

    print("=" * 60)
    print("National Election Tracker - Precinct Map Builder")
    print("=" * 60)

    # Determine which states to build
    states_to_build = {}
    for fips, (code, name) in TARGET_STATES.items():
        if state_filter and code != state_filter:
            continue
        states_to_build[fips] = (code, name)

    if state_filter and not states_to_build:
        print(f"\nERROR: State '{state_filter}' not in target states.")
        print(f"Available: {', '.join(code for code, _ in TARGET_STATES.values())}")
        sys.exit(1)

    # Build each state
    for state_fips, (state_code, state_name) in states_to_build.items():
        build_state_precincts(state_fips, state_code, state_name, args.county)

    # Final summary
    print("\n" + "=" * 60)
    print("Done! Generated precinct map files:")
    for state_fips, (state_code, state_name) in states_to_build.items():
        state_lower = state_code.lower()
        precinct_dir = MAPS_DIR / state_lower / "precincts"
        if precinct_dir.exists():
            files = sorted(precinct_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files)
            print(f"\n  {state_code} per-county: {len(files)} files, {total_size / 1024:.1f} KB total")
            for f in files[:5]:
                size_kb = f.stat().st_size / 1024
                print(f"    {f.relative_to(PROJECT_ROOT)} ({size_kb:.1f} KB)")
            if len(files) > 5:
                print(f"    ... and {len(files) - 5} more")

        statewide = MAPS_DIR / state_lower / "precincts-all.json"
        if statewide.exists():
            size_kb = statewide.stat().st_size / 1024
            print(f"  {state_code} statewide: {statewide.relative_to(PROJECT_ROOT)} ({size_kb:.1f} KB)")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
