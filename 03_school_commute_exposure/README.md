# 03_school_commute_exposure — 통학 기초 데이터 + 노출도 E

> 학교 정·후문 데이터, 주거지 → 학교 최단 통학 경로, 경로별 추정 통학 인원 (E) 산출.
> 04 B2C 챗봇과 05 B2G 대시보드의 공통 의존 stage.

> ⚠️ `output/` 의 대용량 GeoJSON·GPKG는 [루트 README](../README.md#데이터-다운로드-필수)의 Drive `03_stage_outputs.zip` 압축 해제로 확보한다.

## 산출물

| 파일 | 의미 | 사용처 |
|---|---|---|
| `output/school_gates.geojson` | 관악구 22개 초등학교 정·후문 좌표 | 04·05 |
| `output/commuting_zones.geojson` | 초등학교 학구도 폴리곤 | 04·05 |
| `output/residential_buildings.geojson` | 주거지 건물 (세대수 포함) | 03 내부 |
| `output/school_paths_optimal.geojson` | 주거지 → 학교 최단 통학 경로 | 05 (정책 검토) |
| `output/school_paths_with_students.geojson` | **경로별 추정 통학 인원 E (핵심 산출물)** | 05 (ECR 산출) |

추가 GPKG 파일들 (`school_paths_optimal.gpkg`, `school_paths_safety_weighted.gpkg`, `*_commuting_zones.gpkg`, `*_commuting_zone_buildings.gpkg`) 도 동일 데이터의 GeoPackage 형식.

## 노출도 E 산출

```
EstimatedStudents(p) = TotalStudents(s) × Households(p) / Σ_{j ∈ S} Households(j)
```

- `TotalStudents(s)`: 학교 s의 전체 학생 수 (학교알리미 / KEDI)
- `Households(p)`: 경로 p의 출발 주거 건물 세대수
- 분모: 해당 학교 통학구역 내 매칭된 전체 주거 건물의 세대수 합

학생 개별 주소 없이 학교별 전체 학생 수와 건물 세대수 비율로 통학 인원을 분배한다.

### 05 B2G에서의 E 사용

`school_paths_with_students.geojson` 의 경로별 E를 보행 링크 단위로 공간조인(누적)해 링크별 통학노출 `E(l)` 을 산출:

```text
E(l) = Σ_s Σ_{p ∈ P_s, l ∈ p} n(p)
```

## 입력

| 데이터 | 위치 |
|---|---|
| 학구도 shapefile | `data/elementary_commuting_zone/` (00 사본) |
| 주거지 건물·세대수 | 00 사본 |
| 보행 네트워크 | 00 사본 |
| 학교 정·후문 좌표 raw | `../00_data_collection/data/raw/school_gate_seoul_*.csv` |

## 코드 구성

```
src/
├── gate_processor.py                 # 학교 정·후문 데이터 정규화
├── commuting_zone_processor.py       # 학구도 처리
├── optimal_path_processor.py         # 주거지 → 학교 Dijkstra 최단 경로
└── commute_estimation_processor.py   # 경로별 통학 인원 E 추정
```

### 각 프로세서

| 프로세서 | 입력 | 출력 | 설명 |
|---|---|---|---|
| `gate_processor.py` | `school_gate_seoul_*.csv` | `output/school_gates.geojson` | 관악구 22개 초등학교 정·후문 좌표 정규화 (`school_name`, `gate_type`, `lat`, `lon`) |
| `commuting_zone_processor.py` | 학구도 shp (`HAKGUDO_NM`) | `output/commuting_zones.geojson` | 학구도 폴리곤 → GeoJSON, 공동통학구역 처리 포함 |
| `optimal_path_processor.py` | 보행 네트워크 + 학교 + 주거지 | `output/school_paths_optimal.geojson` | 학교 gate → 주거지 건물 Dijkstra (cutoff = 10 km), 경도 cos(37.55°) 보정, 방향 반전 후 저장 |
| `commute_estimation_processor.py` | 최단경로 + 학생 수 + 세대수 | `output/school_paths_with_students.geojson` | `sjoin_nearest(max_distance=100m)` 로 건물 매칭, E 산출 |

`optimal_path_processor.py` 출력 컬럼: `school`, `gate`, `distance`, `households`, `estimated_students`, `geometry`

## 실행

```bash
python src/gate_processor.py
python src/commuting_zone_processor.py
python src/optimal_path_processor.py
python src/commute_estimation_processor.py
```
