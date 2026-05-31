# 05 B2G 대시보드 — ECR 논리 SPEC

## Core Logic

```text
1차 gate 후보  = E 상위 ∩ R 상위 ∩ 현행 비스쿨존

Rbar = 2 × pct(R)               # 고정 정규화 기준 (mock_cctv.py)
ECR  = E × Rbar                  # gate 후보 내부 우선검토 참고지표

N_admin       = min(예산 가능 개소 수, 인력·기간 처리 가능 개소 수)
우선검토군     = gate 후보 중 ECR 상위 N_admin개
```

**트랙 A/B 실제 구현 (`mock_cctv.py`):**
```python
# CCTV 연동 후보 전체 기준 4축 동시 상위 1/3
thr_ecr      = df["ECR"].quantile(2/3)
thr_conflict = df.loc[cctv_mask, "cctv_conflict_type_count"].quantile(2/3)
thr_measure  = df.loc[cctv_mask, "recommended_measure_count"].quantile(2/3)
thr_ce       = df.loc[cctv_mask, "max_cost_eff"].quantile(2/3)
# Track A = 연동 AND 4축 모두 >= threshold
# Track B = 연동 AND 4축 중 하나 이상 미충족
# 대기    = 미연동
```

`pct(R)` 기준 모집단: 기본 city-wide. 자치구별 모드 시 화면과 리포트에 기준 모집단 명시.

---

## 8개 요구사항

### R1 — ECR 정의
`ECR = E × Rbar`, `Rbar = 2 × pct(R)` 고정 공식. 문서와 산출 데이터에 E·R·Rbar·ECR 정의 분리 표시. ECR 설명에 "참고지표"와 "우선검토군 압축" 표현 포함.

### R2 — 2단계 후보 로직
1차 gate는 보호 공백 후보 풀 생성. ECR은 그 후보 풀 안에서만 사용. ECR이 전체 링크의 단독 판정 점수로 쓰이지 않음.

### R3 — 행정용량 제어
```python
N_admin = min(budget_capacity, work_capacity)
priority_group = gate_candidates.sort_values("ECR", ascending=False).head(N_admin)
```
화면3에 예산 입력·처리 가능 건수 입력·실제 적용 N·ECR 상위 N개 표시.

### R4 — 위험 개요 컬럼
`mock_cctv.py`가 `link_id` 단위로 산출하는 실제 컬럼: `cctv_status`, `risk_description`, `conflict_tags_csv`, `recommended_measures`, `cctv_conflict_type_count`, `recommended_measure_count`, `max_cost_eff`. CCTV 미연동 시 `cctv_status="미연동"` + `risk_description="CCTV 진단 후 확정"`. (`conflict_summary`, `preliminary_risk_factors`, `schoolzone_review_flag` 컬럼은 현재 미구현)

### R5 — 맞춤 대책 추천
추천 대책 개수 고정 없음. 대책이 어떤 `risk_tags`에서 파생됐는지 추적 가능해야 함.

### R6 — 스쿨존 검토 플래그
우선검토군 AND (위험유형 3종 이상 OR 추천 대책 3개 이상) → `schoolzone_review_flag=True`. 라벨: "스쿨존 지정·확대 검토 필요" (금지: "자동 지정").

### R7 — 효과 시뮬레이션 경계
`Delta_ECR = ECR × effect_reduction`. 라벨: "위험노출 참고지표 감소량" (금지: "실제 사고 감소량"). 출처 없으면 정량값 비워두고 "출처 확보 필요".

### R8 — 의사결정 보조 경계
최종 결정은 현장조사·경찰 협의·주민 의견·법정 기준 검토를 거친다는 문구 포함.

---

## In Scope / Out of Scope

**In Scope:** ECR 참고지표 복원 / `Rbar = 2×pct(R)` 고정식 / 행정용량 N 제한 / CCTV 상충 기반 위험 개요·태그·대책·플래그 정의 / CCTV 미연동 시 사전 설명 분리 / 해석 한계 명시

**Out of Scope:** ECR을 실제 사고확률로 해석 / Delta ECR을 실제 사고 감소량으로 표현 / 스쿨존 자동 지정 / 추천 시설물을 법적 최종 처방으로 표현 / CCTV 없이 정밀 위험 개요 확정

---

## 필수 문구

```text
ECR은 실제 사고확률이나 확정 위험량이 아니라,
1차 gate 후보 내부에서 정책 개선 우선검토군을 압축하기 위한
노출가중 위험 참고지표이다.
```

```text
본 대시보드는 스쿨존 지정·확대와 시설개선의 의사결정을 보조하는 도구이며,
최종 결정은 현장조사, 경찰 협의, 주민 의견, 법정 기준 검토를 거쳐 이뤄진다.
```

---

## 리뷰 리스크

| 리스크 | 완화책 |
|---|---|
| ECR이 실제 위험량처럼 오해 | 모든 화면에서 E·Rbar·ECR 분해 표시 + "참고지표" 라벨 |
| 정규화 기준 변동 시 경계 후보 달라짐 | 고정 정규화식 명시 + 한계 문구 |
| 추천 대책이 임의 생성처럼 보임 | CCTV 상충 태그·대책 매핑 근거를 컬럼에 보존 |
| 스쿨존 자동화처럼 보임 | 라벨을 "지정·확대 검토"로 고정, 최종 절차 명시 |
