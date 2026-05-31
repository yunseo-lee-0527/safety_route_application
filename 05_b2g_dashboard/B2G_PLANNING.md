# 05 B2G 대시보드 — 기획 개요

> B2C는 아이들이 오늘 더 안전하게 걷게 하고, B2G는 교육공공데이터로 통학노출과 위험환경이 겹치는 보호 공백을 찾아 행정의 스쿨존 지정·시설개선 검토를 돕는다.

---

## 1. 두 엔진 다이어그램

```text
        교육공공데이터 (학구도, 학교현황·학생수)
                    │
                    ▼
          통학 노출 E — "아이가 실제로 어디를 얼마나 걷나"
                    │
      ┌─────────────┴─────────────┐
      ▼                           ▼
  B2C 엔진 (시민·학부모)        B2G 엔진 (지자체·경찰)
  · 안전 통학 경로 추천          ① 보호 공백 후보 gate
  · 위험경로 원인 설명           ② ECR 우선검토군 압축
                                ③ CCTV 상충 기반 위험 개요
                                ④ 맞춤 시설 추천
                                ⑤ 스쿨존 지정·확대 검토 플래그
                                ⑥ 정책근거 리포트
```

---

## 2. B2G 역할 경계

**의사결정 보조 도구. 정책 결정 도구가 아니다.**

최종 결정 절차: **현장조사 → 경찰 협의 → 주민 의견 → 법정 기준 검토 → 지자체 정책 판단**

---

## 3. 후보 발굴 로직

### 3.1 기호

| 기호 | 정의 |
|---|---|
| `E(l)` | 링크 l 통학 노출 (추정 통학아동/일) |
| `R(l)` | 보행안전 위험지수 |
| `Z(l)` | 현행 어린이보호구역 여부 |
| `Rbar(l)` | `2 × pct(R(l))` |
| `ECR(l)` | `E(l) × Rbar(l)` |

### 3.2 1차 gate

```text
gate(l) = 1
  iff pct(E(l)) >= 1 - N   (기본 N=20%)
  and pct(R(l)) >= 1 - M   (기본 M=30%)
  and Z(l) = 0
```

"아이들이 많이 다니는데 제도적 보호가 비어 있는 통학 안전 사각지대"

### 3.3 2차 ECR

```text
Rbar(l) = 2 × pct(R(l))
ECR(l)  = E(l) × Rbar(l)
```

ECR은 실제 사고확률이 아니라 gate 후보 내부에서 행정검토 우선순위를 압축하는 **노출가중 위험 참고지표**다.

### 3.4 행정용량 기반 우선검토군

```python
N_admin = min(budget_capacity, work_capacity)
priority_group = gate_candidates.sort_values("ECR", ascending=False).head(N_admin)
```

### 3.5 검증 지표

| 지표 | 값 | 해석 |
|---|---:|---|
| R AUC | 0.76 | 위험축 R이 실제 어린이사고와 연관됨 |
| E AUC | 0.52 | E는 사고예측값이 아니라 통학노출값 |
| gate 사고농축 lift | 3.63x | gate 후보 집합이 실제 사고를 기저 대비 농축 |

---

## 4. CCTV 상충 기반 위험 개요

ECR은 "어디를 먼저 볼지" 스크리닝 장치. "왜 위험한가"는 우선검토군 대상 CCTV 상충 분석 이후 확정한다.

### 4.1 link_id별 컬럼

실제 구현된 컬럼 (`mock_cctv.py` 산출):

| 컬럼 | 의미 |
|---|---|
| `cctv_status` | "연동" 또는 "미연동" |
| `conflict_tags_csv` | 상충 태그 쉼표 구분 문자열 (예: "짧은 PET/TTC,우회전 미감속") |
| `cctv_conflict_type_count` | 상충 태그 개수 |
| `measure_count` | 추천 시설 대책 수 |
| `max_cost_eff` | 시설 대책 최대 비용효과 점수 |

기획에만 있고 미구현된 컬럼 (현재 코드 없음):

| 컬럼 | 상태 |
|---|---|
| `conflict_summary` | 미구현 |
| `risk_description` | 미구현 |
| `schoolzone_review_flag` | 미구현 |
| `preliminary_risk_factors` | 미구현 |

### 4.2 스쿨존 검토 플래그 (기획 논리 — 미구현)

```text
schoolzone_review_flag = True  ← 현재 코드에 없음
  iff priority_group = True
  and (cctv_conflict_type_count >= 3 OR recommended_measure_count >= 3)
```

표현: **"스쿨존 지정·확대 검토 필요"** (금지: "자동 지정", "지정 확정")

실제 구현에서는 Track A/B 4축 분위수 방식으로 우선검토군을 선정하며, `schoolzone_review_flag` 컬럼은 산출되지 않는다. (`mock_cctv.py` Track A/B 로직 참고)

---

## 5. 효과 시뮬레이션

```text
Delta_ECR = ECR × effect_reduction
CE        = Delta_ECR / Cost
```

`effect_reduction`: 공인 CMF 또는 보수 감소율. 출처 없으면 정량값 미표기.

**Delta ECR은 실제 사고 감소량이 아니라 위험노출 참고지표 감소량이다.**

---

## 6. 4화면 구성

| # | 화면 | 핵심 |
|---|---|---|
| 1 | 보호 공백 후보 지도 | gate 후보 + ECR 우선검토군 + E/Rbar/ECR 분해 |
| 2 | 후보별 CCTV 위험 개요 | 상충 요약·risk_tags·추천 대책·스쿨존 검토 플래그 |
| 3 | 행정용량 시뮬레이터 | 예산·처리건수 → N_admin, Delta ECR |
| 4 | 정책근거 리포트 | 후보 선정 근거·추천 대책·의사결정 보조 경계 문구 |

---

## 7. 표현 경계

| 허용 | 금지 |
|---|---|
| "스쿨존 지정·확대 검토 필요" | "스쿨존 지정 확정", "자동 지정" |
| "Delta ECR = 위험노출 참고지표 감소량" | "예상 사고 감소량" |
| "ECR은 우선검토군 참고지표" | "ECR 높은 곳 = 사고위험 확정" |
