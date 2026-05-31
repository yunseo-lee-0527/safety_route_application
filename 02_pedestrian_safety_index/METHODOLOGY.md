# 02 보행안전지수 — 산출 방법론

## 1. 입력 및 보행 네트워크 정제

| 항목 | 값 |
|---|---:|
| 서울시 공식 보행 네트워크 (관악구 raw) | 11,138 |
| 제외 (관악산 등 산지 링크) | 216 |
| 최종 보행 edge | **10,922** |

도로 위험도 원값은 척도 해석이 어렵기 때문에 percentile rank로 변환해 사용한다.

```text
road_risk_pct = percentile_rank(local_method_risk_index)   ∈ [0, 1]
```

---

## 2. 케이스 분류 (우선순위 순)

| 우선순위 | 케이스 | 기준 | 점수 |
|---|---|---|---|
| 1 | `case_D_crosswalk` | 원자료 `crosswalk=1` AND 도로와 45° 이상 교차 | 건너는 도로의 `road_risk_pct` |
| 2 | `case_D_crossing` | geometry상 도로와 45° 이상 교차 | 건너는 도로의 `road_risk_pct` |
| 3 | `special_safe_facility` | 육교·교량·터널·건물 내부·공원녹지 | 0.0 |
| 4 | `case_A_separated` | 보행 전용 또는 독립 보행축 | 0.0 |
| 5 | `case_B_shared_road` | 도로와 5m 이내 평행·겹침 | 해당 도로의 `road_risk_pct` |
| 6 | `case_B_nearest_road` | 80m 이내 도로 존재 | 거리 보정 후 도로 위험도 반영 |
| 7 | `case_C_no_nearby_road` | 80m 이내 도로 없음 | 0.0 |

현재 케이스 분포: `case_B_shared_road` 52.1%, `case_B_nearest_road` 28.1%, `case_A_separated` 10.0%

---

## 3. 횡단보도 매핑

횡단보도 링크에 도로를 매핑하는 순서:

1. 횡단보도 링크 중점에서 **20m 이내** 후보 중 `risk_pct` 최대 도로 선택
2. 20m 이내 없으면 **80m 이내** 최근접 도로 선택
3. 80m 이내도 없으면 전체 도로망 최근접 + `crosswalk_mapping_warning = nearest_road_over_80m` 표시

횡단보도는 안전시설이라는 이유로 0점 처리하지 않는다.

| 항목 | 값 |
|---|---:|
| `crosswalk=1` edge 전체 | 108 |
| 20m 이내 최대 위험 도로 선택 | 36 |
| 80m 이내 최근접 선택 | 33 |
| 80m 밖 (경고) | 39 |
| 횡단보도 평균 점수 | 0.585 |

---

## 4. 검증 결과

| 항목 | 값 |
|---|---:|
| 전체 보행 edge | 10,922 |
| unclassified | 0 |
| `safety_score_0_1 >= 0.95` | 310 |
| 전체 평균 | 0.456 |

---

## 5. 데이터 한계

| 한계 | 영향 |
|---|---|
| 보도 폭·조명·경사·불법주정차 미반영 | "차도 노출 위험"을 추정한 값이지 보행환경 직접 측정이 아님 |
| `walking_type=1111`의 이질성 | 보차혼합/분리보도/하천변 보행축을 모두 포함할 수 있음 |
| 횡단보도 80m 초과 매핑 39개 | `crosswalk=1` 플래그가 차도 횡단보도만 의미하지 않을 수 있음 |
