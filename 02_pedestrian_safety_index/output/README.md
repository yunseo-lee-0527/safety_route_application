# 보행 edge 안전도 지수 산출 방법

이 폴더는 서울시 공식 보행 네트워크의 관악구 보행 edge에 도로 위험도를 매핑해 보행 edge별 위험도 점수(`safety_score_0_1`)를 부여한 결과를 담는다.

점수는 이름은 `safety_score_0_1`이지만 해석상 위험도에 가깝다.

```text
0 = 안전
1 = 위험
```

## 산출물

| 파일 | 내용 |
|---|---|
| `gwanak_walking_edge_safety_utf8.csv` | UTF-8 보행 edge별 점수 |
| `gwanak_walking_edge_safety.csv` | CP949 보행 edge별 점수 |
| `gwanak_walking_edge_safety.geojson` | 지도/GIS용 GeoJSON |
| `walking_edge_safety_summary.json` | 케이스별 개수, 파라미터, 점수 분포 |
| `case_counts_latest.txt` | 케이스별 link 수 텍스트 요약 |

통합 시각화는 상위 폴더의 [`road_and_walking_safety_map.html`](../road_and_walking_safety_map.html)에서 확인한다.

## 입력 데이터

| 데이터 | 사용 방식 |
|---|---|
| `../data/raw/seoul_walking_network_download.csv` | 관악구 보행 LINK 추출 (`src/01_build_walking_edge_safety.py`가 직접 참조) |
| `../yunseo_lee/road_safety_full_remap_service/gwanak_road_safety_scores_full_remap_service_utf8.csv` | 01의 도로 위험도 (`code ROOT / "yunseo_lee" / ...` 하드코딩 경로) |

## 도로 위험도 반영 방식

도로 안전도 CSV의 `local_method_risk_index`를 전체 도로 링크 내 percentile로 변환한다.

```text
road_risk_pct = percentile_rank(local_method_risk_index)
```

보행 edge가 차량 도로와 직접적으로 관계되는 케이스에서는 매칭된 도로의 `road_risk_pct`를 보행 위험도 점수로 사용한다.

```text
safety_score_0_1 = road_risk_pct
```

차량 도로 노출이 없거나 분리 보행공간으로 판단되는 케이스는 `0.0`으로 둔다.

## 케이스 분류

보행 edge는 아래 우선순위로 분류한다.

| 케이스 | 기준 | 점수 |
|---|---|---|
| `case_D_crosswalk` | 원자료 `crosswalk=1`이고 도로와 45도 이상으로 교차 | 건너는 도로의 위험도 percentile |
| `case_D_crossing` | `crosswalk=0`이어도 geometry상 도로와 45도 이상 교차 | 건너는 도로의 위험도 percentile |
| `special_safe_facility` | 육교, 교량, 터널, 건물 내부, 공원녹지 등 차량 노출이 낮은 시설 | 0.0 |
| `case_A_separated` | 보행 전용/보행+자전거+PM 또는 독립 보행축 | 0.0 |
| `case_B_shared_road` | 보행 edge가 도로와 5m 이내에서 평행·겹침 | 해당 도로의 위험도 percentile |
| `case_B_nearest_road` | 위 조건은 아니지만 80m 이내 가장 가까운 도로가 있음 | 거리 보정 후 도로 위험도 반영 |
| `case_C_no_nearby_road` | 80m 이내 차량 도로 없음 | 0.0 |
| `unclassified` | 현재 산출물에서는 0개 | 해당 없음 |

## 이번 재산출 결과

새 도로 안전도 지수를 반영해 보행 edge를 다시 계산했다.

| 항목 | 값 |
|---|---:|
| 입력 보행 LINK | 11,138 |
| 산지/분석 제외 링크 | 216 |
| 최종 보행 edge | 10,922 |
| unclassified | 0 |
| `safety_score_0_1 >= 0.95` | 310 |

walking_type별 평균 위험도는 다음과 같다.

| walking_type | 평균 `safety_score_0_1` |
|---|---:|
| `1100` | 0.000 |
| `1111` | 0.394 |
| `1011` | 0.649 |
| `1000` | 0.705 |
| `0000` | 0.757 |

## 횡단보도 주의

보행 네트워크의 횡단보도 여부는 원자료 플래그만 믿지 않고, 실제 도로와의 geometry 교차 여부도 확인한다. 도로와 45도 이상으로 교차하는 경우를 실제 횡단 성격으로 보고, 이때 건너는 도로의 위험도를 반영한다.
