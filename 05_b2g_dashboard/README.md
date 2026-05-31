# 05_b2g_dashboard — 안전 사각지대 진단·정책 결정 보조 대시보드 (B2G)

> 행정기관용 보호공백 후보 발굴 + ECR 우선검토군 + CCTV 상충 분석 + 시설 개선 검토 대시보드.
> Streamlit + folium 기반 4화면 구성.
>
> 전체 기획: [B2G_PLANNING.md](B2G_PLANNING.md)
> ECR 논리 상세: [ECR_SPEC.md](ECR_SPEC.md)
> 산출물 컬럼 안내: [OUTPUT_GUIDE.md](OUTPUT_GUIDE.md)

## 실행

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

## 입력

| 파일 | 위치 | 출처 |
|---|---|---|
| `data/all_links.geojson` | 보행 링크 전체 (안전도 포함) | 02 output |
| `data/candidates_full.geojson` | 보호공백 후보 (gate 통과) | 02 output 기반 사전 산출 |
| `data/b2g_metrics.json` | gate · ECR · 검증 지표 요약 | 사전 산출 |

03의 `school_paths_with_students.geojson` (경로별 E) 도 연동해 실시간 ECR 산출 가능.

## 코드 구성

```
05_b2g_dashboard/
├── dashboard.py            # Streamlit 4화면 대시보드 (메인)
├── mock_cctv.py            # CCTV 상충 mock 데이터 생성기 + 트랙 분류
├── data/                   # 입력 데이터
├── B2G_PLANNING.md         # 기획·설계 개요
├── ECR_SPEC.md             # ECR 논리 요구사항 (8개)
├── OUTPUT_GUIDE.md         # 목표 산출물 컬럼 안내
├── README.md               # 본 문서
└── requirements.txt
```

## 핵심 로직

### 기호

| 기호 | 정의 |
|---|---|
| `E(l)` | 링크 l 통학 노출 (추정 통학아동/일) |
| `R(l)` | 보행 안전 위험지수 |
| `Rbar(l)` | `2 × pct(R(l))` — 고정 정규화 위험 참고 가중치 |
| `ECR(l)` | `E(l) × Rbar(l)` — 노출가중 위험 참고지표 |

### 우선 검토군 선정

보호공백 후보 gate:
```
gate(l) = E 상위 N% (기본 20%) ∩ R 상위 M% (기본 30%) ∩ 비스쿨존
```

ECR 우선검토군:
```python
Rbar = 2 * percentile_rank(R)
ECR  = E * Rbar
N_admin = min(budget_capacity, work_capacity)
priority_group = gate_candidates.sort_values("ECR", ascending=False).head(N_admin)
```

**ECR 은 실제 사고 확률이 아니라 gate 후보 내부의 우선검토군 압축 참고지표다.**

검증 지표 (ECR과 독립):

| 지표 | 값 |
|---|---:|
| R AUC (어린이 사고 예측) | 0.76 |
| E AUC | 0.52 |
| gate 사고농축 lift | 3.63× |

### CCTV 상충 기반 위험 개요

`mock_cctv.py` 가 link_id 별 다음 컬럼을 생성한다:

- `cctv_status`: `"연동"` / `"미연동"`
- `risk_description`: 자연어 위험 개요 (미연동 시 `"CCTV 진단 후 확정"`)
- `conflict_tags_csv`: 상충 유형 태그 (CSV 문자열, 대시보드 로드 시 리스트로 파싱)
- `recommended_measures`: 맞춤 시설 대책 (JSON 리스트)
- `cctv_conflict_type_count`: 상충 유형 종류 수
- `recommended_measure_count`: 추천 대책 수
- `max_cost_eff`: 최대 cost-effectiveness 값

CMF 값은 FHWA CMF Clearinghouse 공식 CMF ID 기준 (`mock_cctv.py` 의 `CMF_TABLE` 참조).

### 트랙 A / B 분류

트랙 A/B 는 **4축 동시 상위 1/3** 조건으로 분류 (CCTV 연동 후보 전체 기준):

```python
thr_ecr      = df["ECR"].quantile(2/3)
thr_conflict = df.loc[cctv_mask, "cctv_conflict_type_count"].quantile(2/3)
thr_measure  = df.loc[cctv_mask, "recommended_measure_count"].quantile(2/3)
thr_ce       = df.loc[cctv_mask, "max_cost_eff"].quantile(2/3)

# 트랙 A: cctv_status == "연동" AND 4축 모두 상위 1/3
# 트랙 B: cctv_status == "연동" AND 4축 중 하나 이상 미충족
# 대기:   cctv_status == "미연동"
```

트랙 내 순위: `track_rank`, 표시 레이블: `track_label` (예: `"A-#1"`)

### 4화면 구성

| # | 화면 | 핵심 |
|---|---|---|
| 1 | 보호공백 후보 지도 | gate 후보 + ECR 우선검토군 강조 + E / Rbar / ECR 분해 |
| 2 | 후보별 CCTV 위험 개요 | 상충 요약 · 위험 태그 · 추천 대책 · 스쿨존 검토 플래그 |
| 3 | 행정용량 기반 시뮬레이터 | 예산 · 처리건수 → N_admin, ΔECR 참고값 |
| 4 | 정책근거 리포트 | 후보 선정 근거 + 추천 대책 + 의사결정 보조 경계 문구 |

## 표현 경계

| 허용 | 금지 |
|---|---|
| "스쿨존 지정·확대 검토 필요" | "스쿨존 지정 확정" / "자동 지정" |
| "ΔECR = 위험노출 참고지표 감소량" | "예상 사고 감소량" / "확정 위험 감소" |
| "ECR 은 우선검토군 참고지표" | "ECR 이 높은 곳 = 사고위험 확정" |
