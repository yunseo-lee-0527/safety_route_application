# 04_b2c_chatbot — AI 통학 경로 추천 챗봇 (B2C)

초등학생의 출발지·학년·남은 시간·자연어 요청을 바탕으로 관악구 통학로 안전 경로를 안내하는 **모바일 PWA + FastAPI + Streamlit** 챗봇.

> **시연 메인 화면은 모바일 PWA** (`mobile/`). Streamlit 앱은 알고리즘 동작 빠른 검증용.

> ⚠️ `data/` 의 일부 GIS 파일은 [루트 README](../README.md#데이터-다운로드-필수)의 Drive `03_stage_outputs.zip` 압축 해제로 확보된다.

## 빠른 실행 (한 명령으로 모바일 PWA 띄우기)

```bash
pip install -r requirements.txt
python run_mobile.py
```

`run_mobile.py` 가 FastAPI 백엔드(8001)와 정적 서버(8000)를 동시에 실행하고 브라우저를 자동으로 연다.

- **모바일 PWA**: http://127.0.0.1:8000
- **API Swagger**: http://127.0.0.1:8001/docs
- 종료: 터미널에서 Ctrl+C

> GPS 자동 위치는 `localhost` / `127.0.0.1` 또는 HTTPS 환경에서만 동작한다.

## API 키 설정 (Gemini)

자연어 nudge 와 위험 설명 생성에 Gemini API를 사용한다.

- **모바일 PWA / FastAPI** (`run_mobile.py`): 키 없으면 `llm=None` 으로 설정 후 템플릿 폴백으로 계속 동작 (시연 가능).
- **Streamlit** (`streamlit_app/app.py`): 키 없으면 `st.error` + `st.stop()` 으로 서비스 중단.

키 발급: <https://aistudio.google.com/apikey>

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml 안의 YOUR_GEMINI_API_KEY_HERE 를 실제 키로 교체
```

또는 환경변수:

```powershell
# Windows PowerShell
$env:GOOGLE_API_KEY = "your_api_key"
```

```bash
# Linux / macOS
export GOOGLE_API_KEY="your_api_key"
```

## 폴더 구조

```text
04_b2c_chatbot/
├── run_mobile.py           # 모바일 PWA 한 번에 실행
├── api/main.py             # FastAPI 백엔드 (모바일·Streamlit 공유)
├── core/                   # 공통 코어
│   ├── graph_loader.py     # 보행망 → networkx + KD-tree
│   ├── routing.py          # α-Dijkstra + cap sweep
│   ├── personas.py         # 학년 / 스타일별 α·cap
│   ├── nudge.py            # 자연어 → α / cap (Gemini)
│   └── road_risk.py        # 차도 위험도 설명
├── mobile/                 # 모바일 PWA (시연 메인)
│   ├── index.html
│   ├── app.js              # API_BASE = http://127.0.0.1:8001
│   ├── styles.css
│   ├── manifest.json       # PWA
│   ├── sw.js               # 서비스 워커
│   └── icon.svg
├── streamlit_app/app.py    # 알고리즘 검증용 Streamlit UI
├── data/                   # 입력 데이터 (Drive zip 압축 해제 필요)
├── docs/                   # 챗봇 설계 문서 (라우팅 방법론·UI 사양·구현 컨텍스트)
├── .streamlit/secrets.toml.example
├── requirements.txt
├── README.md               # 본 문서
└── STAGE_README.md         # 파이프라인 stage 메타
```

## 입력 데이터

`data/` 위치 (02·03 산출물 사본):

```
data/
├── gwanak_walking_edge_safety.geojson                # 02 output (보행 안전도)
├── gwanak_road_safety_scores_full_remap_service.csv  # 01 output (차도 위험도 설명용)
├── school_gates.geojson                              # 03 output (학교 정·후문)
├── schoolzones.geojson                               # 00 output (스쿨존)
└── elementary_commuting_zone.{shp,shx,dbf,prj}       # 03 output (학구도)
```

## 수동 실행 (`run_mobile.py` 안 쓸 때)

터미널 1 — FastAPI 백엔드:

```bash
uvicorn api.main:app --port 8001
```

터미널 2 — 모바일 정적 서버:

```bash
cd mobile
python -m http.server 8000
```

브라우저: http://127.0.0.1:8000

Streamlit 시연 (보조):

```bash
streamlit run streamlit_app/app.py
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 헬스 체크 (`{ok, llm, bundle_loaded}`) |
| GET | `/api/schools` | 학교·출입문 목록 |
| GET | `/api/schoolzones` | 스쿨존 폴리곤 GeoJSON |
| GET | `/api/school-at?lat=&lon=` | 좌표가 속한 통학구역 |
| POST | `/api/route` | 출발 좌표·학년·시간 → 경로 추천 |
| POST | `/api/nudge` | 자연어 발화 → 경로 재조정 |
| GET | `/api/road/{edge_id}` | 특정 보행 링크 위험 설명 |
| POST | `/api/road/nearest` | 지도 클릭 좌표 주변 위험 설명 |

Swagger: http://127.0.0.1:8001/docs

## 설계 문서

| 파일 | 내용 |
|---|---|
| [STAGE_README.md](STAGE_README.md) | 파이프라인 stage 메타 |
| [docs/ROUTING_METHODOLOGY.md](docs/ROUTING_METHODOLOGY.md) | Lagrangian Dijkstra·페르소나·nudge 방법론 (실제 코드 교정값 기준) |
| [docs/UI_SPEC.md](docs/UI_SPEC.md) | 사이드바·지도 색상·챗 영역·빌드 순서·구현 범위 |
| [docs/context.md](docs/context.md) | AI 구현 컨텍스트 최소 사양 (튜닝 상수·API 계약) |

> **튜닝 상수**: `D_max = 1.50`, `D_min = 0.05` 는 `core/personas.py` 실제 교정값.
