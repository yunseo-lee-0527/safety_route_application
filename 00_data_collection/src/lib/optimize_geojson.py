"""Optimize GeoJSON files for web display.

- Rounds coordinates to 5 decimal places (~1m precision)
- Simplifies LineString geometries (Douglas-Peucker)
- Strips verbose properties to reduce file size

Usage:
    python scripts/optimize_geojson.py
"""
import json
import os
import sys
from pathlib import Path

WEB_DATA = Path(__file__).resolve().parent.parent / 'web' / 'data'

# Decimal places for coordinate rounding (5 = ~1.1m precision)
PRECISION = 5

# Douglas-Peucker tolerance in degrees (~11m at Seoul's latitude)
SIMPLIFY_TOLERANCE = 0.0001

# Properties to KEEP per layer (None = keep all)
KEEP_PROPS = {
    'school_paths_optimal.geojson': ['school', 'gate', 'distance'],
    'school_paths_with_students.geojson': ['school', 'gate', 'distance', 'estimated_students', 'households'],
    'walking_network.geojson': ['length', 'emd_nm', 'crosswalk', 'overpass', 'bridge', 'tunnel', 'building'],
    'residential_buildings.geojson': ['households', 'zone_layer', 'school_nm'],
}

# Files that should have geometry simplification (LineStrings)
SIMPLIFY_FILES = {
    'school_paths_optimal.geojson',
    'school_paths_with_students.geojson',
    'walking_network.geojson',
}


def round_coords(coords, precision):
    """Recursively round coordinates."""
    if isinstance(coords[0], (int, float)):
        return [round(c, precision) for c in coords]
    return [round_coords(c, precision) for c in coords]


def simplify_linestring(coords, tolerance):
    """Douglas-Peucker simplification for a single LineString."""
    if len(coords) <= 2:
        return coords

    # Find the point farthest from the line between first and last
    first, last = coords[0], coords[-1]
    max_dist = 0
    max_idx = 0

    dx = last[0] - first[0]
    dy = last[1] - first[1]
    line_len_sq = dx * dx + dy * dy

    for i in range(1, len(coords) - 1):
        if line_len_sq == 0:
            dist = ((coords[i][0] - first[0]) ** 2 + (coords[i][1] - first[1]) ** 2) ** 0.5
        else:
            t = max(0, min(1, ((coords[i][0] - first[0]) * dx + (coords[i][1] - first[1]) * dy) / line_len_sq))
            proj_x = first[0] + t * dx
            proj_y = first[1] + t * dy
            dist = ((coords[i][0] - proj_x) ** 2 + (coords[i][1] - proj_y) ** 2) ** 0.5
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > tolerance:
        left = simplify_linestring(coords[:max_idx + 1], tolerance)
        right = simplify_linestring(coords[max_idx:], tolerance)
        return left[:-1] + right
    else:
        return [coords[0], coords[-1]]


def simplify_geometry(geom, tolerance):
    """Simplify a GeoJSON geometry object."""
    gtype = geom.get('type', '')
    coords = geom.get('coordinates', [])

    if gtype == 'LineString':
        geom['coordinates'] = simplify_linestring(coords, tolerance)
    elif gtype == 'MultiLineString':
        geom['coordinates'] = [simplify_linestring(line, tolerance) for line in coords]

    return geom


def optimize_file(filepath, keep_props=None, simplify=False):
    """Optimize a single GeoJSON file in-place."""
    name = filepath.name
    size_before = filepath.stat().st_size

    print(f"\n{'='*60}")
    print(f"Processing: {name}")
    print(f"  Size before: {size_before / 1024 / 1024:.1f} MB")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    print(f"  Features: {len(features):,}")

    total_points_before = 0
    total_points_after = 0

    for feat in features:
        geom = feat.get('geometry')
        if not geom:
            continue

        # Count points before
        coords_str = json.dumps(geom.get('coordinates', []))
        total_points_before += coords_str.count(',') // 2 + 1

        # Simplify geometry if applicable
        if simplify:
            simplify_geometry(geom, SIMPLIFY_TOLERANCE)

        # Round coordinates
        if geom.get('coordinates'):
            geom['coordinates'] = round_coords(geom['coordinates'], PRECISION)

        # Count points after
        coords_str = json.dumps(geom.get('coordinates', []))
        total_points_after += coords_str.count(',') // 2 + 1

        # Strip properties
        if keep_props is not None:
            props = feat.get('properties', {})
            feat['properties'] = {k: v for k, v in props.items() if k in keep_props}

    # Write optimized file
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    size_after = filepath.stat().st_size
    reduction = (1 - size_after / size_before) * 100

    print(f"  Size after:  {size_after / 1024 / 1024:.1f} MB  ({reduction:.0f}% reduction)")
    if simplify:
        print(f"  Points: {total_points_before:,} -> {total_points_after:,}")


def main():
    if not WEB_DATA.exists():
        print(f"ERROR: {WEB_DATA} does not exist")
        sys.exit(1)

    geojson_files = sorted(WEB_DATA.glob('*.geojson'))
    if not geojson_files:
        print("No GeoJSON files found")
        sys.exit(1)

    print(f"Found {len(geojson_files)} GeoJSON files in {WEB_DATA}")

    for fp in geojson_files:
        keep = KEEP_PROPS.get(fp.name)
        do_simplify = fp.name in SIMPLIFY_FILES
        optimize_file(fp, keep_props=keep, simplify=do_simplify)

    print(f"\n{'='*60}")
    print("Done! All files optimized.")
    total_size = sum(f.stat().st_size for f in geojson_files)
    print(f"Total size: {total_size / 1024 / 1024:.1f} MB")


if __name__ == '__main__':
    main()
