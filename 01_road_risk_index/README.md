# 01_road_risk_index — 차도 위험도 지수 산출

> 의왕시 보행안전지수 방법론을 관악구 차도망에 적용해 도로 링크별 위험도 지수를 산출한다.
> 7,384개 물리 차도 엣지 (drive + service 통합).
>
> 상세 방법론: [METHODOLOGY.md](METHODOLOGY.md)
> 의왕시 비교 참조: [REFERENCE_UIWANG.md](REFERENCE_UIWANG.md)

## 산출물 (02로 전달)

| 파일 | 의미 |
|---|---|
| `output/gwanak_road_safety_scores_full_remap_service_utf8.csv` | 7,384개 차도 엣지 위험도 (UTF-8) |
| `output/gwanak_road_safety_scores_full_remap_service.csv` | 동일 데이터 cp949 |
| `output/road_safety_full_remap_service_summary.json` | 변수 선택·가중치·분포 요약 |

핵심 컬럼:
- `local_method_risk_index` — 높을수록 위험
- `local_method_safety_index` — 높을수록 안전
- `local_method_risk_decile` — 1~10 (10이 가장 위험)
- `risk_percentile` — [0, 1] percentile rank (02 보행 안전도 산출 입력)

## 입력

`data/` 위치 (00 산출물 사본):

- OSM drive+service 도로망 (관악구)
- 횡단보도·신호등 시설물 point (`seoul_facility_points_normalized.csv`)
- TAAS 보행자 사고 ↔ 도로 링크 매핑 결과 (`gwanak_link_with_accidents.csv`)
- TOPIS 차량통행속도
- KHCM 위계 기준 통행량 추정 입력
- 어린이 시설 좌표

## 방법론 요약

| 단계 | 값 / 내용 |
|---|---|
| 도로망 | drive + service (13,599 directed → 7,384 physical) |
| 시설물 매핑 | 80 m 이내 최근접 edge (횡단보도 1,784, 신호등 1,320) |
| 후보 변수 | 6개 |
| 변수 선택 | sqrt 변환 후 Pearson |corr| ≥ 0.139485 → 5개 선택 |
| 위험도 산출 | z-score 합산 × 그룹 가중치 (road_6lane 1.981, child_facility 1.019) |

전체 산출 절차는 [METHODOLOGY.md](METHODOLOGY.md) 참고.

## 코드 구성

```
src/
├── 01_apply_local_downloads.py    # 의왕시 보행안전지수 방법론 독립 구현 (5-그룹 가중치, 참조용)
├── 02_build_road_safety.py        # 차도 위험도 지수 산출 (메인)
└── 03_fix_crosswalk_distance.py   # 횡단보도 매핑 거리 보정
```

## 실행

```bash
python src/01_apply_local_downloads.py
python src/02_build_road_safety.py
python src/03_fix_crosswalk_distance.py
```
