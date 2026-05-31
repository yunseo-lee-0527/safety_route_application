from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import wkt
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
WORK = PROJECT / "data" / "processed" / "service_full_remap"
OUT = ROOT / "road_safety_full_remap_service"
WORK.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

METRIC_CRS = "EPSG:5179"
ROAD_CLASSES = {
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "living_street",
    "busway",
    "service",
    "unclassified",
}

CLASS_VOLUME_DEFAULTS = {
    "trunk": 2275.0,
    "trunk_link": 940.0,
    "primary": 1800.0,
    "primary_link": 800.0,
    "secondary": 480.0,
    "secondary_link": 320.0,
    "tertiary": 260.0,
    "tertiary_link": 90.0,
    "residential": 80.0,
    "living_street": 30.0,
    "busway": 600.0,
    "service": 30.0,
    "unclassified": 80.0,
}


def run(cmd: list[str]) -> None:
    print("RUN", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, cwd=PROJECT, check=True)


def create_base_network() -> Path:
    src = PROJECT / "data" / "raw" / "osm" / "gwanak_osmnx_all.gpkg"
    out = WORK / "gwanak_osmnx_drive_service.gpkg"
    if out.exists():
        out.unlink()
    edges = gpd.read_file(src, layer="edges").to_crs("EPSG:4326")
    nodes = gpd.read_file(src, layer="nodes").to_crs("EPSG:4326")
    edges["road_class"] = edges["road_class"].fillna("").astype(str)
    edges = edges[edges["road_class"].isin(ROAD_CLASSES)].copy()
    node_ids = set(edges["u"].astype(str)).union(set(edges["v"].astype(str)))
    nodes["osmid"] = nodes["osmid"].astype(str)
    nodes = nodes[nodes["osmid"].isin(node_ids)].copy()
    edges.to_file(out, layer="edges", driver="GPKG")
    nodes.to_file(out, layer="nodes", driver="GPKG")
    print(f"base network edges={len(edges):,}, nodes={len(nodes):,}")
    return out


def link_node_table(edges_m: gpd.GeoDataFrame) -> pd.DataFrame:
    left = edges_m[["osm_edge_id", "u"]].rename(columns={"u": "node_id"})
    right = edges_m[["osm_edge_id", "v"]].rename(columns={"v": "node_id"})
    out = pd.concat([left, right], ignore_index=True)
    out["node_id"] = out["node_id"].astype(str)
    return out.drop_duplicates()


def load_facility_points() -> gpd.GeoDataFrame:
    path = PROJECT / "data" / "processed" / "seoul" / "seoul_facility_points_normalized.csv"
    if not path.exists():
        path = Path(r"C:\Users\iy579\schoolzone_analysis\data\processed\seoul\seoul_facility_points_normalized.csv")
    df = pd.read_csv(path, low_memory=False)
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df = df.dropna(subset=["longitude", "latitude", "facility_category"]).copy()
    df = df[df["longitude"].between(124, 132) & df["latitude"].between(33, 39)].copy()
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["longitude"], df["latitude"]), crs="EPSG:4326")


def node_based_facility(
    edges_m: gpd.GeoDataFrame,
    nodes_m: gpd.GeoDataFrame,
    points_m: gpd.GeoDataFrame,
    category: str,
    out_col: str,
    weight_col: str,
    max_distance: float = 80.0,
) -> pd.DataFrame:
    base = pd.DataFrame({"osm_edge_id": edges_m["osm_edge_id"]})
    base[out_col] = 0
    base[weight_col] = 0.0
    pts = points_m[points_m["facility_category"].eq(category)].copy()
    if pts.empty:
        return base
    pts["_src_id"] = range(len(pts))
    nearest = gpd.sjoin_nearest(
        pts,
        nodes_m[["osmid", "geometry"]],
        how="left",
        max_distance=max_distance,
        distance_col="nearest_node_distance_m",
    ).dropna(subset=["osmid"])
    if nearest.empty:
        return base
    nearest = nearest.sort_values(["_src_id", "nearest_node_distance_m"]).drop_duplicates("_src_id")
    nearest["node_id"] = nearest["osmid"].astype(str)
    node_counts = nearest.groupby("node_id").size().reset_index(name=out_col)
    node_edges = link_node_table(edges_m)
    expanded = node_edges.merge(node_counts, on="node_id", how="inner")
    counts = expanded.groupby("osm_edge_id", as_index=False)[out_col].sum()
    incident = node_edges.groupby("node_id").size().reset_index(name="_incident")
    weighted = expanded.merge(incident, on="node_id", how="left")
    weighted[weight_col] = weighted[out_col] / weighted["_incident"]
    weights = weighted.groupby("osm_edge_id", as_index=False)[weight_col].sum()
    return base.drop(columns=[out_col, weight_col]).merge(counts, on="osm_edge_id", how="left").merge(weights, on="osm_edge_id", how="left").fillna({out_col: 0, weight_col: 0.0})


def edge_based_facility(
    edges_m: gpd.GeoDataFrame,
    points_m: gpd.GeoDataFrame,
    category: str,
    out_col: str,
    max_distance: float = 60.0,
) -> pd.DataFrame:
    base = pd.DataFrame({"osm_edge_id": edges_m["osm_edge_id"]})
    base[out_col] = 0
    pts = points_m[points_m["facility_category"].eq(category)].copy()
    if pts.empty:
        return base
    pts["_src_id"] = range(len(pts))
    nearest = gpd.sjoin_nearest(
        pts,
        edges_m[["osm_edge_id", "geometry"]],
        how="left",
        max_distance=max_distance,
        distance_col="nearest_edge_distance_m",
    ).dropna(subset=["osm_edge_id"])
    if nearest.empty:
        return base
    nearest = nearest.sort_values(["_src_id", "nearest_edge_distance_m"]).drop_duplicates("_src_id")
    counts = nearest.groupby("osm_edge_id").size().reset_index(name=out_col)
    return base.drop(columns=[out_col]).merge(counts, on="osm_edge_id", how="left").fillna({out_col: 0})


def nearest_edge_facility(
    edges_m: gpd.GeoDataFrame,
    points_m: gpd.GeoDataFrame,
    category: str,
    out_col: str,
    weight_col: str,
    distance_col: str,
    max_distance: float = 80.0,
) -> pd.DataFrame:
    """Assign each facility point to one nearest road edge.

    Crosswalks and traffic signals used to be attached to the nearest OSM node
    and then expanded to all incident edges. For the road safety index we now
    use the simpler interpretation requested for the report: each point affects
    only the closest drive+service road edge within the search radius.
    """
    work_edges = edges_m.copy()
    uv_min = np.minimum(work_edges["u"].astype(str), work_edges["v"].astype(str))
    uv_max = np.maximum(work_edges["u"].astype(str), work_edges["v"].astype(str))
    work_edges["_physical_edge_id"] = uv_min + "_" + uv_max + "_" + work_edges["key"].astype(str)
    base = pd.DataFrame({"osm_edge_id": work_edges["osm_edge_id"], "_physical_edge_id": work_edges["_physical_edge_id"]})
    base[out_col] = 0
    base[weight_col] = 0.0
    base[distance_col] = np.nan
    pts = points_m[points_m["facility_category"].eq(category)].copy()
    if pts.empty:
        return base
    pts["_src_id"] = range(len(pts))
    nearest = gpd.sjoin_nearest(
        pts,
        work_edges[["osm_edge_id", "_physical_edge_id", "geometry"]],
        how="left",
        max_distance=max_distance,
        distance_col=distance_col,
    ).dropna(subset=["osm_edge_id"])
    if nearest.empty:
        return base.drop(columns=["_physical_edge_id"])
    nearest = nearest.sort_values(["_src_id", distance_col]).drop_duplicates("_src_id")
    counts = nearest.groupby("_physical_edge_id").size().reset_index(name=out_col)
    distances = nearest.groupby("_physical_edge_id", as_index=False)[distance_col].mean()
    result = base.drop(columns=[out_col, weight_col, distance_col]).merge(counts, on="_physical_edge_id", how="left")
    result = result.merge(distances, on="_physical_edge_id", how="left")
    result[out_col] = result[out_col].fillna(0).astype(int)
    result[weight_col] = result[out_col].astype(float)
    return result.drop(columns=["_physical_edge_id"])


def collapse_bidirectional_edges(edges: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    """Collapse u->v and v->u OSM edges into one physical road link.

    OSMnx stores many roads as directed edges. For safety scoring, those two
    directions should not act like two independent roads because the same
    crosswalks, signals, school zones, and facility buffers are usually mapped
    to both. We score one physical link, then walking edges match to that link.
    """
    work = edges.copy()
    for col in ["u", "v", "key"]:
        if col not in work.columns:
            work[col] = ""
        work[col] = work[col].astype(str)

    uv_min = np.minimum(work["u"], work["v"])
    uv_max = np.maximum(work["u"], work["v"])
    work["physical_edge_id"] = uv_min + "_" + uv_max + "_" + work["key"]

    before = len(work)
    duplicate_groups = int((work.groupby("physical_edge_id").size() > 1).sum())

    numeric_cols = [
        c for c in work.columns
        if c != "geometry" and pd.api.types.is_numeric_dtype(work[c])
    ]
    mean_cols = {
        "length_m",
        "traffic_speed_08_09_kmh",
        "traffic_speed_daily_avg_kmh",
        "traffic_speed_used_kmh",
        "traffic_speed_estimated_kmh",
        "traffic_lanes_avg",
        "traffic_lanes_estimated",
        "osm_lanes_numeric",
        "osm_maxspeed_numeric",
    }
    agg = {}
    for col in numeric_cols:
        agg[col] = "mean" if col in mean_cols else "max"

    object_cols = [
        c for c in work.columns
        if c not in numeric_cols and c not in {"geometry", "physical_edge_id"}
    ]
    representative = (
        work.sort_values(["physical_edge_id", "length_m"], ascending=[True, False], na_position="last")
        .drop_duplicates("physical_edge_id")
        [["physical_edge_id", "geometry", *object_cols]]
    )
    numeric = work.groupby("physical_edge_id", as_index=False).agg(agg) if agg else work[["physical_edge_id"]].drop_duplicates()
    collapsed = representative.merge(numeric, on="physical_edge_id", how="left")
    collapsed = gpd.GeoDataFrame(collapsed, geometry="geometry", crs=edges.crs)
    collapsed["directed_edge_count"] = collapsed["physical_edge_id"].map(work.groupby("physical_edge_id").size()).astype(int)
    collapsed["osm_edge_id"] = collapsed["physical_edge_id"]

    meta = {
        "before_directed_edges": int(before),
        "after_physical_edges": int(len(collapsed)),
        "collapsed_directed_edges": int(before - len(collapsed)),
        "duplicate_physical_edge_groups": duplicate_groups,
    }
    return collapsed, meta


def create_facility_gpkg(base_gpkg: Path) -> Path:
    out_dir = WORK / "facilities"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "gwanak_osm_drive_safety_facilities.gpkg"
    if out.exists():
        out.unlink()
    edges = gpd.read_file(base_gpkg, layer="edges")
    edges["osm_edge_id"] = edges["osm_edge_id"].astype(str)
    edges["u"] = edges["u"].astype(str)
    edges["v"] = edges["v"].astype(str)
    edges_m = edges.to_crs(METRIC_CRS)
    points_m = load_facility_points().to_crs(METRIC_CRS)
    minx, miny, maxx, maxy = edges_m.total_bounds
    points_m = points_m.cx[minx - 300 : maxx + 300, miny - 300 : maxy + 300].copy()
    result = edges.copy()
    for frame in [
        nearest_edge_facility(edges_m, points_m, "crosswalk", "crosswalk_count", "crosswalk_weight", "nearest_crosswalk_distance_m"),
        nearest_edge_facility(edges_m, points_m, "signal", "traffic_signal_count", "traffic_signal_weight", "nearest_signal_distance_m"),
        edge_based_facility(edges_m, points_m, "speed_bump", "speed_bump_count"),
        edge_based_facility(edges_m, points_m, "cctv", "cctv_count"),
    ]:
        result = result.merge(frame, on="osm_edge_id", how="left")
    for col in ["crosswalk_count", "traffic_signal_count", "speed_bump_count", "cctv_count"]:
        result[col] = result[col].fillna(0).astype("int64")
    result["is_school_zone"] = 0
    for col in ["crosswalk_weight", "traffic_signal_weight"]:
        result[col] = result[col].fillna(0).astype(float).round(6)
    for col in ["nearest_crosswalk_distance_m", "nearest_signal_distance_m"]:
        result[col] = pd.to_numeric(result[col], errors="coerce").round(3)
    result.to_file(out, layer="edges", driver="GPKG")
    pd.DataFrame(result.drop(columns="geometry")).assign(geometry_wkt=result.geometry.to_wkt()).to_csv(
        out_dir / "gwanak_osm_drive_safety_facilities.csv", index=False, encoding="utf-8-sig"
    )
    print(f"facility remap edges={len(result):,}")
    for col in ["crosswalk_count", "traffic_signal_count", "speed_bump_count", "cctv_count"]:
        print(f"{col}: total={int(result[col].sum()):,}, nonzero={(result[col] > 0).sum():,}")
    return out


def run_existing_mappers(base_gpkg: Path) -> Path:
    accidents_dir = WORK / "accidents"
    traffic_dir = WORK / "traffic"
    for d in [accidents_dir, traffic_dir]:
        d.mkdir(parents=True, exist_ok=True)

    facility_gpkg = create_facility_gpkg(base_gpkg)

    accident_base = PROJECT / "data" / "raw" / "accidents"
    if not (accident_base / "gwanak_children_accidents.csv").exists():
        accident_base = Path(r"C:\Users\iy579\schoolzone_analysis\data\raw\accidents")

    run([
        sys.executable,
        "scripts/map_gwanak_accidents_to_osm.py",
        "--edge-gpkg",
        str(facility_gpkg),
        "--osm-gpkg",
        str(base_gpkg),
        "--children-csv",
        str(accident_base / "gwanak_children_accidents.csv"),
        "--pedestrian-csv",
        str(accident_base / "gwanak_pedestrian_accidents.csv"),
        "--severe-csv",
        str(accident_base / "gwanak_severe_accidents.csv"),
        "--out-dir",
        str(accidents_dir),
    ])
    accident_gpkg = accidents_dir / "gwanak_osm_drive_strict_30_20_with_accidents.gpkg"

    run([
        sys.executable,
        "scripts/map_gwanak_traffic_speed_to_osm.py",
        "--base-gpkg",
        str(accident_gpkg),
        "--out-dir",
        str(traffic_dir),
    ])
    return traffic_dir / "gwanak_osm_drive_child_safety_hybrid_final_with_topis_speed.gpkg"


def estimated_volume(row: pd.Series) -> float:
    base = CLASS_VOLUME_DEFAULTS.get(str(row.get("road_class")), 80.0)
    lanes = row.get("traffic_lanes_estimated")
    try:
        lanes = float(lanes)
    except (TypeError, ValueError):
        lanes = 1.0
    default_lanes = {
        "primary": 4.0,
        "secondary": 2.5,
        "tertiary": 2.0,
        "residential": 1.0,
        "service": 1.0,
        "living_street": 1.0,
    }.get(str(row.get("road_class")), 1.0)
    return float(base * max(0.5, lanes / default_lanes))


def count_points_300m(edges: gpd.GeoDataFrame, points: gpd.GeoDataFrame, out_col: str) -> pd.DataFrame:
    base = pd.DataFrame({"osm_edge_id": edges["osm_edge_id"], out_col: 0})
    if points.empty:
        return base
    buffers = edges[["osm_edge_id", "geometry"]].copy()
    buffers["geometry"] = buffers.geometry.buffer(300)
    joined = gpd.sjoin(points, buffers, how="inner", predicate="within")
    counts = joined.groupby("osm_edge_id").size().reset_index(name=out_col)
    return base.drop(columns=[out_col]).merge(counts, on="osm_edge_id", how="left").fillna({out_col: 0})


def load_childcare_points(bounds) -> gpd.GeoDataFrame:
    files = sorted(
        [p for p in Path(r"C:\Users\iy579\Downloads").glob("*.xls") if "20260430" in p.name],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not files:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    df = pd.read_excel(files[0])
    minx, miny, maxx, maxy = bounds

    # Official Seoul childcare sheet layout, 2026-04-30:
    # col 1 = district, col 4 = operation status, col 16 = latitude, col 17 = longitude.
    # Filter to operating facilities in Gwanak-gu before applying a very small bbox guard.
    district = df.iloc[:, 1].astype(str).str.strip()
    status = df.iloc[:, 4].astype(str).str.strip()
    lat = pd.to_numeric(df.iloc[:, 16], errors="coerce")
    lon = pd.to_numeric(df.iloc[:, 17], errors="coerce")

    pts = pd.DataFrame({"lon": lon, "lat": lat})
    pts = pts[
        district.eq("\uad00\uc545\uad6c")
        & status.eq("\uc815\uc0c1")
        & pts["lon"].between(minx - 0.005, maxx + 0.005)
        & pts["lat"].between(miny - 0.005, maxy + 0.005)
    ].copy()
    return gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy(pts["lon"], pts["lat"]), crs="EPSG:4326")


def score_edges(traffic_gpkg: Path) -> tuple[pd.DataFrame, dict]:
    edges = gpd.read_file(traffic_gpkg, layer="edges").to_crs("EPSG:4326")
    edges["osm_edge_id"] = edges["osm_edge_id"].astype(str)
    # 새 네트워크 매핑은 _hybrid_weight 없이 _weight로 저장 → 통일
    if "pedestrian_accident_hybrid_weight" not in edges.columns and "pedestrian_accident_weight" in edges.columns:
        edges = edges.rename(columns={"pedestrian_accident_weight": "pedestrian_accident_hybrid_weight"})
    edges_m = edges.to_crs(METRIC_CRS)
    bounds = tuple(edges.total_bounds)

    child_pts = load_childcare_points(bounds).to_crs(METRIC_CRS)

    for frame in [
        count_points_300m(edges_m, child_pts, "child_facility_count_300m"),
    ]:
        edges = edges.merge(frame, on="osm_edge_id", how="left")

    edges["estimated_traffic_volume"] = edges.apply(estimated_volume, axis=1).round(2)
    edges["inverse_speed_risk"] = 1.0 / pd.to_numeric(edges["traffic_speed_estimated_kmh"], errors="coerce").clip(lower=1)

    for col in [
        "crosswalk_count",
        "crosswalk_weight",
        "traffic_signal_count",
        "traffic_signal_weight",
        "nearest_crosswalk_distance_m",
        "nearest_signal_distance_m",
        "child_facility_count_300m",
        "pedestrian_accident_hybrid_weight",
    ]:
        if col not in edges.columns:
            edges[col] = 0
        edges[col] = pd.to_numeric(edges[col], errors="coerce").fillna(0)

    edges, collapse_meta = collapse_bidirectional_edges(edges)
    edges_m = edges.to_crs(METRIC_CRS)

    edges["length_m"] = pd.to_numeric(edges["length_m"], errors="coerce").fillna(edges_m.geometry.length)
    edges["length_m_for_density"] = edges["length_m"].clip(lower=20.0)

    for raw_col, density_col, cap_value in [
        ("crosswalk_count", "crosswalk_count_per_100m", 8.0),
        ("traffic_signal_count", "traffic_signal_count_per_100m", 8.0),
    ]:
        edges[density_col] = (
            pd.to_numeric(edges[raw_col], errors="coerce").fillna(0)
            / edges["length_m_for_density"]
            * 100.0
        ).clip(lower=0, upper=cap_value)

    vals = pd.to_numeric(edges["child_facility_count_300m"], errors="coerce").fillna(0).clip(lower=0)
    positive = vals[vals > 0]
    child_cap = float(positive.quantile(0.95)) if len(positive) else 0.0
    child_cap = max(child_cap, 1.0) if len(positive) else 0.0
    edges["child_facility_count_300m_capped"] = vals.clip(upper=child_cap)

    candidate_features = [
        "crosswalk_count_per_100m",
        "traffic_signal_count_per_100m",
        "traffic_lanes_estimated",
        "estimated_traffic_volume",
        "inverse_speed_risk",
        "child_facility_count_300m_capped",
    ]
    transformed = []
    for col in candidate_features:
        tcol = f"{col}_sqrt"
        edges[col] = pd.to_numeric(edges[col], errors="coerce").fillna(0)
        edges[tcol] = np.sqrt(np.clip(edges[col], 0, None))
        transformed.append(tcol)

    target = "pedestrian_accident_hybrid_weight"
    corr = {col: float(edges[col].corr(edges[target])) if edges[col].std() != 0 else 0.0 for col in transformed}
    corr = {col: (0.0 if pd.isna(value) else float(value)) for col, value in corr.items()}
    threshold = float(np.mean([abs(v) for v in corr.values()]))
    selected = [col for col, val in corr.items() if abs(val) >= threshold]
    if not selected:
        selected = transformed

    z = StandardScaler().fit_transform(edges[selected])

    # ────────────────────────────────────────────────────────────────────
    # PDF 충실 그룹 가중치: 1 + |r_group| / Σ|r_groups|
    # 변수별 가중치 w_i는 제거 (PDF는 Σz_i 단순 합)
    # ────────────────────────────────────────────────────────────────────
    def _w_formula(r: float, r_sum: float) -> float:
        if not np.isfinite(r) or r_sum == 0:
            return 1.0
        return round(abs(float(r)) / float(r_sum), 3) + 1.0

    # 그룹 플래그 (PDF 충실: 어린이/노인 시설 분리, 인구 데이터 미확보 → 가중치 무력화)
    edges["wide_road_flag"]            = (edges["traffic_lanes_estimated"] >= 6).astype(int)
    edges["high_traffic_flag"]         = (edges["estimated_traffic_volume"] > edges["estimated_traffic_volume"].mean()).astype(int)
    edges["child_facility_nearby_flag"]   = (edges["child_facility_count_300m_capped"] > 0).astype(int)

    target_series = edges[target]
    group_corr = {
        "road_6lane_or_traffic": float(max(
            abs(edges["wide_road_flag"].corr(target_series)),
            abs(edges["high_traffic_flag"].corr(target_series)),
        )),
        "child_facility":   float(abs(edges["child_facility_nearby_flag"].corr(target_series))),
    }
    group_corr = {k: (0.0 if not np.isfinite(v) else v) for k, v in group_corr.items()}
    corr_sum = sum(group_corr.values())
    group_weights = {k: _w_formula(r, corr_sum) for k, r in group_corr.items()}

    edges["road_6lane_or_traffic_weight"] = np.where(
        (edges["wide_road_flag"] == 1) | (edges["high_traffic_flag"] == 1),
        group_weights["road_6lane_or_traffic"], 1.0,
    )
    # 인구 가중치는 행정경계 shapefile 미확보로 무력화 (PDF의 'LINK_SUM_TAXI == 0이면 1.0' 패턴)
    edges["child_facility_weight"] = np.where(
        edges["child_facility_nearby_flag"] == 1, group_weights["child_facility"], 1.0,
    )
    edges["final_local_method_weight"] = (
        edges["road_6lane_or_traffic_weight"]
        * edges["child_facility_weight"]
    )
    # PDF 충실: Σ z_i (변수별 가중치 w_i 없음) × W
    edges["local_method_risk_index"] = z.sum(axis=1) * edges["final_local_method_weight"]
    edges["local_method_safety_index"] = -edges["local_method_risk_index"]
    edges["local_method_risk_decile"] = (pd.qcut(edges["local_method_risk_index"].rank(method="first"), 10, labels=False) + 1).astype(int)
    edges["geometry_wkt"] = edges.geometry.to_wkt()

    out_cols = [
        "osm_edge_id", "physical_edge_id", "directed_edge_count",
        "road_name", "road_class", "length_m", "length_m_for_density",
        "traffic_lanes_estimated", "traffic_lanes_source", "traffic_speed_estimated_kmh",
        "traffic_speed_estimate_source", "traffic_speed_08_09_kmh", "traffic_speed_daily_avg_kmh",
        "traffic_speed_used_kmh", "traffic_speed_source", "traffic_lanes_avg", "traffic_lanes_max",
        "topis_link_count", "topis_record_count", "estimated_traffic_volume", "inverse_speed_risk",
        "crosswalk_count", "crosswalk_weight", "traffic_signal_count", "traffic_signal_weight",
        "nearest_crosswalk_distance_m", "nearest_signal_distance_m",
        "crosswalk_count_per_100m", "traffic_signal_count_per_100m",
        "child_facility_count_300m", "child_facility_count_300m_capped",
        "road_6lane_or_traffic_weight", "child_facility_weight",
        "final_local_method_weight", "pedestrian_accident_hybrid_weight",
        "local_method_risk_index", "local_method_safety_index", "local_method_risk_decile", "geometry_wkt",
    ]
    for col in out_cols:
        if col not in edges.columns:
            edges[col] = np.nan
    out = pd.DataFrame(edges[out_cols])

    meta = {
        "n_edges": int(len(out)),
        "road_class_counts": {str(k): int(v) for k, v in out["road_class"].value_counts().items()},
        "candidate_features": candidate_features,
        "mean_abs_correlation_for_selection": threshold,
        "selected_transformed_features": selected,
        "correlations_with_target": corr,
        "per_variable_weights": "removed - PDF chungsil sansik (Sum z_i x W)",
        "group_correlations_for_weights": group_corr,
        "applied_group_weights": group_weights,
        "physical_link_collapse": collapse_meta,
        "length_adjustment": {
            "density_denominator": "length_m_for_density = max(length_m, 20m); length is not an independent candidate variable",
            "crosswalk_signal_mapping": "each crosswalk/signal point assigned to one nearest drive+service road edge within 80m",
            "crosswalk_signal_density": "nearest-edge raw counts per 100m, clipped to 8 per 100m",
            "facility_cap": "child facility counts within 300m clipped at positive p95",
        },
        "child_facility_points": int(len(child_pts)),
        "topis_source_counts": {str(k): int(v) for k, v in edges["traffic_speed_estimate_source"].value_counts(dropna=False).items()},
        "score_distribution": {
            "mean": float(out["local_method_risk_index"].mean()),
            "median": float(out["local_method_risk_index"].median()),
            "p95": float(out["local_method_risk_index"].quantile(0.95)),
            "n_nan": int(out["local_method_risk_index"].isna().sum()),
        },
    }
    return out, meta


def write_outputs(out: pd.DataFrame, meta: dict) -> Path:
    utf8 = OUT / "gwanak_road_safety_scores_full_remap_service_utf8.csv"
    cp949 = OUT / "gwanak_road_safety_scores_full_remap_service.csv"
    out.to_csv(utf8, index=False, encoding="utf-8-sig")
    out.to_csv(cp949, index=False, encoding="cp949", errors="replace")
    (OUT / "road_safety_full_remap_service_summary.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selected_lines = "\n".join(f"- `{col}`" for col in meta["selected_transformed_features"])
    candidate_lines = "\n".join(f"- `{col}`" for col in meta["candidate_features"])
    collapse = meta["physical_link_collapse"]
    (OUT / "README.md").write_text(
        f"""# 도로 안전도 지수 산출 방법

이 폴더는 의왕시 방법론의 변수 선택 흐름을 관악구 drive+service 도로망에 적용한 도로 링크별 위험도/안전도 산출물이다.

이번 버전의 핵심 변경사항은 다음과 같다.

- 횡단보도와 신호등은 최근접 OSM node가 아니라 가장 가까운 drive+service 도로 edge에 직접 매핑했다.
- `schoolzone_overlap_share`, 노인의료복지시설, 생활인구 취약비율은 산출 과정과 후보 변수에서 제외했다.
- `length_m`은 독립 후보 변수에서 제외했다. 단, 횡단보도/신호등 밀도를 계산할 때 짧은 링크 보정을 위한 분모로만 사용했다.

## 산출물

| 파일 | 내용 |
|---|---|
| `gwanak_road_safety_scores_full_remap_service_utf8.csv` | UTF-8 도로 링크별 안전도 지수 |
| `gwanak_road_safety_scores_full_remap_service.csv` | CP949 도로 링크별 안전도 지수 |
| `road_safety_full_remap_service_summary.json` | 변수 선택, 상관계수, 그룹 가중치, 점수 분포 요약 |

## 도로망

| 항목 | 값 |
|---|---:|
| 통합 전 directed edge | {collapse['before_directed_edges']:,} |
| 통합 후 physical edge | {collapse['after_physical_edges']:,} |
| 제거된 중복 directed edge | {collapse['collapsed_directed_edges']:,} |

## 횡단보도/신호등 매핑

각 시설 point는 80m 이내 가장 가까운 drive+service 도로 edge 1개에 배정했다. 최근접 검색은 directed edge에서 수행하되, 같은 물리 도로의 양방향 중 한쪽에만 시설물이 붙는 문제를 막기 위해 최근접 edge의 `physical_edge_id`에 count를 부여했다.

## 후보 변수

{candidate_lines}

제외 변수: `length_m`, `schoolzone_overlap_share`, `elderly_medical_facility_count_300m_capped`, `vulnerable_living_population_ratio`.

## 점수 산출

```text
threshold = mean(abs(correlation_i))
selected = variables where abs(correlation_i) >= threshold
base_risk = sum(z_score_i for selected variables)
final_risk = base_risk * final_local_method_weight
safety_index = -final_risk
```

이번 산출의 변수 선택 기준값은 `{meta['mean_abs_correlation_for_selection']:.6f}`이고, 선택 변수는 다음과 같다.

{selected_lines}

최종 그룹 가중치는 도로/교통 그룹과 어린이시설 그룹만 적용했다.
""",
        encoding="utf-8",
    )
    return utf8

def coords_from_wkt(geom_wkt):
    geom = wkt.loads(geom_wkt)
    if geom.geom_type == "LineString":
        return [[y, x] for x, y in geom.coords]
    if geom.geom_type == "MultiLineString":
        return [[[y, x] for x, y in part.coords] for part in geom.geoms]
    return []


def add_line(layer, coords, color, weight, opacity, tooltip=None):
    if not coords:
        return
    if isinstance(coords[0][0], list):
        for part in coords:
            folium.PolyLine(part, color=color, weight=weight, opacity=opacity, tooltip=tooltip).add_to(layer)
    else:
        folium.PolyLine(coords, color=color, weight=weight, opacity=opacity, tooltip=tooltip).add_to(layer)


def create_map(csv_path: Path) -> Path:
    roads = pd.read_csv(csv_path, encoding="utf-8-sig")
    walks = pd.read_csv(ROOT / "walking_edge_safety" / "gwanak_walking_edge_safety_utf8.csv", encoding="utf-8-sig")
    roads["risk_pct"] = roads["local_method_risk_index"].rank(pct=True)
    walks["safety_score_0_1"] = pd.to_numeric(walks["safety_score_0_1"], errors="coerce")

    def color(score):
        if pd.isna(score):
            return "#9ca3af"
        if score < 0.2:
            return "#1a9850"
        if score < 0.4:
            return "#91cf60"
        if score < 0.6:
            return "#ffffbf"
        if score < 0.8:
            return "#fc8d59"
        return "#d73027"

    xs, ys = [], []
    for geom_wkt in walks["geometry_wkt"].dropna().head(300):
        for x, y in wkt.loads(geom_wkt).coords:
            xs.append(x)
            ys.append(y)
    m = folium.Map(location=[sum(ys) / len(ys), sum(xs) / len(xs)], zoom_start=13, tiles="CartoDB positron", prefer_canvas=True)
    road_layer = folium.FeatureGroup(name="Full-remap road risk score", show=True)
    walk_layer = folium.FeatureGroup(name="Walking edge safety score", show=True)
    for _, row in roads.iterrows():
        tooltip = f"Road risk pct: {row['risk_pct']:.3f}<br>Class: {row.get('road_class', '')}<br>Source: full remap"
        add_line(road_layer, coords_from_wkt(row["geometry_wkt"]), color(row["risk_pct"]), 2.1, 0.58, tooltip)
    for _, row in walks.iterrows():
        tooltip = f"Walking score: {row['safety_score_0_1']:.3f}<br>Case: {row.get('edge_safety_basis', '')}"
        add_line(walk_layer, coords_from_wkt(row["geometry_wkt"]), color(row["safety_score_0_1"]), 4, 0.75, tooltip)
    road_layer.add_to(m)
    walk_layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    map_path = ROOT / "road_and_walking_safety_map_full_remap_service.html"
    m.save(map_path)
    return map_path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-remap", action="store_true",
                        help="매핑이 이미 완료된 경우 네트워크 구축/매핑 단계를 건너뛰고 "
                             "의왕시 방법론 산출 단계만 실행한다.")
    args = parser.parse_args()

    if args.skip_remap:
        # 이미 완성된 중간 산출물 사용
        traffic_gpkg = WORK / "traffic" / "gwanak_osm_drive_child_safety_hybrid_final_with_estimated_speed_lanes.gpkg"
        if not traffic_gpkg.exists():
            raise FileNotFoundError(f"중간 산출물 없음: {traffic_gpkg}")
        print(f"[skip-remap] 기존 traffic GPKG 사용: {traffic_gpkg}")
    else:
        base = create_base_network()
        traffic_gpkg = run_existing_mappers(base)

    out, meta = score_edges(traffic_gpkg)
    csv_path = write_outputs(out, meta)
    map_path = create_map(csv_path)
    print(csv_path.resolve())
    print(map_path.resolve())
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
