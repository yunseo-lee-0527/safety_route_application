"""사고 데이터 처리"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from shapely.geometry import Point
import sys
import logging
sys.path.append(str(Path(__file__).parent.parent))

from config import Paths
from utils.geojson_writer import GeoJSONWriter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AccidentProcessor:
    def __init__(self):
        pass
    
    def run(self):
        # CSV 로드
        df = pd.read_csv(Paths.DATA_RAW / 'accident_data.csv', encoding='cp949')

        if '사고유형구분' in df.columns:
            df = df[df['사고유형구분'].str.contains('어린이', na=False)]
            logger.info(f"Filtered to child accidents: {len(df)} records")
            
        # 위도/경도 결측 제거
        df = df.dropna(subset=['위도', '경도'])
        df['위도'] = pd.to_numeric(df['위도'], errors='coerce')
        df['경도'] = pd.to_numeric(df['경도'], errors='coerce')
        df = df.dropna(subset=['위도', '경도'])
        
        print(f"Loaded {len(df)} accidents")
        
        # GeoJSON features 생성
        features = []
        for _, row in df.iterrows():
            point = Point(float(row['경도']), float(row['위도']))
            
            # 모든 컬럼을 properties로
            properties = row.drop(['위도', '경도']).to_dict()
            # NaN → None
            properties = {k: (None if pd.isna(v) else v) for k, v in properties.items()}
            
            features.append(GeoJSONWriter.feature(point, properties))
        
        # 저장
        output = Paths.DATA_PROCESSED / 'accidents.geojson'
        GeoJSONWriter.write(features, output)
        print(f"✅ Saved to {output}")

        import shutil
        web_dst = Paths.WEB_DATA / output.name
        web_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, web_dst)
        print(f"Copied to {web_dst}")
        
        return features

if __name__ == '__main__':
    processor = AccidentProcessor()
    processor.run()