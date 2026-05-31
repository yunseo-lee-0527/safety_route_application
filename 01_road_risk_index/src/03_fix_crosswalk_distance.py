"""
fix_crosswalk_distance.py
=========================
문제: case_D_crosswalk 매핑에 거리 제한이 없어서, 산 속 횡단보도 링크가
      500m~1500m 떨어진 남부순환로(trunk, 74km/h)의 위험도를 그대로 받는다.

원인: 원래 스크립트에서 crosswalk 링크 중점 → 가장 가까운 차도를 거리 제한 없이
      sjoin_nearest 로 찾기 때문에, 주변에 차도가 없는 산악 지역에서 먼 간선도로에
      매칭된다.

수정: crosswalk_midpoint_road_distance_m > CROSSWALK_MAX_M 인 case_D_crosswalk
      링크들을 case_C_no_nearby_road 로 재분류하고 score = 0.0 을 부여한다.
      (80m 기준은 다른 케이스의 no_nearby_road 판정 기준과 동일)

입력:
    ../walking_edge_safety/gwanak_walking_edge_safety_utf8.csv

출력:
    ../walking_edge_safety/gwanak_walking_edge_safety_utf8.csv  (덮어쓰기)
    ../walking_edge_safety/gwanak_walking_edge_safety.csv       (cp949)
    ../walking_edge_safety/gwanak_walking_edge_safety.geojson   (GeoJSON)
    ../walking_edge_safety/walking_edge_safety_summary.json     (통계 업데이트)
"""

from pathlib import Path
import json
import pandas as pd
import geopandas as gpd
from shapely import wkt as shapely_wkt

CROSSWALK_MAX_M = 80.0          # 횡단보도 중점 → 차도 거리 임계값

WALK_DIR = Path(__file__).resolve().parents[1] / "walking_edge_safety"
UTF8_CSV  = WALK_DIR / "gwanak_walking_edge_safety_utf8.csv"
CP949_CSV = WALK_DIR / "gwanak_walking_edge_safety.csv"
GEOJSON   = WALK_DIR / "gwanak_walking_edge_safety.geojson"
SUMMARY   = WALK_DIR / "walking_edge_safety_summary.json"


def main():
    df = pd.read_csv(UTF8_CSV)
    original_case_counts = df["edge_safety_basis"].value_counts().to_dict()

    # ── 수정 대상 ──────────────────────────────────────────────────────────
    # case_D_crosswalk이면서 crosswalk 중점 → 차도 거리가 CROSSWALK_MAX_M 초과
    is_crosswalk = df["edge_safety_basis"] == "case_D_crosswalk"
    is_far = df["crosswalk_midpoint_road_distance_m"] > CROSSWALK_MAX_M

    target_mask = is_crosswalk & is_far
    n_fixed = int(target_mask.sum())
    print(f"수정 대상: {n_fixed} 링크 "
          f"(case_D_crosswalk이면서 매칭 거리 > {CROSSWALK_MAX_M}m)")

    # 수정 전 평균 위험 점수 확인
    before_score = df.loc[target_mask, "safety_score_0_1"].mean()
    print(f"수정 전 평균 score: {before_score:.4f}")

    # ── 수정 적용 ──────────────────────────────────────────────────────────
    df.loc[target_mask, "edge_safety_basis"]    = "case_C_no_nearby_road"
    df.loc[target_mask, "safety_score_0_1"]     = 0.0
    df.loc[target_mask, "postprocess_note"]     = (
        f"crosswalk_midpoint_road_distance_m > {CROSSWALK_MAX_M}m → "
        "재분류: case_C_no_nearby_road, score=0.0"
    )

    print(f"수정 후 평균 score: {df.loc[target_mask, 'safety_score_0_1'].mean():.4f}")

    # ── 통계 요약 ──────────────────────────────────────────────────────────
    new_case_counts = df["edge_safety_basis"].value_counts().to_dict()
    score_desc = df["safety_score_0_1"]
    score_summary = {
        "mean":            round(float(score_desc.mean()), 4),
        "median":          round(float(score_desc.median()), 4),
        "p25":             round(float(score_desc.quantile(0.25)), 4),
        "p75":             round(float(score_desc.quantile(0.75)), 4),
        "p95":             round(float(score_desc.quantile(0.95)), 4),
        "n_score_0":       int((score_desc == 0.0).sum()),
        "n_score_above_0p8": int((score_desc > 0.8).sum()),
        "n_nan":           int(score_desc.isna().sum()),
    }

    print("\n=== 케이스 변화 ===")
    all_cases = sorted(set(original_case_counts) | set(new_case_counts))
    for c in all_cases:
        before = original_case_counts.get(c, 0)
        after  = new_case_counts.get(c, 0)
        diff   = after - before
        marker = f"  (변화: {diff:+d})" if diff != 0 else ""
        print(f"  {c}: {before} → {after}{marker}")

    print("\n=== 점수 분포 변화 ===")
    print(f"  평균  : {score_summary['mean']}")
    print(f"  중앙값: {score_summary['median']}")
    print(f"  score=0 링크: {score_summary['n_score_0']}")
    print(f"  score>0.8 링크: {score_summary['n_score_above_0p8']}")

    # ── 저장 ──────────────────────────────────────────────────────────────
    df.to_csv(UTF8_CSV, index=False, encoding="utf-8-sig")
    df.to_csv(CP949_CSV, index=False, encoding="cp949")
    print(f"\n저장: {UTF8_CSV}")
    print(f"저장: {CP949_CSV}")

    # GeoJSON 재생성
    df_geom = df.dropna(subset=["geometry_wkt"]).copy()
    df_geom["geometry"] = df_geom["geometry_wkt"].apply(shapely_wkt.loads)
    gdf = gpd.GeoDataFrame(df_geom.drop(columns=["geometry_wkt"]),
                           geometry="geometry", crs="EPSG:4326")
    gdf.to_file(GEOJSON, driver="GeoJSON")
    print(f"저장: {GEOJSON}")

    # summary JSON 업데이트
    if SUMMARY.exists():
        with open(SUMMARY, encoding="utf-8") as f:
            summary = json.load(f)
    else:
        summary = {}

    summary["postprocess_crosswalk_distance_fix"] = {
        "description": (
            f"case_D_crosswalk 링크 중 crosswalk 중점 → 차도 거리 "
            f"> {CROSSWALK_MAX_M}m인 {n_fixed}개를 case_C_no_nearby_road "
            f"(score=0.0)로 재분류. 산악 지역에서 거리 제한 없는 매칭으로 "
            "발생하는 남부순환로·사당대로 등 원거리 간선도로 위험도 전이 문제 수정."
        ),
        "threshold_m": CROSSWALK_MAX_M,
        "n_reclassified": n_fixed,
    }
    summary["case_counts"] = new_case_counts
    summary["score_distribution"] = score_summary

    with open(SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"저장: {SUMMARY}")


if __name__ == "__main__":
    main()
