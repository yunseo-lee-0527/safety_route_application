"""
학교 정문 데이터 처리 Processor

CSV 파일을 읽어 GeoJSON으로 변환
"""
import pandas as pd
import logging
from pathlib import Path
from typing import List, Dict, Any
from shapely.geometry import Point

try:
    from .base_processor import BaseProcessor
    from ..config import Paths, STYLES, get_gate_csv_files
    from ..utils.geojson_writer import GeoJSONWriter
except ImportError:
    # 단독 실행 시
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    from config import Paths, STYLES, get_gate_csv_files
    from utils.geojson_writer import GeoJSONWriter
    
    # BaseProcessor 간단 구현
    class BaseProcessor:
        def __init__(self, config):
            self.config = config
            self.logger = logging.getLogger(self.__class__.__name__)
        
        def run(self):
            self.logger.info(f"Starting {self.__class__.__name__}")
            raw_data = self.load_raw_data()
            self.logger.info(f"Loaded {len(raw_data)} records")
            
            features = self.process(raw_data)
            self.logger.info(f"Processed {len(features)} features")
            
            self.validate(features)
            
            output_path = self.get_output_path()
            self.save(features, output_path)
            self.logger.info(f"Saved to {output_path}")
            
            return features
        
        def validate(self, features):
            for i, f in enumerate(features):
                geom = f.get('geometry')
                if not geom or not geom.get('coordinates'):
                    raise ValueError(f"Feature {i} has invalid geometry")
        
        def save(self, features, output_path):
            GeoJSONWriter.write(features, output_path)
            import shutil
            web_dst = Paths.WEB_DATA / Path(output_path).name
            web_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, web_dst)
            self.logger.info(f"Copied to {web_dst}")

logger = logging.getLogger(__name__)



def _read_gate_csv(path) -> "pd.DataFrame":
    """Read a gate CSV with automatic encoding and separator detection.

    Encoding priority: utf-8-sig → utf-8 → cp949 → euc-kr
    Separator: detected from the header line (tab or comma).
    """
    import pandas as pd

    # Step 1: find a working encoding by reading raw bytes
    with open(path, 'rb') as fh:
        raw = fh.read()

    decoded = None
    used_enc = None
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            decoded = raw.decode(enc)
            used_enc = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if decoded is None:
        raise ValueError(f"Cannot decode {path.name}: tried utf-8-sig/utf-8/cp949/euc-kr")

    # Step 2: sniff separator from first header line
    first_line = decoded.splitlines()[0]
    sep = '	' if chr(9) in first_line else ','

    return pd.read_csv(path, encoding=used_enc, sep=sep)

class GateProcessor(BaseProcessor):
    """
    학교 정문 데이터 Processor
    
    Input: CSV 파일 (UTF-16, TSV)
    Output: GeoJSON (WGS84)
    
    CSV 컬럼:
    - school_name: 학교명
    - gate_type: 정문/후문 구분
    - lat: 위도 (WGS84)
    - lon: 경도 (WGS84)
    """
    
    def __init__(self, config: dict = None):
        super().__init__(config or {})
        
        # 컬럼명 설정
        self.col_school = 'school_name'
        self.col_gate = 'gate_type'
        self.col_lat = 'lat'
        self.col_lon = 'lon'
    
    def load_raw_data(self) -> pd.DataFrame:
        """모든 지구별 gate CSV 파일을 로드하여 단일 DataFrame으로 병합.

        Naming convention: school_gate_{city}_{district}.csv (UTF-16, TSV)
        A 'district' column is derived from the filename so downstream
        processors can filter or group by district if needed.
        """
        csv_files = get_gate_csv_files()

        if not csv_files:
            raise FileNotFoundError(
                f"No school gate CSV files found in {Paths.DATA_RAW}. "
                f"Expected pattern: school_gate_seoul_*.csv"
            )

        self.logger.info(f"Found {len(csv_files)} gate CSV files")

        frames = []
        for csv_path in csv_files:
            # Extract district: school_gate_seoul_yongsan.csv -> yongsan
            parts = csv_path.stem.split('_')  # ['school','gate','seoul','yongsan',...]
            district = '_'.join(parts[3:]) if len(parts) > 3 else csv_path.stem

            try:
                df = _read_gate_csv(csv_path)
            except Exception as e:
                self.logger.warning(f"Failed to read {csv_path.name}: {e} — skipping")
                continue

            # 필수 컬럼 체크
            required_cols = [self.col_school, self.col_lat, self.col_lon]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                self.logger.warning(
                    f"{csv_path.name}: missing columns {missing} — skipping"
                )
                continue

            df['district'] = district
            frames.append(df)
            self.logger.info(f"  {csv_path.name}: {len(df)} rows")

        if not frames:
            raise ValueError("All gate CSV files failed to load. Check file format.")

        combined = pd.concat(frames, ignore_index=True)
        self.logger.info(f"Total rows after concat: {len(combined)}")
        self.logger.debug(f"Columns: {combined.columns.tolist()}")

        # 결측치 제거
        combined = combined.dropna(
            subset=[self.col_school, self.col_lat, self.col_lon]
        ).copy()

        # 숫자 변환
        combined[self.col_lat] = pd.to_numeric(combined[self.col_lat], errors='coerce')
        combined[self.col_lon] = pd.to_numeric(combined[self.col_lon], errors='coerce')
        combined = combined.dropna(subset=[self.col_lat, self.col_lon])

        self.logger.info(f"After cleaning: {len(combined)} rows")
        return combined

    def process(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """GeoJSON features 생성"""
        features = []
        
        for idx, row in df.iterrows():
            # Geometry 생성
            point = Point(float(row[self.col_lon]), float(row[self.col_lat]))
            
            # Properties 구성
            properties = {
                'school_name': str(row[self.col_school]),
                'gate_type': str(row.get(self.col_gate, '')),
                'lat': float(row[self.col_lat]),
                'lon': float(row[self.col_lon]),
                'district': str(row.get('district', '')),
            }
            
            # gate_type이 비어있으면 '정문'으로 가정
            if not properties['gate_type']:
                properties['gate_type'] = '정문'
            
            # Feature 생성
            feature = GeoJSONWriter.feature(
                geometry=point,
                properties=properties,
                feature_id=idx
            )
            
            features.append(feature)
        
        return features
    
    def get_output_path(self) -> Path:
        """출력 파일 경로"""
        return Paths.GATES_GEOJSON
    
    def validate(self, features: List[Dict[str, Any]]):
        """추가 검증"""
        super().validate(features)
        
        # 좌표 범위 검증 (서울 주변)
        for i, feature in enumerate(features):
            coords = feature['geometry']['coordinates']
            lon, lat = coords[0], coords[1]
            
            # 서울 범위: 위도 37.4-37.7, 경도 126.8-127.2
            if not (37.4 <= lat <= 37.7 and 126.8 <= lon <= 127.2):
                self.logger.warning(
                    f"Feature {i} has coordinates outside Seoul: "
                    f"lat={lat:.6f}, lon={lon:.6f}"
                )
        
        # 중복 학교명 체크
        schools = [f['properties']['school_name'] for f in features]
        unique_schools = set(schools)
        
        if len(schools) != len(unique_schools):
            self.logger.warning(
                f"Found {len(schools) - len(unique_schools)} duplicate school names"
            )
        
        self.logger.info(f"Validation passed: {len(features)} features, {len(unique_schools)} unique schools")


# =============================================================================
# 실행
# =============================================================================

def main():
    """단독 실행용"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    processor = GateProcessor()
    
    try:
        features = processor.run()
        
        print("\n✅ Processing completed successfully")
        print(f"   Output: {processor.get_output_path()}")
        print(f"   Features: {len(features)}")
        
        # 샘플 출력
        if features:
            print("\nSample feature:")
            import json
            print(json.dumps(features[0], ensure_ascii=False, indent=2))
    
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        raise


if __name__ == '__main__':
    main()
