"""
road_risk.py
============
"왜 위험한가"를 데이터로 설명하는 레이어.

- 보행 edge GeoJSON(위험 점수·케이스·matched_road_id) + 도로 위험 CSV(원인 변수)를
  matched_road_id == physical_edge_id 로 조인한다. (조인율 100% 확인)
- 클릭 좌표 → 최근접 보행 edge snap (vertex 기반 KDTree).
- 하이브리드 기여도 랭킹으로 상위 위험 요인을 뽑고, Gemini로 2~3문장 자연어화
  (실패 시 템플릿 폴백).
- 추천 경로의 위험 구간(run)을 자동 추출.

점수 0(안전)에 가까울수록 안전, 1에 가까울수록 위험.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

# ── 위험도 밴드 (지도 색·밴드 라벨·위험 카운트가 공유하는 단일 기준) ──
RISK_SAFE = 0.33
RISK_HIGH = 0.66
SNAP_MAX_M = 60.0  # 이보다 멀면 "근처 도로 없음"

# 차로 수는 실측 출처일 때만 노출 (road_class_default = 등급 기반 추정이라 숨김)
MEASURED_LANE_SOURCES = ("topis_observed", "osm_lanes")

# 기여도 정규화 스케일 (관악 분포 기준, road_risk_distributions 검증값)
#   excess = weight - 1.0 (baseline 초과분)
TRAFFIC_EXCESS_SCALE = 0.949    # road_6lane_or_traffic_weight p90 = 1.949
ACCIDENT_SCALE = 2.0            # pedestrian_accident_hybrid_weight 강한 수준
FACILITY_EXCESS_SCALE = 0.0281  # vulnerable_facility_weight p90 = 1.0281
# 산식 내 예측력(=risk_index 상관) 기반 중요도 가중
IMPORTANCE = {"traffic": 0.68, "accident": 0.22, "facility": 0.04}

ROAD_CLASS_KO = {
    "trunk": "자동차전용도로급 대로", "trunk_link": "대로 연결로",
    "primary": "주간선도로(대로)", "primary_link": "주간선 연결로",
    "secondary": "보조간선도로", "secondary_link": "보조간선 연결로",
    "tertiary": "집산도로", "tertiary_link": "집산 연결로",
    "busway": "중앙버스전용도로",
    "residential": "주택가 이면도로", "living_street": "생활도로",
    "service": "이면·서비스 도로", "unclassified": "비분류 도로",
}

# edge_safety_basis → (상황 라벨, 안전 여부)
CASE_KO = {
    "case_D_crossing": ("차도를 직접 건너는 구간", False),
    "case_D_crosswalk": ("차도를 건너는 횡단보도", False),
    "case_B_shared_road": ("차도와 바로 맞붙은 보도", False),
    "case_B_nearest_road": ("가까운 차도에 노출된 구간", False),
    "case_A_separated": ("차도와 분리된 보행로", True),
    "special_safe_facility": ("육교·교량 등 차도와 분리된 시설", True),
    "case_C_no_nearby_road": ("인근에 차도가 없는 구간", True),
}


RISK_SEVERE = 0.85  # 위험/매우위험 경계


def risk_band(score: float) -> tuple[str, str]:
    """(라벨, hex색) — 지도 색·밴드 라벨·위험 카운트가 공유하는 단일 기준.

    안전 ≤0.33(초록) · 주의 ≤0.66(노랑) · 위험 ≤0.85(주황) · 매우위험 >0.85(빨강).
    """
    if score <= RISK_SAFE:
        return "안전", "#1D9E75"
    if score <= RISK_HIGH:
        return "주의", "#FFE066"
    if score <= RISK_SEVERE:
        return "위험", "#FF9933"
    return "매우 위험", "#E63946"


@dataclass
class RoadRiskData:
    by_edge: dict                       # {walk_edge_id(int): record dict}
    edge_geom: dict                     # {walk_edge_id: [(lat,lon), ...]}
    snap_tree: cKDTree
    snap_xy_to_edge: np.ndarray         # KDTree 포인트 → walk_edge_id
    feature_collection: dict            # 위험도 색칠 레이어용 (folium GeoJson)
    _mx: float
    _my: float

    def nearest_edge(self, lat: float, lon: float) -> tuple[int | None, float]:
        q = np.array([lon * self._mx, lat * self._my])
        dist, idx = self.snap_tree.query(q, k=1)
        return int(self.snap_xy_to_edge[idx]), float(dist)


def _to_float(x, default=np.nan):
    try:
        v = float(x)
        return v if not math.isnan(v) else default
    except (TypeError, ValueError):
        return default


def _clean_str(x):
    """결측(None/nan/'nan'/공백)을 None 으로 정규화."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    return s if s and s.lower() != "nan" else None


@lru_cache(maxsize=1)
def load_road_risk(base_dir: str | None = None) -> RoadRiskData:
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent / "data"
    geo_path = base / "gwanak_walking_edge_safety.geojson"
    csv_path = base / "gwanak_road_safety_scores_full_remap_service.csv"

    road = pd.read_csv(csv_path, encoding="cp949", low_memory=False)
    road_by_id = road.set_index(road["physical_edge_id"].astype(str)).to_dict("index")

    with open(geo_path, encoding="utf-8") as fh:
        gj = json.load(fh)

    by_edge: dict = {}
    edge_geom: dict = {}
    verts_lat: list[float] = []
    verts_lon: list[float] = []
    verts_eid: list[int] = []
    fc_features: list[dict] = []

    for feat in gj["features"]:
        p = feat["properties"]
        try:
            eid = int(float(p["walk_edge_id"]))
        except (TypeError, ValueError, KeyError):
            continue
        score = _to_float(p.get("safety_score_0_1"), 0.0)
        if math.isnan(score):
            score = 0.0
        road_id = p.get("matched_road_id")
        r = road_by_id.get(str(road_id)) if road_id is not None else None

        by_edge[eid] = {
            "edge_id": eid,
            "score": float(min(max(score, 0.0), 1.0)),
            "basis": p.get("edge_safety_basis"),
            "emd": p.get("emd_nm"),
            "road_id": road_id,
            "road_name": (_clean_str(r.get("road_name")) if r else None),
            "road_class": (_clean_str(r.get("road_class")) if r else None),
            "speed": (_to_float(r.get("traffic_speed_used_kmh")) if r else np.nan),
            # 실측 출처(TOPIS/OSM)일 때만 차로 수 노출, 등급 추정값은 NaN 처리해 숨김
            "lanes": (_to_float(r.get("traffic_lanes_estimated"))
                      if (r and _clean_str(r.get("traffic_lanes_source")) in MEASURED_LANE_SOURCES)
                      else np.nan),
            "crosswalk_n": (_to_float(r.get("crosswalk_count"), 0.0) if r else 0.0),
            "signal_n": (_to_float(r.get("traffic_signal_count"), 0.0) if r else 0.0),
            "is_school_zone": (bool(_to_float(r.get("is_school_zone"), 0.0)) if r else False),
            "w_traffic": (_to_float(r.get("road_6lane_or_traffic_weight"), 1.0) if r else 1.0),
            "w_facility": (_to_float(r.get("vulnerable_facility_weight"), 1.0) if r else 1.0),
            "w_accident": (_to_float(r.get("pedestrian_accident_hybrid_weight"), 0.0) if r else 0.0),
            "child_fac": (_to_float(r.get("child_facility_count_300m"), 0.0) if r else 0.0),
            "elderly_fac": (_to_float(r.get("elderly_medical_facility_count_300m"), 0.0) if r else 0.0),
        }

        coords = feat.get("geometry", {}).get("coordinates") or []
        latlon = [(c[1], c[0]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
        edge_geom[eid] = latlon
        for lat, lon in latlon:
            verts_lat.append(lat); verts_lon.append(lon); verts_eid.append(eid)

        if len(latlon) >= 2:
            fc_features.append({
                "type": "Feature",
                "properties": {"color": risk_band(by_edge[eid]["score"])[1]},
                "geometry": {"type": "LineString",
                             "coordinates": [[lon, lat] for lat, lon in latlon]},
            })

    lat0 = math.radians(float(np.mean(verts_lat))) if verts_lat else 0.0
    mx = 111000.0 * math.cos(lat0)
    my = 111000.0
    xy = np.column_stack([np.array(verts_lon) * mx, np.array(verts_lat) * my])
    tree = cKDTree(xy)

    return RoadRiskData(
        by_edge=by_edge,
        edge_geom=edge_geom,
        snap_tree=tree,
        snap_xy_to_edge=np.array(verts_eid, dtype="int64"),
        feature_collection={"type": "FeatureCollection", "features": fc_features},
        _mx=mx, _my=my,
    )


# ── 기여도 랭킹 (하이브리드) ──────────────────────────────────────
def rank_factors(rec: dict) -> list[dict]:
    """위험 기여 상위 요인 (정규화 excess × 예측 중요도). 큰 순."""
    out = []
    tr_excess = max(rec["w_traffic"] - 1.0, 0.0)
    if tr_excess > 0:
        rc = ROAD_CLASS_KO.get(rec["road_class"], "차도")
        lanes = rec["lanes"]
        detail = rc
        if not math.isnan(lanes) and lanes >= 2:
            detail += f" {int(round(lanes))}차로"
        out.append({
            "key": "traffic", "label": "넓은 차도·교통량",
            "detail": detail,
            "weighted": min(tr_excess / TRAFFIC_EXCESS_SCALE, 1.0) * IMPORTANCE["traffic"],
        })
    if rec["w_accident"] > 0:
        out.append({
            "key": "accident", "label": "보행자 사고 이력",
            "detail": "인근에서 보행자 사고가 보고된 구간",
            "weighted": min(rec["w_accident"] / ACCIDENT_SCALE, 1.0) * IMPORTANCE["accident"],
        })
    fac_excess = max(rec["w_facility"] - 1.0, 0.0)
    if fac_excess > 0:
        n = int(rec["child_fac"] + rec["elderly_fac"])
        out.append({
            "key": "facility", "label": "어린이·노약자 시설 밀집",
            "detail": (f"반경 300m 내 보호 대상 시설 {n}곳" if n else "반경 300m 내 보호 대상 시설"),
            "weighted": min(fac_excess / FACILITY_EXCESS_SCALE, 1.0) * IMPORTANCE["facility"],
        })
    out.sort(key=lambda d: d["weighted"], reverse=True)
    return out


def context_notes(rec: dict) -> list[str]:
    """요인과 별개로 항상 보강하는 상황 단서."""
    notes = []
    label, safe = CASE_KO.get(rec["basis"], (None, None))
    if label:
        notes.append(label)
    if not safe:  # 위험 케이스에서만 보호시설 부재를 강조
        if rec["crosswalk_n"] == 0 and rec["signal_n"] == 0:
            notes.append("주변에 횡단보도·신호등 보호시설이 없음")
    if rec["is_school_zone"]:
        notes.append("스쿨존 구간")
    return notes


# 약한 요인(예: 취약시설)이 단독으로 헤드라인이 되는 걸 막는 임계
STRONG_FACTOR_MIN = 0.10


def primary_reason(rec: dict, factors: list[dict]) -> dict:
    """헤드라인 이유 1개. 강한 요인(교통·사고)이 있으면 그것, 없으면 상황(케이스)."""
    strong = [f for f in factors if f["key"] in ("traffic", "accident")
              and f["weighted"] >= STRONG_FACTOR_MIN]
    if strong:
        return {"label": strong[0]["label"], "detail": strong[0].get("detail"), "is_case": False}
    case_label, safe = CASE_KO.get(rec["basis"], (None, None))
    if case_label and not safe:
        return {"label": case_label, "detail": None, "is_case": True}
    if factors:
        return {"label": factors[0]["label"], "detail": factors[0].get("detail"), "is_case": False}
    return {"label": "주변 차도 노출", "detail": None, "is_case": True}


def build_facts(rec: dict) -> dict:
    """LLM/템플릿 공용 구조화 사실."""
    band, _ = risk_band(rec["score"])
    factors = rank_factors(rec)[:3]
    return {
        "edge_id": rec["edge_id"],
        "road_name": rec["road_name"] or "이름 없는 도로",
        "band": band,
        "score_pct": int(round(rec["score"] * 100)),
        "factors": factors,
        "primary": primary_reason(rec, factors),
        "notes": context_notes(rec),
        "speed": rec["speed"], "lanes": rec["lanes"],
        "is_safe_case": CASE_KO.get(rec["basis"], (None, False))[1],
    }


# ── 자연어 문장화 ────────────────────────────────────────────────
def template_phrase(facts: dict) -> str:
    if facts["score_pct"] <= int(RISK_SAFE * 100):
        base = "차도와 분리된 보행로로, 비교적 안전한 구간이에요."
        if facts["is_safe_case"] and facts["notes"]:
            base += f" {facts['notes'][0]}."
        return base

    prim = facts["primary"]
    # 첫 문장: 도로 상태 직접 설명
    detail = prim.get("detail") or prim["label"]
    first = f"이 구간은 **{detail}**로 보행 주의가 필요한 구간입니다."

    # 두 번째 문장: 구체적 위험 요인
    others = [f["label"] for f in facts["factors"] if f["label"] != prim["label"]]
    if others:
        second = "차량 통행량과 " + "·".join(others) + " 등의 요인이 복합적으로 작용하고 있어요."
    else:
        speed_ok = not math.isnan(facts["speed"])
        lane_ok = not math.isnan(facts["lanes"]) and facts["lanes"] >= 2
        if speed_ok or lane_ok:
            specs = []
            if lane_ok:
                specs.append(f"{int(round(facts['lanes']))}차로")
            if speed_ok:
                specs.append(f"차량 속도 약 {facts['speed']:.0f}km/h")
            second = " ".join(specs) + "의 도로라 차량 속도가 높을 수 있어요."
        else:
            second = "차도와의 거리가 가까워 통행 중 주의가 필요해요."

    # 세 번째 문장: 행동 안내 (횡단보도 여부에 따라 분기)
    is_crossing = any("건너" in n or "횡단" in n for n in facts["notes"])
    if is_crossing:
        third = "횡단 전 좌우를 충분히 확인하고 건너세요."
    elif facts["is_safe_case"] is False:
        third = "가능하면 건물 쪽으로 붙어 걷고, 차량 접근 시 멈춰 주세요."
    else:
        third = "주변 차량 흐름을 확인하며 이동하세요."

    return f"{first} {second} {third}"


_GEMINI_SYS = (
    "너는 초등학생 통학로 안전 담당자야. "
    "아래 '사실'만 근거로 이 도로 구간이 {topic} 3문장으로 설명해.\n"
    "문장 구조를 반드시 지켜:\n"
    "  1문장: 도로의 물리적 상태 직접 설명 (예: '이 도로는 보차분리가 되어 있지 않아 차량과 가까운 구간입니다.')\n"
    "  2문장: 구체적 위험 요인 (차선 수·속도·사고 이력 등 사실 기반)\n"
    "  3문장: 행동 안내 (예: '횡단 시 좌우를 충분히 살피세요.')\n"
    "규칙: 마크다운 굵게(**)는 핵심 위험 요소 단 한 곳. "
    "호칭('보호자님' 등) 금지. 사실에 없는 수치·지명 지어내기 절대 금지. "
    "한국어 문장만 출력."
)


def phrase_with_gemini(facts: dict, llm) -> str:
    """결정론적 사실 → Gemini 2~3문장. 실패 시 템플릿 폴백."""
    if llm is None:
        return template_phrase(facts)
    is_safe = facts["score_pct"] <= int(RISK_SAFE * 100)
    topic = "왜 비교적 안전한지" if is_safe else "왜 위험한지"
    fact_lines = [
        f"- 위험도: {facts['band']} ({facts['score_pct']}/100, 0=안전·100=위험)",
        f"- 도로명: {facts['road_name']}",
    ]
    if not math.isnan(facts["speed"]):
        fact_lines.append(f"- 추정 차량속도: {facts['speed']:.0f}km/h")
    if not math.isnan(facts["lanes"]) and facts["lanes"] >= 2:
        fact_lines.append(f"- 차로수: {int(round(facts['lanes']))}")
    if not is_safe:
        prim = facts["primary"]
        pd = f" ({prim['detail']})" if prim.get("detail") else ""
        fact_lines.append(f"- 핵심 이유: {prim['label']}{pd}")
        for i, f in enumerate(facts["factors"], 1):
            if f["label"] == prim["label"]:
                continue
            d = f" ({f['detail']})" if f.get("detail") else ""
            fact_lines.append(f"- 추가 요인{i}: {f['label']}{d}")
    for n in facts["notes"]:
        fact_lines.append(f"- 상황: {n}")
    prompt = _GEMINI_SYS.format(topic=topic) + "\n\n[사실]\n" + "\n".join(fact_lines) + "\n\n[설명]"
    try:
        resp = llm.generate_content(prompt)
        text = (resp.text or "").strip()
        return text if text else template_phrase(facts)
    except Exception:
        return template_phrase(facts)


def explain_edge(rrd: RoadRiskData, edge_id: int, llm=None) -> dict | None:
    rec = rrd.by_edge.get(edge_id)
    if rec is None:
        return None
    facts = build_facts(rec)
    return {"facts": facts, "text": phrase_with_gemini(facts, llm),
            "geom": rrd.edge_geom.get(edge_id, [])}


# ── 추천 경로의 위험 구간 자동 추출 ──────────────────────────────
def route_danger_segments(route, rrd: RoadRiskData,
                          threshold: float = RISK_HIGH) -> list[dict]:
    """경로 edge를 위험 run 으로 묶어 대표 구간을 반환.

    route.edges: [(u, v, data), ...]  data 에 edge_id / risk / length_m / geom.
    각 run 의 대표 edge(최고 위험)를 골라 요약 사실을 붙인다.
    """
    runs: list[list] = []
    cur: list = []
    for u, v, data in route.edges:
        if data["risk"] > threshold:
            cur.append((u, v, data))
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)

    segments = []
    for run in runs:
        rep = max(run, key=lambda e: e[2]["risk"])
        eid = int(rep[2]["edge_id"])
        rec = rrd.by_edge.get(eid)
        length = sum(e[2]["length_m"] for e in run)
        facts = build_facts(rec) if rec else None
        reason = facts["primary"]["label"] if facts else "위험 구간"
        road_name = (rec["road_name"] if rec else None)
        title = road_name or reason
        rep_coords = list(rep[2]["geom"].coords) if rep[2].get("geom") else []
        mid = rep_coords[len(rep_coords) // 2] if rep_coords else None
        segments.append({
            "edge_id": eid,
            "title": title,
            "reason": reason,
            "length_m": int(length),
            "risk": float(rep[2]["risk"]),
            "band": risk_band(rep[2]["risk"])[0],
            "mid_coord": [mid[1], mid[0]] if mid else None,  # [lat, lon]
        })
    # 위험 높은 순
    segments.sort(key=lambda s: s["risk"], reverse=True)
    return segments
