# 05 B2G 대시보드 — 실제 산출물 안내

> `mock_cctv.py` + `dashboard.py` 기준. 계획 대비 미구현 항목은 별도 표시.

---

## 데이터 출처와 산출 지위

| 요소 | 출처/산식 | 상태 | 해석 |
|---|---|---|---|
| 통학 노출 `E` | `school_paths_with_students.geojson` 공간조인 | 실데이터 | 추정 통학아동/일 |
| 위험 `R` | `safety_score_0_1` (보행안전지수) | 실데이터 | AUC 0.76 |
| 현행 스쿨존 `Z` | `is_sz` 컬럼 | 실데이터 | |
| `Rbar` | `2 × pct(R)` (`mock_cctv.py`) | 산출됨 | |
| `ECR` | `E × Rbar` | 산출됨 | 우선검토군 압축 참고지표 |
| CCTV 상충 분석 | mock 데이터 (`mock_cctv.py`) | mock 구현 | 실 CCTV 연동 전 단계 |

---

## `mock_cctv.py` 가 생성하는 GeoJSON 컬럼

```text
link_id, E, R, Rbar, ECR
cctv_status              ← "연동" / "미연동"
risk_description         ← 자연어 위험 개요 (미연동: "CCTV 진단 후 확정")
conflict_tags_csv        ← 쉼표 구분 상충 태그 문자열 (dashboard에서 리스트 파싱)
recommended_measures     ← JSON 리스트
cctv_conflict_type_count ← 상충 유형 종류 수
recommended_measure_count← 추천 대책 수
max_cost_eff             ← 최대 cost-effectiveness
track                    ← "A" / "B" / "대기"
track_rank               ← 트랙 내 ECR 순위 (정수)
track_label              ← e.g. "A-#1" / "B-#3" / "—"
```

> `R_percentile`, `gate_candidate`, `ecr_rank`, `schoolzone_review_flag`, `preliminary_risk_factors`, `conflict_summary` 는 **미구현**.

---

## 트랙 A/B 분류 로직 (`mock_cctv.py`)

```python
# CCTV 연동 후보 전체 분포 기준, 4축 동시 상위 1/3
thr_ecr      = df["ECR"].quantile(2/3)
thr_conflict = df.loc[cctv_mask, "cctv_conflict_type_count"].quantile(2/3)
thr_measure  = df.loc[cctv_mask, "recommended_measure_count"].quantile(2/3)
thr_ce       = df.loc[cctv_mask, "max_cost_eff"].quantile(2/3)
# Track A = 연동 AND 4축 모두 >= threshold
# Track B = 연동 AND 조건 불충족
# 대기    = 미연동
```

---

## 화면별 실제 구현 상태

### 화면 1 — 보호 공백 후보 지도

- Folium 인터랙티브 지도 표시 ✅
- gate 후보 + ECR 우선검토군 강조 ✅
- E/Rbar/ECR 분해 표시 ✅
- 파일 출력 (PNG, CSV): **미구현**

### 화면 2 — 후보별 CCTV 위험 개요

- 상충 요약·위험 태그·추천 대책 표시 ✅ (track B만)
- 후보 PDF 온디맨드 생성 (`generate_candidate_pdf()`) ✅
- 추천 시설 대책 매핑 (상충 태그 → 시설):

| CCTV 상충 태그 | 추천 대책 |
|---|---|
| 짧은 PET/TTC | 고원식 횡단보도, 속도저감시설, 노면표시 강화 |
| 우회전 미감속 | 우회전 일시정지 표지, 보행자 우선신호 |
| 횡단부 상충 | 보행신호 보강, 횡단보도 재도색, 보행섬 |
| 등교시간 반복 상충 | 시간대별 교통지도, 가변 안내표지 |
| 시야 제한 상충 | 주정차 금지구역, 가각부 정비 |

미연동 시: `"CCTV 진단 후 확정"` 라벨 표시.

### 화면 3 — 행정용량 기반 시뮬레이터

```python
N_admin        = min(floor(budget / cost), period_limit)
priority_group = candidates.sort_values("ECR").head(N_admin)
```

- 예산·처리건수 슬라이더 → N_admin → 우선검토군 테이블 ✅
- CSV 내보내기: **미구현**
- Delta ECR 계산: **미구현**

### 화면 4 — 정책근거 리포트

- 마스터 요약 PDF (`generate_master_pdf()`): 검증지표·요약 테이블·경계 문구 ✅
- 후보별 상세 PDF: 온디맨드 생성 ✅
- 후보별 CCTV 분석, 추천 대책 full 섹션: **미구현**

---

## 표현 경계

| 허용 | 금지 |
|---|---|
| "스쿨존 지정·확대 검토 필요" | "스쿨존 지정 확정" / "자동 지정" |
| "Delta ECR = 위험노출 참고지표 감소량" | "예상 사고 감소량" |
| "ECR은 우선검토군 참고지표" | "ECR이 높은 곳 = 사고위험 확정" |
