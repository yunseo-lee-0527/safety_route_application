"""
graph_loader.py
===============
3개 GeoJSON 로드 → 관악 크롭 → networkx 그래프 + KD-tree + 스쿨존 spatial join.
런타임 캐싱 (@lru_cache — Streamlit/API 공용 싱글턴).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, MultiPolygon


GWANAK_DISTRICT_KO = "관악구"
GWANAK_DISTRICT_EN = "gwanak"


@dataclass
class DataBundle:
    G: nx.Graph
    node_coords: dict          # {node_id: (lat, lon)}
    snap_tree: "SnapTree"
    schools: dict              # {school_name: [gate_node_id, ...]}  라우팅 타깃
    school_centroid: dict      # {school_name: (lat, lon)}  지도 표시용
    school_gates: dict         # {school_name: [{type, lat, lon, node_id}, ...]}  정문/후문 표시용
    zones_gdf: gpd.GeoDataFrame  # 관악 폴리곤들 (오버레이용)
    edge_in_zone: dict         # {(u, v): bool}  스쿨존 비율 계산용
    r_ref: float
    commuting_zones: list      # [(school_name, shapely_geom_wgs84), ...]  핀 → 학교 자동매핑용


class SnapTree:
    """평면 근사 cKDTree wrapper. 관악 영역 정도면 오차 < 1%."""

    def __init__(self, node_coords: dict):
        self.node_ids = list(node_coords.keys())
        latlon = np.array([node_coords[n] for n in self.node_ids])  # (N, 2)
        self._latlon = latlon
        # 평면 근사: lat → m, lon → m * cos(lat0)
        lat0 = float(np.deg2rad(latlon[:, 0].mean()))
        self._mx = 111000.0 * np.cos(lat0)  # m per deg lon
        self._my = 111000.0                  # m per deg lat
        xy = np.column_stack([latlon[:, 1] * self._mx, latlon[:, 0] * self._my])
        self.tree = cKDTree(xy)

    def nearest(self, lat: float, lon: float) -> tuple:
        """returns (node_id, distance_m)"""
        q = np.array([lon * self._mx, lat * self._my])
        dist, idx = self.tree.query(q, k=1)
        return self.node_ids[idx], float(dist)


def _load_edges(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    # 데이터는 이미 관악구 한정. 컬럼 정규화.
    keep = ["walk_edge_id", "source_u", "source_v", "length_m",
            "safety_score_0_1", "walking_type", "crosswalk",
            "edge_safety_basis", "emd_nm", "geometry"]
    gdf = gdf[[c for c in keep if c in gdf.columns]].copy()
    # null safety_score → 0 (보차분리 인도 취급)
    gdf["safety_score_0_1"] = gdf["safety_score_0_1"].fillna(0.0).clip(0.0, 1.0)
    # source_u/v·edge_id가 '89702.0' 같은 float 문자열로 저장된 경우 → float 경유 후 int
    gdf["source_u"] = gdf["source_u"].astype(float).astype("int64")
    gdf["source_v"] = gdf["source_v"].astype(float).astype("int64")
    if "walk_edge_id" in gdf.columns:
        gdf["walk_edge_id"] = gdf["walk_edge_id"].astype(float).astype("int64")
    return gdf


def _load_zones(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if "district" in gdf.columns:
        gdf = gdf[gdf["district"] == GWANAK_DISTRICT_KO].copy()
    return gdf.reset_index(drop=True)


def _load_gates(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if "district" in gdf.columns:
        gdf = gdf[gdf["district"] == GWANAK_DISTRICT_EN].copy()
    return gdf.reset_index(drop=True)


def _build_graph_and_nodes(edges: gpd.GeoDataFrame) -> tuple[nx.Graph, dict]:
    G = nx.Graph()
    node_coords: dict = {}
    for _, row in edges.iterrows():
        u, v = int(row["source_u"]), int(row["source_v"])
        coords = list(row["geometry"].coords)  # [(lon, lat), ...]
        if u not in node_coords:
            node_coords[u] = (coords[0][1], coords[0][0])
        if v not in node_coords:
            node_coords[v] = (coords[-1][1], coords[-1][0])
        length = float(row["length_m"])
        risk = float(row["safety_score_0_1"])
        # MultiGraph 아님: 중복 시 더 짧은(또는 더 안전한) 쪽 채택
        basis = str(row["edge_safety_basis"]) if "edge_safety_basis" in row.index and row["edge_safety_basis"] == row["edge_safety_basis"] else ""
        if G.has_edge(u, v):
            existing = G[u][v]
            if length < existing["length_m"]:
                G[u][v].update(length_m=length, risk=risk,
                               edge_id=int(row["walk_edge_id"]),
                               basis=basis,
                               geom=row["geometry"])
        else:
            G.add_edge(u, v,
                       length_m=length,
                       risk=risk,
                       edge_id=int(row["walk_edge_id"]),
                       basis=basis,
                       geom=row["geometry"])
    return G, node_coords


def _spatial_join_edges_zones(edges: gpd.GeoDataFrame,
                              zones: gpd.GeoDataFrame) -> dict:
    """엣지 → 스쿨존 포함 여부. {(u, v): bool}"""
    if zones.empty:
        return {}
    from shapely.validation import make_valid
    from shapely.ops import unary_union

    zones_fixed = zones.copy()
    zones_fixed["geometry"] = zones_fixed.geometry.apply(make_valid)
    try:
        union_geom = unary_union(list(zones_fixed.geometry))
    except Exception:
        # 부분 합치기 fallback
        union_geom = None
        for g in zones_fixed.geometry:
            union_geom = g if union_geom is None else union_geom.union(g)

    out = {}
    for _, row in edges.iterrows():
        u, v = int(row["source_u"]), int(row["source_v"])
        in_zone = row["geometry"].intersects(union_geom)
        key = (min(u, v), max(u, v))
        out[key] = in_zone
    return out


# 정문 먼저, 후문 다음 순으로 표시 (그 외는 뒤로)
_GATE_ORDER = {"정문": 0, "후문": 1}


def _snap_gates_to_nodes(gates: gpd.GeoDataFrame,
                        snap_tree: SnapTree,
                        max_dist_m: float = 200.0) -> tuple[dict, dict, dict]:
    """학교명 → [노드 id...] / 학교명 → 중심 좌표(lat, lon) / 학교명 → [게이트 상세...].

    게이트 상세는 정문/후문 표시·확인용으로 **모든** 출입문을 보존한다(좌표는 원본).
    라우팅 타깃(schools)에는 보행로에 스냅된(<= max_dist_m) 노드만 넣는다.
    """
    schools: dict = {}
    centroids: dict = {}
    school_gates: dict = {}
    for _, row in gates.iterrows():
        name = str(row["school_name"]).strip()
        gtype = (str(row["gate_type"]).strip() if "gate_type" in row and row["gate_type"] is not None else "") or "출입문"
        lat, lon = float(row["lat"]), float(row["lon"])
        node_id, dist = snap_tree.nearest(lat, lon)
        snapped = dist <= max_dist_m
        # 표시용: 출입문은 스냅 여부와 무관하게 원본 좌표로 모두 기록 (여부 확인 목적)
        school_gates.setdefault(name, []).append({
            "type": gtype, "lat": lat, "lon": lon,
            "node_id": int(node_id) if snapped else None,
        })
        if not snapped:
            continue
        # 라우팅용: 스냅된 노드만 타깃에 추가
        schools.setdefault(name, [])
        if node_id not in schools[name]:
            schools[name].append(node_id)
        centroids.setdefault(name, []).append((lat, lon))
    centroids_mean = {
        name: (float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts])))
        for name, pts in centroids.items()
    }
    for name in school_gates:
        school_gates[name].sort(key=lambda g: _GATE_ORDER.get(g["type"], 9))
    return schools, centroids_mean, school_gates



GWANAK_SGG_CD = "620"


def _load_commuting_zones(path: Path, valid_schools: set) -> list:
    if not path.exists():
        return []
    gdf = gpd.read_file(path, encoding="euc-kr")
    if "SGG_CD" in gdf.columns:
        gdf = gdf[gdf["SGG_CD"] == GWANAK_SGG_CD].copy()
    if gdf.empty:
        return []
    gdf = gdf.to_crs(epsg=4326)
    out = []
    for _, row in gdf.iterrows():
        nm = str(row["HAKGUDO_NM"]).strip()
        if nm.endswith("초통학구역"):
            school = nm[:-len("초통학구역")] + "초등학교"
        else:
            continue
        if school not in valid_schools:
            continue
        out.append((school, row["geometry"]))
    return out


def school_for_point(bundle, lat: float, lon: float):
    from shapely.geometry import Point
    pt = Point(lon, lat)
    for name, geom in bundle.commuting_zones:
        if geom.contains(pt):
            return name
    return None

def _compute_r_ref(edges: gpd.GeoDataFrame) -> float:
    pos = edges["safety_score_0_1"][edges["safety_score_0_1"] > 0]
    return float(pos.mean()) if not pos.empty else 0.5


@lru_cache(maxsize=1)
def load_bundle(base_dir: str | None = None) -> DataBundle:
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "data"
    edges_path = base / "gwanak_walking_edge_safety.geojson"
    zones_path = base / "schoolzones.geojson"
    gates_path = base / "school_gates.geojson"
    commuting_path = base / "elementary_commuting_zone.shp"

    edges = _load_edges(edges_path)
    zones = _load_zones(zones_path)
    gates = _load_gates(gates_path)

    G, node_coords = _build_graph_and_nodes(edges)
    snap_tree = SnapTree(node_coords)
    schools, centroids, school_gates = _snap_gates_to_nodes(gates, snap_tree)
    edge_in_zone = _spatial_join_edges_zones(edges, zones)
    r_ref = _compute_r_ref(edges)
    commuting_zones = _load_commuting_zones(commuting_path, set(schools.keys()))

    return DataBundle(
        G=G,
        node_coords=node_coords,
        snap_tree=snap_tree,
        schools=schools,
        school_centroid=centroids,
        school_gates=school_gates,
        zones_gdf=zones,
        edge_in_zone=edge_in_zone,
        r_ref=r_ref,
        commuting_zones=commuting_zones,
    )



