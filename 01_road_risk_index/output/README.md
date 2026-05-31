# 도로 안전도 지수 산출 방법

이 폴더는 의왕시 방법론의 변수 선택 흐름을 관악구 drive+service 도로망에 적용한 도로 링크별 위험도/안전도 산출물이다.

이번 버전의 핵심 변경사항은 다음과 같다.

- 횡단보도와 신호등은 최근접 OSM node가 아니라 **가장 가까운 drive+service 도로 edge**에 직접 매핑했다.
- `schoolzone_overlap_share`, 노인의료복지시설, 생활인구 취약비율은 산출 과정과 후보 변수에서 제외했다.
- `length_m`은 독립 후보 변수에서 제외했다. 단, 횡단보도/신호등 밀도를 계산할 때 짧은 링크 보정을 위한 분모로만 사용했다.

## 산출물

> `02_build_road_safety.py` 는 `01_road_risk_index/road_safety_full_remap_service/` 에 출력한다.
> 이 폴더(`output/`)의 파일들은 별도로 복사된 것이다.

| 파일 | 내용 |
|---|---|
| `gwanak_road_safety_scores_full_remap_service_utf8.csv` | UTF-8 도로 링크별 안전도 지수 |
| `gwanak_road_safety_scores_full_remap_service.csv` | CP949 도로 링크별 안전도 지수 |
| `road_safety_full_remap_service_summary.json` | 변수 선택, 상관계수, 그룹 가중치, 점수 분포 요약 |

## 도로망

OSM `network_type=all`에서 차량 통행 성격이 있는 도로를 선별했다. 기존 drive-only 도로망에 비해 보행 네트워크와의 매칭 누락을 줄이기 위해 `service`, `residential`, `living_street` 등을 포함했다.

OSMnx는 같은 도로를 `u->v`, `v->u` directed edge로 저장하는 경우가 많다. 최종 안전도는 물리적 도로 링크 기준이어야 하므로 `u`, `v`, `key`를 기준으로 양방향 edge를 하나의 `physical_edge_id`로 통합했다.

| 항목 | 값 |
|---|---:|
| 통합 전 directed edge | 13,599 |
| 통합 후 physical edge | 7,384 |
| 제거된 중복 directed edge | 6,215 |

## 횡단보도/신호등 매핑

입력 시설물 point는 `data/processed/seoul/seoul_facility_points_normalized.csv`의 `facility_category`를 사용했다.

| 시설 | category | 매핑 방식 |
|---|---|---|
| 횡단보도 | `crosswalk` | point에서 80m 이내 가장 가까운 drive+service 도로 edge 1개에 배정 |
| 신호등 | `signal` | point에서 80m 이내 가장 가까운 drive+service 도로 edge 1개에 배정 |

주의할 점은 최근접 검색은 directed edge에서 수행하되, 같은 물리 도로의 양방향 중 어느 한쪽에만 시설물이 붙는 것을 막기 위해 최근접 edge의 `physical_edge_id`에 count를 부여했다는 점이다. 이후 directed edge collapse 과정에서 해당 물리 링크의 시설물 수가 보존된다.

이번 산출에서 매핑된 시설물 수는 다음과 같다.

| 항목 | 값 |
|---|---:|
| 횡단보도 point | 1,784 |
| 횡단보도가 매핑된 directed edge | 1,456 |
| 신호등 point | 1,320 |
| 신호등이 매핑된 directed edge | 834 |

## 후보 변수

이번 도로 안전도 산출의 후보 변수는 다음 6개다.

| 변수 | 계산 방식 |
|---|---|
| `crosswalk_count_per_100m` | `crosswalk_count / max(length_m, 20m) * 100`, 상한 8 |
| `traffic_signal_count_per_100m` | `traffic_signal_count / max(length_m, 20m) * 100`, 상한 8 |
| `traffic_lanes_estimated` | TOPIS 차선 수 우선, 없으면 OSM/도로등급 기반 추정 |
| `estimated_traffic_volume` | 도로등급별 기준 교통량에 차선 추정치를 반영한 상대 교통량 |
| `inverse_speed_risk` | `1 / max(traffic_speed_estimated_kmh, 1)` |
| `child_facility_count_300m_capped` | 도로 300m 버퍼 내 어린이시설 수, 양수 기준 95분위 상한 |

제외한 변수는 다음과 같다.

| 제외 변수 | 제외 이유 |
|---|---|
| `length_m` | 의왕시 방법론의 직접 안전도 후보 변수로 보기 어려워 제외. 밀도 계산의 분모 보정에만 사용 |
| `schoolzone_overlap_share` | 스쿨존 폴리곤 정밀도와 정책 변수 중복 해석 우려로 제외 |
| `elderly_medical_facility_count_300m_capped` | 주소 지오코딩 기반 좌표 불확실성과 사용자 요청에 따라 제외 |
| `vulnerable_living_population_ratio` | 행정동 단위 생활인구 결합 과정 전체를 제외 |

## 변수 선택 및 점수 산출

각 후보 변수는 `sqrt(max(x, 0))` 변환 후 보행자 사고 가중치(`pedestrian_accident_hybrid_weight`)와 피어슨 상관계수를 계산했다. 후보 변수 전체의 평균 절댓값 상관계수 이상인 변수만 선택했다.

```text
threshold = mean(abs(correlation_i))
selected = variables where abs(correlation_i) >= threshold
base_risk = sum(z_score_i for selected variables)
final_risk = base_risk * final_local_method_weight
safety_index = -final_risk
```

이번 산출의 변수 선택 기준값은 `0.139485`이며, 선택 변수는 다음 5개다.

- `crosswalk_count_per_100m_sqrt`
- `traffic_signal_count_per_100m_sqrt`
- `traffic_lanes_estimated_sqrt`
- `estimated_traffic_volume_sqrt`
- `inverse_speed_risk_sqrt`

최종 그룹 가중치는 도로/교통 그룹과 어린이시설 그룹만 적용했다.

| 그룹 | 적용 조건 | 가중치 |
|---|---|---:|
| `road_6lane_or_traffic` | 6차로 이상 또는 추정 교통량 평균 초과 | 1.981 |
| `child_facility` | 300m 내 어린이시설 존재 | 1.019 |

`local_method_risk_index`가 높을수록 위험하고, `local_method_safety_index`는 그 반대 부호다. `local_method_risk_decile`은 전체 물리 도로 링크를 10분위로 나눈 값이며 10분위가 가장 위험하다.
