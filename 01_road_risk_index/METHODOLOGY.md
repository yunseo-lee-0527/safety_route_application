# 01 도로 위험도 지수 — 산출 방법론

## 전체 흐름

```text
drive+service OSM 도로망 구축 (관악구)
→ 횡단보도 / 신호등 / 어린이시설 / TOPIS 속도 / 교통량 결합
→ 후보 변수 6개 생성 (밀도 보정 포함)
→ sqrt 변환 후 보행자사고 가중치와 Pearson 상관계수 계산
→ 평균 절댓값 상관계수(0.139485) 이상 변수 5개 선택
→ z-score 합산 × 그룹 가중치 곱셈 → local_method_risk_index
→ percentile rank [0,1]로 정규화 → 02 보행안전지수로 전달
```

---

## 1. 도로망 구축

포함 도로 등급 (OSMnx `network_type=all`에서 차량 통행 성격 있는 것):

```text
trunk, trunk_link, primary, primary_link,
secondary, secondary_link, tertiary, tertiary_link,
residential, living_street, busway, service, unclassified
```

OSMnx directed edge를 물리 도로 단위로 collapse.

| 항목 | 값 |
|---|---:|
| 통합 전 directed edge | 13,599 |
| 통합 후 physical edge | 7,384 |

`service`/`residential`/`living_street` 포함 이유: 보행 네트워크와의 매핑 누락을 줄이기 위해.

---

## 2. 시설물 매핑

```text
시설 point → 80m 이내 가장 가까운 도로 edge 1개
```

동일 물리 도로의 양방향 중 한쪽에만 시설물이 붙는 것을 막기 위해 `physical_edge_id` 단위로 count를 보존한다.

| 시설 | 매핑된 point 수 |
|---|---:|
| 횡단보도 | 1,784 |
| 신호등 | 1,320 |

밀도 보정 (짧은 링크 과도 밀도 방지):

```text
length_m_for_density = max(length_m, 20m)
crosswalk_count_per_100m       = crosswalk_count       / length_m_for_density * 100
traffic_signal_count_per_100m  = traffic_signal_count  / length_m_for_density * 100
```

`length_m` 자체는 독립 후보 변수로 사용하지 않는다 (밀도 분모 전용).

---

## 3. 후보 변수 (6개)

| 변수 | 의미 |
|---|---|
| `crosswalk_count_per_100m` | 횡단보도 밀도 |
| `traffic_signal_count_per_100m` | 신호등 밀도 |
| `traffic_lanes_estimated` | TOPIS/OSM/도로등급 기반 추정 차선 수 |
| `estimated_traffic_volume` | 도로등급별 기준 교통량 × 차선 수 |
| `inverse_speed_risk` | 역속도 지표 (속도↓ → 위험↑) |
| `child_facility_count_300m_capped` | 300m 내 어린이시설 수 (95분위 상한) |

---

## 4. 변수 선택

```text
x_sqrt = sqrt(max(x, 0))
threshold = mean(|correlation_i|)  →  0.139485
selected  = variables where |correlation_i| >= threshold
```

| 선정 변수 | 상관계수 |
|---|---:|
| `crosswalk_count_per_100m_sqrt` | +0.180 |
| `estimated_traffic_volume_sqrt` | +0.173 |
| `traffic_signal_count_per_100m_sqrt` | +0.167 |
| `traffic_lanes_estimated_sqrt` | +0.149 |
| `inverse_speed_risk_sqrt` | −0.162 |

`child_facility_count_300m_capped_sqrt`는 |r|=0.007로 탈락. 단 어린이시설 존재 여부는 그룹 가중치 계산에 반영한다.

---

## 5. 도로 위험도 산출식

```text
base_risk = Σ z_score_i   (선택된 5개 변수)
```

그룹 가중치 (`w = 1 + |r_group| / Σ|r_group|` 구조):

| 그룹 | 트리거 조건 | 가중치 |
|---|---|---:|
| `road_6lane_or_traffic` | 6차로 이상 또는 추정 교통량 평균 초과 | 동적 산출 (1.981은 실행 결과 예시) |
| `child_facility` | 300m 내 어린이시설 존재 | 동적 산출 (1.019는 실행 결과 예시) |

가중치는 `w = 1 + |r_group| / Σ|r_group|` 식으로 실행 시 Pearson 상관계수에서 계산된다. 고정값이 아니다.

```text
final_weight              = road_6lane_or_traffic_weight × child_facility_weight
local_method_risk_index   = base_risk × final_weight
local_method_safety_index = -local_method_risk_index
```

---

## 6. 산출물

| 파일 | 설명 |
|---|---|
| `road_safety_full_remap_service/gwanak_road_safety_scores_full_remap_service_utf8.csv` | 7,384 물리 edge 위험도 (UTF-8) |
| `road_safety_full_remap_service/gwanak_road_safety_scores_full_remap_service.csv` | 동일 cp949 |
| `road_safety_full_remap_service/road_safety_full_remap_service_summary.json` | 변수 선택·가중치·분포 요약 |

핵심 컬럼: `local_method_risk_index` (클수록 위험), `local_method_risk_decile` (10=최위험), `risk_percentile` (02에서 보행 edge 점수로 사용).

---

## 7. 데이터 한계

| 한계 | 영향 |
|---|---|
| TOPIS 직접 매칭률 12.0% | service/residential 도로는 등급 기반 추정 비중 높음 |
| 어린이시설 포인트 1,395개 (관악구 어린이집 146개 대비 과다) | 공간 필터가 인근 구까지 포함했을 가능성 — 시설물 변별력 약화 |
| 보도 폭·조명·경사·불법주정차 미반영 | 실제 보행 위험 완전 설명 불가 |
