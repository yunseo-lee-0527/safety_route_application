"""
Mock CCTV 데이터 생성 — B2G 대시보드용.

- 상위 11개(N_admin) 후보에 CCTV 상충 시나리오 부여
- 나머지 135개는 cctv_status="미연동", "CCTV 진단 후 확정"
- ECR(E×Rbar) 계산, 트랙 A/B 분류 (4축 동시 상위 1/3)
- 출력: data/candidates_full.geojson
"""
import json
import math
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely.geometry import mapping

DATA_DIR = Path("../0518/output")
OUT_DIR = Path("data")
OUT_DIR.mkdir(exist_ok=True)

# ── CMF 테이블 (FHWA CMF Clearinghouse 공식 CMF ID 기준) ───────────────────
CMF_TABLE = {
    "고원식 횡단보도":        {"cmf": 0.55, "source": "FHWA CMF #136", "cost": 12_000_000},
    "속도저감시설":           {"cmf": 0.60, "source": "FHWA CMF #132", "cost": 5_000_000},
    "우회전 일시정지 표지":   {"cmf": None, "source": "직접 대응 CMF 없음", "cost": 800_000},
    "보행자 우선신호":        {"cmf": 0.95, "source": "FHWA CMF #1376", "cost": 15_000_000},
    "횡단보도 재도색":        {"cmf": 0.63, "source": "FHWA CMF #2697", "cost": 2_000_000},
    "보행섬":                 {"cmf": 0.685, "source": "FHWA CMF #8799", "cost": 25_000_000},
    "주정차 금지구역":        {"cmf": 0.80, "source": "FHWA CMF #153", "cost": 500_000},
    "시야확보 표지":          {"cmf": 1.07, "source": "FHWA CMF #65", "cost": 300_000},
    "AI 불법주정차 감지":     {"cmf": None, "source": "출처 확보 필요", "cost": None},
    "보행공간 분리시설":      {"cmf": 0.26, "source": "FHWA CMF #1333", "cost": 30_000_000},
    "방호울타리":             {"cmf": None, "source": "직접 대응 CMF 없음", "cost": 8_000_000},
}

# ── 상위 11개 CCTV 시나리오 (link_id → 시나리오) ────────────────────────────
# 상충 태그: 짧은PET/TTC, 우회전미감속, 횡단부상충, 시야제한상충, 차대보행자근접
SCENARIOS = {
    "L-0001": {
        "conflict_tags": ["짧은 PET/TTC", "우회전 미감속", "횡단부 상충"],
        "measures": ["고원식 횡단보도", "우회전 일시정지 표지", "보행자 우선신호", "횡단보도 재도색"],
        "risk_description": "통학 밀집 구간. 차량 우회전 시 보행자 근접 통과 반복, 횡단부 상충 집중.",
    },
    "L-0002": {
        "conflict_tags": ["짧은 PET/TTC", "차대보행자 근접 주행", "횡단부 상충"],
        "measures": ["고원식 횡단보도", "보행공간 분리시설", "방호울타리", "속도저감시설"],
        "risk_description": "보차분리 미흡 구간. 통학 시간대 차량 근접 주행 빈번.",
    },
    "L-0003": {
        "conflict_tags": ["횡단부 상충", "시야 제한 상충"],
        "measures": ["횡단보도 재도색", "보행섬", "시야확보 표지", "주정차 금지구역"],
        "risk_description": "불법 주정차로 인한 시야 제한. 횡단보도 진입부 상충 집중.",
    },
    "L-0004": {
        "conflict_tags": ["시야 제한 상충", "우회전 미감속"],
        "measures": ["주정차 금지구역", "시야확보 표지", "우회전 일시정지 표지", "AI 불법주정차 감지"],
        "risk_description": "교차로 인근 불법주정차로 시야 확보 불량. 우회전 미감속 반복.",
    },
    "L-0005": {
        "conflict_tags": ["짧은 PET/TTC", "우회전 미감속", "시야 제한 상충", "차대보행자 근접 주행"],
        "measures": ["고원식 횡단보도", "우회전 일시정지 표지", "보행공간 분리시설", "시야확보 표지", "속도저감시설"],
        "risk_description": "복합 위험 구간. 4개 유형 상충 동시 발생. 구역 단위 종합 개선 필요.",
    },
    "L-0006": {
        "conflict_tags": ["횡단부 상충"],
        "measures": ["횡단보도 재도색", "속도저감시설"],
        "risk_description": "횡단보도 시인성 불량. 속도 미준수.",
    },
    "L-0007": {
        "conflict_tags": ["차대보행자 근접 주행"],
        "measures": ["보행공간 분리시설", "방호울타리"],
        "risk_description": "이면도로 보차분리 없음. 차량 근접 주행.",
    },
    "L-0008": {
        "conflict_tags": ["짧은 PET/TTC", "횡단부 상충"],
        "measures": ["고원식 횡단보도", "횡단보도 재도색", "보행섬"],
        "risk_description": "통학로 교차 구간. 짧은 PET/TTC 및 횡단부 상충.",
    },
    "L-0009": {
        "conflict_tags": ["우회전 미감속", "시야 제한 상충"],
        "measures": ["우회전 일시정지 표지", "주정차 금지구역", "시야확보 표지"],
        "risk_description": "우회전 차량 감속 불량, 주정차 시야 차단.",
    },
    "L-0010": {
        "conflict_tags": ["짧은 PET/TTC"],
        "measures": ["속도저감시설", "고원식 횡단보도"],
        "risk_description": "통학 시간대 차량 속도 과다. TTC 짧음.",
    },
    "L-0011": {
        "conflict_tags": ["횡단부 상충", "차대보행자 근접 주행"],
        "measures": ["횡단보도 재도색", "보행공간 분리시설"],
        "risk_description": "좁은 이면도로 보차혼용. 횡단부 상충 및 근접 주행.",
    },
}


def build_measure_rows(link_id: str) -> list[dict]:
    scenario = SCENARIOS.get(link_id)
    if not scenario:
        return []
    rows = []
    for m in scenario["measures"]:
        info = CMF_TABLE[m]
        cmf = info["cmf"]
        cost = info["cost"]
        effect = round(1 - cmf, 2) if cmf is not None else None
        ce = round(effect / cost * 1_000_000, 4) if (effect and cost) else None
        rows.append({
            "measure": m,
            "effect_reduction": effect,
            "source": info["source"],
            "cost_만원": int(cost / 10_000) if cost else None,
            "CE": ce,
        })
    return rows


def main():
    # ── 후보 GeoJSON 로드 ────────────────────────────────────────────────────
    gdf = gpd.read_file(DATA_DIR / "candidates_ranked.geojson")
    print(f"후보 {len(gdf)}개 로드")

    # ── Rbar, ECR 계산 (gate 후보 전체 분포 기준) ────────────────────────────
    gdf["Rbar"] = (gdf["R"].rank(pct=True) * 2).round(4)
    gdf["ECR"] = (gdf["E"] * gdf["Rbar"]).round(2)

    # ── CCTV 데이터 부여 ─────────────────────────────────────────────────────
    n_admin = 11  # screen3_plan.csv 기준 예산 내 착수 가능 건수

    records = []
    for _, row in gdf.iterrows():
        lid = row["link_id"]
        is_cctv = lid in SCENARIOS

        if is_cctv:
            sc = SCENARIOS[lid]
            measures = build_measure_rows(lid)
            ce_vals = [m["CE"] for m in measures if m["CE"] is not None]
            max_ce = max(ce_vals) if ce_vals else None
            rec = {
                "link_id": lid,
                "deploy_rank": int(row["deploy_rank"]),
                "E": float(row["E"]),
                "R": float(row["R"]),
                "Rbar": float(row["Rbar"]),
                "ECR": float(row["ECR"]),
                "is_sz": int(row["is_sz"]),
                "maxspeed": row["maxspeed"] if not pd.isna(row["maxspeed"]) else None,
                "lanes": row["lanes"] if not pd.isna(row["lanes"]) else None,
                "crosswalk_count": int(row["crosswalk_count"]),
                "signal_count": int(row["signal_count"]),
                "speed_bump_count": int(row["speed_bump_count"]),
                "traffic_volume": float(row["traffic_volume"]),
                "cctv_status": "연동",
                "conflict_tags": sc["conflict_tags"],
                "cctv_conflict_type_count": len(sc["conflict_tags"]),
                "risk_description": sc["risk_description"],
                "recommended_measures": measures,
                "recommended_measure_count": len(measures),
                "max_cost_eff": max_ce,
            }
        else:
            rec = {
                "link_id": lid,
                "deploy_rank": int(row["deploy_rank"]),
                "E": float(row["E"]),
                "R": float(row["R"]),
                "Rbar": float(row["Rbar"]),
                "ECR": float(row["ECR"]),
                "is_sz": int(row["is_sz"]),
                "maxspeed": row["maxspeed"] if not pd.isna(row["maxspeed"]) else None,
                "lanes": row["lanes"] if not pd.isna(row["lanes"]) else None,
                "crosswalk_count": int(row["crosswalk_count"]),
                "signal_count": int(row["signal_count"]),
                "speed_bump_count": int(row["speed_bump_count"]),
                "traffic_volume": float(row["traffic_volume"]),
                "cctv_status": "미연동",
                "conflict_tags": [],
                "cctv_conflict_type_count": None,
                "risk_description": "CCTV 진단 후 확정",
                "recommended_measures": [],
                "recommended_measure_count": None,
                "max_cost_eff": None,
            }
        records.append(rec)

    df = pd.DataFrame(records)

    # ── 트랙 A/B 분류 (4축 동시 상위 1/3, 후보 전체 분포 기준) ─────────────
    # 축1: ECR 상위 1/3
    thr_ecr = df["ECR"].quantile(2 / 3)
    # 축2~4는 CCTV 연동 후보만 유효 — 미연동은 트랙 A 불가
    cctv_mask = df["cctv_status"] == "연동"
    thr_conflict = df.loc[cctv_mask, "cctv_conflict_type_count"].quantile(2 / 3)
    thr_measure = df.loc[cctv_mask, "recommended_measure_count"].quantile(2 / 3)
    thr_ce = df.loc[cctv_mask, "max_cost_eff"].quantile(2 / 3)

    def classify(row):
        if row["cctv_status"] != "연동":
            return "대기"  # CCTV 미연동: 트랙 미분류
        ax1 = row["ECR"] >= thr_ecr
        ax2 = row["cctv_conflict_type_count"] >= thr_conflict
        ax3 = row["recommended_measure_count"] >= thr_measure
        ax4 = (row["max_cost_eff"] is not None and
               row["max_cost_eff"] >= thr_ce)
        if ax1 and ax2 and ax3 and ax4:
            return "A"
        return "B"

    df["track"] = df.apply(classify, axis=1)

    # 트랙 내 ECR 순위
    for t in ["A", "B"]:
        mask = df["track"] == t
        df.loc[mask, "track_rank"] = (
            df.loc[mask, "ECR"].rank(ascending=False).astype(int)
        )
    df["track_rank"] = df["track_rank"].where(df["track"].isin(["A", "B"]), None)
    df["track_label"] = df.apply(
        lambda r: f"{r['track']}-#{int(r['track_rank'])}"
        if r["track"] in ("A", "B") else "—",
        axis=1,
    )

    # ── GeoJSON 직접 작성 (geopandas to_file 우회 — OGR StringList 오류 방지) ──
    gdf2 = gdf[["link_id", "geometry"]].merge(df, on="link_id")

    def _clean(v):
        """JSON 직렬화 가능한 기본 타입으로 변환."""
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        if hasattr(v, "item"):      # numpy scalar
            return v.item()
        return v

    features = []
    for _, row in gdf2.iterrows():
        # conflict_tags: list[str] → 쉼표 구분 문자열 (OGR StringList 회피)
        tags = row["conflict_tags"]
        tags_str = ",".join(tags) if isinstance(tags, list) else ""

        props = {
            "link_id": row["link_id"],
            "deploy_rank": _clean(row["deploy_rank"]),
            "E": _clean(row["E"]),
            "R": _clean(row["R"]),
            "Rbar": _clean(row["Rbar"]),
            "ECR": _clean(row["ECR"]),
            "is_sz": _clean(row["is_sz"]),
            "maxspeed": _clean(row["maxspeed"]),
            "lanes": _clean(row["lanes"]),
            "crosswalk_count": _clean(row["crosswalk_count"]),
            "signal_count": _clean(row["signal_count"]),
            "speed_bump_count": _clean(row["speed_bump_count"]),
            "traffic_volume": _clean(row["traffic_volume"]),
            "cctv_status": row["cctv_status"],
            "conflict_tags_csv": tags_str,          # 쉼표 구분 문자열
            "cctv_conflict_type_count": _clean(row["cctv_conflict_type_count"]),
            "risk_description": row["risk_description"],
            "recommended_measures": row["recommended_measures"],  # list[dict]
            "recommended_measure_count": _clean(row["recommended_measure_count"]),
            "max_cost_eff": _clean(row["max_cost_eff"]),
            "track": row["track"],
            "track_rank": _clean(row["track_rank"]),
            "track_label": row["track_label"],
        }
        features.append({
            "type": "Feature",
            "geometry": mapping(row["geometry"]),
            "properties": props,
        })

    geojson_obj = {"type": "FeatureCollection", "features": features}
    out_path = OUT_DIR / "candidates_full.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(geojson_obj, f, ensure_ascii=False)

    # ── 요약 출력 ─────────────────────────────────────────────────────────────
    track_counts = df["track"].value_counts()
    print(f"\n트랙 분류 결과 (N_admin={n_admin}):")
    print(f"  트랙 A (지정·확대 검토 권고): {track_counts.get('A', 0)}개")
    print(f"  트랙 B (시설 개선 우선 검토): {track_counts.get('B', 0)}개")
    print(f"  CCTV 미연동 (대기):           {track_counts.get('대기', 0)}개")
    print(f"\n4축 임계:")
    print(f"  축1 ECR ≥ {thr_ecr:.2f}")
    print(f"  축2 상충유형수 ≥ {thr_conflict:.1f}")
    print(f"  축3 대책수 ≥ {thr_measure:.1f}")
    print(f"  축4 max_CE ≥ {thr_ce:.4f}")
    print(f"\nsaved: {OUT_DIR / 'candidates_full.geojson'}")
    print("\n[트랙 A 후보]")
    a = df[df["track"] == "A"][["link_id", "track_label", "ECR",
                                 "cctv_conflict_type_count",
                                 "recommended_measure_count", "max_cost_eff"]]
    print(a.to_string(index=False))


if __name__ == "__main__":
    main()
