"""
좌표계 변환 유틸리티

EPSG:5174 (한국 중부 원점 TM) ↔ EPSG:4326 (WGS84) 변환
싱글톤 패턴으로 Transformer 인스턴스 재사용
"""
from pyproj import Transformer
from typing import Tuple, List
from shapely.geometry import Point, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
import functools

try:
    from .config import COORD_CONFIG
except ImportError:
    from config import COORD_CONFIG


class CoordinateTransformer:
    """
    좌표계 변환 클래스 (싱글톤)
    
    용도:
    - EPSG:5174 → WGS84 변환 (보정 적용)
    - WGS84 → EPSG:5174 변환
    - Shapely geometry 객체 변환
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Transformer 초기화"""
        # EPSG:5174 → WGS84
        self.to_wgs84 = Transformer.from_crs(
            "EPSG:5174", 
            "EPSG:4326", 
            always_xy=True
        )
        
        # WGS84 → EPSG:5174
        self.to_5174 = Transformer.from_crs(
            "EPSG:4326", 
            "EPSG:5174", 
            always_xy=True
        )
        
        # EPSG:5179 (OSM 경로 분석용) → WGS84
        self.to_wgs84_from_5179 = Transformer.from_crs(
            "EPSG:5179",
            "EPSG:4326",
            always_xy=True
        )
    
    def epsg5174_to_wgs84(
        self, 
        x: float, 
        y: float, 
        apply_shift: bool = True
    ) -> Tuple[float, float]:
        """
        EPSG:5174 → WGS84 변환
        
        Args:
            x: EPSG:5174 X 좌표
            y: EPSG:5174 Y 좌표
            apply_shift: 보정 적용 여부 (기본값: True)
        
        Returns:
            (lat, lon) 튜플
        """
        if apply_shift:
            x_shifted = x + COORD_CONFIG.dx
            y_shifted = y + COORD_CONFIG.dy
        else:
            x_shifted, y_shifted = x, y
        
        lon, lat = self.to_wgs84.transform(x_shifted, y_shifted)
        return lat, lon
    
    def wgs84_to_epsg5174(
        self, 
        lat: float, 
        lon: float
    ) -> Tuple[float, float]:
        """
        WGS84 → EPSG:5174 변환
        
        Args:
            lat: 위도
            lon: 경도
        
        Returns:
            (x, y) 튜플 (EPSG:5174 좌표)
        """
        x, y = self.to_5174.transform(lon, lat)
        return x, y
    
    def epsg5179_to_wgs84(
        self,
        x: float,
        y: float
    ) -> Tuple[float, float]:
        """
        EPSG:5179 → WGS84 변환 (OSM 경로 분석 결과용)
        
        Args:
            x: EPSG:5179 X 좌표
            y: EPSG:5179 Y 좌표
        
        Returns:
            (lat, lon) 튜플
        """
        lon, lat = self.to_wgs84_from_5179.transform(x, y)
        return lat, lon
    
    def transform_coords_list(
        self,
        coords: List[Tuple[float, float]],
        from_crs: str = "EPSG:5174",
        apply_shift: bool = True
    ) -> List[Tuple[float, float]]:
        """
        좌표 리스트 변환
        
        Args:
            coords: [(x, y), ...] 형태의 좌표 리스트
            from_crs: 원본 좌표계 ("EPSG:5174" 또는 "EPSG:5179")
            apply_shift: EPSG:5174인 경우 보정 적용 여부
        
        Returns:
            [(lat, lon), ...] 형태의 WGS84 좌표 리스트
        """
        result = []
        
        for x, y in coords:
            if from_crs == "EPSG:5174":
                lat, lon = self.epsg5174_to_wgs84(x, y, apply_shift)
            elif from_crs == "EPSG:5179":
                lat, lon = self.epsg5179_to_wgs84(x, y)
            else:
                raise ValueError(f"Unsupported CRS: {from_crs}")
            
            result.append((lat, lon))
        
        return result
    
    def transform_geometry(
        self,
        geometry: BaseGeometry,
        from_crs: str = "EPSG:5174",
        apply_shift: bool = True
    ) -> BaseGeometry:
        """
        Shapely geometry 객체 변환
        
        Args:
            geometry: Shapely geometry (Point, LineString, Polygon 등)
            from_crs: 원본 좌표계
            apply_shift: EPSG:5174인 경우 보정 적용 여부
        
        Returns:
            WGS84로 변환된 geometry
        """
        if from_crs == "EPSG:5174":
            def transform_func(x, y):
                if apply_shift:
                    x_shifted = x + COORD_CONFIG.dx
                    y_shifted = y + COORD_CONFIG.dy
                else:
                    x_shifted, y_shifted = x, y
                
                lon, lat = self.to_wgs84.transform(x_shifted, y_shifted)
                return lon, lat
        
        elif from_crs == "EPSG:5179":
            def transform_func(x, y):
                lon, lat = self.to_wgs84_from_5179.transform(x, y)
                return lon, lat
        
        else:
            raise ValueError(f"Unsupported CRS: {from_crs}")
        
        return transform(transform_func, geometry)


# =============================================================================
# 글로벌 인스턴스 (싱글톤)
# =============================================================================

transformer = CoordinateTransformer()


# =============================================================================
# 편의 함수
# =============================================================================

def ring_to_latlng_list(
    coords: List[Tuple[float, float]],
    from_crs: str = "EPSG:5174"
) -> List[List[float]]:
    """
    Polygon 외곽선 좌표를 Leaflet 형식으로 변환
    
    Args:
        coords: [(x, y), ...] 형태의 좌표 리스트
        from_crs: 원본 좌표계
    
    Returns:
        [[lat, lon], ...] 형태의 리스트 (Leaflet polygon 형식)
    """
    result = []
    
    for x, y in coords:
        if from_crs == "EPSG:5174":
            lat, lon = transformer.epsg5174_to_wgs84(x, y)
        elif from_crs == "EPSG:5179":
            lat, lon = transformer.epsg5179_to_wgs84(x, y)
        else:
            raise ValueError(f"Unsupported CRS: {from_crs}")
        
        result.append([lat, lon])
    
    return result


def point_to_latlng(
    x: float,
    y: float,
    from_crs: str = "EPSG:5174"
) -> Tuple[float, float]:
    """
    단일 점 좌표 변환
    
    Args:
        x: X 좌표
        y: Y 좌표
        from_crs: 원본 좌표계
    
    Returns:
        (lat, lon) 튜플
    """
    if from_crs == "EPSG:5174":
        return transformer.epsg5174_to_wgs84(x, y)
    elif from_crs == "EPSG:5179":
        return transformer.epsg5179_to_wgs84(x, y)
    else:
        raise ValueError(f"Unsupported CRS: {from_crs}")


def linestring_to_latlngs(
    line: LineString,
    from_crs: str = "EPSG:5179"
) -> List[List[float]]:
    """
    LineString을 Leaflet 형식으로 변환
    
    Args:
        line: Shapely LineString 객체
        from_crs: 원본 좌표계
    
    Returns:
        [[lat, lon], ...] 형태의 리스트
    """
    coords = list(line.coords)
    return ring_to_latlng_list(coords, from_crs)


# =============================================================================
# 테스트 및 검증
# =============================================================================

def validate_transformation():
    """변환 정확도 검증"""
    
    # 테스트 포인트: 용산구청 (알려진 좌표)
    test_cases = [
        {
            'name': '용산구청',
            'epsg5174': (205000, 452000),  # 근사값
            'expected_wgs84': (37.532, 126.990)  # 근사값
        }
    ]
    
    print("=== Coordinate Transformation Validation ===\n")
    
    for case in test_cases:
        x, y = case['epsg5174']
        expected_lat, expected_lon = case['expected_wgs84']
        
        # 변환
        lat, lon = transformer.epsg5174_to_wgs84(x, y, apply_shift=True)
        
        # 오차 계산
        lat_error = abs(lat - expected_lat)
        lon_error = abs(lon - expected_lon)
        
        print(f"Location: {case['name']}")
        print(f"  Input (EPSG:5174): X={x}, Y={y}")
        print(f"  Output (WGS84): {lat:.6f}, {lon:.6f}")
        print(f"  Expected: {expected_lat:.6f}, {expected_lon:.6f}")
        print(f"  Error: Lat={lat_error:.6f}°, Lon={lon_error:.6f}°")
        print()
    
    # 역변환 테스트
    print("=== Round-trip Test ===\n")
    
    original_lat, original_lon = 37.534, 126.980
    print(f"Original WGS84: {original_lat}, {original_lon}")
    
    # WGS84 → EPSG:5174
    x, y = transformer.wgs84_to_epsg5174(original_lat, original_lon)
    print(f"Converted to EPSG:5174: X={x:.2f}, Y={y:.2f}")
    
    # EPSG:5174 → WGS84 (보정 없이)
    lat, lon = transformer.epsg5174_to_wgs84(x, y, apply_shift=False)
    print(f"Converted back to WGS84: {lat:.6f}, {lon:.6f}")
    
    # 오차
    error = ((lat - original_lat)**2 + (lon - original_lon)**2)**0.5
    print(f"Round-trip error: {error:.8f}°")


if __name__ == '__main__':
    # 검증 실행
    validate_transformation()
    
    # 사용 예시
    print("\n=== Usage Examples ===\n")
    
    # 1. 단일 점 변환
    lat, lon = transformer.epsg5174_to_wgs84(205000, 452000)
    print(f"1. Point transformation: ({lat:.6f}, {lon:.6f})")
    
    # 2. 좌표 리스트 변환
    coords = [(205000, 452000), (205100, 452100), (205200, 452000)]
    latlngs = transformer.transform_coords_list(coords)
    print(f"2. Coords list: {latlngs}")
    
    # 3. Shapely geometry 변환
    point = Point(205000, 452000)
    transformed = transformer.transform_geometry(point)
    print(f"3. Geometry: {transformed}")
