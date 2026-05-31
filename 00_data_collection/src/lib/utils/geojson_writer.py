"""
GeoJSON 생성 및 저장 유틸리티

표준 GeoJSON 포맷으로 데이터 출력
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Union
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
import logging

logger = logging.getLogger(__name__)


class GeoJSONWriter:
    """
    GeoJSON 파일 생성 헬퍼
    
    표준 GeoJSON Feature 및 FeatureCollection 생성
    """
    
    @staticmethod
    def feature(
        geometry: Union[BaseGeometry, Dict],
        properties: Dict[str, Any] = None,
        feature_id: Union[str, int] = None
    ) -> Dict[str, Any]:
        """
        단일 Feature 객체 생성
        
        Args:
            geometry: Shapely geometry 또는 GeoJSON geometry dict
            properties: Feature properties (속성 정보)
            feature_id: Feature ID (선택사항)
        
        Returns:
            GeoJSON Feature 딕셔너리
        
        Example:
            >>> from shapely.geometry import Point
            >>> feature = GeoJSONWriter.feature(
            ...     Point(126.98, 37.53),
            ...     {'name': '용산역', 'type': 'station'}
            ... )
        """
        # Shapely geometry → GeoJSON dict
        if isinstance(geometry, BaseGeometry):
            geom_dict = mapping(geometry)
        else:
            geom_dict = geometry
        
        feature_dict = {
            "type": "Feature",
            "geometry": geom_dict,
            "properties": properties or {}
        }
        
        if feature_id is not None:
            feature_dict["id"] = feature_id
        
        return feature_dict
    
    @staticmethod
    def feature_collection(
        features: List[Dict[str, Any]],
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        FeatureCollection 객체 생성
        
        Args:
            features: Feature 딕셔너리 리스트
            metadata: 메타데이터 (선택사항)
        
        Returns:
            GeoJSON FeatureCollection 딕셔너리
        """
        collection = {
            "type": "FeatureCollection",
            "features": features
        }
        
        # 메타데이터 추가 (선택사항)
        if metadata:
            collection["metadata"] = metadata
        
        return collection
    
    @staticmethod
    def write(
        features: Union[List[Dict[str, Any]], Dict[str, Any]],
        output_path: Union[str, Path],
        pretty: bool = False,
        ensure_parent: bool = True
    ):
        """
        GeoJSON 파일 저장
        
        Args:
            features: Feature 리스트 또는 FeatureCollection
            output_path: 출력 파일 경로
            pretty: 보기 좋게 포맷팅 (들여쓰기 적용)
            ensure_parent: 부모 디렉토리 자동 생성
        
        Example:
            >>> features = [
            ...     GeoJSONWriter.feature(Point(126.98, 37.53), {'name': 'A'}),
            ...     GeoJSONWriter.feature(Point(126.99, 37.54), {'name': 'B'})
            ... ]
            >>> GeoJSONWriter.write(features, 'output.geojson')
        """
        output_path = Path(output_path)
        
        # 부모 디렉토리 생성
        if ensure_parent:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Feature 리스트 → FeatureCollection 변환
        if isinstance(features, list):
            geojson = GeoJSONWriter.feature_collection(features)
        else:
            geojson = features
        
        # 파일 저장
        with open(output_path, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(geojson, f, ensure_ascii=False, indent=2)
            else:
                json.dump(geojson, f, ensure_ascii=False)
        
        logger.info(f"Saved {len(geojson.get('features', []))} features to {output_path}")
    
    @staticmethod
    def read(file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        GeoJSON 파일 읽기
        
        Args:
            file_path: GeoJSON 파일 경로
        
        Returns:
            GeoJSON 딕셔너리
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def validate(geojson: Dict[str, Any]) -> bool:
        """
        GeoJSON 유효성 검증 (간단한 검증)
        
        Args:
            geojson: GeoJSON 딕셔너리
        
        Returns:
            유효하면 True
        
        Raises:
            ValueError: 유효하지 않은 경우
        """
        # Type 체크
        geojson_type = geojson.get('type')
        if geojson_type not in ['Feature', 'FeatureCollection']:
            raise ValueError(f"Invalid type: {geojson_type}")
        
        # FeatureCollection인 경우 features 체크
        if geojson_type == 'FeatureCollection':
            if 'features' not in geojson:
                raise ValueError("FeatureCollection must have 'features'")
            
            if not isinstance(geojson['features'], list):
                raise ValueError("'features' must be a list")
            
            # 각 Feature 검증
            for i, feature in enumerate(geojson['features']):
                if feature.get('type') != 'Feature':
                    raise ValueError(f"Feature {i} has invalid type: {feature.get('type')}")
                
                if 'geometry' not in feature:
                    raise ValueError(f"Feature {i} missing 'geometry'")
                
                # geometry 검증
                geom = feature['geometry']
                if geom is not None:  # null geometry는 허용
                    if 'type' not in geom or 'coordinates' not in geom:
                        raise ValueError(f"Feature {i} has invalid geometry")
        
        # Feature인 경우
        elif geojson_type == 'Feature':
            if 'geometry' not in geojson:
                raise ValueError("Feature must have 'geometry'")
        
        return True


class GeoJSONBuilder:
    """
    GeoJSON 생성 빌더 (체이닝 패턴)
    
    Example:
        >>> builder = GeoJSONBuilder()
        >>> builder.add_feature(Point(126.98, 37.53), {'name': 'A'}) \
        ...        .add_feature(Point(126.99, 37.54), {'name': 'B'}) \
        ...        .save('output.geojson')
    """
    
    def __init__(self, metadata: Dict[str, Any] = None):
        self.features = []
        self.metadata = metadata or {}
    
    def add_feature(
        self,
        geometry: Union[BaseGeometry, Dict],
        properties: Dict[str, Any] = None,
        feature_id: Union[str, int] = None
    ) -> 'GeoJSONBuilder':
        """Feature 추가 (체이닝)"""
        feature = GeoJSONWriter.feature(geometry, properties, feature_id)
        self.features.append(feature)
        return self
    
    def add_features(
        self,
        features: List[Dict[str, Any]]
    ) -> 'GeoJSONBuilder':
        """여러 Feature 추가 (체이닝)"""
        self.features.extend(features)
        return self
    
    def set_metadata(self, metadata: Dict[str, Any]) -> 'GeoJSONBuilder':
        """메타데이터 설정 (체이닝)"""
        self.metadata.update(metadata)
        return self
    
    def build(self) -> Dict[str, Any]:
        """FeatureCollection 생성"""
        return GeoJSONWriter.feature_collection(self.features, self.metadata)
    
    def save(
        self,
        output_path: Union[str, Path],
        pretty: bool = False
    ) -> 'GeoJSONBuilder':
        """파일로 저장 (체이닝)"""
        geojson = self.build()
        GeoJSONWriter.write(geojson, output_path, pretty)
        return self
    
    def clear(self) -> 'GeoJSONBuilder':
        """Feature 초기화 (체이닝)"""
        self.features = []
        return self
    
    def __len__(self):
        return len(self.features)


# =============================================================================
# 편의 함수
# =============================================================================

def quick_save(
    geometries: List[BaseGeometry],
    output_path: Union[str, Path],
    properties_list: List[Dict[str, Any]] = None,
    pretty: bool = False
):
    """
    빠른 저장 (간단한 경우)
    
    Args:
        geometries: Shapely geometry 리스트
        output_path: 출력 경로
        properties_list: properties 리스트 (geometries와 같은 길이)
        pretty: 포맷팅 여부
    
    Example:
        >>> from shapely.geometry import Point
        >>> points = [Point(126.98, 37.53), Point(126.99, 37.54)]
        >>> quick_save(points, 'points.geojson')
    """
    if properties_list is None:
        properties_list = [{}] * len(geometries)
    
    if len(geometries) != len(properties_list):
        raise ValueError("geometries and properties_list must have same length")
    
    features = [
        GeoJSONWriter.feature(geom, props)
        for geom, props in zip(geometries, properties_list)
    ]
    
    GeoJSONWriter.write(features, output_path, pretty)


def merge_geojson_files(
    input_paths: List[Union[str, Path]],
    output_path: Union[str, Path]
):
    """
    여러 GeoJSON 파일 병합
    
    Args:
        input_paths: 입력 파일 경로 리스트
        output_path: 출력 파일 경로
    """
    all_features = []
    
    for path in input_paths:
        geojson = GeoJSONWriter.read(path)
        
        if geojson.get('type') == 'FeatureCollection':
            all_features.extend(geojson.get('features', []))
        elif geojson.get('type') == 'Feature':
            all_features.append(geojson)
    
    GeoJSONWriter.write(all_features, output_path)
    logger.info(f"Merged {len(input_paths)} files into {output_path} ({len(all_features)} features)")


# =============================================================================
# 테스트
# =============================================================================

if __name__ == '__main__':
    from shapely.geometry import Point, LineString, Polygon
    
    print("=== GeoJSON Writer Test ===\n")
    
    # 1. 단일 Feature 생성
    print("1. Single Feature:")
    feature = GeoJSONWriter.feature(
        Point(126.98, 37.53),
        {'name': '용산역', 'type': 'station'}
    )
    print(json.dumps(feature, ensure_ascii=False, indent=2))
    
    # 2. FeatureCollection 생성
    print("\n2. FeatureCollection:")
    features = [
        GeoJSONWriter.feature(Point(126.98, 37.53), {'name': 'A'}),
        GeoJSONWriter.feature(Point(126.99, 37.54), {'name': 'B'}),
        GeoJSONWriter.feature(
            LineString([(126.98, 37.53), (126.99, 37.54)]),
            {'name': 'Line AB'}
        )
    ]
    collection = GeoJSONWriter.feature_collection(features)
    print(f"Created collection with {len(features)} features")
    
    # 3. Builder 패턴
    print("\n3. Builder Pattern:")
    builder = GeoJSONBuilder()
    builder.add_feature(Point(126.98, 37.53), {'name': 'Point 1'}) \
           .add_feature(Point(126.99, 37.54), {'name': 'Point 2'}) \
           .set_metadata({'source': 'test', 'version': '1.0'})
    
    print(f"Builder has {len(builder)} features")
    
    # 4. 검증
    print("\n4. Validation:")
    try:
        GeoJSONWriter.validate(collection)
        print("✅ Valid GeoJSON")
    except ValueError as e:
        print(f"❌ Invalid: {e}")
    
    # 5. 파일 저장 (임시)
    print("\n5. File Save:")
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.geojson', delete=False) as f:
        temp_path = f.name
    
    GeoJSONWriter.write(features, temp_path, pretty=True)
    print(f"Saved to {temp_path}")
    
    # 읽기
    loaded = GeoJSONWriter.read(temp_path)
    print(f"Loaded {len(loaded['features'])} features")
    
    # 정리
    Path(temp_path).unlink()
