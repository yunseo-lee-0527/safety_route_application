from __future__ import annotations

from pathlib import Path

import folium
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import pandas as pd
from folium import GeoJson, GeoJsonTooltip
from shapely import wkt

ROOT = Path(__file__).resolve().parents[2]
ROAD_CSV = ROOT / "yunseo_lee" / "road_safety_full_remap_service" / "gwanak_road_safety_scores_full_remap_service_utf8.csv"
WALK_CSV = ROOT / "yunseo_lee" / "walking_edge_safety" / "gwanak_walking_edge_safety_utf8.csv"
OUT_HTML = ROOT / "yunseo_lee" / "road_and_walking_safety_map.html"


def score_to_hex(score: float | None, cmap_name: str = "RdYlGn_r") -> str:
    if score is None or pd.isna(score):
        return "#aaaaaa"
    cmap = cm.get_cmap(cmap_name)
    rgba = cmap(float(max(0.0, min(1.0, score))))
    return mcolors.to_hex(rgba)


DECILE_COLORS = {i: score_to_hex((i - 0.5) / 10.0) for i in range(1, 11)}


def _round_coords(coords, prec: int = 5):
    return [[round(x, prec), round(y, prec)] for x, y in coords]


def _geom_to_geojson_coords(geom):
    if geom.geom_type == "LineString":
        return {"type": "LineString", "coordinates": _round_coords(geom.coords)}
    return {
        "type": "MultiLineString",
        "coordinates": [_round_coords(part.coords) for part in geom.geoms],
    }


def _f(row: pd.Series, col: str, default=0.0) -> float:
    value = row.get(col, default)
    if pd.isna(value):
        return float(default)
    return float(value)


def build_road_geojson(df: pd.DataFrame) -> dict:
    features = []
    for _, row in df.iterrows():
        try:
            geom = wkt.loads(row["geometry_wkt"])
        except Exception:
            continue
        decile = int(row.get("local_method_risk_decile") or 5)
        features.append({
            "type": "Feature",
            "geometry": _geom_to_geojson_coords(geom),
            "properties": {
                "road_name": str(row.get("road_name", "") or ""),
                "road_class": str(row.get("road_class", "") or ""),
                "risk_decile": decile,
                "risk_index": round(_f(row, "local_method_risk_index"), 3),
                "safety_index": round(_f(row, "local_method_safety_index"), 3),
                "length_m": round(_f(row, "length_m"), 1),
                "crosswalk_density": round(_f(row, "crosswalk_count_per_100m"), 2),
                "signal_density": round(_f(row, "traffic_signal_count_per_100m"), 2),
                "child_facility": round(_f(row, "child_facility_count_300m_capped"), 1),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_walk_geojson(df: pd.DataFrame) -> dict:
    features = []
    for _, row in df.iterrows():
        try:
            geom = wkt.loads(row["geometry_wkt"])
        except Exception:
            continue
        score = row.get("safety_score_0_1")
        score_val = float(score) if not pd.isna(score) else None
        features.append({
            "type": "Feature",
            "geometry": _geom_to_geojson_coords(geom),
            "properties": {
                "score": round(score_val, 3) if score_val is not None else None,
                "score_str": f"{score_val:.3f}" if score_val is not None else "N/A",
                "basis": str(row.get("edge_safety_basis", "") or ""),
                "walking_type": str(row.get("walking_type", "") or ""),
                "crosswalk": int(row.get("crosswalk", 0) or 0),
                "length_m": round(_f(row, "length_m"), 1),
                "matched_road": str(row.get("matched_road_name", "") or ""),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def build_map(road_gj: dict, walk_gj: dict) -> folium.Map:
    m = folium.Map(location=[37.478, 126.951], zoom_start=13, tiles="CartoDB positron", prefer_canvas=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)

    GeoJson(
        road_gj,
        name="도로 안전도 지수",
        style_function=lambda f: {
            "color": DECILE_COLORS.get(f["properties"].get("risk_decile", 5), "#aaaaaa"),
            "weight": 3,
            "opacity": 0.55,
        },
        tooltip=GeoJsonTooltip(
            fields=[
                "road_name", "road_class", "risk_decile", "risk_index", "length_m",
                "crosswalk_density", "signal_density", "child_facility",
            ],
            aliases=[
                "도로명", "도로등급", "위험도 분위", "위험도 지수", "링크 길이(m)",
                "횡단보도/100m", "신호등/100m", "어린이시설(상한)",
            ],
            localize=True,
            sticky=True,
        ),
        show=True,
    ).add_to(m)

    GeoJson(
        walk_gj,
        name="보행 edge 안전도 지수",
        style_function=lambda f: {
            "color": score_to_hex(f["properties"].get("score")),
            "weight": 4,
            "opacity": 0.82,
        },
        tooltip=GeoJsonTooltip(
            fields=["score_str", "basis", "walking_type", "crosswalk", "length_m", "matched_road"],
            aliases=["점수(0=안전, 1=위험)", "분류", "보행유형", "횡단보도 플래그", "길이(m)", "매칭 도로"],
            localize=True,
            sticky=True,
        ),
        show=True,
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:12px 14px;border:1px solid #888;
                border-radius:6px;font-family:sans-serif;font-size:12px;
                box-shadow:0 2px 6px rgba(0,0,0,.15);">
      <div style="font-weight:700;margin-bottom:6px;">관악구 안전도 지수</div>
      <div>도로: 1분위 초록, 10분위 빨강</div>
      <div>보행: 0 안전, 1 위험</div>
      <div style="margin-top:6px;color:#555;">횡단보도/신호등은 최근접 도로 edge 기준</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    return m


def main() -> None:
    roads = pd.read_csv(ROAD_CSV, encoding="utf-8-sig").dropna(subset=["geometry_wkt"])
    walks = pd.read_csv(WALK_CSV, encoding="utf-8-sig").dropna(subset=["geometry_wkt"])
    road_gj = build_road_geojson(roads)
    walk_gj = build_walk_geojson(walks)
    build_map(road_gj, walk_gj).save(str(OUT_HTML))
    print(f"saved {OUT_HTML} ({OUT_HTML.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
