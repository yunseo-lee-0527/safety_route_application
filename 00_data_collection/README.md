# 00_data_collection — 데이터 수집·전처리

파이프라인의 첫 단계. raw 공공데이터를 분석 가능한 형태로 정제해 이후 stage가 소비할 수 있도록 한다.

> ⚠️ `data/raw/` 와 `output/` 의 대용량 파일은 [루트 README](../README.md#데이터-다운로드-필수)의 Drive에서 받아 압축 해제해야 한다.

## 산출물 (다음 stage 입력)

| 파일 | 위치 | 사용처 |
|---|---|---|
| `walking_network.geojson` | `output/processed_seoul_intermediate/` | 02 |
| `schoolzones.geojson` | `output/processed_seoul_intermediate/` | 02·05 |
| `accidents.geojson` | `output/processed_seoul_intermediate/` | 01·검증 |
| `links_with_accident_count.csv` | `output/` | 01 |
| `taas_accidents.geojson` / `taas_accidents_with_latlon.csv` | `src/` 로컬 | 01 |

## 입력 (raw)

`data/raw/` 위치 (Drive `01_raw_data.zip` 압축 해제 후):

| 데이터 | 형식 | 출처 |
|---|---|---|
| TAAS 보행자 사고 | curl 응답 + GeoJSON | 도로교통공단 TAAS |
| 서울시 도보 네트워크 | 자치구별 CSV (cp949) | 서울 열린데이터 광장 |
| 신호등·횡단보도 (자치구별) | xlsx | 서울 열린데이터 광장 |
| CCTV 설치현황 (자치구별) | xlsx | 서울 열린데이터 광장 |
| 차량통행속도 (TOPIS) | xlsx | 서울특별시 TOPIS |
| 과속방지턱 공간정보 | shp | 서울 열린데이터 광장 |
| 학교 정·후문 좌표 | `school_gate_seoul_*.csv` | 공공데이터포털 |
| 학구도 | `elementary_commuting_zone/` shp | 학구도안내서비스 |
| 행정경계 | `BND_SIGUNGU_PG.*` | 공공데이터포털 |
| 표준노드링크 (MOCT) | shp/dbf | 국가교통정보센터 |

## 코드 구성

```
src/
├── taas_convert.py                  # TAAS curl 응답 → GeoJSON 변환 (EPSG:5179 → WGS84)
├── curlconverting.py                # curl 명령 파싱 헬퍼
├── join_accidents_to_links.py       # sjoin_nearest로 사고 → MOCT 링크 매핑
├── plot_accidents.py                # 사고 시각화
├── visualize_seoul_node_link.py     # 표준노드링크 시각화
├── map_link_to_uiwang_road_code.py  # 의왕 코드 매핑 (참조)
├── accident_processor.py            # 어린이 사고 필터 + GeoJSON 변환
├── schoolzone_processor.py          # 관악구 어린이보호구역 폴리곤 (EPSG:5174 → WGS84)
├── walking_network_processor.py     # 보행 네트워크 GeoJSON 변환 (cp949 청크 로드)
└── lib/                             # 공통 설정·유틸
    ├── build_all.py                 # 일괄 실행 entry point
    ├── config.py
    └── optimize_geojson.py
```

### 핵심 프로세서 요약

| 파일 | 입력 | 출력 |
|---|---|---|
| `taas_convert.py` | `src/taas_response.json` | `src/taas_accidents.geojson`, `src/taas_accidents_with_latlon.csv` |
| `join_accidents_to_links.py` | TAAS 사고 좌표 + `MOCT_LINK.shp` | `output/links_with_accident_count.csv` |
| `schoolzone_processor.py` | `data/raw/*_스쿨존.json` | `output/processed_seoul_intermediate/schoolzones.geojson` |
| `walking_network_processor.py` | `data/raw/서울시 자치구별 도보 네트워크 공간정보.csv` | `output/processed_seoul_intermediate/walking_network.geojson` |
| `accident_processor.py` | `data/raw/accident_data.csv` (cp949) | `output/processed_seoul_intermediate/accidents.geojson` |

## 실행

```bash
# 일괄 실행 (전체 파이프라인 재생성 시)
python src/lib/build_all.py

# 개별 실행 예시
python src/taas_convert.py
python src/join_accidents_to_links.py
```
