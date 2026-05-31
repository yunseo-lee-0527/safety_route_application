# 관악구 통학로 안전경로 챗봇 — 구현 정리

> 실제 코드(`api/main.py`, `streamlit_app/app.py`, `core/` 모듈) 기반 문서.

---

## 1. 개요

### 1.1 목적

관악구 초등학생 학부모를 대상으로 자녀의 등굣길에 대한 안전 경로 추천 서비스 제공.
학년, 페르소나, 남은 시간, 자연어 발화를 조합해 Lagrangian Dijkstra로 맞춤형 통학로를 제시한다.

### 1.2 진입점

| 파일 | 역할 |
|---|---|
| `run_mobile.py` | FastAPI(8001) + 정적 서버(8000) 동시 실행 → 브라우저 자동 오픈 (시연 메인) |
| `api/main.py` | FastAPI REST API 서버 |
| `streamlit_app/app.py` | Streamlit 알고리즘 검증용 UI |
| `mobile/` | 정적 PWA (HTML/CSS/JS) |

### 1.3 데이터 파일

| 파일 | 내용 |
|---|---|
| `data/gwanak_walking_edge_safety.geojson` | 관악구 10,922개 보행 링크 (`safety_score_0_1`, `edge_safety_basis` 포함) |
| `data/schoolzones.geojson` | 스쿨존 폴리곤 (지도 오버레이용) |
| `data/school_gates.geojson` | 관악구 초등학교 정·후문 좌표 |
| `data/elementary_commuting_zone.shp` | 학구도 (핀→학교 자동 매핑용) |

---

## 2. 핵심 모듈 (`core/`)

| 모듈 | 역할 |
|---|---|
| `graph_loader.py` | GeoJSON 로드 → NetworkX 그래프 + cKDTree SnapTree + 스쿨존 spatial join. `@lru_cache` 싱글턴 |
| `routing.py` | Lagrangian Dijkstra + 이분탐색 |
| `road_risk.py` | 엣지 위험도 설명, `risk_band()`, 위험 구간 추출 |
| `nudge.py` | 자연어 nudge (규칙 레이어 + Gemini 폴백) |
| `personas.py` | 4 페르소나 정의, alpha/cap 상수 |

---

## 3. 비용 함수 및 라우팅

```python
cost(e, α) = length_m(e) × (1 + α × risk(e))
# risk(e) = safety_score_0_1 ∈ [0,1], null → 0.0
```

### 3.1 Lagrangian Dijkstra + 이분탐색 (`routing.py`)

```python
# find_route(G, src, gates, alpha_eff, cap_eff, alpha_floor, eps=0.05)
# 1) α=0 최단 길이 산출
# 2) alpha_eff 적용 시 cap 충족 → 즉시 반환
# 3) alpha_floor에서도 cap 초과 → floor 경로 + warning=True
# 4) 이분탐색: cap 만족하는 최대 α 찾기 (eps=BISECTION_EPS=0.05)
```

Multi-target: 모든 gate 노드에 Dijkstra 실행 후 실제 길이 기준 최솟값 선택.

---

## 4. 페르소나 & 파라미터 (`personas.py`)

```python
D_MAX, D_MIN, D_FLOOR = 1.50, 0.05, 0.10
CAP_LADDER  = (0.0, 0.15, 0.50)
CAP_EXTREME = 0.0
DEFAULT_PERSONA_ID = "timid"
```

| 페르소나 ID | 이름 | alpha축 | cap | 학년 |
|---|---|---|---|---|
| `timid` | 소심한 아이 | max (D=1.50) | 0.50 | 전 학년 |
| `safe_rush` | 안전·쫓김 | max (D=1.50) | 0.15 | 전 학년 |
| `leisurely` | 마이페이스 | min (D=0.05) | 0.50 | 4~6학년 |
| `default` | 기본/서두름 | min (D=0.05) | 0.15 | 4~6학년 |

```python
alpha = D_value / r_ref          # r_ref = mean(safety_score > 0)
alpha_floor(1~3학년) = 0.10 / r_ref
alpha_floor(4~6학년) = 0.0
```

---

## 5. 시간 기반 cap 조정

```python
# api/main.py, streamlit_app/app.py — assess_time_vs_path()
WALK_SPEED_BY_GRADE = {1: 45, 2: 45, 3: 55, 4: 55, 5: 65, 6: 65}  # m/분
slack = time_left_min / estimated_min - 1.0
# slack >= 0.50 → cap=0.50 / >= 0.15 → 0.15 / >= 0.0 → 0.0 / < 0 → 0.0
```

nudge가 `cap_override`를 설정한 경우 시간 기반 cap을 덮어씀.

---

## 6. 자연어 Nudge (`nudge.py`)

규칙 레이어 우선, 규칙 미스 시 Gemini 폴백.

| 규칙 | 효과 |
|---|---|
| 안전 스냅 | `alpha_axis := "max"` |
| 안전 완화 | cap +1단계 (CAP_LADDER 위) |
| 속도 스텝 | cap -1단계 |
| 지각임박 | `cap := 0.0` (CAP_EXTREME) |

충돌 해소: 안전+속도 동시 매치 → `alpha_axis="max"`, cap +1.
Gemini LLM: `"safer"` 적용 가능 / `"faster"` 는 규칙 레이어 없이 단독 발동 금지.

---

## 7. 위험도 등급 및 색상 (`road_risk.py`)

```python
RISK_SAFE   = 0.33  # ≤0.33 → 안전  #1D9E75 (초록)
RISK_HIGH   = 0.66  # ≤0.66 → 주의  #FFE066 (노랑)
RISK_SEVERE = 0.85  # ≤0.85 → 위험  #FF9933 (주황)
             # >0.85 → 매우위험  #E63946 (빨강)
```

위험 요인 중요도:
```python
IMPORTANCE = {"traffic": 0.68, "accident": 0.22, "facility": 0.04}
```

---

## 8. OD 스냅 (`graph_loader.py`)

| 연산 | 값 | 위치 |
|---|---|---|
| 출발지 스냅 (API) | 300m | `api/main.py R_SNAP_M` |
| 출발지 스냅 (Streamlit) | 100m | `streamlit_app/app.py R_SNAP_M` |
| 게이트 스냅 | 200m | `graph_loader._snap_gates_to_nodes(max_dist_m=200)` |
| 위험 설명 스냅 | 60m | `road_risk.SNAP_MAX_M` |

SnapTree는 관악구 위도 기준 평면 근사 cKDTree (오차 < 1%).

---

## 9. API 엔드포인트 (`api/main.py`, 포트 8001)

| 엔드포인트 | 메서드 | 역할 |
|---|---|---|
| `/api/route` | POST | 경로 탐색 (학교, 학년, 좌표, 시간, 페르소나) |
| `/api/nudge` | POST | 자연어 발화 → 경로 재조정 |
| `/api/schools` | GET | 학교 목록 |
| `/api/explain_edge` | POST | 엣지 클릭 → 위험도 설명 |

---

## 10. 안내문 생성 (`road_risk.py` + Gemini)

```
규칙 레이어 → 원시 속성 직접 읽기 → 구조화 요인 리스트
                                           ↓
Gemini 2.5 Flash — 리스트 안에서만 자연어 표현
                   새 사실·수치 생성 금지
                   실패 시 → 템플릿 폴백
```

Streamlit: API 키 없으면 `st.error` + `st.stop()` (LLM 기능 불가).
API: API 키 없으면 `llm=None`, 템플릿 폴백으로 계속 동작.
