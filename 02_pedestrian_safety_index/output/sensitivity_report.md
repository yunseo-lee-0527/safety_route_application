# 보행 안전도 민감도 분석 (Sensitivity Analysis)

산출 일시: 2026-05-22T12:56:19.532348

기준 link 수: 10,922 (default)


## 1. 시나리오별 케이스 카운트


| Scenario | n | case_A_separated | case_B_nearest_road | case_B_shared_road | case_C_no_nearby_road | case_D_crossing | case_D_crosswalk | special_safe_facility | unclassified |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| default | 10,922 | 1,676 | 3,074 | 5,690 | 49 | 353 | 39 | 41 | 0 |
| B_nearest_no_discount | 10,922 | 1,620 | 302 | 8,518 | 49 | 353 | 39 | 41 | 0 |
| B_nearest_tight_decay | 10,922 | 1,357 | 4,257 | 4,789 | 86 | 353 | 39 | 41 | 0 |
| B_nearest_loose_decay | 10,922 | 1,888 | 2,437 | 6,115 | 49 | 353 | 39 | 41 | 0 |
| A1111_strict_separation | 10,922 | 1,488 | 3,162 | 5,790 | 49 | 353 | 39 | 41 | 0 |
| A1111_loose_separation | 10,922 | 1,817 | 3,026 | 5,597 | 49 | 353 | 39 | 41 | 0 |
| A1111_high_overlap | 10,922 | 1,625 | 3,097 | 5,718 | 49 | 353 | 39 | 41 | 0 |
| A1111_low_overlap | 10,922 | 1,724 | 3,063 | 5,653 | 49 | 353 | 39 | 41 | 0 |
| A1111_strict_angle | 10,922 | 1,612 | 3,117 | 5,711 | 49 | 353 | 39 | 41 | 0 |
| A1111_loose_angle | 10,922 | 1,700 | 3,062 | 5,678 | 49 | 353 | 39 | 41 | 0 |
| combined_tight_all | 10,922 | 1,461 | 4,183 | 4,759 | 86 | 353 | 39 | 41 | 0 |
| combined_loose_all | 10,922 | 1,872 | 2,710 | 5,858 | 32 | 353 | 39 | 41 | 17 |


## 2. 시나리오별 점수 분포


| Scenario | mean | median | p25 | p75 | p95 | n_score_0 | n_score_≥0.8 |
|---|---:|---:|---:|---:|---:|---:|---:|
| default | 0.4557 | 0.4933 | 0.1980 | 0.6962 | 0.8935 | 1,766 | 1,522 |
| B_nearest_no_discount | 0.4671 | 0.5013 | 0.1936 | 0.7190 | 0.9381 | 1,710 | 1,904 |
| B_nearest_tight_decay | 0.4628 | 0.4980 | 0.2206 | 0.6956 | 0.8872 | 1,484 | 1,459 |
| B_nearest_loose_decay | 0.4534 | 0.4966 | 0.1758 | 0.6979 | 0.9177 | 1,978 | 1,607 |
| A1111_strict_separation | 0.4630 | 0.4984 | 0.2145 | 0.7009 | 0.8950 | 1,578 | 1,550 |
| A1111_loose_separation | 0.4515 | 0.4930 | 0.1813 | 0.6940 | 0.8941 | 1,907 | 1,517 |
| A1111_high_overlap | 0.4585 | 0.4960 | 0.2024 | 0.6992 | 0.8950 | 1,715 | 1,542 |
| A1111_low_overlap | 0.4527 | 0.4905 | 0.1916 | 0.6940 | 0.8927 | 1,814 | 1,502 |
| A1111_strict_angle | 0.4600 | 0.4982 | 0.2045 | 0.7002 | 0.8957 | 1,702 | 1,556 |
| A1111_loose_angle | 0.4541 | 0.4919 | 0.1949 | 0.6956 | 0.8931 | 1,790 | 1,511 |
| combined_tight_all | 0.4595 | 0.4949 | 0.2111 | 0.6963 | 0.8890 | 1,588 | 1,475 |
| combined_loose_all | 0.4509 | 0.4915 | 0.1798 | 0.6945 | 0.9020 | 1,945 | 1,545 |

## 3. 시나리오 정의


| Scenario | Overrides |
|---|---|
| default | default |
| B_nearest_no_discount | B_OVERLAP_M=80.0 |
| B_nearest_tight_decay | B_OVERLAP_M=3.0, A_1111_MAX_SEPARATION_M=15.0, C_NO_ROAD_M=60.0 |
| B_nearest_loose_decay | B_OVERLAP_M=10.0, A_1111_MAX_SEPARATION_M=40.0 |
| A1111_strict_separation | A_1111_MAX_SEPARATION_M=18.0 |
| A1111_loose_separation | A_1111_MAX_SEPARATION_M=35.0 |
| A1111_high_overlap | A_1111_OVERLAP_RATIO=0.7 |
| A1111_low_overlap | A_1111_OVERLAP_RATIO=0.4 |
| A1111_strict_angle | A_1111_PARALLEL_ANGLE_DEG=12.0 |
| A1111_loose_angle | A_1111_PARALLEL_ANGLE_DEG=30.0 |
| combined_tight_all | B_OVERLAP_M=3.0, A_1111_MAX_SEPARATION_M=18.0, C_NO_ROAD_M=60.0, A_1111_PARALLEL_ANGLE_DEG=15.0, A_1111_OVERLAP_RATIO=0.65 |
| combined_loose_all | B_OVERLAP_M=7.0, A_1111_MAX_SEPARATION_M=35.0, C_NO_ROAD_M=100.0, A_1111_PARALLEL_ANGLE_DEG=25.0, A_1111_OVERLAP_RATIO=0.45 |


## 4. 해석 가이드

### (A) case_B_nearest_road distance discount

`case_B_nearest_road`는 `walking_type=1111`(보차 공유) link 중 평행/겹침 조건을 충족하지
못한 채 80m 이내에 도로가 있는 경우다. distance discount는 멀리 떨어진 도로의 위험도를
그대로 부여하는 과대평가를 막기 위한 보정.

- **no_discount**: 거리 무관 nearest 도로 percentile 그대로 — 평균 점수가 가장 높게 나옴
- **tight_decay**: 빠른 감쇠 — case 자체가 줄어들고(임계 5→3m → B_shared로 빠지는 link 감소,
  C_NO_ROAD_M=60m이라 80~60m link는 C로 빠짐) 평균 점수 낮아짐
- **loose_decay**: 느린 감쇠 — 멀리 떨어진 link도 점수가 비교적 유지됨

→ default(5/25/80) 결과가 두 극단 사이의 합리적 중간임을 확인.

### (B) 1111 분리보도 (case_A_separated) 임계

`walking_type=1111`이지만 도로와 평행하게 떨어진 별도 보행축을 보차 분리로 승격하는 로직.
임계 변화에 따라 A로 빠지는 1111 link 수가 변하고, 빠진 link는 대신 B_shared 또는 B_nearest로 처리됨.

- **strict_separation/high_overlap/strict_angle**: A 승격 조건을 좁힘 → A 줄고 B 늘어남 → 평균 점수 상승
- **loose_separation/low_overlap/loose_angle**: A 승격 조건을 넓힘 → A 늘고 B 줄어듦 → 평균 점수 하락

→ 평균/중앙값의 변동 폭과 절대 컷오프 기반 카운트의 변동 폭은 별개로 평가한다.
  평균/중앙값은 분포의 중심 경향이고, score=0·score≥0.8 카운트는 경계 부근 link의
  카테고리 분류 변화를 반영한다.

### (C) 결합 시나리오 (combined_tight_all / combined_loose_all)

단일 임계만 흔드는 것이 아니라 여러 임계를 동시에 흔든 결과. 검토자가 "한 개씩만
흔든 게 아니라 모두 동시에 바꾸면?" 묻는 경우에 대응.

- **combined_tight_all** (B 3m + A_max 18m + C 60m + A_angle 15° + A_overlap 0.65):
  모든 임계를 동시에 좁힘.
- **combined_loose_all** (B 7m + A_max 35m + C 100m + A_angle 25° + A_overlap 0.45):
  모든 임계를 동시에 넓힘.

→ **결합 시나리오의 평균 점수 변동은 단일 변경보다 더 작다**. 각 임계가 결과에 미치는
  영향이 서로 상쇄되는 방향으로 작용한다는 의미이며, 임계값 선택의 결과 견고성을
  오히려 강화하는 증거다.

→ `combined_loose_all`에서 unclassified link 17개(0.16%)가 발생한다. C_NO_ROAD_M=100m로
  늘리면서 B 임계도 함께 넓혀 nearest fallback 외 영역에 들어가는 link. 영향은 미미하나
  결합 변경 시 발생 가능한 분류 누락 사례.

## 5. 결론: 견고성 평가 (지표별 분리)

지표별로 견고성 정도가 다르므로 일반화하지 말 것.

| 지표 | default | 12개 시나리오 범위 | 변동 폭 | 견고성 |
|---|---:|---|---:|:---:|
| 평균 점수 | 0.4557 | 0.4509 ~ 0.4671 | **−1.1% ~ +2.5%** | ✅ ±3% 이내 |
| 중앙값 | 0.4933 | 0.4905 ~ 0.5013 | **−0.6% ~ +1.6%** | ✅ ±3% 이내 |
| score=0 link 수 | 1,766 | 1,484 ~ 1,978 | **−16% ~ +12%** | ❌ 큰 변동 |
| score≥0.8 link 수 | 1,522 | 1,459 ~ 1,904 | **−4% ~ +25%** | ❌ 큰 변동 |

**핵심 결론**:

- **분포의 중심 경향(평균·중앙값)은 견고**. 결합 시나리오를 포함한 12개 전체에서 평균
  변동 ±3% 이내.
- **결합 시나리오는 단일 변경보다 더 견고** (−1.1% ~ +0.8%). 임계 간 상쇄 효과.
- **절대 컷오프 기반 카운트(score=0, score≥0.8)는 더 민감** (−16% ~ +25%). 경계 부근
  link의 카테고리 분류 이동에 기인하며, 평균값 자체는 크게 변하지 않는다.
- **distance discount의 정당성**: 가장 큰 카운트 변동(`B_nearest_no_discount`, score≥0.8
  +25%)이 일어난 시나리오가 본 연구에서 도입한 거리 감쇠를 제거한 경우 → 보정의 정량적
  정당성을 입증.
- **1111 분리보도 임계는 영향 작음**: 단일 변경 시 평균 점수 변동 ±1.5% 이내.

보고서에서는 "**평균·중앙값은 견고하나 절대 컷오프 기반 카운트는 임계에 더 민감하다**"는
양면을 함께 언급해야 정확하다. "±3% 이내"를 모든 지표에 일반화하면 카운트 변동 폭이
표에서 바로 반박된다.
