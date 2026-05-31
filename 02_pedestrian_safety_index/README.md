# 02_pedestrian_safety_index — 보행 안전도 지수 산출

> 01의 차도 위험도를 관악구 도보 네트워크에 케이스 분류(A/B/C/D) 기반으로 매핑한다.
> 10,922개 보행 링크.
>
> 상세 방법론: [METHODOLOGY.md](METHODOLOGY.md)

## 산출물 (04·05로 전달)

| 파일 | 의미 |
|---|---|
| `output/gwanak_walking_edge_safety.geojson` | 10,922개 보행 링크 안전도 (지도 시각화용) |
| `output/gwanak_walking_edge_safety_utf8.csv` | 동일 데이터 csv (UTF-8) |
| `output/walking_edge_safety_summary.json` | 케이스별 카운트·점수 분포 |
| `output/sensitivity_results.json` | 임계값 민감도 분석 결과 |
| `output/walking_edge_safety_map.html` | 인터랙티브 보행 안전 지도 |
| `output/road_and_walking_safety_map.html` | 차도+보행 통합 시각화 |

핵심 컬럼:
- `safety_score_0_1` — 0이면 안전, 1이면 위험
- `edge_safety_basis` — 적용된 케이스 (`case_A_separated`, `case_B_shared_road`, `case_C_no_nearby_road`, `case_D_crossing/crosswalk`)
- `crosswalk_mapping_warning` — `nearest_road_over_80m` 표시 (주의 필요 횡단보도)

## 케이스 분류

| 케이스 | 의미 | 점수 부여 |
|---|---|---|
| A 분리보도 | 차도와 물리적으로 분리 | 0.000 |
| B 공유·인접 | 차도 위·옆 (거리 5 m, 각도 30°, overlap 50% 등 조건) | 매칭 차도의 `risk_percentile` |
| C 차도 없음 | 80 m 내 차도 없음 | 0.000 |
| D 횡단 | 횡단보도 또는 차도와 45° 이상 교차 | 건너는 차도의 `risk_percentile` |
| special_safe_facility | 육교·교량·터널·공원녹지 | 0.000 |

케이스 분포 (현재 기준):
- `case_B_shared_road`: 약 52.1 %
- `case_B_nearest_road`: 약 28.1 %
- `case_A_separated`: 약 10.0 %

## 입력

`01_build_walking_edge_safety.py` 가 참조하는 입력:

| 경로 | 설명 |
|---|---|
| `../01_road_risk_index/output/gwanak_road_safety_scores_full_remap_service_utf8.csv` | 01의 차도 위험도 |
| `../00_data_collection/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv` | 서울시 보행 네트워크 원본 (cp949) |

## 코드 구성

```
src/
├── 01_build_walking_edge_safety.py    # 케이스 분류 + 점수 산출 (메인)
├── 02_sensitivity_analysis.py         # 임계값 민감도 분석
└── 03_create_combined_map.py          # 차도+보행 통합 지도 생성
```

### `01_build_walking_edge_safety.py` 처리 흐름

1. 서울시 보행 네트워크 로드 (11,138 raw → 산지 링크 제거 후 10,922)
2. 차도 위험도 CSV에서 `risk_percentile` 계산
3. 각 보행 링크에 우선순위 케이스 분류 적용
4. `safety_score_0_1` 부여 + `edge_safety_basis` 기록
5. GeoJSON / CSV 저장

## 실행

```bash
python src/01_build_walking_edge_safety.py
python src/02_sensitivity_analysis.py
python src/03_create_combined_map.py
```

## 검증 요약

| 항목 | 값 |
|---|---:|
| 최종 보행 edge | 10,922 |
| unclassified | 0 |
| `safety_score_0_1 ≥ 0.95` (극위험) | 310 |
| 전체 평균 안전도 | 0.456 |
