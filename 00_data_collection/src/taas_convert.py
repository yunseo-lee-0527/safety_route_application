"""
taas_convert.py
---------------
Parse a TAAS / KoROAD traffic-accident GIS JSON response, convert projected
coordinates (EPSG:5179) to WGS84 (lon/lat), and save CSV + GeoJSON outputs.

Reusable: point INPUT_JSON at any TAAS response file and re-run.
"""

import json
import sys
from pathlib import Path

import pandas as pd
from pyproj import Transformer

# ── Configuration ────────────────────────────────────────────────────────────
# BASE_DIR is always the folder that contains this script file,
# so all inputs and outputs stay inside accident_data_request/
# regardless of which directory the script is launched from.
BASE_DIR    = Path(__file__).resolve().parent
INPUT_JSON  = BASE_DIR / "taas_response.json"
OUTPUT_CSV  = BASE_DIR / "taas_accidents_with_latlon.csv"
OUTPUT_GEO  = BASE_DIR / "taas_accidents.geojson"

SRC_CRS = "EPSG:5179"   # Korean TM / GRS80 projected
DST_CRS = "EPSG:4326"   # WGS84 geographic (lon, lat)

# Candidate keys where the record list might live (tried in order)
CANDIDATE_KEYS = ["accidentInfoList", "resultList", "list", "data", "rows", "items"]
# ─────────────────────────────────────────────────────────────────────────────


def find_record_list(obj, depth: int = 0):
    """
    Recursively search for the first list of dicts that looks like accident
    records.  Returns (list, path_string) or (None, None).
    """
    if depth > 4:
        return None, None
    if isinstance(obj, dict):
        for key in CANDIDATE_KEYS:
            if key in obj and isinstance(obj[key], list) and len(obj[key]) > 0:
                if isinstance(obj[key][0], dict):
                    return obj[key], key
        # Not found at this level — recurse into dict values
        for key, val in obj.items():
            found, path = find_record_list(val, depth + 1)
            if found is not None:
                return found, f"{key}.{path}"
    return None, None


# ── 1. Load JSON ──────────────────────────────────────────────────────────────
if not INPUT_JSON.exists():
    sys.exit(f"[ERROR] Input file not found: {INPUT_JSON.resolve()}")

with open(INPUT_JSON, encoding="utf-8") as f:
    raw = json.load(f)

print(f"[INFO] Loaded: {INPUT_JSON}")
print(f"[INFO] Top-level keys: {list(raw.keys())}")

# ── 2. Auto-detect the record list ───────────────────────────────────────────
records, list_path = find_record_list(raw)

if records is None:
    print("[WARN] Could not auto-detect record list. Printing top-level structure:")
    for k, v in raw.items():
        sample = str(v)[:120]
        print(f"  {k!r}: {sample}")
    sys.exit("[ERROR] Please set CANDIDATE_KEYS to include the correct list key.")

print(f"[INFO] Record list found at path: {list_path!r}  ({len(records)} records)")

# ── 3. Build DataFrame ────────────────────────────────────────────────────────
df = pd.DataFrame(records)
total = len(df)
print(f"\n[INFO] Total records loaded : {total}")
print(f"[INFO] Columns ({len(df.columns)}): {list(df.columns)}")

# ── 4. Filter valid coordinates ───────────────────────────────────────────────
# x_crdnt / y_crdnt are the real projected coordinates (integer or float).
# xCrdnt / yCrdnt (camelCase) are dummy zeros — intentionally ignored.
has_coords = (
    df["x_crdnt"].notna() & df["y_crdnt"].notna() &
    (df["x_crdnt"] != 0)  & (df["y_crdnt"] != 0)
)
df_valid = df[has_coords].copy()
valid = len(df_valid)
print(f"[INFO] Records with valid coordinates : {valid}  "
      f"(dropped {total - valid} null/zero)")

if valid == 0:
    sys.exit("[ERROR] No records with valid coordinates found.")

# ── 5 & 6. Project EPSG:5179 → WGS84 ────────────────────────────────────────
# always_xy=True ensures the transformer always treats the first axis as X (easting)
# and second as Y (northing), regardless of CRS axis-order conventions.
transformer = Transformer.from_crs(SRC_CRS, DST_CRS, always_xy=True)

# pyproj.transform expects (x/easting, y/northing) → returns (lon, lat)
lons, lats = transformer.transform(
    df_valid["x_crdnt"].to_numpy(),
    df_valid["y_crdnt"].to_numpy(),
)

# ── 7. Attach lon / lat columns ───────────────────────────────────────────────
df_valid["lon"] = lons
df_valid["lat"] = lats

# ── 10. Basic validation ──────────────────────────────────────────────────────
print(f"\n[VALIDATION]")
print(f"  Longitude  min={df_valid['lon'].min():.6f}  max={df_valid['lon'].max():.6f}")
print(f"  Latitude   min={df_valid['lat'].min():.6f}  max={df_valid['lat'].max():.6f}")
print("\n  First 5 converted coordinates:")
print(df_valid[["x_crdnt", "y_crdnt", "lon", "lat"]].head(5).to_string(index=False))

# Quick sanity check: South Korea roughly 124-132°E, 33-39°N
lon_ok = df_valid["lon"].between(124, 132).all()
lat_ok = df_valid["lat"].between(33, 39).all()
if not (lon_ok and lat_ok):
    print("[WARN] Some coordinates fall outside South Korea bounding box — "
          "double-check the source CRS.")

# ── 8. Save CSV (utf-8-sig for Excel compatibility with Korean text) ───────────
df_valid.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
print(f"\n[OUTPUT] CSV  → {OUTPUT_CSV.resolve()}")

# ── 9. Save GeoJSON (requires geopandas) ─────────────────────────────────────
try:
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(
        df_valid,
        geometry=[Point(x, y) for x, y in zip(df_valid["lon"], df_valid["lat"])],
        crs="EPSG:4326",
    )
    gdf.to_file(OUTPUT_GEO, driver="GeoJSON")
    print(f"[OUTPUT] GeoJSON → {OUTPUT_GEO.resolve()}")
except ImportError:
    print("[SKIP] geopandas not installed — GeoJSON output skipped.")
    print("       Install with: pip install geopandas")

print("\n[DONE]")
