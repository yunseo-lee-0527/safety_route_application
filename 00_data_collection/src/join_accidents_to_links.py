"""
join_accidents_to_links.py
--------------------------
각 MOCT_LINK 링크에 사고건수를 집계하여 CSV로 저장.

방법:
  1. 사고점(WGS84 lon/lat) → GeoDataFrame
  2. MOCT_LINK 읽기 (EPSG:5186)
  3. 사고점을 EPSG:5186으로 투영 후 sjoin_nearest로 가장 가까운 링크 매핑
  4. 링크별 사고건수 집계
  5. 링크 데이터에 사고건수 join → CSV 출력
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

BASE_DIR     = Path(__file__).resolve().parent
ACCIDENT_CSV = BASE_DIR / "taas_accidents_with_latlon.csv"
LINK_SHP     = BASE_DIR / "node_link_data" / "MOCT_LINK.shp"
OUTPUT_CSV   = BASE_DIR / "links_with_accident_count.csv"

# ── 1. 사고 데이터 로드 ────────────────────────────────────────────────────────
print("[1/5] 사고 데이터 로드 중...")
df_acc = pd.read_csv(ACCIDENT_CSV, encoding="utf-8-sig", low_memory=False)

# lon/lat 유효한 행만 사용
df_acc = df_acc.dropna(subset=["lon", "lat"])
df_acc = df_acc[(df_acc["lon"] != 0) & (df_acc["lat"] != 0)]
print(f"      사고 건수: {len(df_acc):,}")

gdf_acc = gpd.GeoDataFrame(
    df_acc,
    geometry=[Point(lon, lat) for lon, lat in zip(df_acc["lon"], df_acc["lat"])],
    crs="EPSG:4326",
)

# ── 2. MOCT_LINK 로드 ─────────────────────────────────────────────────────────
print("[2/5] MOCT_LINK 링크 데이터 로드 중...")
gdf_link = gpd.read_file(LINK_SHP)
print(f"      링크 건수: {len(gdf_link):,}")
print(f"      링크 CRS : {gdf_link.crs}")

# ── 3. 좌표계 통일 (링크 원본 CRS로 투영) ─────────────────────────────────────
print("[3/5] 좌표계 변환 중 (WGS84 → 링크 CRS)...")
gdf_acc_proj = gdf_acc[["acdnt_no", "geometry"]].to_crs(gdf_link.crs)

# ── 4. 가장 가까운 링크 매핑 (sjoin_nearest) ──────────────────────────────────
print("[4/5] 사고점 → 최근접 링크 매핑 중 (sjoin_nearest)...")
joined = gpd.sjoin_nearest(
    gdf_acc_proj,
    gdf_link[["LINK_ID", "geometry"]],
    how="left",
    distance_col="dist_m",
)

# 중복 방지: 같은 사고가 여러 링크에 매핑되면 가장 가까운 것 하나만 사용
joined = joined.sort_values("dist_m").drop_duplicates(subset="acdnt_no")

# 링크별 사고건수 집계
acc_count = (
    joined.groupby("LINK_ID")
    .size()
    .reset_index(name="accident_count")
)
print(f"      사고가 매핑된 링크 수: {len(acc_count):,}")

# ── 5. 링크 데이터에 사고건수 join → CSV 저장 ────────────────────────────────
print("[5/5] 링크 데이터에 사고건수 join 후 CSV 저장 중...")
df_link_attr = gdf_link.drop(columns="geometry")
df_out = df_link_attr.merge(acc_count, on="LINK_ID", how="left")
df_out["accident_count"] = df_out["accident_count"].fillna(0).astype(int)

df_out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
print(f"\n[완료] 출력 파일: {OUTPUT_CSV.resolve()}")
print(f"       총 링크 수     : {len(df_out):,}")
print(f"       사고 있는 링크 : {(df_out['accident_count'] > 0).sum():,}")
print(f"       총 사고건수    : {df_out['accident_count'].sum():,}")
