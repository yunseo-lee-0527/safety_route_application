"""
visualize_seoul_node_link.py
----------------------------
MOCT_NODE / MOCT_LINK 셰이프파일에서 서울시 영역만 추려
위성지도 위에 노드/링크를 동시에 표시하는 folium HTML을 생성한다.

출력: seoul_node_link_satellite.html
"""

from pathlib import Path

import folium
import geopandas as gpd
from shapely.geometry import box

BASE_DIR        = Path(__file__).resolve().parent
NODE_SHP        = BASE_DIR / "node_link_data" / "MOCT_NODE.shp"
LINK_SHP        = BASE_DIR / "node_link_data" / "MOCT_LINK.shp"
SEOUL_BOUND_SHP = BASE_DIR / "seoul_boundary.shp"
OUTPUT_HTML     = BASE_DIR / "seoul_node_link_satellite.html"

# 1. 서울 경계 ------------------------------------------------------------
print("[1/5] 서울 경계 로드 중...")
seoul = gpd.read_file(SEOUL_BOUND_SHP)
seoul_union_5186 = seoul.union_all() if hasattr(seoul, "union_all") else seoul.unary_union
minx, miny, maxx, maxy = seoul.total_bounds
bbox = (minx, miny, maxx, maxy)
print(f"      서울 bbox(EPSG:5186): {bbox}")

# 2. 링크/노드 bbox 필터로 읽기 (전국 데이터에서 서울만) ------------------
print("[2/5] 링크 데이터 bbox 필터로 로드 중...")
gdf_link = gpd.read_file(LINK_SHP, bbox=bbox)
gdf_link = gdf_link[gdf_link.intersects(seoul_union_5186)].copy()
print(f"      서울 링크 수: {len(gdf_link):,}")

print("[3/5] 노드 데이터 bbox 필터로 로드 중...")
gdf_node = gpd.read_file(NODE_SHP, bbox=bbox)
gdf_node = gdf_node[gdf_node.within(seoul_union_5186)].copy()
print(f"      서울 노드 수: {len(gdf_node):,}")

# 3. WGS84 로 변환 --------------------------------------------------------
print("[4/5] 좌표계 WGS84 변환 중...")
gdf_link_wgs = gdf_link.to_crs(epsg=4326)
gdf_node_wgs = gdf_node.to_crs(epsg=4326)
seoul_wgs    = seoul.to_crs(epsg=4326)

# 4. folium 지도 생성 (Esri 위성타일) -------------------------------------
print("[5/5] folium 지도 생성 중...")
center_lat = (seoul_wgs.total_bounds[1] + seoul_wgs.total_bounds[3]) / 2
center_lon = (seoul_wgs.total_bounds[0] + seoul_wgs.total_bounds[2]) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles=None)

# 위성 (기본)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
    name="Satellite (Esri)",
    overlay=False,
    control=True,
).add_to(m)

# 라벨 오버레이 (선택)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    attr="Esri Boundaries & Places",
    name="Labels (Esri)",
    overlay=True,
    control=True,
).add_to(m)

# OSM 대안
folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, control=True).add_to(m)

# 4-1. 서울 경계 -----------------------------------------------------------
folium.GeoJson(
    seoul_wgs.__geo_interface__,
    name="서울 자치구 경계",
    style_function=lambda f: {
        "color": "#FFD400",
        "weight": 1.5,
        "fillOpacity": 0.0,
    },
).add_to(m)

# 4-2. 링크 (선) ----------------------------------------------------------
link_geojson = gdf_link_wgs[
    ["LINK_ID", "ROAD_NAME", "ROAD_RANK", "LANES", "MAX_SPD", "geometry"]
].__geo_interface__

folium.GeoJson(
    link_geojson,
    name=f"MOCT_LINK ({len(gdf_link_wgs):,})",
    style_function=lambda f: {
        "color": "#00E5FF",
        "weight": 1.2,
        "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["LINK_ID", "ROAD_NAME", "ROAD_RANK", "LANES", "MAX_SPD"],
        aliases=["LINK_ID", "도로명", "등급", "차로수", "제한속도"],
        sticky=False,
    ),
).add_to(m)

# 4-3. 노드 (점) — 단일 GeoJSON 레이어로 경량화 ---------------------------
node_geojson = gdf_node_wgs[
    ["NODE_ID", "NODE_NAME", "NODE_TYPE", "geometry"]
].__geo_interface__

folium.GeoJson(
    node_geojson,
    name=f"MOCT_NODE ({len(gdf_node_wgs):,})",
    marker=folium.CircleMarker(
        radius=2,
        color="#FF3D00",
        fill=True,
        fill_color="#FF3D00",
        fill_opacity=0.9,
        weight=0,
    ),
    tooltip=folium.GeoJsonTooltip(
        fields=["NODE_ID", "NODE_NAME", "NODE_TYPE"],
        aliases=["NODE_ID", "이름", "유형"],
        sticky=False,
    ),
).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

m.fit_bounds([[seoul_wgs.total_bounds[1], seoul_wgs.total_bounds[0]],
              [seoul_wgs.total_bounds[3], seoul_wgs.total_bounds[2]]])

m.save(str(OUTPUT_HTML))
print(f"\n[완료] 출력 HTML: {OUTPUT_HTML.resolve()}")
print(f"       링크 수: {len(gdf_link_wgs):,}")
print(f"       노드 수: {len(gdf_node_wgs):,}")
