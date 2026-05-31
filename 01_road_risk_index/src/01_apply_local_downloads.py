"""
Apply the Uiwang pedestrian-safety methodology to the available Gwanak data.

This script writes the final road-level safety outputs under
yunseo_lee/road_safety.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import ArcGIS
from shapely import wkt
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = Path(r"C:\Users\iy579\Downloads")
OUT_DIR = ROOT / "yunseo_lee" / "road_safety"
TARGET_COL = "pedestrian_accident_hybrid_weight"

ROAD_PATH = ROOT / "traffic_speed" / "gwanak_topis" / "gwanak_osm_drive_child_safety_hybrid_final_with_topis_speed.csv"
TRAFFIC_VOLUME_PATH = ROOT / "pedestrian_safety" / "gwanak_osm_drive_child_safety_hybrid_final_with_traffic.csv"
SCHOOLZONE_PATH = ROOT / "web" / "data" / "schoolzones.geojson"

GWANAK_DONG_CODE_TO_NAME = {
    11620525: "보라매동",
    11620545: "청림동",
    11620565: "성현동",
    11620575: "행운동",
    11620585: "낙성대동",
    11620595: "청룡동",
    11620605: "은천동",
    11620615: "중앙동",
    11620625: "인헌동",
    11620630: "남현동",
    11620645: "서원동",
    11620655: "신원동",
    11620665: "서림동",
    11620685: "신사동",
    11620695: "신림동",
    11620715: "난향동",
    11620725: "조원동",
    11620735: "대학동",
    11620745: "삼성동",
    11620765: "미성동",
    11620775: "난곡동",
}


def read_csv_any(path: Path, **kwargs) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not read CSV: {path}") from last_error


def find_one(pattern: str, min_size: int | None = None) -> Path | None:
    candidates = sorted(DOWNLOADS.glob(pattern), key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    if min_size is not None:
        candidates = [p for p in candidates if p.stat().st_size >= min_size]
    return candidates[0] if candidates else None


def find_download_xlsx(name_parts: list[str]) -> Path | None:
    for path in sorted(DOWNLOADS.glob("*.xlsx")):
        if all(part in path.name for part in name_parts):
            return path
    return None


def w_formula(correlation: float, correlation_sum: float) -> float:
    if not np.isfinite(correlation) or correlation_sum == 0:
        return 1.0
    return round(abs(float(correlation)) / float(correlation_sum), 3) + 1.0


def load_roads() -> gpd.GeoDataFrame:
    roads = pd.read_csv(ROAD_PATH, encoding="utf-8-sig")
    traffic_volume = read_csv_any(TRAFFIC_VOLUME_PATH, usecols=["osm_edge_id", "estimated_traffic_volume"])
    roads = roads.merge(traffic_volume, on="osm_edge_id", how="left")
    roads["geometry"] = roads["geometry_wkt"].map(wkt.loads)
    return gpd.GeoDataFrame(roads, geometry="geometry", crs="EPSG:4326").to_crs("EPSG:5179")


def point_gdf(df: pd.DataFrame, lon_col: str, lat_col: str) -> gpd.GeoDataFrame:
    clean = df.copy()
    clean[lon_col] = pd.to_numeric(clean[lon_col], errors="coerce")
    clean[lat_col] = pd.to_numeric(clean[lat_col], errors="coerce")
    clean = clean.dropna(subset=[lon_col, lat_col])
    return gpd.GeoDataFrame(
        clean,
        geometry=gpd.points_from_xy(clean[lon_col], clean[lat_col]),
        crs="EPSG:4326",
    ).to_crs("EPSG:5179")


def load_child_facilities() -> tuple[gpd.GeoDataFrame, dict]:
    frames: list[gpd.GeoDataFrame] = []
    meta: dict[str, object] = {}

    school_path = find_one("*초중고등학교위치*.csv")
    if school_path:
        schools = read_csv_any(school_path)
        mask = (
            schools["소재지도로명주소"].astype(str).str.contains("관악구", na=False)
            | schools["소재지지번주소"].astype(str).str.contains("관악구", na=False)
        )
        schools = schools[mask & schools["운영상태"].astype(str).str.contains("운영", na=False)].copy()
        schools["facility_source"] = "school_location"
        schools["facility_type"] = schools["학교급구분"]
        schools["facility_name"] = schools["학교명"]
        gdf = point_gdf(schools, "경도", "위도")
        frames.append(gdf[["facility_source", "facility_type", "facility_name", "geometry"]])
        meta["school_location_file"] = str(school_path)
        meta["gwanak_school_points"] = int(len(gdf))

    childcare_path = find_one("*어린이집기본정보조회*.xls", min_size=1_000_000)
    if childcare_path:
        childcare = pd.read_excel(childcare_path)
        childcare = childcare[
            (childcare["시도"].astype(str) == "서울특별시")
            & (childcare["시군구"].astype(str) == "관악구")
            & (childcare["운영현황"].astype(str).isin(["정상", "재개"]))
        ].copy()
        childcare["facility_source"] = "childcare_info"
        childcare["facility_type"] = "어린이집"
        childcare["facility_name"] = childcare["어린이집명"]
        gdf = point_gdf(childcare, "경도", "위도")
        frames.append(gdf[["facility_source", "facility_type", "facility_name", "geometry"]])
        meta["childcare_file"] = str(childcare_path)
        meta["gwanak_childcare_points"] = int(len(gdf))

    if not frames:
        empty = gpd.GeoDataFrame(columns=["facility_source", "facility_type", "facility_name", "geometry"], geometry="geometry", crs="EPSG:5179")
        return empty, meta

    return pd.concat(frames, ignore_index=True), meta


def polygons_from_geometry(geometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        polygons: list[Polygon] = []
        for part in geometry.geoms:
            polygons.extend(polygons_from_geometry(part))
        return polygons
    return []


def load_gwanak_schoolzones() -> tuple[gpd.GeoDataFrame, dict]:
    if not SCHOOLZONE_PATH.exists():
        empty = gpd.GeoDataFrame(columns=["school_name", "district", "geometry"], geometry="geometry", crs="EPSG:5179")
        return empty, {"schoolzone_polygon_file_found": False}

    zones = gpd.read_file(SCHOOLZONE_PATH)
    zones = zones[zones["district"].astype(str).isin(["관악구", "gwanak"])].copy()
    records = []
    for _, row in zones.iterrows():
        for polygon in polygons_from_geometry(make_valid(row.geometry)):
            records.append({"school_name": row.get("school_name"), "district": row.get("district"), "geometry": polygon})

    if not records:
        empty = gpd.GeoDataFrame(columns=["school_name", "district", "geometry"], geometry="geometry", crs="EPSG:5179")
        return empty, {"schoolzone_polygon_file_found": True, "gwanak_schoolzone_polygons": 0}

    polygons = gpd.GeoDataFrame(records, geometry="geometry", crs=zones.crs or "EPSG:4326").to_crs("EPSG:5179")
    polygons["geometry"] = polygons.geometry.map(make_valid)
    meta = {
        "schoolzone_polygon_file": str(SCHOOLZONE_PATH),
        "gwanak_schoolzone_source_features": int(len(zones)),
        "gwanak_schoolzone_polygons": int(len(polygons)),
    }
    return polygons, meta


def load_living_population_by_dong() -> tuple[pd.DataFrame, dict]:
    path = DOWNLOADS / "LOCAL_PEOPLE_DONG_202604" / "LOCAL_PEOPLE_DONG_202604.csv"
    if not path.exists():
        return pd.DataFrame(), {}

    pop = pd.read_csv(path, encoding="utf-8-sig", index_col=False)
    pop["행정동코드"] = (
        pd.to_numeric(pop["행정동코드"].astype(str).str.strip().str.replace('"', "", regex=False), errors="coerce")
        .round()
        .astype("Int64")
    )
    pop = pop[pop["행정동코드"].isin(GWANAK_DONG_CODE_TO_NAME.keys())].copy()
    pop["admin_dong"] = pop["행정동코드"].map(GWANAK_DONG_CODE_TO_NAME)

    child_cols = [c for c in pop.columns if "0세부터9세" in c or "10세부터14세" in c]
    elderly_cols = [c for c in pop.columns if "65세부터69세" in c or "70세이상" in c]
    for col in ["총생활인구수", *child_cols, *elderly_cols]:
        pop[col] = pd.to_numeric(pop[col], errors="coerce")

    pop["child_living_population"] = pop[child_cols].sum(axis=1)
    pop["elderly_living_population"] = pop[elderly_cols].sum(axis=1)
    pop["vulnerable_living_population"] = pop["child_living_population"] + pop["elderly_living_population"]

    agg = pop.groupby("admin_dong", as_index=False).agg(
        total_living_population=("총생활인구수", "mean"),
        child_living_population=("child_living_population", "mean"),
        elderly_living_population=("elderly_living_population", "mean"),
        vulnerable_living_population=("vulnerable_living_population", "mean"),
    )
    agg["child_living_population_ratio"] = agg["child_living_population"] / agg["total_living_population"]
    agg["elderly_living_population_ratio"] = agg["elderly_living_population"] / agg["total_living_population"]
    agg["vulnerable_living_population_ratio"] = agg["vulnerable_living_population"] / agg["total_living_population"]

    meta = {
        "living_population_file": str(path),
        "living_population_month": "2026-04",
        "living_population_child_definition": "0-14세",
        "living_population_elderly_definition": "65세 이상",
        "gwanak_admin_dongs_matched": int(agg["admin_dong"].nunique()),
    }
    return agg, meta


def clean_seoul_address(address: str) -> str:
    cleaned = str(address).replace("서울시", "서울특별시").replace("서울 ", "서울특별시 ")
    if cleaned.startswith("관악구"):
        cleaned = "서울특별시 " + cleaned
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("조원 중앙로", "조원중앙로").replace("신림로169", "신림로 169")
    return cleaned


def load_elderly_medical_facilities() -> tuple[gpd.GeoDataFrame, dict]:
    cache = OUT_DIR / "gwanak_elderly_medical_facilities_geocoded_utf8.csv"
    source = find_download_xlsx(["노인", "의료", "복지시설"])
    if not source:
        empty = gpd.GeoDataFrame(columns=["facility_name", "address", "geometry"], geometry="geometry", crs="EPSG:5179")
        return empty, {"elderly_medical_facility_file_found": False}

    if cache.exists():
        geocoded = pd.read_csv(cache, encoding="utf-8-sig")
    else:
        rows = []
        for sheet in pd.ExcelFile(source).sheet_names:
            df = pd.read_excel(source, sheet_name=sheet, header=2)
            df = df[df["관할\n자치구"].astype(str).eq("관악구")].copy()
            for _, row in df.iterrows():
                rows.append(
                    {
                        "sheet": sheet,
                        "facility_name": str(row["기관명칭"]).strip(),
                        "address": str(row["기관소재지\n(새주소)"]).strip(),
                        "phone": str(row.get("전화", "")).strip(),
                    }
                )

        geocoder = ArcGIS(timeout=20)
        geocode = RateLimiter(geocoder.geocode, min_delay_seconds=0.2, swallow_exceptions=True)
        records = []
        for row in rows:
            query = clean_seoul_address(row["address"])
            location = geocode(query)
            status = "unmatched"
            latitude = np.nan
            longitude = np.nan
            display_name = ""
            if location:
                latitude = location.latitude
                longitude = location.longitude
                display_name = location.address
                status = "matched"
                if not (37.43 <= latitude <= 37.53 and 126.88 <= longitude <= 127.02):
                    status = "out_of_gwanak_bbox"
            records.append(
                {
                    **row,
                    "geocode_query": query,
                    "latitude": latitude,
                    "longitude": longitude,
                    "geocode_status": status,
                    "display_name": display_name,
                }
            )
        geocoded = pd.DataFrame(records)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        geocoded.to_csv(cache, index=False, encoding="utf-8-sig")

    matched = geocoded[geocoded["geocode_status"].eq("matched")].copy()
    points = point_gdf(matched, "longitude", "latitude") if not matched.empty else gpd.GeoDataFrame(columns=["facility_name", "address", "geometry"], geometry="geometry", crs="EPSG:5179")
    meta = {
        "elderly_medical_facility_file": str(source),
        "elderly_medical_facility_geocode_cache": str(cache),
        "gwanak_elderly_medical_facility_rows": int(len(geocoded)),
        "gwanak_elderly_medical_facility_geocoded_rows": int(len(points)),
        "elderly_medical_facility_geocoder": "ArcGIS geocoder via geopy",
    }
    return points, meta


def count_points_within_buffer(roads: gpd.GeoDataFrame, points: gpd.GeoDataFrame, radius_m: float) -> pd.Series:
    if points.empty:
        return pd.Series(0, index=roads.index, dtype=int)
    buffers = roads[["osm_edge_id", "geometry"]].copy()
    buffers["geometry"] = buffers.geometry.buffer(radius_m)
    joined = gpd.sjoin(points[["geometry"]], buffers, how="inner", predicate="within")
    counts = joined.groupby("index_right").size()
    return counts.reindex(roads.index, fill_value=0).astype(int)


def add_schoolzone_overlap(roads: gpd.GeoDataFrame, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    if zones.empty:
        return pd.DataFrame(
            {
                "schoolzone_overlap_length_m": pd.Series(0.0, index=roads.index),
                "schoolzone_overlap_share": pd.Series(0.0, index=roads.index),
            }
        )

    pairs = gpd.sjoin(
        roads[["osm_edge_id", "length_m", "geometry"]],
        zones[["geometry"]],
        how="inner",
        predicate="intersects",
    )
    overlap = pd.Series(0.0, index=roads.index)
    for road_idx, zone_idx in zip(pairs.index, pairs["index_right"]):
        length = roads.loc[road_idx, "geometry"].intersection(zones.loc[zone_idx, "geometry"]).length
        if np.isfinite(length):
            overlap.loc[road_idx] += float(length)

    length_m = pd.to_numeric(roads["length_m"], errors="coerce").replace(0, np.nan)
    share = (overlap / length_m).clip(lower=0, upper=1).fillna(0)
    return pd.DataFrame({"schoolzone_overlap_length_m": overlap, "schoolzone_overlap_share": share})


def add_features(roads: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    meta: dict[str, object] = {}

    child_points, child_meta = load_child_facilities()
    meta.update(child_meta)
    roads["child_facility_count_300m"] = count_points_within_buffer(roads, child_points, 300)

    elderly_points, elderly_meta = load_elderly_medical_facilities()
    meta.update(elderly_meta)
    roads["elderly_medical_facility_count_300m"] = count_points_within_buffer(roads, elderly_points, 300)

    zones, zone_meta = load_gwanak_schoolzones()
    meta.update(zone_meta)
    schoolzone_overlap = add_schoolzone_overlap(roads, zones)
    roads["schoolzone_overlap_length_m"] = schoolzone_overlap["schoolzone_overlap_length_m"]
    roads["schoolzone_overlap_share"] = schoolzone_overlap["schoolzone_overlap_share"]
    roads["schoolzone_polygon_flag"] = (roads["schoolzone_overlap_length_m"] > 0).astype(int)

    living_pop, living_meta = load_living_population_by_dong()
    meta.update(living_meta)
    if not living_pop.empty:
        roads = roads.merge(living_pop, on="admin_dong", how="left")
    else:
        for col in [
            "total_living_population",
            "child_living_population",
            "elderly_living_population",
            "vulnerable_living_population",
            "child_living_population_ratio",
            "elderly_living_population_ratio",
            "vulnerable_living_population_ratio",
        ]:
            roads[col] = np.nan

    roads["traffic_lanes_estimated"] = pd.to_numeric(roads["traffic_lanes_estimated"], errors="coerce").fillna(roads["traffic_lanes_estimated"].median())
    roads["traffic_speed_estimated_kmh"] = pd.to_numeric(roads["traffic_speed_estimated_kmh"], errors="coerce").fillna(roads["traffic_speed_estimated_kmh"].median())
    roads["estimated_traffic_volume"] = pd.to_numeric(roads["estimated_traffic_volume"], errors="coerce").fillna(roads["estimated_traffic_volume"].median())
    roads["inverse_speed_risk"] = 1.0 / roads["traffic_speed_estimated_kmh"].clip(lower=1)
    roads["wide_road_flag"] = (roads["traffic_lanes_estimated"] >= 6).astype(int)
    roads["high_traffic_flag"] = (roads["estimated_traffic_volume"] > roads["estimated_traffic_volume"].mean()).astype(int)
    # PDF 충실: 어린이/노인 생활인구 비율을 각각 독립 평균 초과 flag로 분리
    roads["child_population_high_flag"] = (
        roads["child_living_population_ratio"] > roads["child_living_population_ratio"].mean()
    ).fillna(False).astype(int)
    roads["elderly_population_high_flag"] = (
        roads["elderly_living_population_ratio"] > roads["elderly_living_population_ratio"].mean()
    ).fillna(False).astype(int)
    # 호환성 유지용: 합쳐진 플래그도 보존 (요약 통계용)
    roads["vulnerable_population_high_flag"] = (
        (roads["child_population_high_flag"] == 1) | (roads["elderly_population_high_flag"] == 1)
    ).astype(int)
    # PDF 충실: 어린이/노인복지 시설 각각 독립 플래그 (장애인 데이터 미확보)
    roads["child_facility_nearby_flag"] = (roads["child_facility_count_300m"] > 0).astype(int)
    roads["elderly_facility_nearby_flag"] = (roads["elderly_medical_facility_count_300m"] > 0).astype(int)
    roads["vulnerable_facility_nearby_flag"] = (
        (roads["child_facility_nearby_flag"] == 1) | (roads["elderly_facility_nearby_flag"] == 1)
    ).astype(int)

    return roads, meta


def calculate_index(roads: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict]:
    numeric_features = [
        "length_m",
        "crosswalk_weight",
        "crosswalk_count",
        "traffic_signal_weight",
        "traffic_signal_count",
        "traffic_lanes_estimated",
        "estimated_traffic_volume",
        "inverse_speed_risk",
        "child_facility_count_300m",
        "elderly_medical_facility_count_300m",
        "schoolzone_overlap_share",
        "vulnerable_living_population_ratio",
    ]
    for col in numeric_features:
        roads[col] = pd.to_numeric(roads[col], errors="coerce").fillna(0)
        roads[f"{col}_sqrt"] = np.sqrt(roads[col].clip(lower=0))

    transformed = [f"{col}_sqrt" for col in numeric_features]
    correlations = {col: float(roads[col].corr(roads[TARGET_COL])) for col in transformed}
    finite_abs_correlations = [abs(corr) for corr in correlations.values() if np.isfinite(corr)]
    mean_abs_correlation = float(np.mean(finite_abs_correlations)) if finite_abs_correlations else 0.0
    selected = [
        col
        for col, corr in correlations.items()
        if np.isfinite(corr) and abs(corr) >= mean_abs_correlation
    ]
    if not selected:
        selected = transformed

    # PDF 충실: 유동인구·시설물 가중치를 어린이/노인 각각 독립적으로 산출
    # (장애인 그룹은 데이터 미확보로 제외)
    group_corr = {
        "road_6lane_or_traffic": float(max(abs(roads["wide_road_flag"].corr(roads[TARGET_COL])), abs(roads["high_traffic_flag"].corr(roads[TARGET_COL])))),
        "child_population":      float(abs(roads["child_population_high_flag"].corr(roads[TARGET_COL]))),
        "elderly_population":    float(abs(roads["elderly_population_high_flag"].corr(roads[TARGET_COL]))),
        "child_facility":        float(abs(roads["child_facility_nearby_flag"].corr(roads[TARGET_COL]))),
        "elderly_facility":      float(abs(roads["elderly_facility_nearby_flag"].corr(roads[TARGET_COL]))),
    }
    corr_sum = sum(v for v in group_corr.values() if np.isfinite(v))
    weights = {name: w_formula(corr, corr_sum) for name, corr in group_corr.items()}

    roads["road_6lane_or_traffic_weight"] = np.where(
        (roads["wide_road_flag"] == 1) | (roads["high_traffic_flag"] == 1),
        weights["road_6lane_or_traffic"], 1.0,
    )
    roads["child_population_weight"] = np.where(
        roads["child_population_high_flag"] == 1, weights["child_population"], 1.0,
    )
    roads["elderly_population_weight"] = np.where(
        roads["elderly_population_high_flag"] == 1, weights["elderly_population"], 1.0,
    )
    roads["child_facility_weight"] = np.where(
        roads["child_facility_nearby_flag"] == 1, weights["child_facility"], 1.0,
    )
    roads["elderly_facility_weight"] = np.where(
        roads["elderly_facility_nearby_flag"] == 1, weights["elderly_facility"], 1.0,
    )
    # 합산 가중치 (요약/호환용)
    roads["vulnerable_population_weight"] = roads["child_population_weight"] * roads["elderly_population_weight"]
    roads["vulnerable_facility_weight"]   = roads["child_facility_weight"] * roads["elderly_facility_weight"]
    roads["final_local_method_weight"] = (
        roads["road_6lane_or_traffic_weight"]
        * roads["child_population_weight"]
        * roads["elderly_population_weight"]
        * roads["child_facility_weight"]
        * roads["elderly_facility_weight"]
    )

    scaler = StandardScaler()
    z_cols = [f"{col}_z" for col in selected]
    roads[z_cols] = scaler.fit_transform(roads[selected])
    roads["local_method_risk_index"] = roads[z_cols].sum(axis=1) * roads["final_local_method_weight"]
    roads["local_method_safety_index"] = -roads["local_method_risk_index"]
    roads["local_method_risk_decile"] = pd.qcut(
        roads["local_method_risk_index"].rank(method="first"),
        q=10,
        labels=list(range(1, 11)),
    ).astype(int)

    summary = {
        "n_links": int(len(roads)),
        "target_column": TARGET_COL,
        "candidate_features": numeric_features,
        "variable_selection_rule": "abs(correlation_with_target) >= mean_abs_correlation_across_candidate_features",
        "mean_abs_correlation_for_selection": mean_abs_correlation,
        "selected_transformed_features": selected,
        "correlations_with_target": correlations,
        "group_correlations_for_weights": group_corr,
        "applied_weights": weights,
        "risk_index_corr_with_target": float(roads["local_method_risk_index"].corr(roads[TARGET_COL])),
        "wide_road_flag_count": int(roads["wide_road_flag"].sum()),
        "high_traffic_flag_count": int(roads["high_traffic_flag"].sum()),
        "child_population_high_flag_count": int(roads["child_population_high_flag"].sum()),
        "elderly_population_high_flag_count": int(roads["elderly_population_high_flag"].sum()),
        "vulnerable_population_high_flag_count": int(roads["vulnerable_population_high_flag"].sum()),
        "child_facility_nearby_flag_count": int(roads["child_facility_nearby_flag"].sum()),
        "elderly_facility_nearby_flag_count": int(roads["elderly_facility_nearby_flag"].sum()),
        "vulnerable_facility_nearby_flag_count": int(roads["vulnerable_facility_nearby_flag"].sum()),
        "schoolzone_polygon_flag_count": int(roads["schoolzone_polygon_flag"].sum()),
    }
    return roads.drop(columns=z_cols), summary


def write_markdown(meta: dict, summary: dict) -> None:
    lines = [
        "# 의왕시 방법론 추가 적용 결과",
        "",
        "의왕시 방법론의 가중치 구조를 관악구 도로 링크 데이터에 다시 적용한 산출물이다.",
        "",
        "## 실제로 적용한 데이터",
        "",
        f"- 도로 차선/속도: `{ROAD_PATH}`의 TOPIS 결합 컬럼",
        f"- 추정 교통량: `{TRAFFIC_VOLUME_PATH}`의 `estimated_traffic_volume`",
        f"- 생활인구: `{meta.get('living_population_file', '없음')}`",
        f"- 학교 위치: `{meta.get('school_location_file', '없음')}`",
        f"- 어린이집 위치: `{meta.get('childcare_file', '없음')}`",
        f"- 스쿨존 폴리곤: `{meta.get('schoolzone_polygon_file', '없음')}`",
        f"- 서울시 노인의료복지시설: `{meta.get('elderly_medical_facility_file', '없음')}`",
        "",
        "## 구현 방식",
        "",
        "- 링크 geometry를 EPSG:5179로 변환했다.",
        "- 관악구 학교/어린이집 좌표를 점 데이터로 만들고, 링크 300m 버퍼 안에 들어오는 개수를 `child_facility_count_300m`로 계산했다.",
        "- 서울시 노인의료복지시설 주소 27개는 ArcGIS 지오코더로 좌표 변환했고, 링크 300m 버퍼 안 개수를 `elderly_medical_facility_count_300m`로 계산했다.",
        "- 어린이보호구역 지정현황 행정동 집계는 쓰지 않았다. 대신 Drive `web/data/schoolzones.geojson`의 실제 스쿨존 폴리곤과 도로 링크의 겹침 길이/비율을 계산했다.",
        "- 2026년 4월 서울 생활인구는 행정동 코드-이름 매핑으로 관악구 21개 행정동 평균값을 만들고 링크의 `admin_dong`에 병합했다.",
        "- 어린이는 0-14세, 노인은 65세 이상으로 정의했다.",
        "- 장애인 생활인구와 관악구 장애인복지시설 좌표는 로컬 파일에 없어 가중치에 넣지 않았다.",
        "- 후보 변수에 sqrt 변환을 적용하고, 보행자 사고 가중치와의 상관계수 기준으로 변수를 골랐다.",
        "- 최종 가중치는 `도로/교통 가중치 * 보행약자 생활인구 가중치 * 보행약자 시설물 가중치`로 계산했다.",
        "",
        "## 주요 결과",
        "",
        f"- 링크 수: {summary['n_links']:,}",
        f"- 변수 선택 기준: 후보 변수 전체의 평균 절댓값 상관계수 이상 ({summary['mean_abs_correlation_for_selection']:.4f})",
        f"- 선택 변수: {', '.join(summary['selected_transformed_features'])}",
        f"- 위험지수와 보행자 사고 가중치 상관계수: {summary['risk_index_corr_with_target']:+.4f}",
        f"- 6차로 또는 평균 초과 교통량 플래그 링크: {summary['high_traffic_flag_count']:,}개",
        f"- 보행약자 생활인구 비율 평균 초과 링크: {summary['vulnerable_population_high_flag_count']:,}개",
        f"- 300m 내 어린이 시설 존재 링크: {summary['child_facility_nearby_flag_count']:,}개",
        f"- 300m 내 노인의료복지시설 존재 링크: {summary['elderly_facility_nearby_flag_count']:,}개",
        f"- 스쿨존 폴리곤과 겹치는 링크: {summary['schoolzone_polygon_flag_count']:,}개",
        "",
        "## 아직 못 한 부분",
        "",
        "- 장애인 생활인구 데이터는 관악구 기준으로 확보하지 못했다.",
        "- 관악구 장애인복지시설 좌표 데이터는 로컬에 없었다. 로컬 `장애인복지시설(영유아,작업활동등)현황.csv`는 경기도 데이터라 관악구에 적용하지 않았다.",
        "- 노인의료복지시설 좌표는 원본에 직접 들어있던 값이 아니라 주소를 지오코딩한 결과이므로, 공공기관 공식 좌표가 있으면 그걸로 대체하는 편이 더 낫다.",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    roads = load_roads()
    roads, meta = add_features(roads)
    result, summary = calculate_index(roads)

    output_cols = [
        "osm_edge_id",
        "road_name",
        "road_class",
        "admin_dong",
        "length_m",
        "traffic_lanes_estimated",
        "traffic_lanes_source",
        "traffic_speed_estimated_kmh",
        "traffic_speed_estimate_source",
        "traffic_speed_08_09_kmh",
        "traffic_speed_daily_avg_kmh",
        "traffic_speed_used_kmh",
        "traffic_speed_source",
        "traffic_lanes_avg",
        "traffic_lanes_max",
        "topis_link_count",
        "topis_record_count",
        "estimated_traffic_volume",
        "inverse_speed_risk",
        "crosswalk_count",
        "crosswalk_weight",
        "traffic_signal_count",
        "traffic_signal_weight",
        "is_school_zone",
        "child_facility_count_300m",
        "elderly_medical_facility_count_300m",
        "schoolzone_overlap_length_m",
        "schoolzone_overlap_share",
        "child_living_population_ratio",
        "elderly_living_population_ratio",
        "vulnerable_living_population_ratio",
        "road_6lane_or_traffic_weight",
        "vulnerable_population_weight",
        "vulnerable_facility_weight",
        "final_local_method_weight",
        "pedestrian_accident_hybrid_weight",
        "local_method_risk_index",
        "local_method_safety_index",
        "local_method_risk_decile",
        "geometry_wkt",
    ]
    existing_cols = [col for col in output_cols if col in result.columns]
    result[existing_cols].to_csv(OUT_DIR / "gwanak_road_safety_scores_utf8.csv", index=False, encoding="utf-8-sig")
    result[existing_cols].to_csv(OUT_DIR / "gwanak_road_safety_scores.csv", index=False, encoding="cp949")

    with (OUT_DIR / "road_safety_summary.json").open("w", encoding="utf-8") as f:
        json.dump({"input_metadata": meta, "summary": summary}, f, ensure_ascii=False, indent=2)

    write_markdown(meta, summary)
    print(json.dumps({"input_metadata": meta, "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
