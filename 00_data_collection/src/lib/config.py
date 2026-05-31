"""
프로젝트 전역 설정
모든 좌표계 변환 상수와 경로 설정을 중앙화
"""
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

# 프로젝트 루트 경로
PROJECT_ROOT = Path(__file__).parent.parent


def _resolve_dir(standard: Path, *fallbacks: Path) -> Path:
    """Return the first existing path among candidates, else the standard path."""
    if standard.exists():
        return standard
    for fb in fallbacks:
        if fb.exists():
            return fb
    return standard


# =============================================================================
# 경로 설정
# =============================================================================

class Paths:
    """파일 경로 중앙 관리"""

    # 데이터 디렉토리 — 표준 위치 우선, 없으면 상위 폴더의 data-raw- 폴더 사용
    DATA_RAW       = _resolve_dir(PROJECT_ROOT / 'data' / 'raw',
                                  PROJECT_ROOT.parent / 'data-raw-')
    DATA_PROCESSED = _resolve_dir(PROJECT_ROOT / 'data' / 'processed')

    # 원본 데이터 파일
    # SCHOOLZONE_JSON removed — use get_schoolzone_json_files() instead
    # GATE_CSV removed — use get_gate_csv_files() instead
    # Seoul-wide pedestrian network (cp949 CSV)
    WALKING_NETWORK_CSV = DATA_RAW / '서울시 자치구별 도보 네트워크 공간정보.csv'
    # Seoul-wide commuting zone & building shapefiles
    COMMUTING_ZONE_SHP  = DATA_RAW / 'elementary_commuting_zone' / 'elementary_commuting_zone.shp'
    SEOUL_BUILDINGS_SHP = DATA_RAW / 'seoul_buildings' / 'seoul_buildings.shp'
    ACCIDENT_CSV = DATA_RAW / 'accident_data.csv'

    # Generated output GeoPackages (Seoul-wide)
    _OUTPUT_DIR = _resolve_dir(PROJECT_ROOT / 'output',
                               PROJECT_ROOT.parent / 'output-')
    SEOUL_COMMUTING_ZONES_GPKG       = _OUTPUT_DIR / 'seoul_commuting_zones.gpkg'
    SEOUL_RESIDENTIAL_BUILDINGS_GPKG = _OUTPUT_DIR / 'seoul_commuting_zone_buildings.gpkg'

    # 처리된 데이터 파일 (GeoJSON)
    SCHOOLZONES_GEOJSON = DATA_PROCESSED / 'schoolzones.geojson'
    GATES_GEOJSON = DATA_PROCESSED / 'school_gates.geojson'
    WALKING_NETWORK_GEOJSON = DATA_PROCESSED / 'walking_network.geojson'
    ACCIDENTS_GEOJSON = DATA_PROCESSED / 'accidents.geojson'
    COMMUTING_ZONES_GEOJSON = DATA_PROCESSED / 'commuting_zones.geojson'
    RESIDENTIAL_BUILDINGS_GEOJSON = DATA_PROCESSED / 'residential_buildings.geojson'
    OPTIMAL_PATHS_GEOJSON = DATA_PROCESSED / 'school_paths_optimal.geojson'
    SAFETY_PATHS_GEOJSON = DATA_PROCESSED / 'school_paths_safety.geojson'

    # 웹 데이터 디렉토리 (심볼릭 링크 또는 복사 대상)
    WEB_DATA = _resolve_dir(PROJECT_ROOT / 'web' / 'data',
                            PROJECT_ROOT.parent / 'web-data-')


# =============================================================================
# 좌표계 변환 설정
# =============================================================================

@dataclass
class CoordinateConfig:
    """
    EPSG:5174 좌표계 보정 설정
    
    용산구 데이터는 EPSG:5174 좌표계를 사용하지만,
    실제 위치와 약간의 오차가 있어 보정이 필요함.
    """
    # 기준점 (EPSG:5174)
    x0: float = 205082.6999790271
    y0: float = 462756.8055959368
    
    # 목표 위치 (WGS84 - 실제 지도상 위치)
    lat_target: float = 37.664409
    lon_target: float = 127.057603
    
    # 계산된 오프셋 (미터 단위)
    dx: float = -69.70515757519752
    dy: float = -308.8022599006654

COORD_CONFIG = CoordinateConfig()


# =============================================================================
# 레이어 매핑
# =============================================================================

# BUILDING_LAYER_MAP, SCHOOL_LAYER_MAPPING, LAYER_SCHOOL_MAPPING removed.
# Layer-to-school matching is now done dynamically from the GPKG in each processor.



# =============================================================================
# 스타일 설정
# =============================================================================

@dataclass
class LayerStyles:
    """레이어별 스타일 설정"""
    
    # 학교 구역 폴리곤
    SCHOOLZONE_POLYGON = {
        'color': '#0066cc',
        'weight': 2,
        'fillOpacity': 0.12
    }
    
    # 통학 구역 폴리곤
    COMMUTING_ZONE_POLYGON = {
        'color': '#dc3545',
        'weight': 2,
        'fillOpacity': 0.08
    }
    
    # 학교 정문 색상 (gate_type별)
    GATE_COLORS = {
        '정문': '#28a745',  # 초록
        '후문': '#fd7e14',  # 주황
        'default': '#6f42c1'  # 보라
    }
    
    # 보행 네트워크
    WALKING_NETWORK = {
        'color': '#6c757d',
        'weight': 1,
        'opacity': 0.6
    }
    
    # 최적 경로
    OPTIMAL_PATH = {
        'color': '#007bff',
        'weight': 3,
        'opacity': 0.7
    }
    
    # 안전 경로
    SAFETY_PATH = {
        'color': '#28a745',
        'weight': 3,
        'opacity': 0.7,
        'dashArray': '5, 5'
    }

STYLES = LayerStyles()


# =============================================================================
# OSM 네트워크 설정
# =============================================================================

@dataclass
class OSMConfig:
    """OSM 도로망 다운로드 및 경로 분석 설정"""
    
    # 대상 지역
    place_name: str = "Seoul, South Korea"
    
    # 네트워크 타입
    network_type: str = "walk"
    
    # 투영 좌표계 (미터 단위 계산용)
    projection_crs: str = "EPSG:5179"
    
    # 안전 가중치 계산 설정
    safety_weights = {
        'no_sidewalk': 2.0,      # 보도 없음 (위험)
        'pedestrian_only': 0.8,  # 보행자 전용 (안전)
        'narrow_residential': 2.5,  # 좁은 이면도로 (매우 위험)
        'residential': 1.5,      # 이면도로
        'wide_road': 1.0         # 대로변
    }
    
    # 도로 폭 기준 (미터)
    road_width_thresholds = {
        'narrow': 6.0,
        'medium': 9.0,
        'wide': 12.0
    }

OSM_CONFIG = OSMConfig()


# =============================================================================
# 로깅 설정
# =============================================================================

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout'
        },
        'file': {
            'class': 'logging.FileHandler',
            'level': 'DEBUG',
            'formatter': 'standard',
            'filename': 'logs/processing.log',
            'mode': 'a'
        }
    },
    'loggers': {
        '': {  # root logger
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True
        }
    }
}


# =============================================================================
# 유틸리티 함수
# =============================================================================

def get_gate_csv_files(city: str = 'seoul') -> list:
    """Return sorted list of all school gate CSV paths for the given city.

    File naming convention: school_gate_{city}_{district}.csv
    Example: school_gate_seoul_yongsan.csv, school_gate_seoul_gangnam.csv

    Args:
        city: City code used in filename (default 'seoul').
              Pass '*' to match any city.

    Returns:
        List[Path] sorted alphabetically by filename.
    """
    pattern = f'school_gate_{city}_*.csv' if city != '*' else 'school_gate_*.csv'
    return sorted(Paths.DATA_RAW.glob(pattern))



def get_schoolzone_json_files() -> list:
    """Return sorted list of all school-zone JSON paths (district *_스쿨존.json).

    File naming convention: {district}_스쿨존.json
    Example: 용산구_스쿨존.json, 강남구_스쿨존.json
    """
    return sorted(Paths.DATA_RAW.glob('*_스쿨존.json'))

def ensure_directories():
    """필요한 디렉토리 생성"""
    directories = [
        Paths.DATA_RAW,
        Paths.DATA_PROCESSED,
        Paths.WEB_DATA,
        PROJECT_ROOT / 'logs'
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

# get_school_layer_name removed — layer matching is now dynamic per processor

# get_layer_school_name removed — layer matching is now dynamic per processor

# ✅ CSV에서 로드하는 함수 추가
def load_school_enrollment():
    """
    CSV에서 학교별 학생수 로드
    
    Returns:
        dict: {학교명: 학생수}
    """
    import pandas as pd
    
    csv_path = Paths.DATA_RAW / 'seoul_elementary_school_enrollment.csv'
    
    if not csv_path.exists():
        raise FileNotFoundError(f"Enrollment CSV not found: {csv_path}")
    
    # CSV 로드 (UTF-8 BOM 우선, 이후 fallback)
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            break
        except (UnicodeDecodeError, Exception):
            continue
    else:
        raise ValueError(f"Could not decode {csv_path} with any supported encoding")

    # 컬럼 탐색: 정확히 '학교명' 우선, 그다음 '총계'
    # 주의: '학교' 포함 조건은 '학교급코드' 등 비문자열 컬럼도 걸리므로 사용하지 않음
    school_col = next((c for c in df.columns if c == '학교명'), None) \
              or next((c for c in df.columns if '학교명' in c), None)
    total_col  = next((c for c in df.columns if c == '총계'),  None) \
              or next((c for c in df.columns if '총계' in c),  None)

    if not school_col or not total_col:
        raise ValueError(f"Could not find school name or total columns. Available: {df.columns.tolist()}")
    
    # 모든 서울 초등학교 반환
    enrollment = {}
    for _, row in df.iterrows():
        school_name = str(row[school_col]).strip() if not pd.isna(row[school_col]) else None
        if not school_name:
            continue
        total = row[total_col]
        if pd.isna(total):
            continue
        try:
            total = int(total)
        except (ValueError, TypeError):
            continue
        enrollment[school_name] = total

    return enrollment

if __name__ == '__main__':
    # 설정 확인용
    print("Project Root:", PROJECT_ROOT)
    print("\nData Paths:")
    print(f"  Raw: {Paths.DATA_RAW}")
    print(f"  Processed: {Paths.DATA_PROCESSED}")
    print(f"\nCoordinate Config:")
    print(f"  Offset: dx={COORD_CONFIG.dx:.2f}m, dy={COORD_CONFIG.dy:.2f}m")
    print("Gate CSV files:", len(get_gate_csv_files()))
    print("School zone JSON files:", len(get_schoolzone_json_files()))
    
    # 디렉토리 생성
    ensure_directories()
    print("\n[OK] Directories created")


