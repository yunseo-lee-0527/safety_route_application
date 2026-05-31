"""
보행 edge 안전도 v2: 보차 분리 여부 + 횡단 여부 기반 케이스 분류

케이스 우선순위: D(횡단) > B(외길 겹침) > A(보차 분리) > C(차도 없음)
점수 [0=안전, 1=위험]: D·B는 건너거나 겹치는 도로의 위험도 percentile rank, A·C는 0.

출력: yunseo_lee/walking_edge_safety/
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
ROAD_CSV = ROOT / "yunseo_lee" / "road_safety_full_remap_service" / "gwanak_road_safety_scores_full_remap_service_utf8.csv"
WALK_CSV = ROOT / "data" / "raw" / "seoul_walking_network_download.csv"
OUT_DIR = ROOT / "yunseo_lee" / "walking_edge_safety"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 좌표계
# ---------------------------------------------------------------------------
WGS84 = "EPSG:4326"
METRIC = "EPSG:5179"

# ---------------------------------------------------------------------------
# 임계값 (설계서 §4)
# ---------------------------------------------------------------------------
NEAREST_CROSS_M = 80.0          # Case D crossing: 중점~도로 최대 탐색 거리
CROSSING_SNAP_M = 2.0           # near-miss road crossing tolerance
CROSSWALK_MAX_M = 80.0          # Case D crosswalk: 횡단보도 중점~차도 거리 상한 (폴백)
B_OVERLAP_M = 5.0               # Case B: 도로와의 최대 거리
B_PARALLEL_ANGLE_DEG = 30.0     # Case B: 방향 차이 최대각 (완화: 15→30)
B_OVERLAP_RATIO = 0.5           # Case B: 겹침 비율 (완화: 0.7→0.5)
A_SIDE_BUFFER_M = 10.0          # Case A: 도로 좌/우 탐색 거리
A_SIDE_PARALLEL_ANGLE_DEG = 15.0
A_SIDE_OVERLAP_RATIO = 0.5      # Case A: 도로 길이 기준 겹침 비율
C_NO_ROAD_M = 80.0              # Case C: 차도 없음 반경
B_NEAREST_FALLBACK_M = 80.0     # Case B 폴백: 1111 타입의 미분류 link를 nearest road와 매칭
A_1111_MIN_SEPARATION_M = 3.0   # 1111 separated path: below this is likely shared roadway
A_1111_MAX_SEPARATION_M = 25.0  # beyond this, road exposure is too indirect
A_1111_PARALLEL_ANGLE_DEG = 20.0
A_1111_OVERLAP_RATIO = 0.55
A_1111_MIN_LENGTH_M = 20.0
                                 # C_NO_ROAD_M(80m)과 동일하게 맞춰 unclassified=0 달성.
                                 # C와 B 폴백 사이 gap 없음:
                                 #   ≥80m → case_C (차도 없음, 0.0)
                                 #   <80m → case_B_nearest_road (도로 위험도 전이)

# walking_type 코드: A-1에 포함할 보행자 전용·자전거 공유 코드
PEDESTRIAN_TYPES = {"1000", "1011"}
MAJOR_ROAD_CLASSES = {
    "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "busway",
}
LOCAL_SEPARATED_ROAD_CLASSES = {"residential", "living_street"}
A_1111_LOCAL_MAX_SEPARATION_M = 18.0
A_1111_LOCAL_PARALLEL_ANGLE_DEG = 15.0
A_1111_LOCAL_OVERLAP_RATIO = 0.70
A_1111_LOCAL_MIN_LENGTH_M = 25.0

# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _line_angle(geom) -> float | None:
    """선형 geometry의 방향각(도, 0~180)."""
    parts = list(geom.geoms) if geom.geom_type.startswith("Multi") else [geom]
    longest = max(parts, key=lambda g: g.length, default=None)
    if longest is None or longest.length <= 0:
        return None
    coords = list(longest.coords)
    if len(coords) < 2:
        return None
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    angle = math.degrees(math.atan2(dy, dx)) % 180
    return angle


def _angle_diff(a1: float | None, a2: float | None) -> float:
    """두 방향각(0~180) 차이. 어느 하나가 None이면 90 반환."""
    if a1 is None or a2 is None:
        return 90.0
    diff = abs(a1 - a2) % 180
    return min(diff, 180 - diff)


def _midpoint(geom) -> Point:
    return geom.interpolate(0.5, normalized=True)


def _overlap_length(g1, g2_buffered) -> float:
    """g1과 g2_buffered의 교차 길이(g1 기준 선형 길이 추정)."""
    try:
        inter = g1.intersection(g2_buffered)
        if inter.is_empty:
            return 0.0
        if inter.geom_type in ("LineString", "MultiLineString"):
            return inter.length
        if inter.geom_type in ("GeometryCollection",):
            total = 0.0
            for g in inter.geoms:
                if g.geom_type in ("LineString", "MultiLineString"):
                    total += g.length
            return total
        return 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

def load_roads() -> gpd.GeoDataFrame:
    df = pd.read_csv(ROAD_CSV, encoding="utf-8-sig")
    df = df.dropna(subset=["geometry_wkt", "local_method_risk_index"]).copy()
    df["geometry"] = df["geometry_wkt"].map(wkt.loads)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=WGS84)
    gdf = gdf.to_crs(METRIC)
    # percentile rank (전체 관악구 도로 분포 기준)
    gdf["risk_pct"] = gdf["local_method_risk_index"].rank(pct=True, method="average")
    print(f"[도로] {len(gdf):,}개 로드 완료 (risk_pct 범위 {gdf['risk_pct'].min():.3f}~{gdf['risk_pct'].max():.3f})")
    return gdf


def load_walking(roads_metric: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    raw = pd.read_csv(WALK_CSV, encoding="cp949")
    raw = raw[raw["노드링크 유형"].astype(str).eq("LINK")].copy()
    raw = raw[raw["시군구명"].astype(str).eq("관악구")].copy()
    raw = raw[raw["링크 WKT"].astype(str).str.startswith("LINESTRING", na=False)].copy()
    raw["geometry"] = raw["링크 WKT"].map(wkt.loads)
    walk = gpd.GeoDataFrame(raw, geometry="geometry", crs=WGS84)
    walk["walk_edge_id"] = raw["링크 ID"].astype(str)
    walk["length_m"]     = pd.to_numeric(raw["링크 길이"], errors="coerce")
    # "1111.0" 같은 float 문자열 → 정수 문자열로 정규화 (zero-padded 4자리)
    _wt = pd.to_numeric(raw["링크 유형 코드"], errors="coerce").fillna(-1).astype(int)
    walk["walking_type"] = _wt.map(lambda v: f"{v:04d}" if v >= 0 else "NA")
    walk["emd_nm"]       = raw["읍면동명"].astype(str)
    walk["crosswalk"]    = pd.to_numeric(raw["횡단보도"], errors="coerce").fillna(0).astype(int)
    walk["overpass"]     = pd.to_numeric(raw["육교"],     errors="coerce").fillna(0).astype(int)
    walk["bridge"]       = pd.to_numeric(raw["교량"],     errors="coerce").fillna(0).astype(int)
    walk["tunnel"]       = pd.to_numeric(raw["터널"],     errors="coerce").fillna(0).astype(int)
    walk["building"]     = pd.to_numeric(raw["건물내"],   errors="coerce").fillna(0).astype(int)
    walk["park_green"]   = pd.to_numeric(raw["공원,녹지"],errors="coerce").fillna(0).astype(int)
    walk["source_u"]     = raw["시작노드 ID"].astype(str)
    walk["source_v"]     = raw["종료노드 ID"].astype(str)
    walk = walk.to_crs(METRIC)
    walk["length_m"] = walk["length_m"].fillna(walk.geometry.length)
    print(f"[보행망] {len(walk):,}개 로드 완료 (관악구 LINK)")
    return walk


# ---------------------------------------------------------------------------
# Case A-2 사전 계산: 도로 좌/우에 평행 보행 link 양쪽 존재 → A 마킹
# ---------------------------------------------------------------------------

def _true_half_buffers(road_geom, buf_m: float):
    """
    도로 geometry 법선 방향 기반 좌/우 반버퍼.
    좌측: 전체 버퍼에서 오른쪽 절반을 빼는 방식 대신,
    도로 중심선에서 법선을 따라 좌/우를 구분.
    실용 근사: 전체 버퍼를 두 사분면으로 나누는 대신,
    단순히 도로 중심선을 매우 약간 오프셋해 좌/우 폴리곤을 생성.
    """
    try:
        left_offset  = road_geom.offset_curve(buf_m * 0.5)   # 좌측
        right_offset = road_geom.offset_curve(-buf_m * 0.5)  # 우측
        left_poly  = road_geom.buffer(buf_m).intersection(left_offset.buffer(buf_m))
        right_poly = road_geom.buffer(buf_m).intersection(right_offset.buffer(buf_m))
        return left_poly, right_poly
    except Exception:
        fb = road_geom.buffer(buf_m)
        return fb, fb


def mark_case_a_two_sided(
    walk_m: gpd.GeoDataFrame,
    roads_m: gpd.GeoDataFrame,
) -> set[str]:
    """
    각 도로 link 양쪽에 평행 보행 link가 있으면 그 보행 link ID를 반환.
    """
    walk_sindex = walk_m.sindex
    road_angle = roads_m.geometry.map(_line_angle)

    a_ids: set[str] = set()

    for road_idx, road_row in roads_m.iterrows():
        road_geom = road_row.geometry
        road_len  = road_geom.length
        r_angle   = road_angle.loc[road_idx]

        # 도로 주변 보행 link 후보
        buf = road_geom.buffer(A_SIDE_BUFFER_M)
        cands_idx = list(walk_sindex.query(buf, predicate="intersects"))
        if not cands_idx:
            continue

        left_sides  = []
        right_sides = []

        left_buf, right_buf = _true_half_buffers(road_geom, A_SIDE_BUFFER_M)

        for ci in cands_idx:
            wrow = walk_m.iloc[ci]
            w_angle = _line_angle(wrow.geometry)
            if _angle_diff(r_angle, w_angle) > A_SIDE_PARALLEL_ANGLE_DEG:
                continue
            # 겹침 비율 (도로 길이 기준)
            if road_len > 0:
                ov = _overlap_length(road_geom, wrow.geometry.buffer(A_SIDE_BUFFER_M))
                ratio = ov / road_len
            else:
                ratio = 0.0
            if ratio < A_SIDE_OVERLAP_RATIO:
                continue
            wid = wrow["walk_edge_id"]
            w_geom = wrow.geometry
            in_left  = left_buf.contains(w_geom.centroid) if not left_buf.is_empty else False
            in_right = right_buf.contains(w_geom.centroid) if not right_buf.is_empty else False
            if in_left:
                left_sides.append(wid)
            if in_right:
                right_sides.append(wid)

        if left_sides and right_sides:
            a_ids.update(left_sides)
            a_ids.update(right_sides)

    print(f"[Case A-2] 도로 양쪽 평행 보행 link: {len(a_ids):,}개")
    return a_ids


# ---------------------------------------------------------------------------
# 메인 분류 루프
# ---------------------------------------------------------------------------

def classify(walk_m: gpd.GeoDataFrame, roads_m: gpd.GeoDataFrame) -> pd.DataFrame:
    roads_sindex = roads_m.sindex
    road_angle   = roads_m.geometry.map(_line_angle)

    # Case A-2 사전 계산
    print("[Case A-2] 도로 양쪽 평행 보행 link 사전 계산 중...")
    case_a2_ids = mark_case_a_two_sided(walk_m, roads_m)

    records = []
    special_near_road_warnings = []

    for i, row in enumerate(walk_m.itertuples(), 1):
        if i % 1000 == 0:
            print(f"  분류 중... {i:,}/{len(walk_m):,}")

        wid      = row.walk_edge_id
        geom     = row.geometry
        length   = row.length_m if not (isinstance(row.length_m, float) and np.isnan(row.length_m)) else geom.length
        w_angle  = _line_angle(geom)
        w_type   = str(row.walking_type)

        rec: dict[str, Any] = {
            "walk_edge_id":           wid,
            "source_u":               row.source_u,
            "source_v":               row.source_v,
            "length_m":               length,
            "walking_type":           w_type,
            "crosswalk":              row.crosswalk,
            "overpass":               row.overpass,
            "bridge":                 row.bridge,
            "tunnel":                 row.tunnel,
            "building":               row.building,
            "park_green":             row.park_green,
            "emd_nm":                 row.emd_nm,
            "edge_safety_basis":      None,
            "case_A_subtype":         None,
            "matched_road_id":        None,
            "matched_road_risk_index":None,
            "matched_road_risk_pct":  None,
            "safety_score_0_1":       np.nan,
            "geometry_wkt":           None,  # 루프 후 walk_m 전체 geometry에서 일괄 변환
        }

        # ── 0단계. Priority 0: crosswalk=1 (최우선) ──────────────────────────
        # crosswalk=1이면 반드시 case_D_crosswalk로 분류하고 이후 단계로 내려가지 않음.
        #
        # 도로 선택 우선순위: ① 각도 ≥45° + 거리 ≤2m 기하 교차 → 가장 수직인 도로
        #                    ② 해당 없으면 CROSSWALK_MAX_M 이내 가장 수직인 도로 (폴백)
        #                    ③ 그것도 없으면 case_C_no_nearby_road (score=0.0)
        # → angle_diff 우선(실제로 건너는 도로 선택) → 거리 → 위험도 순으로 정렬.
        if int(row.crosswalk) == 1:
            mid = _midpoint(geom)

            # ① 기하 교차 차도 탐색 (angle≥45°, dist≤CROSSING_SNAP_M)
            crossing_cands = []
            for ci in list(roads_sindex.query(geom.buffer(CROSSING_SNAP_M), predicate="intersects")):
                road_geom = roads_m.geometry.iloc[ci]
                ad = _angle_diff(w_angle, road_angle.iloc[ci])
                if ad < 45.0:
                    continue
                dist = float(geom.distance(road_geom))
                if dist > CROSSING_SNAP_M:
                    continue
                try:
                    inter = geom.intersection(road_geom)
                except Exception:
                    inter = None
                inter_len = 0.0
                if inter is not None and not inter.is_empty:
                    inter_len = inter.length if inter.geom_type in ("LineString", "MultiLineString") else 0.0
                if inter_len <= 1.0:
                    crossing_cands.append((ci, ad, dist))

            if crossing_cands:
                # angle_diff 최대 → 거리 최소 → risk_pct 최대 순으로 선택
                ranked = [(ad, -dist, float(roads_m.iloc[ci]["risk_pct"]), ci)
                          for ci, ad, dist in crossing_cands]
                best_ad, neg_dist, _, best = max(ranked)
                best_row = roads_m.iloc[best]
                rec["edge_safety_basis"]           = "case_D_crosswalk"
                rec["matched_road_id"]             = best_row["osm_edge_id"]
                rec["matched_road_risk_index"]     = best_row["local_method_risk_index"]
                rec["matched_road_risk_pct"]       = best_row["risk_pct"]
                rec["safety_score_0_1"]            = float(best_row["risk_pct"])
                rec["crosswalk_midpoint_road_id"]  = best_row["osm_edge_id"]
                rec["crosswalk_midpoint_road_distance_m"] = float(-neg_dist)
                records.append(rec)
                continue

            # ② 폴백: CROSSWALK_MAX_M 이내 가장 수직에 가까운 차도
            near_cands = list(roads_sindex.query(mid.buffer(CROSSWALK_MAX_M), predicate="intersects"))
            if near_cands:
                perp = [(ci, _angle_diff(w_angle, road_angle.iloc[ci])) for ci in near_cands]
                perp_ok = [(ci, ad) for ci, ad in perp if ad >= 30.0]
                if perp_ok:
                    best = max(perp_ok, key=lambda x: x[1])[0]
                else:
                    dists = [roads_m.geometry.iloc[ci].distance(mid) for ci in near_cands]
                    best = near_cands[int(np.argmin(dists))]
                best_row = roads_m.iloc[best]
                rec["edge_safety_basis"]           = "case_D_crosswalk"
                rec["matched_road_id"]             = best_row["osm_edge_id"]
                rec["matched_road_risk_index"]     = best_row["local_method_risk_index"]
                rec["matched_road_risk_pct"]       = best_row["risk_pct"]
                rec["safety_score_0_1"]            = float(best_row["risk_pct"])
                rec["crosswalk_midpoint_road_id"]  = best_row["osm_edge_id"]
                rec["crosswalk_midpoint_road_distance_m"] = float(roads_m.geometry.iloc[best].distance(mid))
            else:
                # ③ 80m 이내 차도 없음
                rec["edge_safety_basis"] = "case_C_no_nearby_road"
                rec["safety_score_0_1"]  = 0.0
            records.append(rec)
            continue  # crosswalk=1은 항상 여기서 종료

        # crosswalk=1이 아닌 링크에 한해 특수 시설 판정.
        # building=1은 지하철역/건물내 보행망에 넓게 붙어 도심 교차부를
        # 과도하게 0점 처리하므로 특수 안전시설에서 제외한다.
        special_flags = {
            "overpass": row.overpass,
            "bridge":   row.bridge,
            "tunnel":   row.tunnel,
            "park_green": row.park_green,
        }
        triggered = [k for k, v in special_flags.items() if int(v) == 1]
        if triggered:
            rec["edge_safety_basis"] = "special_safe_facility"
            rec["safety_score_0_1"]  = 0.0
            records.append(rec)
            continue

        # ── 2단계. Priority 2: 기하학적 도로 횡단 ────────────────────────
        # (b) 공간 교차 + 45도 이상 + 교차 길이 ≤ 1m → case_D_crossing
        # If a walking edge actually crosses one or more road edges, attach the
        # riskiest crossed road. Re-selecting the nearest road around the
        # midpoint can incorrectly pick a nearby service road instead of the
        # arterial being crossed.
        crossing_cands = []
        if w_type != "1111":
            cands = list(roads_sindex.query(geom.buffer(CROSSING_SNAP_M), predicate="intersects"))
        else:
            cands = []
        for ci in cands:
            road_geom = roads_m.geometry.iloc[ci]
            r_angle = road_angle.iloc[ci]
            angle_diff = _angle_diff(w_angle, r_angle)
            if angle_diff < 45.0:
                continue
            dist = float(geom.distance(road_geom))
            if dist > CROSSING_SNAP_M:
                continue
            try:
                inter = geom.intersection(road_geom)
            except Exception:
                inter = None
            inter_len = 0.0
            if inter is not None and not inter.is_empty:
                inter_len = inter.length if inter.geom_type in ("LineString", "MultiLineString") else 0.0
            # Long overlaps are usually shared/parallel geometry, not a crossing.
            if inter_len <= 1.0:
                crossing_cands.append((ci, angle_diff, inter_len, dist))

        if crossing_cands:
            mid = _midpoint(geom)
            # angle_diff 최대(가장 수직, 실제로 건너는 도로) → 거리 최소 → risk_pct 최대 순
            ranked = [
                (ad, -float(roads_m.geometry.iloc[ci].distance(mid)), float(roads_m.iloc[ci]["risk_pct"]), ci)
                for ci, ad, inter_len, dist in crossing_cands
            ]
            best_ad, neg_dist, _, best = max(ranked)
            best_row = roads_m.iloc[best]
            rec["edge_safety_basis"]       = "case_D_crossing"
            rec["matched_road_id"]         = best_row["osm_edge_id"]
            rec["matched_road_risk_index"] = best_row["local_method_risk_index"]
            rec["matched_road_risk_pct"]   = best_row["risk_pct"]
            rec["safety_score_0_1"]        = float(best_row["risk_pct"])
            rec["case_D_distance_m"]       = float(-neg_dist)
            rec["crossing_mapping_strategy"] = "max_risk_intersecting_or_within_8m"
            records.append(rec)
            continue

        # ?? 3??. Priority 3: ??? ?? ?? ?? ?????????????????????
        # Priority 3-0: selected 1111 links that behave like separated sidewalks.
        # Keep this before Case B so long, parallel, offset walking axes along
        # major roads/riverside paths are not treated as shared roadway.
        if w_type == "1111" and length >= A_1111_MIN_LENGTH_M:
            sep_best = None
            sep_candidates = list(roads_sindex.query(geom.buffer(A_1111_MAX_SEPARATION_M), predicate="intersects"))
            for ci in sep_candidates:
                road_geom = roads_m.geometry.iloc[ci]
                road_cls = str(roads_m.iloc[ci].get("road_class", ""))
                road_name = str(roads_m.iloc[ci].get("road_name", "") or "").strip()
                is_major_candidate = road_cls in MAJOR_ROAD_CLASSES
                is_named_local_candidate = (
                    road_cls in LOCAL_SEPARATED_ROAD_CLASSES
                    and road_name
                    and road_name.lower() != "nan"
                )
                if not (is_major_candidate or is_named_local_candidate):
                    continue
                dist = float(geom.distance(road_geom))

                max_sep = A_1111_MAX_SEPARATION_M if is_major_candidate else A_1111_LOCAL_MAX_SEPARATION_M
                max_angle = A_1111_PARALLEL_ANGLE_DEG if is_major_candidate else A_1111_LOCAL_PARALLEL_ANGLE_DEG
                min_ratio = A_1111_OVERLAP_RATIO if is_major_candidate else A_1111_LOCAL_OVERLAP_RATIO
                min_len = A_1111_MIN_LENGTH_M if is_major_candidate else A_1111_LOCAL_MIN_LENGTH_M

                if length < min_len:
                    continue
                if dist < A_1111_MIN_SEPARATION_M or dist > max_sep:
                    continue
                angle_diff = _angle_diff(w_angle, road_angle.iloc[ci])
                if angle_diff > max_angle:
                    continue
                overlap = _overlap_length(geom, road_geom.buffer(max_sep))
                ratio = overlap / length if length > 0 else 0.0
                if ratio < min_ratio:
                    continue
                candidate_key = (
                    1 if is_major_candidate else 0,
                    ratio,
                    -dist,
                    float(roads_m.iloc[ci]["risk_pct"]),
                    ci,
                )
                if sep_best is None or candidate_key > sep_best[0]:
                    subtype = "1111_parallel_separated" if is_major_candidate else "1111_named_local_parallel_separated"
                    sep_best = (candidate_key, roads_m.iloc[ci], dist, ratio, angle_diff, subtype)

            if sep_best is not None:
                _, best_row, dist, ratio, angle_diff, subtype = sep_best
                rec["edge_safety_basis"]       = "case_A_separated"
                rec["case_A_subtype"]          = subtype
                rec["matched_road_id"]         = best_row["osm_edge_id"]
                rec["matched_road_risk_index"] = best_row["local_method_risk_index"]
                rec["matched_road_risk_pct"]   = best_row["risk_pct"]
                rec["safety_score_0_1"]        = 0.0
                rec["case_A_reference_distance_m"] = dist
                rec["case_A_reference_overlap_ratio"] = ratio
                rec["case_A_reference_angle_diff_deg"] = angle_diff
                records.append(rec)
                continue

        buf_b = geom.buffer(B_OVERLAP_M)
        cands_b = list(roads_sindex.query(buf_b, predicate="intersects"))
        best_b_idx  = None
        best_b_dist = float("inf")

        for ci in cands_b:
            road_geom = roads_m.geometry.iloc[ci]
            r_angle   = road_angle.iloc[ci]
            if _angle_diff(w_angle, r_angle) > B_PARALLEL_ANGLE_DEG:
                continue
            ov = _overlap_length(geom, road_geom.buffer(B_OVERLAP_M))
            ratio = ov / length if length > 0 else 0.0
            if ratio < B_OVERLAP_RATIO:
                continue
            dist = geom.distance(road_geom)
            if dist < best_b_dist:
                best_b_dist = dist
                best_b_idx  = ci

        if best_b_idx is not None:
            best_row = roads_m.iloc[best_b_idx]
            rec["edge_safety_basis"]       = "case_B_shared_road"
            rec["matched_road_id"]         = best_row["osm_edge_id"]
            rec["matched_road_risk_index"] = best_row["local_method_risk_index"]
            rec["matched_road_risk_pct"]   = best_row["risk_pct"]
            rec["safety_score_0_1"]        = float(best_row["risk_pct"])
            records.append(rec)
            continue

        # ── 4단계. Priority 4: 보행전용 타입 ─────────────────────────────
        if w_type in PEDESTRIAN_TYPES:
            rec["edge_safety_basis"] = "case_A_separated"
            rec["case_A_subtype"]    = "walking_type_only"
            rec["safety_score_0_1"]  = 0.0
            records.append(rec)
            continue

        # ── 5단계. Priority 5: 양측 분리 보도 (비-1111 전용) ──────────────
        # 1111(차량+보행 혼용)은 양쪽에 있어도 보차 분리 보도로 볼 수 없음.
        # 1111이 도로 양쪽에 쌍으로 나타나는 것은 왕복 차로 표현일 가능성이 높고,
        # 보도로 확인할 방법이 없으므로 score=0.0 으로 처리하면 오히려 위험을 가림.
        if wid in case_a2_ids and w_type not in {"1111"}:
            rec["edge_safety_basis"] = "case_A_separated_two_sided"
            rec["case_A_subtype"]    = "two_sided"
            rec["safety_score_0_1"]  = 0.0
            records.append(rec)
            continue

        # ── 6단계. Priority 6: 주변 차도 없음 ────────────────────────────
        near_any = list(roads_sindex.query(geom.buffer(C_NO_ROAD_M), predicate="intersects"))
        if not near_any:
            rec["edge_safety_basis"] = "case_C_no_nearby_road"
            rec["safety_score_0_1"]  = 0.0
            records.append(rec)
            continue

        # ── 7단계. Priority 7: 보차 혼용 + 도로 인접 (1111, 80m 이내) ───
        # C_NO_ROAD_M=80m 와 동일 기준 → Priority 6/7 사이 gap 없음
        # Distance discount: 다른 case의 거리 임계(B 5m, A_1111 25m, C 80m)와 일관성
        #   d ≤ 5m       → factor = 1.0           (B_shared 강도)
        #   5 < d ≤ 25m  → factor = 1.0 → 0.5     (선형 감쇠)
        #   25 < d ≤ 80m → factor = 0.5 → 0.0     (선형 감쇠)
        if w_type == "1111":
            near_b = list(roads_sindex.query(geom.buffer(B_NEAREST_FALLBACK_M), predicate="intersects"))
            if near_b:
                dists = [roads_m.geometry.iloc[ci].distance(geom) for ci in near_b]
                best  = near_b[int(np.argmin(dists))]
                d_min = float(dists[int(np.argmin(dists))])
                best_row = roads_m.iloc[best]

                if d_min <= B_OVERLAP_M:
                    factor = 1.0
                elif d_min <= A_1111_MAX_SEPARATION_M:
                    factor = 1.0 - 0.5 * (d_min - B_OVERLAP_M) / (A_1111_MAX_SEPARATION_M - B_OVERLAP_M)
                elif d_min <= C_NO_ROAD_M:
                    factor = 0.5 - 0.5 * (d_min - A_1111_MAX_SEPARATION_M) / (C_NO_ROAD_M - A_1111_MAX_SEPARATION_M)
                else:
                    factor = 0.0
                factor = max(0.0, min(1.0, factor))

                rec["edge_safety_basis"]       = "case_B_nearest_road"
                rec["matched_road_id"]         = best_row["osm_edge_id"]
                rec["matched_road_risk_index"] = best_row["local_method_risk_index"]
                rec["matched_road_risk_pct"]   = best_row["risk_pct"]
                rec["nearest_road_distance_m"] = d_min
                rec["distance_discount_factor"] = factor
                rec["safety_score_0_1"]        = float(best_row["risk_pct"]) * factor
                records.append(rec)
                continue

        # ── 5단계. fallback (unclassified) ───────────────────────────────
        rec["edge_safety_basis"] = "unclassified"
        rec["safety_score_0_1"]  = np.nan
        records.append(rec)

    result = pd.DataFrame(records)

    # geometry_wkt를 WGS84로 변환 (metric CRS에서 저장했으므로 재변환)
    # 이미 wkt는 metric이므로 GeoDataFrame에서 변환
    geom_series = walk_m.geometry.to_crs(WGS84)
    result["geometry_wkt"] = [g.wkt for g in geom_series]

    print(f"\n[특수 유형 경고] building==1인데 도로 5m 이내: {len(special_near_road_warnings)}개")
    if special_near_road_warnings[:5]:
        print(f"  예시 ID: {special_near_road_warnings[:5]}")

    return result


# ---------------------------------------------------------------------------
# 검증 보고 (설계서 §7)
# ---------------------------------------------------------------------------

def validation_report(result: pd.DataFrame, roads: gpd.GeoDataFrame) -> dict[str, Any]:
    basis_counts = result["edge_safety_basis"].value_counts().to_dict()
    scores       = result["safety_score_0_1"].dropna()

    report: dict[str, Any] = {
        "n_total": len(result),
        "case_counts": {
            "case_D_crosswalk":      basis_counts.get("case_D_crosswalk", 0),
            "case_D_crossing":       basis_counts.get("case_D_crossing", 0),
            "case_B_shared_road":    basis_counts.get("case_B_shared_road", 0),
            "case_B_nearest_road":   basis_counts.get("case_B_nearest_road", 0),
            "case_A_separated":      basis_counts.get("case_A_separated", 0),
            "case_C_no_nearby_road": basis_counts.get("case_C_no_nearby_road", 0),
            "special_safe_facility": basis_counts.get("special_safe_facility", 0),
            "unclassified":          basis_counts.get("unclassified", 0),
        },
        "score_distribution": {
            "mean":         round(float(scores.mean()), 4) if len(scores) else None,
            "median":       round(float(scores.median()), 4) if len(scores) else None,
            "p25":          round(float(scores.quantile(0.25)), 4) if len(scores) else None,
            "p75":          round(float(scores.quantile(0.75)), 4) if len(scores) else None,
            "p95":          round(float(scores.quantile(0.95)), 4) if len(scores) else None,
            "n_score_0":          int((result["safety_score_0_1"] == 0.0).sum()),
            "n_score_above_0p8":  int((result["safety_score_0_1"] >= 0.8).sum()),
        },
        "road_input_metadata": {
            "n_roads_total":         len(roads),
            "percentile_basis":      "gwanak_all_roads local_method_risk_index",
        },
    }

    print("\n" + "="*60)
    print("§7 검증 보고")
    print("="*60)

    # 1. unclassified
    unc = result[result["edge_safety_basis"] == "unclassified"]
    print(f"\n1. unclassified link: {len(unc)}개")
    if len(unc) > 0:
        print(unc[["walk_edge_id", "walking_type", "emd_nm"]].head(5).to_string(index=False))

    # 2. 특수 유형 자동 0
    special = result[result["edge_safety_basis"] == "special_safe_facility"]
    print(f"\n2. 특수 유형 자동 0점: {len(special)}개")
    print(f"   (overpass/bridge/tunnel/building/park_green 플래그별 분포)")
    for col in ["overpass", "bridge", "tunnel", "building", "park_green"]:
        cnt = int((result[col] == 1).sum())
        if cnt:
            print(f"   {col}: {cnt}개")

    # 3. Case D NEAREST_CROSS_M 초과 (crosswalk=1인데 C로 강등된 케이스)
    d_degraded = result[
        (result["crosswalk"] == 1) & (result["edge_safety_basis"] == "case_C_no_nearby_road")
    ]
    print(f"\n3. crosswalk=1인데 Case C로 강등 (80m 안 도로 없음): {len(d_degraded)}개")

    # 4. Case A 양쪽 검출 비대칭 (Case B로 분류된 walking_type=1111 중 도로 거의 100% 겹침)
    b_full = result[result["edge_safety_basis"] == "case_B_shared_road"]
    print(f"\n4. Case B (외길 겹침) 총 {len(b_full)}개")
    if "walking_type" in b_full.columns:
        print(f"   walking_type 분포:\n{b_full['walking_type'].value_counts().to_string()}")

    # 5. Case B 거의 100% 겹침 (length < 5m)
    short_b = b_full[b_full["length_m"] < 5.0] if "length_m" in b_full.columns else pd.DataFrame()
    print(f"\n5. Case B 중 길이 < 5m (매우 짧은 외길): {len(short_b)}개")

    # 6. 점수 0.95+ link
    top_risk = result[result["safety_score_0_1"] >= 0.95]
    print(f"\n6. 점수 0.95 이상 (최상위 위험): {len(top_risk)}개")
    if len(top_risk) > 0:
        print(top_risk[["walk_edge_id", "emd_nm", "safety_score_0_1", "matched_road_risk_index"]].head(5).to_string(index=False))

    # 7. walking_type별 평균 점수
    print("\n7. walking_type별 평균 safety_score_0_1:")
    type_means = result.groupby("walking_type")["safety_score_0_1"].mean().sort_values()
    print(type_means.to_string())

    # 8. 매우 짧은 link
    short = result[result["length_m"] < 5.0] if "length_m" in result.columns else pd.DataFrame()
    print(f"\n8. 길이 < 5m link 총 {len(short)}개")
    if len(short) > 0:
        print(f"   케이스 분포:\n{short['edge_safety_basis'].value_counts().to_string()}")

    print("="*60)
    return report


# ---------------------------------------------------------------------------
# 지도 HTML 생성
# ---------------------------------------------------------------------------

def create_map(result: pd.DataFrame, roads: gpd.GeoDataFrame, summary: dict) -> None:
    try:
        import folium
        from folium.plugins import Fullscreen, MeasureControl
        from shapely import wkt as shapely_wkt
    except ImportError:
        print("[지도] folium 미설치 — 지도 건너뜀")
        return

    center_lat, center_lon = 37.478, 126.951
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="CartoDB positron")

    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Esri 위성", overlay=False, control=True,
    ).add_to(m)

    Fullscreen(position="topright").add_to(m)
    MeasureControl(position="topleft", primary_length_unit="meters").add_to(m)

    def score_color(score) -> str:
        if pd.isna(score):
            return "#9ca3af"
        v = float(score)
        if v <= 0.0:  return "#1a9850"
        if v < 0.2:   return "#66bd63"
        if v < 0.4:   return "#a6d96a"
        if v < 0.6:   return "#fee08b"
        if v < 0.8:   return "#f46d43"
        return "#d73027"

    CASE_COLORS = {
        "case_D_crossing":       "#e41a1c",
        "case_B_shared_road":    "#ff7f00",
        "case_B_nearest_road":   "#ffbf00",
        "case_A_separated":      "#4daf4a",
        "case_C_no_nearby_road": "#377eb8",
        "special_safe_facility": "#984ea3",
        "unclassified":          "#9ca3af",
    }

    def line_coords(geom):
        if geom.geom_type == "LineString":
            return [[(y, x) for x, y in geom.coords]]
        return [[(y, x) for x, y in part.coords] for part in geom.geoms]

    # 메인 레이어: 점수 기반 색상
    walk_score_group = folium.FeatureGroup(name="보행 edge 안전도 (점수 0=안전 → 1=위험)", show=True)
    # 보조 레이어: 케이스별 색상
    walk_case_group  = folium.FeatureGroup(name="보행 edge 케이스 분류", show=False)

    for _, row in result.iterrows():
        try:
            geom = shapely_wkt.loads(row["geometry_wkt"])
        except Exception:
            continue
        score = row["safety_score_0_1"]
        score_str = f"{score:.3f}" if not pd.isna(score) else "N/A"
        basis = row["edge_safety_basis"] or "unclassified"
        tooltip = (
            f"<b>ID:</b> {row['walk_edge_id']}<br>"
            f"<b>케이스:</b> {basis}<br>"
            f"<b>점수:</b> {score_str}<br>"
            f"<b>walking_type:</b> {row['walking_type']}<br>"
            f"<b>emd:</b> {row['emd_nm']}<br>"
            f"<b>길이:</b> {row['length_m']:.1f}m"
        )
        for coords in line_coords(geom):
            folium.PolyLine(coords, color=score_color(score), weight=2.5, opacity=0.85, tooltip=tooltip).add_to(walk_score_group)
            folium.PolyLine(coords, color=CASE_COLORS.get(basis, "#9ca3af"), weight=2.5, opacity=0.85, tooltip=tooltip).add_to(walk_case_group)

    walk_score_group.add_to(m)
    walk_case_group.add_to(m)

    # 도로 레이어
    road_group = folium.FeatureGroup(name="도로 위험도 percentile", show=False)
    roads_wgs = roads.to_crs(WGS84)
    for _, rrow in roads_wgs.iterrows():
        geom = rrow.geometry
        if geom is None or geom.is_empty:
            continue
        color = score_color(rrow.get("risk_pct", 0.5))
        for coords in line_coords(geom):
            folium.PolyLine(coords, color=color, weight=2, opacity=0.6).add_to(road_group)
    road_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # 점수 범례
    cc = summary["case_counts"]
    sd = summary["score_distribution"]
    legend_html = f"""
    <div style="
      position: fixed; bottom: 30px; left: 30px; z-index: 9999;
      background: white; padding: 12px 14px; border: 1px solid #888;
      border-radius: 6px; font-family: sans-serif; font-size: 12px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.15); max-width: 280px;">
      <div style="font-weight: 700; margin-bottom: 6px;">보행 edge 안전도 v2 (관악구)</div>

      <div style="font-weight: 600; margin-top: 4px;">점수 색상 (0=안전, 1=위험)</div>
      <div style="display: flex; align-items: center; margin: 3px 0;">
        <span style="background:#1a9850;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.00 (가장 안전)
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#66bd63;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.00-0.20
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#a6d96a;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.20-0.40
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#fee08b;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.40-0.60
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#f46d43;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.60-0.80
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#d73027;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>0.80-1.00 (가장 위험)
      </div>
      <div style="display:flex;align-items:center;margin:3px 0;">
        <span style="background:#9ca3af;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>미분류 (NaN)
      </div>

      <div style="font-weight: 600; margin-top: 8px;">케이스 분류 색상</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#e41a1c;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>D 횡단: {cc['case_D_crossing']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#ff7f00;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>B 외길 겹침: {cc['case_B_shared_road']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#ffbf00;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>B 폴백(1111+nearest): {cc['case_B_nearest_road']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#4daf4a;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>A 보차 분리: {cc['case_A_separated']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#377eb8;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>C 차도 없음: {cc['case_C_no_nearby_road']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#984ea3;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>특수(육교/교량 등): {cc['special_safe_facility']:,}</div>
      <div style="display:flex;align-items:center;margin:3px 0;"><span style="background:#9ca3af;width:14px;height:14px;display:inline-block;margin-right:6px;"></span>미분류: {cc['unclassified']:,}</div>

      <div style="font-weight: 600; margin-top: 8px;">점수 분포</div>
      <div>평균 {sd['mean']} / 중앙 {sd['median']}</div>
      <div>p25 {sd['p25']} / p75 {sd['p75']} / p95 {sd['p95']}</div>
      <div>점수 0: {sd['n_score_0']:,} / 0.8+: {sd['n_score_above_0p8']:,}</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    out_path = OUT_DIR / "walking_edge_safety_map.html"
    m.save(str(out_path))
    print(f"[지도] 저장: {out_path}")


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------

def save_outputs(result: pd.DataFrame, roads: gpd.GeoDataFrame, summary: dict) -> None:
    # 컬럼명 명확화: safety_score_0_1은 실제로는 위험도 점수 (0=안전, 1=위험)
    # 두 컬럼 모두 노출 (기존 컬럼명 호환 + 명확한 새 컬럼명)
    if "safety_score_0_1" in result.columns and "walking_risk_score_0_1" not in result.columns:
        result["walking_risk_score_0_1"] = result["safety_score_0_1"]

    # CSV (cp949)
    csv_path = OUT_DIR / "gwanak_walking_edge_safety.csv"
    result.to_csv(csv_path, index=False, encoding="cp949")
    print(f"[저장] CSV (cp949): {csv_path}")

    # CSV (utf-8-sig)
    utf8_path = OUT_DIR / "gwanak_walking_edge_safety_utf8.csv"
    result.to_csv(utf8_path, index=False, encoding="utf-8-sig")
    print(f"[저장] CSV (utf8): {utf8_path}")

    # GeoJSON
    geojson_df = result.copy()
    geojson_df["geometry"] = geojson_df["geometry_wkt"].map(wkt.loads)
    gdf = gpd.GeoDataFrame(geojson_df, geometry="geometry", crs=WGS84)
    out_cols = [c for c in gdf.columns if c != "geometry_wkt"]
    geojson_path = OUT_DIR / "gwanak_walking_edge_safety.geojson"
    gdf[out_cols].to_file(geojson_path, driver="GeoJSON")
    print(f"[저장] GeoJSON: {geojson_path}")

    # summary JSON
    params = {
        "NEAREST_CROSS_M": NEAREST_CROSS_M,
            "CROSSING_SNAP_M": CROSSING_SNAP_M,
        "B_OVERLAP_M": B_OVERLAP_M,
        "B_PARALLEL_ANGLE_DEG": B_PARALLEL_ANGLE_DEG,
        "B_OVERLAP_RATIO": B_OVERLAP_RATIO,
        "B_NEAREST_FALLBACK_M": B_NEAREST_FALLBACK_M,
            "A_1111_MIN_SEPARATION_M": A_1111_MIN_SEPARATION_M,
            "A_1111_MAX_SEPARATION_M": A_1111_MAX_SEPARATION_M,
            "A_1111_PARALLEL_ANGLE_DEG": A_1111_PARALLEL_ANGLE_DEG,
            "A_1111_OVERLAP_RATIO": A_1111_OVERLAP_RATIO,
            "A_1111_MIN_LENGTH_M": A_1111_MIN_LENGTH_M,
        "A_SIDE_BUFFER_M": A_SIDE_BUFFER_M,
        "A_SIDE_PARALLEL_ANGLE_DEG": A_SIDE_PARALLEL_ANGLE_DEG,
        "A_SIDE_OVERLAP_RATIO": A_SIDE_OVERLAP_RATIO,
        "C_NO_ROAD_M": C_NO_ROAD_M,
        "PEDESTRIAN_TYPES": sorted(PEDESTRIAN_TYPES),
    }
    full_summary = {
        "method": "case-based (D>B>A>C) with road risk percentile",
        "parameters": {
            **params,
            "CROSSWALK_MAX_M": CROSSWALK_MAX_M,
        },
        "n_walking_edges_total": summary["n_total"],
        "case_counts": summary["case_counts"],
        "score_distribution": summary["score_distribution"],
        "road_input_metadata": summary["road_input_metadata"],
    }
    summary_path = OUT_DIR / "walking_edge_safety_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(full_summary, f, ensure_ascii=False, indent=2)
    print(f"[저장] summary JSON: {summary_path}")

    # 최신 산출 통계 (README는 수동 관리하므로 별도 파일에 기록)
    counts_path = OUT_DIR / "case_counts_latest.txt"
    with open(counts_path, "w", encoding="utf-8") as f:
        f.write(f"# 산출 일시: {pd.Timestamp.now().isoformat()}\n")
        for k, v in summary["case_counts"].items():
            f.write(f"{k}: {v:,}\n")
    print(f"[저장] case counts: {counts_path}")


# ---------------------------------------------------------------------------
# 실행 진입점
# ---------------------------------------------------------------------------

def main():
    print("="*60)
    print("보행 edge 안전도 v2 산출 시작")
    print("="*60)

    roads = load_roads()
    walk  = load_walking(roads)

    print(f"\n[분류] {len(walk):,}개 보행 edge 케이스 분류 시작...")
    result = classify(walk, roads)

    # ── 등산로 제거 (행정경계 + 자연림 polygon 기반) ─────────────────────────
    # 1. 관악구 행정경계 (OSM "Gwanak-gu, Seoul") 밖의 link 제거
    # 2. OSM landuse=forest 또는 natural=wood 폴리곤과 겹치는 link 제거
    # 데이터 파일이 없으면 (오프라인 등) 기존 위경도 휴리스틱으로 폴백
    boundary_p = ROOT / "data" / "raw" / "gwanak_boundary.geojson"
    forest_p   = ROOT / "data" / "raw" / "seoul_forest.geojson"

    geoms = result["geometry_wkt"].map(wkt.loads)
    centroids = gpd.GeoSeries(geoms.map(lambda g: g.centroid), crs=WGS84)

    if boundary_p.exists() and forest_p.exists():
        boundary = gpd.read_file(boundary_p).to_crs(WGS84)
        forest   = gpd.read_file(forest_p).to_crs(WGS84)
        forest   = forest[forest.geometry.type.isin(["Polygon", "MultiPolygon"])]
        boundary_union = boundary.unary_union
        forest_union   = forest.unary_union

        mask_outside_boundary = ~centroids.within(boundary_union)
        mask_in_forest        = centroids.within(forest_union)
        mountain_mask = mask_outside_boundary | mask_in_forest

        n_outside = int(mask_outside_boundary.sum())
        n_forest  = int(mask_in_forest.sum())
        print(f"[등산로 제거] 행정경계 외부: {n_outside}개, 자연림 polygon 내부: {n_forest}개")
    else:
        # 폴백: 위경도 휴리스틱 (외부 polygon 파일 없을 때)
        print(f"[등산로 제거] 경고: polygon 파일 없음 → 위경도 휴리스틱 사용")
        lats = centroids.y
        mask_south = lats < 37.466
        mask_mid_c = (
            (lats >= 37.466) & (lats < 37.470)
            & (result["edge_safety_basis"].isin(["case_C_no_nearby_road", "special_safe_facility"]))
        )
        mountain_mask = mask_south | mask_mid_c

    n_removed = int(mountain_mask.sum())
    result = result[~mountain_mask.values].reset_index(drop=True)
    print(f"[등산로 제거] 총 {n_removed}개 링크 제거 → 잔여 {len(result):,}개")

    summary = validation_report(result, roads)
    save_outputs(result, roads, summary)
    create_map(result, roads, summary)

    print("\n완료.")


if __name__ == "__main__":
    main()
