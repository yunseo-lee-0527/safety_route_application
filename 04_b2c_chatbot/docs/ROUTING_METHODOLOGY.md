# 04 B2C 챗봇 — 라우팅 방법론

## 1. 비용 함수

```text
cost(e, α) = length_m(e) · (1 + α · risk(e))
```

- `length_m(e)`: 링크 길이(m)
- `risk(e) = safety_score_0_1 ∈ [0, 1]`: null → 0.0 처리 (보차분리 인도 취급)
- `α`: 높을수록 위험 링크를 더 피함

---

## 2. 라우팅 알고리즘 (Lagrangian Dijkstra + 이분탐색)

원래 문제("min 위험가중비용 s.t. detour ≤ cap")는 RCSPP(NP-hard). Lagrangian 패널티로 대체해 평범한 Dijkstra로 환원한다.

```python
def find_route(G, src, gates, alpha_eff, cap_eff, alpha_floor, eps=BISECTION_EPS):
    # 1) α=0 기준 최단 경로 길이
    _, short_len = dijkstra_to_gates(G, src, gates, alpha=0.0)

    # 2) 선호 α에서 cap 만족 → 가장 안전한 결과
    p_hi, len_hi = dijkstra_to_gates(G, src, gates, alpha_eff)
    if len_hi / short_len - 1.0 <= cap_eff:
        return build_result(p_hi, alpha_eff, warning=False)

    # 3) floor에서도 cap 초과 → 충돌, floor 경로 + 경고
    p_lo, len_lo = dijkstra_to_gates(G, src, gates, alpha_floor)
    if len_lo / short_len - 1.0 > cap_eff:
        return build_result(p_lo, alpha_floor, warning=True)

    # 4) 이분탐색: cap 만족하는 최대 α (가장 안전한 feasible 경로)
    lo, hi = alpha_floor, alpha_eff
    while hi - lo > eps:
        mid = (hi + lo) / 2.0
        p, plen = dijkstra_to_gates(G, src, gates, mid)
        if plen / short_len - 1.0 <= cap_eff:
            lo = mid
        else:
            hi = mid
    return build_result(best_path, best_alpha, warning=False)
```

Multi-target: 학교의 모든 게이트 노드에 각각 Dijkstra 실행 후 실제 길이 최소 경로 선택.

우선순위: **`α_floor > cap > α선호`**  
cap과 α_floor가 충돌하면 cap을 양보하고 `warning=True` 반환.

---

## 3. α 도출 (D 단위)

α는 비용식 안의 계산값이라 직관으로 정할 수 없다. "전형적 위험 링크를 피하기 위해 최대 D%만큼 더 걷겠다"로부터 역산한다.

```python
# graph_loader.py
r_ref = mean(safety_score_0_1 for edges where safety_score_0_1 > 0)
# r_ref가 비어있으면 0.5 fallback

# personas.py
alpha = D_value / r_ref
```

**D 상수:**

| 상수 | 값 | 파일 |
|---|---|---|
| `D_MAX` | 1.50 | `core/personas.py` |
| `D_MIN` | 0.05 | `core/personas.py` |
| `D_FLOOR` | 0.10 | `core/personas.py` |

---

## 4. cap — 직접 설정

```python
# personas.py
CAP_LADDER  = (0.0, 0.15, 0.50)   # nudge 이산 사다리
CAP_EXTREME = 0.0                  # "지각임박" 극단
```

### 시간 기반 cap 자동 결정 (`assess_time_vs_path`)

```python
speed     = WALK_SPEED_BY_GRADE[grade]   # m/분
estimated = path_length_m / speed
slack     = time_left_min / estimated - 1.0

if slack >= 0.50:  cap = 0.50   # 여유
if slack >= 0.15:  cap = 0.15   # 보통
if slack >= 0.0:   cap = 0.0    # 빠듯
if slack <  0.0:   cap = 0.0    # 이미 늦음
```

nudge가 `cap_override`를 설정한 경우 시간 기반 cap을 덮어쓴다.

**학년별 보행 속도:**

| 학년 | 속도 (m/분) |
|---|---|
| 1, 2 | 45 |
| 3, 4 | 55 |
| 5, 6 | 65 |
| 미지정 | 55 (fallback) |

---

## 5. 페르소나 그리드 (2×2)

| | cap=0.50 | cap=0.15 |
|---|---|---|
| alpha=max (D=1.50) | 소심한 아이 (`timid`) | 안전·쫓김 (`safe_rush`) |
| alpha=min (D=0.05) | 마이페이스 (`leisurely`) | 기본/서두름 (`default`) |

**학년 제한:**
- `leisurely`, `default` (alpha=min): 4~6학년만 허용
- `timid`, `safe_rush` (alpha=max): 전 학년 허용
- 기본 페르소나: `timid`
- 학년 변경으로 disable 시 cap 유지하며 alpha=max 페르소나로 fallback

**α_floor:**

```python
# personas.py
if grade in (1, 2, 3):
    alpha_floor = D_FLOOR / r_ref   # = 0.10 / r_ref
else:
    alpha_floor = 0.0
```

---

## 6. 자연어 nudge

nudge는 `(alpha_axis, cap_eff)`를 이산 사다리 위에서 이동시킨다.  
규칙 레이어 매치 시 결정론적으로 처리; 규칙 미스 시에만 LLM 폴백.

| 규칙 이름 | 주요 트리거 패턴 | 효과 |
|---|---|---|
| 안전 스냅 | `무서`, `차많`, `쌩쌩`, `위험`, `차도`, `교통사고`, `스쿨존` 등 | `alpha_axis := "max"` |
| 안전 완화 | `천천히`, `여유`, `멀어도`, `안전우선`, `보도있는` 등 | cap 1레벨 ↑ |
| 속도 스텝 | `빨리`, `급해`, `늦`, `시간없`, `최단`, `우회적게` 등 | cap 1레벨 ↓ |
| 지각임박 | `곧지각`, `1분남`, `진짜늦`, `0~5분남`, `수업시작` 등 | `cap := 0.0` (extreme) |

**충돌 해소 (같은 발화에 안전+속도 동시 매치):**
```python
# nudge.py
alpha_axis = "max"          # 안전 우선
cap_eff = _step_cap(cap, +1)  # cap 한 칸 위로
```

**비대칭 가드레일:** LLM은 `"safer"` 방향만 적용 가능 — `"faster"`는 규칙 레이어 매치 시에만 발동.  
LLM 출력 형식: `{"direction": "safer" | "faster" | "neutral"}`

---

## 7. 위험도 등급 (`risk_band`)

```python
# road_risk.py
RISK_SAFE   = 0.33   # ≤ 0.33 → 안전 (초록)
RISK_HIGH   = 0.66   # ≤ 0.66 → 주의 (노랑)
RISK_SEVERE = 0.85   # ≤ 0.85 → 위험 (주황)
             # > 0.85 → 매우위험 (빨강)
```

---

## 8. 위험 요인 기여도 (`road_risk.py`)

경로 위험 설명 시 3개 독립 차원의 가중합으로 주요 원인을 선택:

```python
IMPORTANCE = {"traffic": 0.68, "accident": 0.22, "facility": 0.04}
```

| 요인 | 키 | 정규화 기준 |
|---|---|---|
| 교통량 | `road_6lane_or_traffic_weight` | `TRAFFIC_EXCESS_SCALE` |
| 사고 | `pedestrian_accident_hybrid_weight` | `ACCIDENT_SCALE` = 2.0 |
| 시설 | `vulnerable_facility_weight` | `FACILITY_EXCESS_SCALE` |

주요 원인: 가중값 ≥ 0.10인 강한 요인(traffic·accident) 우선 선택.  
해당 없으면 엣지 안전유형(`edge_safety_basis`)으로 fallback.

---

## 9. 스냅 반경 상수

스냅 연산은 3가지로 분리되어 있다:

| 연산 | 상수 | 값 | 파일 |
|---|---|---|---|
| 출발지 → 그래프 노드 | `R_SNAP_M` | 300m (API) / 100m (Streamlit) | `api/main.py`, `streamlit_app/app.py` |
| 학교 게이트 → 그래프 노드 | `max_dist_m` | 200m | `core/graph_loader.py` |
| 사용자 클릭 → 위험 엣지 설명 | `SNAP_MAX_M` | 60m | `core/road_risk.py` |

> API와 Streamlit 프론트엔드가 출발지 스냅 반경에서 불일치(300m vs 100m).

---

## 10. 알고리즘 수치 상수 요약

| 상수 | 값 | 파일 |
|---|---|---|
| `D_MAX` / `D_MIN` / `D_FLOOR` | 1.50 / 0.05 / 0.10 | `core/personas.py` |
| `CAP_LADDER` | (0.0, 0.15, 0.50) | `core/personas.py` |
| `CAP_EXTREME` | 0.0 | `core/personas.py` |
| 이분탐색 ε (`BISECTION_EPS`) | 0.05 | `core/routing.py` |
| `RISK_SAFE` / `RISK_HIGH` / `RISK_SEVERE` | 0.33 / 0.66 / 0.85 | `core/road_risk.py` |
| 출발지 스냅 (API) | 300m | `api/main.py` |
| 출발지 스냅 (Streamlit) | 100m | `streamlit_app/app.py` |
| 게이트 스냅 | 200m | `core/graph_loader.py` |
| 위험 설명 스냅 | 60m | `core/road_risk.py` |
| 보행속도 (학년 1~2 / 3~4 / 5~6) | 45 / 55 / 65 m/분 | `api/main.py`, `streamlit_app/app.py` |
