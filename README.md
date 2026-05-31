# AI 기반 통학 경로 추천과 안전 사각지대 진단 및 정책 결정 보조 서비스

> **제8회 교육 공공데이터 AI 활용대회** 제출 코드베이스
>
> 교육공공데이터(학구도·학교알리미)와 교통·도시환경 데이터(TAAS·OSM·CCTV·신호등·속도)를 결합해
> 관악구 초등학교 통학로의 보행 안전을 정량화하고,
> (1) 시민·학부모용 **AI 통학 경로 추천 챗봇** (B2C)과
> (2) 지자체용 **안전 사각지대 진단·정책 결정 보조 대시보드** (B2G) 두 산출물로 구현했다.

---

## 데이터 다운로드 (필수)

대용량 GIS·중간 산출물은 GitHub 용량 정책상 별도 호스팅한다. 코드 실행 전 아래 Google Drive에서 zip 3개를 받아 레포 루트에서 압축 해제할 것.

**Drive 폴더**: <https://drive.google.com/drive/folders/1sSO2Uxicxp7FoXbFm3ZhUCBok3I0GYJl?usp=sharing>

| 파일 | 압축 크기 | 압축 해제 위치 (레포 루트 기준) |
|---|---|---|
| `01_raw_data.zip` | 495 MB | `00_data_collection/data/raw/` |
| `02_intermediate_outputs.zip` | 265 MB | `00_data_collection/output/` |
| `03_stage_outputs.zip` | 207 MB | `03_school_commute_exposure/`, `04_b2c_chatbot/data/` |

PowerShell 예시:

```powershell
# 레포 루트에서 실행
Expand-Archive 01_raw_data.zip -DestinationPath . -Force
Expand-Archive 02_intermediate_outputs.zip -DestinationPath . -Force
Expand-Archive 03_stage_outputs.zip -DestinationPath . -Force
```

압축 해제 후 폴더 구조는 [폴더 구조](#폴더-구조) 섹션과 동일해진다.

---

## 파이프라인

```
00_data_collection         raw 공공데이터 수집·전처리
        │
        ▼
01_road_risk_index         차도 위험도 R_road 산출
        │                  (7,384개 물리 차도 엣지)
        ▼
02_pedestrian_safety_index 보행 안전도 R_walk 산출
        │                  (10,922개 보행 링크, 케이스 분류 A/B/C/D)
        │
        ├────────────────────────────┐
        ▼                            ▼
03_school_commute_exposure     04_b2c_chatbot
   학교 정·후문, 학구도,           AI 통학 경로 추천 챗봇
   주거지→학교 최단 경로,         (FastAPI + Streamlit + 모바일 PWA)
   경로별 추정 통학인원 E
        │
        ▼
05_b2g_dashboard
   안전 사각지대 진단 대시보드
   (보호공백 후보·ECR 우선검토군·CCTV 상충·시설 개선 검토)
```

---

## 폴더 구조

```
safe-route-policy-assistant/
├── 00_data_collection/         # raw 공공데이터 수집·전처리
├── 01_road_risk_index/         # 차도 위험도 지수
├── 02_pedestrian_safety_index/ # 보행 안전도 지수 (케이스 A/B/C/D)
├── 03_school_commute_exposure/ # 학교문·통학경로·추정 통학인원 E
├── 04_b2c_chatbot/             # B2C 챗봇 (모바일 PWA + FastAPI + Streamlit)
├── 05_b2g_dashboard/           # B2G 진단·정책 결정 보조 대시보드 (Streamlit)
├── figures/                    # 보고서·발표 figure (PDF/PNG + 생성 스크립트)
└── README.md                   # 본 문서
```

각 stage 폴더는 자체 README와 다음 표준 구조:

```
0X_stage_name/
├── src/      # 소스 코드
├── data/     # 입력 데이터 (raw 또는 이전 stage output 사본)
├── output/   # 산출물 (다음 stage 입력)
└── README.md # stage 설명·실행법
```

---

## 실행 순서

각 stage README에 상세 실행 명령이 있다. 전체 파이프라인:

```bash
# 0. 데이터 수집·전처리 (Drive zip 압축 해제 후 일괄 재생성 시)
cd 00_data_collection && python src/lib/build_all.py

# 1. 차도 위험도
cd ../01_road_risk_index
python src/01_apply_local_downloads.py
python src/02_build_road_safety.py
python src/03_fix_crosswalk_distance.py

# 2. 보행 안전도
cd ../02_pedestrian_safety_index
python src/01_build_walking_edge_safety.py
python src/02_sensitivity_analysis.py
python src/03_create_combined_map.py

# 3. 통학 노출 E
cd ../03_school_commute_exposure
python src/gate_processor.py
python src/commuting_zone_processor.py
python src/optimal_path_processor.py
python src/commute_estimation_processor.py

# 4. B2C 챗봇 (모바일 PWA 시연)
cd ../04_b2c_chatbot
pip install -r requirements.txt
python run_mobile.py     # FastAPI(8001) + 정적 서버(8000) 자동 실행 + 브라우저 오픈
# 보조: streamlit run streamlit_app/app.py

# 5. B2G 대시보드
cd ../05_b2g_dashboard
pip install -r requirements.txt
streamlit run dashboard.py
```

> **API 키 (Gemini)**: 챗봇(04)의 자연어 nudge·위험 설명 생성에 사용한다.
> 모바일 PWA/API(`run_mobile.py`)는 키 없이도 템플릿 폴백으로 시연 가능, Streamlit은 키 필수.
> 발급: <https://aistudio.google.com/apikey>
> 설정: `04_b2c_chatbot/.streamlit/secrets.toml.example` 을 `secrets.toml` 로 복사 후 키 입력, 또는 `GOOGLE_API_KEY` 환경변수.

---

## 주요 산출물

| 산출물 | 위치 |
|---|---|
| 차도 위험도 (7,384개 엣지) | `01_road_risk_index/output/gwanak_road_safety_scores_full_remap_service_utf8.csv` |
| 보행 안전도 (10,922개 링크) | `02_pedestrian_safety_index/output/gwanak_walking_edge_safety.geojson` |
| 보행+차도 통합 지도 | `02_pedestrian_safety_index/output/road_and_walking_safety_map.html` |
| 경로별 추정 통학인원 | `03_school_commute_exposure/output/school_paths_with_students.geojson` |
| **B2C 챗봇 (메인 시연)** | `python 04_b2c_chatbot/run_mobile.py` → http://127.0.0.1:8000 |
| B2C 챗봇 (보조 검증 UI) | `streamlit run 04_b2c_chatbot/streamlit_app/app.py` |
| **B2G 대시보드** | `streamlit run 05_b2g_dashboard/dashboard.py` |
| 보고서·발표용 figure | `figures/` |

---

## 검증 지표

| 지표 | 값 | 의미 |
|---|---:|---|
| 차도 위험도 R AUC | 0.76 | 차도 위험도 R이 어린이 사고와 관련 (독립 검증) |
| 통학노출 E AUC | 0.52 | E는 사고 예측이 아닌 노출량 (의도된 결과) |
| 보호공백 후보 사고농축 lift | 3.63× | gate 후보가 실제 사고를 농축 |

---

## 환경

- Python 3.10+
- 주요 라이브러리: `geopandas`, `shapely`, `networkx`, `folium`, `streamlit`, `fastapi`, `scikit-learn`, `google-generativeai`
- 각 stage별 `requirements.txt` 참고

---

## 데이터 출처

- 교육공공데이터: 학구도안내서비스, 학교알리미 / KEDI
- 사고: TAAS 교통사고분석시스템 (도로교통공단)
- 도로망: OpenStreetMap (ODbL), 국가표준노드링크 (국가교통정보센터)
- 서울시 공공데이터: TOPIS 차량통행속도, CCTV 설치현황, 신호등·횡단보도, 과속방지턱 등 (서울 열린데이터 광장)
- 행정경계: 공공데이터포털 BND_SIGUNGU_PG

---

## 익명화 안내

본 코드베이스는 분석 대상이 `관악구`로 명시된 실증 분석이다. 보고서·발표에서는 학교명·개인명·세부 주소를 익명화 처리한다 (`○○초`, `A 자치구`).
