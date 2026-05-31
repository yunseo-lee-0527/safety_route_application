"""
통학 인원 추정 Processor

각 경로에 예상 통학 인원을 비례 배분 (학교별 단일 패스)
"""
import geopandas as gpd
import shutil
from pathlib import Path
from shapely.geometry import Point
import sys
import logging

sys.path.append(str(Path(__file__).parent.parent))

import re

from config import Paths, load_school_enrollment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _school_short_name(full_name: str) -> str:
    if not isinstance(full_name, str):
        return ""
    name = re.sub(r"^서울", "", full_name.strip())
    name = re.sub(r"등학교$", "", name)
    return name.strip()


def _layer_short_name(layer_name: str) -> str:
    return layer_name.replace("_res", "").strip()




class CommuteEstimationProcessor:
    """통학 인원 추정 Processor"""

    def __init__(self):
        self.paths_geojson = Paths.DATA_PROCESSED / 'school_paths_optimal.geojson'
        self.buildings_gpkg = Paths.SEOUL_RESIDENTIAL_BUILDINGS_GPKG
        self.output_geojson = Paths.DATA_PROCESSED / 'school_paths_with_students.geojson'

        logger.info("Loading school enrollment data...")
        self.school_enrollment = load_school_enrollment()
        logger.info(f"Loaded {len(self.school_enrollment)} schools")
        for school, n in self.school_enrollment.items():
            logger.info(f"  {school}: {n}")

    def load_paths(self):
        """경로 GeoJSON 로드"""
        logger.info(f"Loading paths from {self.paths_geojson}")
        gdf = gpd.read_file(self.paths_geojson)
        logger.info(f"Loaded {len(gdf)} paths")
        return gdf

    def _validate_schools(self, gdf_paths):
        """경로의 school 속성값과 enrollment 키 일치 여부 확인.

        불일치 시 학생 수가 배분되지 않으므로 조기에 경고.
        """
        path_schools  = set(gdf_paths['school'].dropna().unique())
        enroll_schools = set(self.school_enrollment.keys())

        unmatched_paths = path_schools - enroll_schools
        if unmatched_paths:
            logger.warning(f"Path schools not in enrollment (will be skipped): {unmatched_paths}")

        missing_paths = enroll_schools - path_schools
        if missing_paths:
            logger.warning(f"Enrollment schools with no paths (0 students distributed): {missing_paths}")

    def match_and_estimate(self, gdf_paths):
        """경로-건물 매칭 및 통학 인원 추정 (학교별 단일 패스)

        각 학교에 대해:
          1. GPKG에서 해당 학교 레이어만 로드 (lazy)
          2. 경로 시작점 ↔ 건물 최근접 조인 (EPSG:5179, 100m 이내)
          3. 세대수 비례로 통학 인원 배분
        """
        import fiona
        available_layers = set(fiona.listlayers(str(self.buildings_gpkg)))

        gdf_paths = gdf_paths.copy()
        gdf_paths['estimated_students'] = 0.0
        gdf_paths['households']         = 0

        # Build reverse mapping: short_name -> layer_name (dynamic)
        layer_short_to_layer = {_layer_short_name(l): l for l in available_layers}

        for school, total_students in self.school_enrollment.items():
            short = _school_short_name(school)
            layer_name = layer_short_to_layer.get(short)
            # fallback: partial substring match
            if not layer_name:
                layer_name = next(
                    (l for s, l in layer_short_to_layer.items()
                     if short in s or s in short),
                    None
                )
            if not layer_name or layer_name not in available_layers:
                logger.warning(f"No GPKG layer for '{school}', skipping")
                continue

            mask = gdf_paths['school'] == school
            school_paths = gdf_paths[mask]
            if len(school_paths) == 0:
                continue

            # 해당 학교 건물만 로드 (전체 로드 후 필터링 제거)
            school_buildings = gpd.read_file(
                self.buildings_gpkg, layer=layer_name
            )[['geometry', 'households']]

            # 경로 시작점 GDF → EPSG:5179 투영
            start_gdf = gpd.GeoDataFrame(
                index=school_paths.index,
                geometry=school_paths.geometry.apply(lambda l: Point(l.coords[0])),
                crs='EPSG:4326'
            ).to_crs('EPSG:5179')

            joined = gpd.sjoin_nearest(
                start_gdf,
                school_buildings.to_crs('EPSG:5179')[['geometry', 'households']],
                how='left',
                max_distance=100  # 미터
            )
            # 거리 동점 시 중복 제거
            joined = joined[~joined.index.duplicated(keep='first')]

            households = joined['households'].fillna(0)
            total_hh   = households.sum()

            unmatched = int((households == 0).sum())
            if unmatched:
                logger.warning(
                    f"{school}: {unmatched}/{len(school_paths)} paths "
                    f"unmatched (>100m from any building)"
                )
            if total_hh == 0:
                logger.warning(f"{school}: no matched households, skipping distribution")
                continue

            gdf_paths.loc[mask, 'households']         = households.values
            gdf_paths.loc[mask, 'estimated_students'] = (
                households / total_hh * total_students
            ).values

            logger.info(
                f"{school}: {total_students} students → "
                f"{len(school_paths)} paths, {int(total_hh)} total households matched"
            )

        est = gdf_paths['estimated_students']
        logger.info("=== Estimation Statistics ===")
        logger.info(f"Total paths:            {len(gdf_paths)}")
        logger.info(f"Paths with students:    {(est > 0).sum()}")
        logger.info(f"Total estimated:        {est.sum():.0f}")
        logger.info(f"Mean / Max per path:    {est.mean():.2f} / {est.max():.2f}")

        return gdf_paths

    def save_result(self, gdf_paths):
        """결과 저장"""
        columns = ['school', 'gate', 'distance', 'households', 'estimated_students', 'geometry']
        result = gdf_paths[columns].copy()
        result['estimated_students'] = result['estimated_students'].round(2)
        result['distance']           = result['distance'].round(2)

        self.output_geojson.parent.mkdir(parents=True, exist_ok=True)
        result.to_file(self.output_geojson, driver='GeoJSON')
        logger.info(f"✅ Saved to {self.output_geojson}")

        # web/data/ 복사 (웹 서버에서 바로 사용)
        web_output = Paths.WEB_DATA / self.output_geojson.name
        web_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.output_geojson, web_output)
        logger.info(f"✅ Copied to {web_output}")

    def run(self):
        """전체 파이프라인 실행"""
        logger.info("=" * 60)
        logger.info("Commute Estimation Processor")
        logger.info("=" * 60)

        try:
            gdf_paths = self.load_paths()
            self._validate_schools(gdf_paths)
            gdf_paths = self.match_and_estimate(gdf_paths)
            self.save_result(gdf_paths)

            logger.info("=" * 60)
            logger.info("✅ Processing completed successfully")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"❌ Processing failed: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    processor = CommuteEstimationProcessor()
    success = processor.run()
    if not success:
        sys.exit(1)
