# 보행 edge 안전도 지수 산출 방법

이 폴더는 관악구 공식 도보 네트워크의 각 보행 link에 안전도 점수를 부여한 결과를 담는다. 점수는 `0`에 가까울수록 안전, `1`에 가까울수록 위험으로 해석한다.

## 산출물

| 파일 | 내용 |
|---|---|
| `gwanak_walking_edge_safety_utf8.csv` | UTF-8 보행 link별 안전도 지수 |
| `gwanak_walking_edge_safety.csv` | CP949 보행 link별 안전도 지수 |
| `gwanak_walking_edge_safety.geojson` | GIS/지도 시각화용 GeoJSON |
| `walking_edge_safety_summary.json` | 케이스 수, 파라미터, 점수 분포 요약 |
| `case_counts_latest.txt` | 케이스별 link 수 텍스트 요약 |

통합 지도는 상위 폴더의 `road_and_walking_safety_map.html`에서 확인한다.

## 입력 데이터

| 데이터 | 사용 방식 |
|---|---|
| `data/raw/seoul_walking_network_download.csv` | 서울시 도보 네트워크 중 관악구 LINK만 사용 |
| `yunseo_lee/road_safety_full_remap_service/gwanak_road_safety_scores_full_remap_service_utf8.csv` | 도로 물리 링크별 위험도 지수를 percentile로 변환해 보행 link에 매핑 (스크립트 하드코딩 경로) |

도로 위험도는 양방향 OSM edge를 물리 링크 단위로 통합한 뒤 계산한 값이다. 따라서 보행 link가 참조하는 도로도 directed edge가 아니라 물리 도로 링크 기준이다.

## 주요 입력 컬럼

| 컬럼 | 의미 |
|---|---|
| `walk_edge_id` | 보행 link ID |
| `source_u`, `source_v` | 시작/종료 노드 |
| `length_m` | 보행 link 길이 |
| `walking_type` | 통행 가능 수단 코드 |
| `crosswalk` | 원자료 횡단보도 플래그 |
| `overpass`, `bridge`, `tunnel`, `building`, `park_green` | 특수 시설 플래그 |
| `geometry_wkt` | 보행 link geometry |

## walking_type 해석

| 코드 | 의미 |
|---|---|
| `1000` | 보행자 전용 |
| `1011` | 보행자 + 자전거 + PM |
| `1100` | 보행자 + 차량 |
| `1111` | 보행자 + 차량 + 자전거 + PM |
| `0000` | 통행 불가 또는 미분류 |

`1111`은 보행자와 차량이 모두 통행 가능한 링크라는 뜻이다. 그러나 실제 데이터에서는 하천변 보행축, 도로변 독립 보행축, 골목길 등이 섞일 수 있으므로 전부 위험 또는 전부 안전으로 처리하지 않고 공간 관계로 다시 분류했다.

## 점수 부여 원칙

보행 link는 아래 우선순위로 분류한다.

```text
횡단/교차 판단
→ 특수 안전 시설
→ 1111 독립 보행축 승격
→ 도로와 공유/인접
→ 도로 없음
```

도로 위험도를 사용하는 케이스는 매칭된 도로의 `local_method_risk_index` percentile을 그대로 보행 위험 점수로 사용한다.

```text
road_risk_pct = percentile_rank(local_method_risk_index)
safety_score_0_1 = road_risk_pct
```

차량 도로 노출이 없다고 판단한 케이스는 `0.0`으로 둔다.

## 케이스 정의

| 케이스 | 기준 | 점수 |
|---|---|---|
| `case_D_crosswalk` | 원자료 `crosswalk=1`이고 실제 도로와 45도 이상으로 교차 | 횡단하는 도로의 위험 percentile |
| `case_D_crossing` | `crosswalk=0`이어도 geometry상 도로를 45도 이상으로 건넘 | 횡단하는 도로의 위험 percentile |
| `special_safe_facility` | 육교, 교량, 터널, 공원녹지 등 차량도로 노출이 낮은 시설 | `0.0` |
| `case_A_separated` | 보행자 전용/보행+자전거+PM 또는 독립 보행축 | `0.0` |
| `case_B_shared_road` | 보행 link가 도로와 5m 이내에서 평행·겹침 | 해당 도로의 위험 percentile |
| `case_B_nearest_road` | 위 조건은 아니지만 80m 이내 도로가 있어 가장 가까운 도로에 노출 | 최근접 도로의 위험 percentile |
| `case_C_no_nearby_road` | 80m 이내 차량도로 없음 | `0.0` |
| `unclassified` | 어떤 규칙에도 걸리지 않음 | 현재 산출물에서는 0개 |

## 횡단보도/도로 교차 처리

원자료의 `crosswalk` 플래그만 믿으면 횡단보도가 아닌 링크가 횡단보도로 잡히거나, 실제 횡단 링크가 빠지는 문제가 있었다. 그래서 현재는 geometry 기준을 우선한다.

- 보행 link와 도로 link가 실제로 교차하거나 2m 이내에서 거의 교차하는지 확인
- 두 선형의 교차 각도가 45도 이상인지 확인
- 길게 평행하게 겹치는 링크는 횡단으로 보지 않음
- 횡단으로 판단되면 해당 도로의 위험 percentile을 부여

즉 횡단보도는 “안전시설이라서 0점”이 아니라, 실제로 건너는 도로의 위험도를 받는다.

## 1111 독립 보행축 승격

`walking_type=1111`이라고 해서 모두 도로 공유로 처리하면 하천변·도로변 독립 보행축이 과하게 위험해진다. 반대로 모두 안전 처리하면 골목길이 과하게 안전해진다. 그래서 다음 조건을 동시에 만족할 때만 `case_A_separated`로 승격한다.

| 조건 | 값 |
|---|---:|
| 보행 link 길이 | 20m 이상 |
| 주요도로와의 거리 | 3m 이상 25m 이하 |
| 주요도로와의 방향 차이 | 20도 이하 |
| 주요도로 buffer와 겹침률 | 55% 이상 |
| 대상 도로 | `trunk`, `primary`, `secondary`, `tertiary`, `busway` 계열 |

이 조건은 “도로와 같은 방향으로 길게 따라가지만, 도로 중심선과 직접 겹치지는 않는 보행축”을 분리 보행공간으로 보기 위한 것이다.

## 현재 결과 요약 (2026-05-21, PDF 충실 산식 + distance discount)

| 케이스 | link 수 | 평균 점수 |
|---|---:|---:|
| `case_B_shared_road` | 5,690 | 0.498 |
| `case_B_nearest_road` | 3,074 | 0.590 |
| `case_A_separated` | 1,676 | 0.000 |
| `case_D_crossing` | 353 | 0.853 |
| `case_C_no_nearby_road` | 49 | 0.000 |
| `special_safe_facility` | 41 | 0.000 |
| `case_D_crosswalk` | 39 | 0.724 |
| `unclassified` | 0 | — |

총 분석 대상 보행 link는 **10,922개**다.

점수 분포:

| 항목 | 값 |
|---|---:|
| 평균 | 0.456 |
| 중앙값 | 0.493 |
| p25 | 0.198 |
| p75 | 0.696 |
| p95 | 0.894 |
| 점수 0 link | 1,766 |
| 점수 0.8 이상 link | 1,522 |

### 변경사항 (2026-05-21)

1. **컬럼명**: `safety_score_0_1` 외에 `walking_risk_score_0_1` 추가 노출 (값은 동일, 의미 명확화)
2. **case_B_nearest_road**: 거리 기반 piecewise discount 도입 — 평균 점수 0.640 → 0.590 (과대평가 보정)
3. **등산로 제거**: 위경도 magic number → **관악구 행정경계 + OSM 산림 polygon** 기반으로 교체 (재현성·견고성 개선)
4. **민감도 분석**: `sensitivity_report.md` 참고. 결과 견고성 ±3% 이내 확인.
5. **연쇄 변경**: 도로 안전도(`road_safety_full_remap_service/`)가 PDF 충실 산식으로 바뀌어 risk_pct 분포가 약간 이동 → 평균 점수 변동.

이전 산출물과 호환되는 컬럼은 모두 유지됨.

## 한계

- 보행 link 자체의 폭, 조명, 경사, 보도 포장 상태, 불법주정차 등은 반영하지 못했다.
- TOPIS 관측값이 없는 생활도로는 도로등급 기반 추정 속도/교통량에 의존한다.
- `case_B_nearest_road`는 실제 시야·차도 노출보다 단순 거리 기반 성격이 강하다.
- `walking_type=1111`은 데이터 정의가 넓어, 독립 보행축 승격 조건을 만족하지 못하면 여전히 도로 노출로 처리된다.

