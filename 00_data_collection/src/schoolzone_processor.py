"""학교구역 데이터 처리 — 전 서울 자치구

Input : data/raw/*_스쿨존.json  (자치구별 학교구역 JSON, 25개 파일)
Output: data/processed/schoolzones.geojson
"""
import json
from pathlib import Path
from shapely import wkt
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
import sys
import logging

sys.path.append(str(Path(__file__).parent.parent))

from config import Paths, get_schoolzone_json_files
from utils.coordinate_transform import transformer
from utils.geojson_writer import GeoJSONWriter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _fix_encoding(text: str) -> str:
    """Shapefile DBF 필드 등에서 cp1252→euc-kr 오인코딩된 문자열 복구."""
    if not isinstance(text, str):
        return text
    try:
        return text.encode('cp1252').decode('euc-kr')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


class SchoolZoneProcessor:
    """전 서울 자치구 학교구역 Processor."""

    def run(self):
        json_files = get_schoolzone_json_files()
        if not json_files:
            raise FileNotFoundError(
                f"No school-zone JSON files found in {Paths.DATA_RAW}. "
                f"Expected pattern: *_스쿨존.json"
            )
        logger.info(f"Found {len(json_files)} school-zone JSON files")

        features = []
        skipped = 0

        for json_path in json_files:
            district = json_path.stem.replace('_스쿨존', '')
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"{json_path.name}: failed to read — {e}")
                skipped += 1
                continue

            try:
                items = data['response']['body']['items']['item']
            except (KeyError, TypeError) as e:
                logger.warning(f"{json_path.name}: unexpected structure — {e}")
                skipped += 1
                continue

            if not isinstance(items, list):
                items = [items]

            file_count = 0
            for item in items:
                name = _fix_encoding(item.get('trgtFcltNm', ''))
                geom_txt = item.get('fturGeomVl', '')

                if not geom_txt:
                    continue

                try:
                    geom = wkt.loads(geom_txt)
                except Exception:
                    continue

                # EPSG:5174 → WGS84
                geom_wgs84 = transformer.transform_geometry(geom, from_crs="EPSG:5174")

                properties = {
                    'school_name': name,
                    'district': district,
                }
                features.append(GeoJSONWriter.feature(geom_wgs84, properties))
                file_count += 1

            logger.info(f"  {json_path.name}: {file_count} zones")

        output = Paths.DATA_PROCESSED / 'schoolzones.geojson'
        GeoJSONWriter.write(features, output)
        logger.info(f"✅ Saved {len(features)} school zones ({skipped} files skipped) → {output}")

        import shutil
        web_dst = Paths.WEB_DATA / output.name
        web_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, web_dst)
        logger.info(f"Copied to {web_dst}")


if __name__ == '__main__':
    processor = SchoolZoneProcessor()
    processor.run()
