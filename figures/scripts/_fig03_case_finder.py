"""
Find the best (school, origin) case for Figure 3 — three-mode comparison.

Mode parameters follow the real chatbot code (core/routing.py find_route +
api/main.py _mode_descriptor):

    safest   : alpha_eff = D_MAX/r_ref ≈ 3.09, cap_eff = 0.50
    balanced : alpha_eff = D_MIN/r_ref ≈ 0.10, cap_eff = 0.15
    shortest : alpha_eff = 0.0,                cap_eff = 0.0

All three use alpha_floor = 0.0 (no low-grade safety floor) for fair
comparison. Bisection convergence is handled internally by find_route.

Scoring: (1 - min pairwise Jaccard of path nodes) + relative length spread.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "04_b2c_chatbot"))

from core.graph_loader import load_bundle  # noqa: E402
from core.personas import D_MAX, D_MIN     # noqa: E402
from core.routing import find_route        # noqa: E402

SAMPLE_PER_SCHOOL = 25
MIN_DIST_M = 350.0
MAX_DIST_M = 900.0
SEED = 42


def haversine_m(c1, c2):
    R = 6371000.0
    lat1, lon1 = math.radians(c1[0]), math.radians(c1[1])
    lat2, lon2 = math.radians(c2[0]), math.radians(c2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    bundle = load_bundle()
    G = bundle.G
    coords = bundle.node_coords
    r_ref = bundle.r_ref
    alpha_max = D_MAX / r_ref
    alpha_min = D_MIN / r_ref

    modes = {
        "safest":   {"alpha_eff": alpha_max, "cap_eff": 0.50},
        "balanced": {"alpha_eff": alpha_min, "cap_eff": 0.15},
        "shortest": {"alpha_eff": 0.0,       "cap_eff": 0.0},
    }
    print(f"r_ref={r_ref:.4f}, alpha_max={alpha_max:.3f}, alpha_min={alpha_min:.3f}")
    print()

    zone_by_school = {name: geom for name, geom in bundle.commuting_zones}

    rng = random.Random(SEED)
    results = []

    for school, gate_nodes in bundle.schools.items():
        centroid = bundle.school_centroid[school]
        zone = zone_by_school.get(school)

        cand = []
        for node, latlon in coords.items():
            d = haversine_m(centroid, latlon)
            if not (MIN_DIST_M <= d <= MAX_DIST_M):
                continue
            if zone is not None:
                pt = Point(latlon[1], latlon[0])
                if not zone.contains(pt):
                    continue
            cand.append(node)

        if len(cand) < 3:
            continue
        sample = rng.sample(cand, min(SAMPLE_PER_SCHOOL, len(cand)))

        for src in sample:
            routes = {}
            ok = True
            for name, params in modes.items():
                r = find_route(G=G, src=src, gates=gate_nodes,
                               alpha_eff=params["alpha_eff"],
                               cap_eff=params["cap_eff"],
                               alpha_floor=0.0)
                if r is None or not r.path:
                    ok = False
                    break
                routes[name] = r
            if not ok:
                continue

            if min(routes[m].total_length_m for m in routes) < 200:
                continue

            sets = [set(routes[m].path) for m in routes]
            min_overlap = 1.0
            for i in range(3):
                for j in range(i + 1, 3):
                    iou = len(sets[i] & sets[j]) / max(len(sets[i] | sets[j]), 1)
                    if iou < min_overlap:
                        min_overlap = iou

            lengths = [routes[m].total_length_m for m in routes]
            length_range = (max(lengths) - min(lengths)) / min(lengths)
            score = (1.0 - min_overlap) + length_range

            results.append({
                "school": school,
                "src": src,
                "src_latlon": coords[src],
                "score": score,
                "min_overlap": min_overlap,
                "length_range": length_range,
                "lengths": {m: routes[m].total_length_m for m in routes},
                "alpha_used": {m: routes[m].alpha_used for m in routes},
                "detour": {m: routes[m].detour_ratio for m in routes},
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    print(f"total candidates evaluated: {len(results)}")
    print()
    print("TOP 10 cases (high route diversity):")
    for r in results[:10]:
        L = r["lengths"]; A = r["alpha_used"]; D = r["detour"]
        print(f"  score={r['score']:.3f}  overlap={r['min_overlap']:.3f}  "
              f"range={r['length_range']:.3f}")
        print(f"    {r['school']}, src={r['src']} @ "
              f"({r['src_latlon'][0]:.5f}, {r['src_latlon'][1]:.5f})")
        print(f"    safest   = {L['safest']:.0f} m  (alpha_used={A['safest']:.2f}, detour={D['safest']:.2f})")
        print(f"    balanced = {L['balanced']:.0f} m  (alpha_used={A['balanced']:.2f}, detour={D['balanced']:.2f})")
        print(f"    shortest = {L['shortest']:.0f} m  (alpha_used={A['shortest']:.2f}, detour={D['shortest']:.2f})")
        print()


if __name__ == "__main__":
    main()
