# 04_b2c_chatbot — AI 챗봇 서비스 (§5)

> 시민용 안전 통학 경로 추천 챗봇.
> 02 보행안전지수 + 03 학교 출입문/학구도를 입력으로 받아 α-Dijkstra + cap sweep 기반 경로 추천.
>
> 기존 chatbot_fin/ 구조 그대로 보존 (API·Streamlit·Mobile PWA 공유 코어).
> 이 stage의 상세 사용법은 `README.md` 를, 본 문서는 stage 메타 정보를 담는다.

## 입력 (02·03에서 복사)

| 파일 | 위치 | 출처 |
|---|---|---|
| `data/gwanak_walking_edge_safety.geojson` | 보행 안전도 | 02 output |
| `data/gwanak_road_safety_scores_full_remap_service.csv` | 도로 위험도 (위험 요인 설명용) | 01 output |
| `data/school_gates.geojson` | 학교 정·후문 | 03 output |
| `data/schoolzones.geojson` | 스쿨존 폴리곤 | 00 output |
| `data/elementary_commuting_zone.*` | 학구도 (shp) | 03 output |

## 코드 구성

```
04_b2c_chatbot/
├── api/                    # FastAPI 엔드포인트 (모바일·Streamlit 공유)
│   └── main.py
├── core/                   # 공통 로직
│   ├── graph_loader.py     # 보행망 → networkx + KD-tree
│   ├── routing.py          # α-Dijkstra + cap sweep
│   ├── personas.py         # 학년/스타일별 α·cap
│   ├── nudge.py            # 자연어 → α/cap 조정 (Gemini)
│   └── road_risk.py        # 도로 위험도 설명 생성
├── streamlit_app/
│   └── app.py              # Streamlit 시연 UI
├── mobile/                 # PWA 모바일 앱
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── manifest.json
│   └── sw.js
├── data/                   # 입력 데이터 (위 표)
├── docs/                   # 챗봇 설계 문서
├── .streamlit/
│   └── secrets.toml.example  # GOOGLE_API_KEY 템플릿 (실제 키 git ignore)
├── .gitignore
├── README.md               # 챗봇 사용/실행 README
├── STAGE_README.md         # ← 이 문서
└── requirements.txt
```

## 실행

```bash
pip install -r requirements.txt

# .streamlit/secrets.toml 생성 (또는 GOOGLE_API_KEY env var)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml 안의 YOUR_GEMINI_API_KEY_HERE를 실제 키로 교체
# 키 발급: https://aistudio.google.com/apikey

# Streamlit 시연
streamlit run streamlit_app/app.py

# FastAPI 백엔드 (모바일 PWA가 호출)
uvicorn api.main:app --reload --port 8001
```

## 핵심 알고리즘 (§5.4~5.7)

- 비용함수: `cost(e, α) = length(e) · (1 + α · risk(e))`
- α 도출: `α = D / r_ref` (D = 우회 의향 %, r_ref = 데이터 산출 평균 위험도)
- 우회 허용치: `detour_ratio = L_route/L_short − 1 ≤ cap`
- 이분탐색으로 cap 만족 최대 α 탐색

학년별 보행 속도·cap 결정 (`api/main.py: WALK_SPEED_BY_GRADE`):
| 학년 | 속도 | 비고 |
|---|---|---|
| 1, 2 | 45 m/분 | 안전 우선 + α_floor=D=0.10 |
| 3, 4 | 55 m/분 | 3학년: α_floor 적용, 4학년: 사용자 선택 가능 |
| 5, 6 | 65 m/분 | 사용자 선택 (안전/빠른) |

자연어 nudge (§5.7):
- 규칙: 안전 키워드 → α↑, 시간부족 → cap↓
- Gemini 보조 분류 (safer/faster/neutral)
- 비대칭 가드레일: 안전 우선 (LLM 단독 "빠른길" 판단은 제한적 적용)

## 보고서 매핑

- §5.2 시스템 구성
- §5.3 그래프 구축과 목적지 결정 (출입문 노드 후보)
- §5.4 안전 경로 추천 비용 함수
- §5.5 우회 허용치와 시간 제약
- §5.6 이분탐색 경로 선택
- §5.7 자연어 기반 경로 조정
- §5.8 위험 구간 설명 생성
- §5.9 API 및 사용자 화면 (FastAPI + Streamlit + PWA)
