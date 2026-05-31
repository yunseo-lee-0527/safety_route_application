# 안전 통학로 챗봇 — AI 구현 컨텍스트

> 챗봇 구현용 최소 사양. 정당화·심사방어·설계근거는 제외.

## 1. 데이터 (팀/공공데이터 제공)

엣지(링크)별:
- `len` : 길이(m)
- `risk` ∈ [0,1] : 스칼라 위험도 (보차분리 인도 = 0)
- 속성 테이블: `보차분리여부`, `도로폭/차로수`, `신호유무`, `스쿨존`(boolean), `횡단보도수` 등

별도 데이터:
- 관악구 보행망 그래프 (노드/엣지 위상)
- 스쿨존 폴리곤 (지도 오버레이 전용)
- 관악구 초등학교 좌표 테이블

## 2. 라우팅 알고리즘

```
cost(e, α) = len(e) · (1 + α · risk(e))

def route(G, src, dst, α_eff, cap_eff, α_floor, ε=0.05):
    short_len = dijkstra_length(G, src, dst, cost=len)         # α=0 기준 최단

    # 1) 선호 α에서 cap 만족 → 스윕 불필요, 가장 안전한 결과
    p_hi = dijkstra(G, src, dst, cost=lambda e: cost(e, α_eff))
    if detour(p_hi, short_len) <= cap_eff:
        return p_hi, α_eff, False

    # 2) floor에서도 cap 초과 → 충돌, floor 경로 + 경고
    p_lo = dijkstra(G, src, dst, cost=lambda e: cost(e, α_floor))
    if detour(p_lo, short_len) > cap_eff:
        return p_lo, α_floor, True

    # 3) 이분탐색: cap 만족하는 *최대* α (가장 안전한 feasible 경로)
    #    detour(α)는 α에 단조증가 → 이분 가능
    lo, hi, best = α_floor, α_eff, p_lo
    while hi - lo > ε:
        mid = (hi + lo) / 2
        p = dijkstra(G, src, dst, cost=lambda e: cost(e, mid))
        if detour(p, short_len) <= cap_eff:
            lo, best = mid, p
        else:
            hi = mid
    return best, lo, False

detour(p, short_len) = len(p)/short_len − 1
```

> **왜 이분탐색이고 그리디 감쇠가 아닌가:** 목표가 "cap 만족"이 아니라 **"cap 지키면서 *최대* α"** (= 가능한 한 안전한 경로). 그리디 하강은 처음 cap을 만족한 α에서 멈춰 필요 이상으로 α가 낮아질 수 있음 = 경로가 필요 이상 덜 안전. detour(α)는 α에 단조증가라 이분 가능, 호출 횟수 `log₂((α_eff−α_floor)/ε)` (ε=0.05이면 약 5회).

`warning=True`면 응답에 "이 시간 안엔 충분히 안전한 길이 없어요" 문구 동반.

## 3. 페르소나 & 파라미터

```python
# 전역 상수
r_ref = mean(risk(e) for e in edges if risk(e) > 0)   # 데이터 산출
D_max, D_min, D_floor = 1.50, 0.05, 0.10             # 실제 교정값 (personas.py 기준)
α_max = D_max / r_ref                                 # 그리드 상한
α_min = D_min / r_ref                                 # 그리드 하한(고학년 기본형)
CAP_MENU = [0.50, 0.15]                               # 2×2 토글 (사다리)
CAP_EXTREME = 0.0                                     # "지각임박" 명명 극단
```

페르소나 표 (사이드바):

| 페르소나 | D_p | α_p = D_p/r_ref | cap_p | 학년 제한 |
|---|---|---|---|---|
| 소심한 아이 | 1.50 | α_max | 0.50 | 전 학년 |
| 안전·쫓김 | 1.50 | α_max | 0.15 | 전 학년 |
| 마이페이스 | 0.05 | D_min/r_ref | 0.50 | 4~6학년만 |
| 기본/서두름 | 0.05 | D_min/r_ref | 0.15 | 4~6학년만 |

저학년(1~3): "마이페이스/기본" 선택 UI에서 disable.

α_floor:
```
α_floor(grade in 1..3) = D_floor / r_ref
α_floor(grade in 4..6) = 0
```

## 4. 자연어 nudge

nudge는 **이산 사다리 위 이동**이지 연속 Δ 덧셈이 아니다(2×2 설계).

```
# α_eff ∈ {α_min, α_max}, 단 α_floor(grade)로 하한
# cap_eff ∈ CAP_MENU ∪ {CAP_EXTREME} = {0, 0.15, 0.50}

α_eff   = max( {α_min, α_max} 중 nudge 결과 ,  α_floor(grade) )
cap_eff = {CAP_MENU 위 토글, 또는 CAP_EXTREME} 중 nudge 결과
```

`α`는 그리드 두 값 사이 토글(안전 스냅 시 α_max 고정), `cap`은 `0.50 ↔ 0.15` 토글에 명명 극단 `0` 추가. **그 외 값은 없다.**

### 4.1 규칙 레이어 (결정론, 우선)

| 트리거 | 정규식(예시) | 효과 |
|---|---|---|
| 안전 스냅 | `무서|차\s*많|쌩쌩|위험` | `D := D_max` (α := α_max) |
| 안전 완화 | `천천히|시간\s*있|여유` | cap: 1레벨 ↑ |
| 속도 스텝 | `빨리|급해|늦` | cap: 1레벨 ↓ |
| 지각임박 | `곧\s*지각|1분\s*남|진짜\s*늦` | `cap := 0` |

복수 매치 → 모두 누적 적용(같은 축 충돌 시 안전쪽 우선).

### 4.2 LLM 의도 분류 (보조, 규칙 미스 시)

- LLM: Gemini API (`core/nudge.py` `llm_intent()`)
- 입력: 사용자 발화
- 출력 스키마: `{"direction": "safer" | "faster" | "neutral"}` (방향만, 크기 없음)
- `safer` → `alpha_axis := "max"` (안전 스냅과 동일) / `neutral` → no-op
- `faster` → **LLM 단독 발동 금지** (규칙 레이어 매치 시에만 cap 감소 허용)

### 4.3 가드레일
- `α↓` 또는 `cap↓` (속도쪽) 는 **규칙 레이어 매치 시에만** 발동. LLM 단독으로 발동 금지.
- `α↑`·`cap↑` (안전쪽) 는 LLM·규칙 어디서든 자유.

### 4.4 stickiness
- 트리거 효과는 세션 내 latch (재발화 시까지 유지).
- 반대 방향의 명시적 트리거가 오면 해제.

### 4.5 투명성
- 적용된 nudge를 응답에 1줄 노출: `"'늦을 것 같다'고 하셔서 더 빠른 길로 안내했어요."`

## 5. 안내문 생성 (사실/표현 분리)

```
pipeline:
  factors = rules.identify(path, edge_attrs)     # 구조화 사실 리스트
  try:
      text = gemini.realize(factors, persona, applied_nudges, timeout=3000ms)
  except (Timeout, RateLimit, NetworkError):
      text = template.realize(factors)
```

### 5.1 요인 식별 규칙 (속성 직접 읽기)

경로 위 각 엣지/구간:
```python
if not e.보차분리 and e.len > L_MIN_단절:     # L_MIN_단절 = 30m
    emit({"type":"인도단절","위치":e.mid,"길이":e.len})
if e.횡단보도 and not e.신호:
    emit({"type":"무신호횡단","위치":e.node})
if e.스쿨존:
    emit({"type":"스쿨존","위치":e.segment})
if e.차로수 >= 4 and not e.보차분리:
    emit({"type":"대로변","위치":e.segment})
# ... 팀 정의에 맞춰 확장
```

### 5.2 LLM 프롬프트 (constrained realization)

```
시스템 프롬프트:
  - 아래 JSON 리스트의 항목만 자연어로 풀어 설명한다.
  - 리스트에 없는 위험·장소·수치를 새로 생성하지 않는다.
  - 결과는 한국어 3~4문장, 학부모/아동 친화 톤.
  - 적용된 nudge가 있으면 그 사실을 1문장으로 언급한다.

입력 JSON:
  {
    "factors": [{"type": ..., "위치": ..., ...}, ...],
    "persona": "소심한 아이",
    "applied_nudges": ["안전 스냅", ...]
  }
```

### 5.3 템플릿 폴백 (LLM 실패 시)

```python
type_templates = {
  "인도단절":  "{위치} 부근 약 {길이}m 구간 인도 단절",
  "무신호횡단": "{위치}에 신호 없는 횡단보도",
  "스쿨존":   "{위치} 스쿨존 통과",
  ...
}
text = "이 길은 " + ", ".join(type_templates[f.type].format(**f) for f in factors) + " 구간이 있어요."
```

## 6. UI

### 6.1 사이드바
- **페르소나**: 4택. 학년 선택에 따라 저학년이면 "마이페이스/기본" disable.
- **학년**: 1~6 라디오.
- **도착지**: 관악구 초등학교 드롭다운.
- **출발지**: "현위치 사용" 버튼 + 지도 핀 클릭.

### 6.2 지도
경로 색상 (엣지 단위, `road_risk.py` `risk_band()` 기준):

| risk | 등급 | 색 |
|---|---|---|
| `≤ 0.33` | 안전 | 초록 (#1D9E75) |
| `≤ 0.66` | 주의 | 연노랑 (#FFE066) |
| `≤ 0.85` | 위험 | 주황 (#FF9933) |
| `> 0.85` | 매우위험 | 빨강 (#E63946) |

상수: `RISK_SAFE=0.33`, `RISK_HIGH=0.66`, `RISK_SEVERE=0.85` (`core/road_risk.py`)

- 스쿨존 폴리곤: 반투명 노랑 오버레이.
- 라이브러리: leaflet 또는 mapbox-gl.

### 6.3 챗 영역
- 자연어 입력창.
- 응답 영역: 안내문(§5) + 적용된 nudge 1줄(§4.5) + (필요 시) warning 문구(§2).

## 7. OD → 그래프 노드

- 좌표 `(lat, lon)` → `core/graph_loader.py` `SnapTree` (cKDTree, 평면 근사) 스냅.
- 반경 초과 시 `"근처에 보도가 없어요"` 응답:
  - API (`api/main.py`): `R_SNAP_M = 300.0m`
  - Streamlit (`streamlit_app/app.py`): `R_SNAP_M = 100.0m`
- 학교 게이트 스냅: `graph_loader.py` `_snap_gates_to_nodes(max_dist_m=200.0)`
- 위험 설명용 엣지 스냅: `SNAP_MAX_M = 60.0m` (`core/road_risk.py`)

## 8. 빌드 순서 (각 단계 독립 데모 가능)

1. 그래프 + OD 스냅 + Lagrangian Dijkstra 루프 (§2, §7)
2. 색상 경로 + 스쿨존 지도 시각화 (§6.2)
3. 규칙 기반 요인 식별기 (§5.1)
4. LLM constrained 안내문 + 템플릿 폴백 (§5.2, §5.3)
5. 자연어 nudge 파이프라인 (§4)

## 9. 구현 안 함

- 요인-한정 트리거 (특정 요인만 회피)
- nudge 강도 3단계 ("조금/꽤/너무")
- 하굣길 (학교→집, baseline 다름)
- 학부모 설문 / 문헌 인용

## 10. 튜닝 상수 모음

| 상수 | 값 | 위치 |
|---|---|---|
| `D_max` | 1.50 | §3 (personas.py 교정값) |
| `D_min` | 0.05 | §3 (personas.py 교정값) |
| `D_floor` | 0.10 | §3 |
| `r_ref` | 데이터 산출 | §3 |
| `CAP_MENU` | [0.50, 0.15] (2레벨 토글) | §3·§4 |
| `CAP_EXTREME` | 0.0 (지각임박만) | §3·§4 |
| Lagrangian 이분탐색 ε (α 정밀도) | 0.05 (≈ 5회 Dijkstra) | §2 |
| 인도단절 최소 길이 `L_MIN_단절` | 30m | §5.1 |
| OD 스냅 반경 (API) | 300m | `api/main.py` |
| OD 스냅 반경 (Streamlit) | 100m | `streamlit_app/app.py` |
| 게이트 스냅 반경 | 200m | `core/graph_loader.py` |
| 위험 설명 스냅 반경 `SNAP_MAX_M` | 60m | `core/road_risk.py` |
