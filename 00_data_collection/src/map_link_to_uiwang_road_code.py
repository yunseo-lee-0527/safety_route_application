"""
map_link_to_uiwang_road_code.py
-------------------------------
의왕시 보행안전지수 지도(도로코드 1~) ↔ 표준노드링크(MOCT_LINK) 매핑.

입력:
  - 의왕시 보행안전지수 지도 시각화 데이터.shp (994 polygons, 행 순서 = 도로코드 순서)
  - 경기도 의왕시_보행안전지수_20221202.csv     (994행, 도로코드 + 보행안전지수)
  - node_link_data/MOCT_LINK.shp                (전국 표준노드링크)
  - taas_accidents_with_latlon.csv              (사고점 lon/lat)

출력:
  1) uiwang_link_to_road_code.csv
     LINK_ID 단위. 어느 도로코드 폴리곤과 가장 많이 겹치는지 + 보행안전지수 + 해당 링크 사고건수
  2) uiwang_road_code_with_accidents.csv
     도로코드 단위. 보행안전지수 + 총 사고건수(폴리곤 내부 사고점 기준) + 매핑된 LINK 수

가정:
  - 시각화 SHP에는 .dbf/.prj가 없으므로 행 순서가 CSV의 도로코드 순서(첫 행 = 도로코드 1, 두 번째 행 = 도로코드 2 …)와 동일.
  - 시각화 SHP의 CRS는 EPSG:5186 (의왕시 bounds로 검증됨).
"""

import os
os.environ["SHAPE_RESTORE_SHX"] = "YES"   # .shx 누락 시 자동 복원

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

BASE_DIR        = Path(__file__).resolve().parent
UIWANG_SHP      = BASE_DIR / "의왕시 보행안전지수 지도 시각화 데이터.shp"
UIWANG_CSV      = BASE_DIR / "경기도 의왕시_보행안전지수_20221202.csv"
LINK_SHP        = BASE_DIR / "node_link_data" / "MOCT_LINK.shp"
ACCIDENT_CSV    = BASE_DIR / "taas_accidents_with_latlon.csv"

OUT_LINK2CODE   = BASE_DIR / "uiwang_link_to_road_code.csv"
OUT_CODE_AGG    = BASE_DIR / "uiwang_road_code_with_accidents.csv"

UIWANG_CRS      = "EPSG:5186"

# ── 1. 의왕 폴리곤 로드 + 도로코드 부여 ────────────────────────────────────────
print("[1/6] 의왕 폴리곤 + 도로코드 로드 중...")
gdf_uiwang = gpd.read_file(UIWANG_SHP).set_crs(UIWANG_CRS)
df_safe    = pd.read_csv(UIWANG_CSV, encoding="utf-8-sig")

assert len(gdf_uiwang) == len(df_safe), (
    f"폴리곤 수({len(gdf_uiwang)})와 CSV 행 수({len(df_safe)})가 다릅니다."
)

# 행 순서대로 도로코드/지수 부여
gdf_uiwang["도로코드"]     = df_safe["도로코드"].values
gdf_uiwang["보행안전지수"] = df_safe["보행안전지수"].values
print(f"      폴리곤 수: {len(gdf_uiwang):,} / 도로코드 범위: "
      f"{gdf_uiwang['도로코드'].min()}~{gdf_uiwang['도로코드'].max()}")

# ── 2. MOCT_LINK 로드 후 의왕 bbox로 클립 ────────────────────────────────────
print("[2/6] MOCT_LINK 로드 + 의왕시 영역으로 클립 중...")
uiwang_bbox = tuple(gdf_uiwang.total_bounds)   # (minx, miny, maxx, maxy)
# bbox 인자 + mask CRS를 일치시키기 위해 같은 CRS의 SHP를 직접 read
gdf_link = gpd.read_file(LINK_SHP, bbox=uiwang_bbox)
# CRS는 EPSG:5186과 동일 좌표계이지만 표기가 달라 set_crs로 통일
gdf_link = gdf_link.set_crs(UIWANG_CRS, allow_override=True)
print(f"      의왕 bbox 내 링크 수: {len(gdf_link):,}")

# ── 3. LINK ↔ 도로코드 매핑 (intersection 길이 최대 기준) ──────────────────────
print("[3/6] 링크-폴리곤 공간조인(intersection 길이 최대) 계산 중...")
# overlay로 각 LINK ∩ 폴리곤 부분기하 생성 후 길이 계산
inter = gpd.overlay(
    gdf_link[["LINK_ID", "ROAD_NAME", "ROAD_RANK", "LENGTH", "geometry"]],
    gdf_uiwang[["도로코드", "보행안전지수", "geometry"]],
    how="intersection",
    keep_geom_type=False,
)
inter["inter_len"] = inter.geometry.length
# LINK_ID당 가장 길게 겹치는 도로코드 1개 선택
inter_sorted = inter.sort_values("inter_len", ascending=False)
link2code = inter_sorted.drop_duplicates(subset="LINK_ID", keep="first")
link2code = link2code[[
    "LINK_ID", "ROAD_NAME", "ROAD_RANK", "LENGTH",
    "도로코드", "보행안전지수", "inter_len",
]].rename(columns={"inter_len": "intersection_length_m"})
print(f"      도로코드와 매핑된 링크 수: {len(link2code):,}")

# ── 4. 사고점 → 도로코드 폴리곤 spatial join ───────────────────────────────────
print("[4/6] 사고점 → 도로코드 폴리곤 매핑 중...")
df_acc = pd.read_csv(ACCIDENT_CSV, encoding="utf-8-sig", low_memory=False)
df_acc = df_acc.dropna(subset=["lon", "lat"])
df_acc = df_acc[(df_acc["lon"] != 0) & (df_acc["lat"] != 0)]
gdf_acc = gpd.GeoDataFrame(
    df_acc[["acdnt_no", "lon", "lat"]],
    geometry=[Point(x, y) for x, y in zip(df_acc["lon"], df_acc["lat"])],
    crs="EPSG:4326",
).to_crs(UIWANG_CRS)

acc_in_poly = gpd.sjoin(
    gdf_acc, gdf_uiwang[["도로코드", "geometry"]],
    how="inner", predicate="within",
)
print(f"      의왕 폴리곤 내부 사고 수: {len(acc_in_poly):,} / 전체 {len(gdf_acc):,}")

acc_per_code = (
    acc_in_poly.groupby("도로코드").size()
    .reset_index(name="accident_count")
)

# ── 5. 출력1: LINK ↔ 도로코드 매핑 + 링크별 사고건수 ──────────────────────────
print("[5/6] 출력1 작성: 링크 단위 매핑 CSV...")
# 링크별 사고건수: 사고점이 그 LINK_ID와 가장 가까운 LINK인 경우. 이전 산출물 재사용.
prev_link_csv = BASE_DIR / "links_with_accident_count.csv"
if prev_link_csv.exists():
    df_prev = pd.read_csv(
        prev_link_csv, encoding="utf-8-sig",
        usecols=["LINK_ID", "accident_count"],
        dtype={"LINK_ID": str},
    )
    link2code["LINK_ID"] = link2code["LINK_ID"].astype(str)
    link2code = link2code.merge(df_prev, on="LINK_ID", how="left")
    link2code["accident_count"] = link2code["accident_count"].fillna(0).astype(int)
else:
    link2code["accident_count"] = 0

link2code.to_csv(OUT_LINK2CODE, index=False, encoding="utf-8-sig")
print(f"      → {OUT_LINK2CODE.name}")

# ── 6. 출력2: 도로코드 단위 집계 ──────────────────────────────────────────────
print("[6/6] 출력2 작성: 도로코드 단위 집계 CSV...")
mapped_link_count = (
    link2code.groupby("도로코드").size()
    .reset_index(name="mapped_link_count")
)

df_code = (
    df_safe
    .merge(acc_per_code, on="도로코드", how="left")
    .merge(mapped_link_count, on="도로코드", how="left")
)
df_code["accident_count"]    = df_code["accident_count"].fillna(0).astype(int)
df_code["mapped_link_count"] = df_code["mapped_link_count"].fillna(0).astype(int)
df_code.to_csv(OUT_CODE_AGG, index=False, encoding="utf-8-sig")
print(f"      → {OUT_CODE_AGG.name}")

# ── 요약 ──────────────────────────────────────────────────────────────────────
print("\n[요약]")
print(f"  도로코드 수            : {len(df_code):,}")
print(f"  매핑된 표준 LINK 수    : {len(link2code):,}")
print(f"  도로코드 폴리곤 내 사고: {df_code['accident_count'].sum():,}")
print(f"  사고가 있는 도로코드   : {(df_code['accident_count'] > 0).sum():,}")
