"""
통학구역 및 주거 건물 데이터 처리 — 서울시 전체

Input:
  data/raw/elementary_commuting_zone/elementary_commuting_zone.shp
      전국 초등학교 통학구역 (SD_CD='11' → 서울 622개 구역)
  data/raw/seoul_buildings/seoul_buildings.shp
      서울시 전체 건물 (695,774개)

Output:
  output/seoul_commuting_zones.gpkg        (통학구역 폴리곤, 경로 계산 입력용)
  output/seoul_commuting_zone_buildings.gpkg (학교별 주거 건물 레이어)
  data/processed/commuting_zones.geojson   (웹 표시용)
  data/processed/residential_buildings.geojson (웹 표시용)

Layer naming: HAKGUDO_NM에서 추출 → e.g. '서울한남초통학구역' → '한남초_res'
"""
import geopandas as gpd
import pandas as pd
from pathlib import Path
import sys
import logging
import re

sys.path.append(str(Path(__file__).parent.parent))

from config import Paths
from utils.geojson_writer import GeoJSONWriter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── 서울 SD_CD ────────────────────────────────────────────────────────────────
_SEOUL_SD_CD = '11'


def _fix_encoding(text: str) -> str:
    """cp1252→euc-kr 오인코딩 복구 (shp DBF 텍스트 컬럼)."""
    if not isinstance(text, str):
        return text
    try:
        return text.encode('cp1252').decode('euc-kr')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _zone_to_layer_name(hakgudo_nm: str) -> str:
    """통학구역명 → GPKG 레이어명.

    '서울한남초통학구역'       → '한남초_res'
    '신광초통학구역'           → '신광초_res'
    '서울금옥초서울옥수초공동통학구역' → '금옥초_res'  (첫 번째 학교명 사용)
    """
    # 공동통학구역: 첫 번째 학교명 추출
    name = re.sub(r'공동통학구역$', '', hakgudo_nm)
    name = re.sub(r'통학구역$', '', name)
    # 여러 학교 연결 패턴 '서울금옥초서울옥수초' → '서울금옥초' (take first)
    multi = re.findall(r'서울\S+초|[가-힣]+초', name)
    if multi:
        name = multi[0]
    # '서울' 접두사 제거
    name = re.sub(r'^서울', '', name)
    # GPKG에서 허용하지 않는 문자 제거
    name = re.sub(r'[^\w가-힣]', '', name)
    return f'{name}_res' if name else 'unknown_res'


class CommutingZoneProcessor:
    """서울시 전체 통학구역 + 주거 건물 Processor."""

    def __init__(self):
        self.zone_shp     = Paths.COMMUTING_ZONE_SHP
        self.bld_shp      = Paths.SEOUL_BUILDINGS_SHP
        self.zones_gpkg   = Paths.SEOUL_COMMUTING_ZONES_GPKG
        self.bld_gpkg     = Paths.SEOUL_RESIDENTIAL_BUILDINGS_GPKG
        self.zones_geojson = Paths.COMMUTING_ZONES_GEOJSON
        self.bld_geojson   = Paths.RESIDENTIAL_BUILDINGS_GEOJSON

    # ── 1. 통학구역 처리 ──────────────────────────────────────────────────────

    def process_zones(self) -> gpd.GeoDataFrame:
        logger.info(f"Loading commuting zones from {self.zone_shp}")
        gdf = gpd.read_file(self.zone_shp)

        # 서울만 필터
        gdf = gdf[gdf['SD_CD'].astype(str) == _SEOUL_SD_CD].copy()
        logger.info(f"Seoul commuting zones: {len(gdf)}")

        # 인코딩 복구
        for col in ['HAKGUDO_NM', 'EDU_NM', 'EDU_UP_NM']:
            if col in gdf.columns:
                gdf[col] = gdf[col].apply(_fix_encoding)

        # 레이어명 추가
        gdf['layer_name'] = gdf['HAKGUDO_NM'].apply(_zone_to_layer_name)

        # WGS84 변환
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # GPKG 저장
        self.zones_gpkg.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(self.zones_gpkg, layer='zones', driver='GPKG')
        logger.info(f"✅ Saved zones GPKG → {self.zones_gpkg}")

        # GeoJSON 저장 (웹용)
        self.zones_geojson.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(self.zones_geojson, driver='GeoJSON', encoding='utf-8')
        logger.info(f"✅ Saved zones GeoJSON → {self.zones_geojson}")

        import shutil
        web_dst = Paths.WEB_DATA / self.zones_geojson.name
        web_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.zones_geojson, web_dst)
        logger.info(f"Copied to {web_dst}")

        return gdf

    # ── 2. 건물 × 통학구역 공간 조인 ─────────────────────────────────────────

    def process_buildings(self, zones_gdf: gpd.GeoDataFrame):
        logger.info(f"Loading buildings from {self.bld_shp}")
        buildings = gpd.read_file(self.bld_shp)
        logger.info(f"Total buildings: {len(buildings):,}, CRS: {buildings.crs}")

        # 투영 좌표계로 통일 (공간 조인용)
        proj_crs = 'EPSG:5179'
        buildings_proj = buildings.to_crs(proj_crs)
        zones_proj     = zones_gdf.to_crs(proj_crs)

        # households proxy: A26 (층수), 최소 1
        buildings_proj['households'] = (
            buildings_proj['A26'].fillna(1).clip(lower=1).round().astype(int)
        )

        logger.info("Starting spatial join (building ∩ school zones) …")

        # gpd.sjoin은 R-tree 공간 인덱스를 사용하여
        # 기존 row-by-row intersects 대비 대폭 빠름 (600개 구역 × 695K 건물)
        joined = gpd.sjoin(
            buildings_proj[['geometry', 'households']],
            zones_proj[['geometry', 'layer_name', 'HAKGUDO_NM']],
            how='inner',
            predicate='intersects'
        )

        if len(joined) == 0:
            logger.warning("No buildings matched any zone.")
            return

        combined = joined[['geometry', 'households', 'layer_name', 'HAKGUDO_NM']].copy()
        combined.rename(columns={'layer_name': 'zone_layer', 'HAKGUDO_NM': 'school_nm'}, inplace=True)
        combined = gpd.GeoDataFrame(combined, crs=proj_crs)
        logger.info(f"Total building-zone records: {len(combined):,}")

        # GPKG: 레이어별 저장 (중단 후 재시작 가능 — 이미 쓴 레이어는 건너뜀)
        self.bld_gpkg.parent.mkdir(parents=True, exist_ok=True)
        layer_names = combined['zone_layer'].unique()
        logger.info(f"Writing {len(layer_names)} GPKG layers ...")

        # Determine which layers are already written (natural checkpoint via GPKG)
        existing_layers: set = set()
        if self.bld_gpkg.exists():
            import fiona
            existing_layers = set(fiona.listlayers(str(self.bld_gpkg)))
            if existing_layers:
                logger.info(f"Resuming: {len(existing_layers)} layers already in GPKG")

        for layer_name in layer_names:
            if layer_name in existing_layers:
                logger.info(f"  Skipping {layer_name} (already in GPKG)")
                continue
            subset = combined[combined['zone_layer'] == layer_name][['geometry', 'households']].copy()
            subset = subset.to_crs(epsg=4326)
            subset.to_file(self.bld_gpkg, layer=layer_name, driver='GPKG')

        logger.info(f"Saved buildings GPKG -> {self.bld_gpkg}")

        # GeoJSON (웹용) — 학교명 포함, WGS84
        web_gdf = combined.to_crs(epsg=4326)
        self.bld_geojson.parent.mkdir(parents=True, exist_ok=True)
        web_gdf.to_file(self.bld_geojson, driver='GeoJSON', encoding='utf-8')
        logger.info(f"✅ Saved buildings GeoJSON → {self.bld_geojson}")

        import shutil
        web_dst = Paths.WEB_DATA / self.bld_geojson.name
        web_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.bld_geojson, web_dst)
        logger.info(f"Copied to {web_dst}")

    # ── 3. 전체 실행 ─────────────────────────────────────────────────────────

    def run(self):
        logger.info("=" * 60)
        logger.info("Commuting Zone Processor  (Seoul-wide)")
        logger.info("=" * 60)

        zones_gdf = self.process_zones()
        self.process_buildings(zones_gdf)

        logger.info("=" * 60)
        logger.info("✅ CommutingZoneProcessor completed")
        logger.info("=" * 60)


if __name__ == '__main__':
    processor = CommutingZoneProcessor()
    processor.run()
