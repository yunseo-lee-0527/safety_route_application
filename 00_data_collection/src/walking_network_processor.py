"""
보행 네트워크 GeoJSON 변환 Processor — 서울시 전체

Input : data/raw/서울시 자치구별 도보 네트워크 공간정보.csv  (cp949, ~100 MB)
Output: data/processed/walking_network.geojson
        web/data/walking_network.geojson
"""
import shutil
from pathlib import Path
from shapely.wkt import loads as wkt_loads
import pandas as pd
import sys
import logging

sys.path.append(str(Path(__file__).parent.parent))

from config import Paths
from utils.geojson_writer import GeoJSONWriter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CSV column names (cp949, after pandas read) ──────────────────────────────
_COL_TYPE      = '노드링크 유형'
_COL_LINK_WKT  = '링크 WKT'
_COL_LINK_ID   = '링크 ID'
_COL_TYPE_CD   = '링크 유형 코드'
_COL_START     = '시작노드 ID'
_COL_END       = '종료노드 ID'
_COL_LENGTH    = '링크 길이'
_COL_EMD       = '읍면동명'
_COL_OVERPASS  = '고가도로'
_COL_BRIDGE    = '교량'
_COL_TUNNEL    = '터널'
_COL_FOOTBR    = '육교'
_COL_CROSSWALK = '횡단보도'
_COL_BUILDING  = '건물내'


class WalkingNetworkProcessor:
    """서울시 보행 네트워크 CSV → GeoJSON Processor."""

    def __init__(self):
        self.input_csv       = Paths.WALKING_NETWORK_CSV
        self.output_geojson  = Paths.DATA_PROCESSED / 'walking_network.geojson'
        self.web_output      = Paths.WEB_DATA / 'walking_network.geojson'

    def run(self):
        logger.info("=" * 60)
        logger.info("Walking Network Processor (Seoul-wide CSV)")
        logger.info("=" * 60)

        if not self.input_csv.exists():
            raise FileNotFoundError(f"Walking network CSV not found: {self.input_csv}")

        logger.info(f"Loading {self.input_csv.name} …")

        # Read in chunks to be memory-efficient (file is ~100 MB)
        features = []
        skipped  = 0
        total    = 0

        for chunk in pd.read_csv(self.input_csv, encoding='cp949', chunksize=50_000):
            # Keep only LINK rows
            links = chunk[chunk[_COL_TYPE] == 'LINK']
            total += len(chunk)

            for _, row in links.iterrows():
                wkt_str = row.get(_COL_LINK_WKT)
                if not isinstance(wkt_str, str) or not wkt_str.startswith('LINESTRING'):
                    skipped += 1
                    continue

                try:
                    geom = wkt_loads(wkt_str)
                except Exception:
                    skipped += 1
                    continue

                props = {
                    'lnkg_id':   row.get(_COL_LINK_ID),
                    'length':    row.get(_COL_LENGTH),
                    'type_cd':   row.get(_COL_TYPE_CD),
                    'crosswalk': row.get(_COL_CROSSWALK),
                    'overpass':  row.get(_COL_OVERPASS),
                    'bridge':    row.get(_COL_BRIDGE),
                    'tunnel':    row.get(_COL_TUNNEL),
                    'building':  row.get(_COL_BUILDING),
                    'emd_nm':    row.get(_COL_EMD),
                }
                features.append(GeoJSONWriter.feature(geom, props))

        logger.info(f"Total rows processed: {total:,}  |  LINK features: {len(features):,}  |  skipped: {skipped:,}")

        # data/processed/
        self.output_geojson.parent.mkdir(parents=True, exist_ok=True)
        GeoJSONWriter.write(features, self.output_geojson)
        logger.info(f"✅ Saved → {self.output_geojson}")

        # web/data/
        self.web_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.output_geojson, self.web_output)
        logger.info(f"✅ Copied → {self.web_output}")

        return True


if __name__ == '__main__':
    processor = WalkingNetworkProcessor()
    success = processor.run()
    if not success:
        sys.exit(1)
