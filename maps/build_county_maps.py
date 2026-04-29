"""
Build county and state boundary TopoJSON maps from Census TIGER shapefiles.

Downloads Census TIGER 2024 cartographic boundary files, filters/simplifies
them, and outputs TopoJSON files for the frontend map components.

Usage:
    python maps/build_county_maps.py

Output:
    data/maps/la/counties.json   - Louisiana parishes
    data/maps/in/counties.json   - Indiana counties
    data/maps/oh/counties.json   - Ohio counties
    data/maps/us-states.json     - US state boundaries
"""

import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
import topojson

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MAPS_DIR = DATA_DIR / "maps"
DB_PATH = DATA_DIR / "elections.db"

# Cache downloaded shapefiles here (gitignored via *.shp etc.)
CACHE_DIR = PROJECT_ROOT / "_shapefile_cache"

# Census TIGER 2024 cartographic boundary files (1:500k)
COUNTY_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"
)
STATE_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip"
)

# Target states: FIPS -> (2-letter code, name)
TARGET_STATES = {
    "22": ("LA", "Louisiana"),
    "18": ("IN", "Indiana"),
    "39": ("OH", "Ohio"),
}

# All 50 states + DC for the US map (FIPS -> code, name)
ALL_STATES = {
    "01": ("AL", "Alabama"),
    "02": ("AK", "Alaska"),
    "04": ("AZ", "Arizona"),
    "05": ("AR", "Arkansas"),
    "06": ("CA", "California"),
    "08": ("CO", "Colorado"),
    "09": ("CT", "Connecticut"),
    "10": ("DE", "Delaware"),
    "11": ("DC", "District of Columbia"),
    "12": ("FL", "Florida"),
    "13": ("GA", "Georgia"),
    "15": ("HI", "Hawaii"),
    "16": ("ID", "Idaho"),
    "17": ("IL", "Illinois"),
    "18": ("IN", "Indiana"),
    "19": ("IA", "Iowa"),
    "20": ("KS", "Kansas"),
    "21": ("KY", "Kentucky"),
    "22": ("LA", "Louisiana"),
    "23": ("ME", "Maine"),
    "24": ("MD", "Maryland"),
    "25": ("MA", "Massachusetts"),
    "26": ("MI", "Michigan"),
    "27": ("MN", "Minnesota"),
    "28": ("MS", "Mississippi"),
    "29": ("MO", "Missouri"),
    "30": ("MT", "Montana"),
    "31": ("NE", "Nebraska"),
    "32": ("NV", "Nevada"),
    "33": ("NH", "New Hampshire"),
    "34": ("NJ", "New Jersey"),
    "35": ("NM", "New Mexico"),
    "36": ("NY", "New York"),
    "37": ("NC", "North Carolina"),
    "38": ("ND", "North Dakota"),
    "39": ("OH", "Ohio"),
    "40": ("OK", "Oklahoma"),
    "41": ("OR", "Oregon"),
    "42": ("PA", "Pennsylvania"),
    "44": ("RI", "Rhode Island"),
    "45": ("SC", "South Carolina"),
    "46": ("SD", "South Dakota"),
    "47": ("TN", "Tennessee"),
    "48": ("TX", "Texas"),
    "49": ("UT", "Utah"),
    "50": ("VT", "Vermont"),
    "51": ("VA", "Virginia"),
    "53": ("WA", "Washington"),
    "54": ("WV", "West Virginia"),
    "55": ("WI", "Wisconsin"),
    "56": ("WY", "Wyoming"),
}

# Simplification tolerances (in degrees; smaller = more detail)
COUNTY_TOLERANCE = 0.005
STATE_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def download_shapefile(url: str, name: str) -> Path:
    """Download and extract a Census TIGER shapefile zip. Returns extracted dir."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE_DIR / f"{name}.zip"
    extract_dir = CACHE_DIR / name

    if extract_dir.exists() and any(extract_dir.glob("*.shp")):
        print(f"  Using cached {name}")
        return extract_dir

    print(f"  Downloading {url} ...")
    urlretrieve(url, zip_path)
    print(f"  Extracting to {extract_dir} ...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    return extract_dir


def load_county_code_lookup(state_code: str) -> dict[str, str]:
    """
    Build a mapping from 5-digit FIPS (e.g. '22001') to the county `code`
    used in the elections database (e.g. '01' for LA, '001' for IN).
    """
    if not DB_PATH.exists():
        print(f"  WARNING: Database not found at {DB_PATH}, using FIPS county codes")
        return {}

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT fips, code FROM counties WHERE state = ?",
        (state_code,),
    )
    lookup = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return lookup


def build_county_topojson(
    counties_gdf: gpd.GeoDataFrame,
    state_fips: str,
    state_code: str,
) -> dict:
    """
    Filter counties for one state, simplify, and return TopoJSON dict.
    """
    # Filter to this state
    state_counties = counties_gdf[counties_gdf["STATEFP"] == state_fips].copy()
    print(f"  {state_code}: {len(state_counties)} counties/parishes")

    if state_counties.empty:
        print(f"  WARNING: No counties found for FIPS {state_fips}")
        return {}

    # Simplify geometries
    state_counties = state_counties.copy()
    state_counties["geometry"] = state_counties["geometry"].simplify(
        COUNTY_TOLERANCE, preserve_topology=True
    )

    # Build county_code lookup from DB
    code_lookup = load_county_code_lookup(state_code)

    # Build the 5-digit FIPS for each county
    state_counties["fips"] = state_counties["STATEFP"] + state_counties["COUNTYFP"]

    # Map to DB county_code; fall back to COUNTYFP if DB not available
    if code_lookup:
        state_counties["county_code"] = state_counties["fips"].map(
            lambda f: code_lookup.get(f, f[2:])  # fallback: strip state prefix
        )
    else:
        state_counties["county_code"] = state_counties["COUNTYFP"]

    # Keep only the properties we need
    state_counties["name"] = state_counties["NAME"]
    result_gdf = state_counties[["name", "fips", "county_code", "geometry"]].copy()

    # Convert to TopoJSON
    topo = topojson.Topology(
        result_gdf,
        prequantize=1e5,
        toposimplify=0.0001,
        object_name="counties",
    )

    return json.loads(topo.to_json())


def build_us_states_topojson(states_gdf: gpd.GeoDataFrame) -> dict:
    """
    Build a TopoJSON of all US state boundaries with has_data flags.
    """
    # Filter to 50 states + DC (exclude territories)
    valid_fips = set(ALL_STATES.keys())
    us_states = states_gdf[states_gdf["STATEFP"].isin(valid_fips)].copy()
    print(f"  US states: {len(us_states)} features")

    # Simplify
    us_states["geometry"] = us_states["geometry"].simplify(
        STATE_TOLERANCE, preserve_topology=True
    )

    # Add properties
    us_states["code"] = us_states["STATEFP"].map(lambda f: ALL_STATES[f][0])
    us_states["name"] = us_states["STATEFP"].map(lambda f: ALL_STATES[f][1])
    us_states["fips"] = us_states["STATEFP"]
    target_fips = set(TARGET_STATES.keys())
    us_states["has_data"] = us_states["STATEFP"].isin(target_fips)

    # Keep only what we need
    result_gdf = us_states[["code", "name", "fips", "has_data", "geometry"]].copy()

    # Convert to TopoJSON
    topo = topojson.Topology(
        result_gdf,
        prequantize=1e5,
        toposimplify=0.001,
        object_name="states",
    )

    return json.loads(topo.to_json())


def write_json(data: dict, path: Path) -> None:
    """Write JSON to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact output
    size_kb = path.stat().st_size / 1024
    print(f"  Wrote {path} ({size_kb:.1f} KB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 60)
    print("National Election Tracker - Map Builder")
    print("=" * 60)

    # Step 1: Download shapefiles
    print("\n[1/3] Downloading Census TIGER shapefiles...")
    county_dir = download_shapefile(COUNTY_URL, "cb_2024_us_county_500k")
    state_dir = download_shapefile(STATE_URL, "cb_2024_us_state_500k")

    # Step 2: Load into GeoDataFrames
    print("\n[2/3] Loading shapefiles...")
    county_shp = next(county_dir.glob("*.shp"))
    state_shp = next(state_dir.glob("*.shp"))

    counties_gdf = gpd.read_file(county_shp)
    states_gdf = gpd.read_file(state_shp)
    print(f"  Loaded {len(counties_gdf)} counties, {len(states_gdf)} states/territories")

    # Step 3: Build TopoJSON files
    print("\n[3/3] Building TopoJSON files...")

    # County maps for each target state
    for state_fips, (state_code, state_name) in TARGET_STATES.items():
        print(f"\n  --- {state_name} ({state_code}) ---")
        topo_data = build_county_topojson(counties_gdf, state_fips, state_code)
        if topo_data:
            out_path = MAPS_DIR / state_code.lower() / "counties.json"
            write_json(topo_data, out_path)

    # US states map
    print("\n  --- US States ---")
    us_topo = build_us_states_topojson(states_gdf)
    write_json(us_topo, MAPS_DIR / "us-states.json")

    # Summary
    print("\n" + "=" * 60)
    print("Done! Generated map files:")
    for p in sorted(MAPS_DIR.rglob("*.json")):
        size_kb = p.stat().st_size / 1024
        rel = p.relative_to(PROJECT_ROOT)
        print(f"  {rel} ({size_kb:.1f} KB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
