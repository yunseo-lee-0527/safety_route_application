"""
api/main.py — 관악 안전통학 모바일 백엔드 (FastAPI)
=================================================
core/ 의 경로 탐색·위험 설명 로직을 REST 엔드포인트로 노출한다.
Streamlit 앱(streamlit_app/app.py)과 동일한 코어를 공유하므로 로직 중복이 없다.

실행 (레포 루트에서):
    uvicorn api.main:app --reload --port 8001

엔드포인트
    GET  /api/health
    GET  /api/schools                학교 목록 (도착지 선택용)
    POST /api/route                  출발 좌표 → 경로 + 위험 요약
    POST /api/nudge                  자연어 발화 → 경로 재조정
    GET  /api/road/{edge_id}         특정 보행 구간 위험 설명 (Gemini)
    POST /api/road/nearest           좌표 → 최근접 보행 구간 위험 설명
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

# 레포 루트를 import 경로에 추가 (uvicorn 을 어디서 띄워도 core/ 를 찾도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.graph_loader import load_bundle, school_for_point
from core.nudge import NudgeState, process_utterance
from core.personas import alpha_floor_for, alpha_max_for, alpha_min_for
from core.road_risk import (
    SNAP_MAX_M, explain_edge, load_road_risk, risk_band, route_danger_segments,
)
from core.routing import find_route, compute_short_path_length

# ── 상수 (streamlit_app/app.py 와 동일 기준) ──────────────────────
R_SNAP_M = 300.0
RISK_SAFE = 0.33
RISK_HIGH = 0.66
WALK_SPEED_BY_GRADE = {1: 45, 2: 45, 3: 55, 4: 55, 5: 65, 6: 65}  # m/분

# 위험 요인 key → 프론트엔드 아이콘 (Tabler)
FACTOR_ICON = {
    "traffic": "ti-car",
    "accident": "ti-alert-triangle",
    "facility": "ti-building-community",
}

# ── LLM (Gemini) — 키 없으면 None, 그러면 템플릿 폴백 ──────────────
LLM = None


class _GeminiWrapper:
    """google-genai 신규 SDK를 기존 generate_content(prompt) 인터페이스로 래핑."""
    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def generate_content(self, prompt: str):
        return self._client.models.generate_content(model=self._model, contents=prompt)


def _init_llm():
    global LLM
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        try:
            try:
                import tomllib  # py3.11+
            except ModuleNotFoundError:
                import tomli as tomllib  # py3.10
            secrets = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
            if secrets.exists():
                api_key = tomllib.loads(secrets.read_text(encoding="utf-8")).get("GOOGLE_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        return
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        LLM = _GeminiWrapper(client, "gemini-2.5-flash")
    except Exception:
        LLM = None


# ── FastAPI ───────────────────────────────────────────────────────
app = FastAPI(title="관악 안전통학 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 데모용. 배포 시 모바일 출처로 제한.
    allow_methods=["*"],
    allow_headers=["*"],
)

_BUNDLE = None
_RRD = None


@app.on_event("startup")
def _startup():
    global _BUNDLE, _RRD
    _init_llm()
    _BUNDLE = load_bundle()       # @lru_cache — 1회 로딩 후 싱글턴
    _RRD = load_road_risk()


# ── 요청/응답 스키마 ──────────────────────────────────────────────
class RouteRequest(BaseModel):
    lat: float
    lon: float
    grade: int = Field(ge=1, le=6)
    style: str = "safe"           # "safe" → alpha max, "fast" → alpha min
    time_left_min: int = 30
    cap_override: float | None = None   # nudge 등으로 명시된 cap (없으면 시간 기반)
    destination: str | None = None      # 명시 도착 학교 (없으면 학구도 자동 결정)
    preferred_gate: str | None = None   # "정문" | "후문" — 지정 시 해당 출입문으로만 라우팅


class NudgeRequest(RouteRequest):
    text: str
    base_style: str = "safe"      # 페르소나 기본 (reset 기준)


# ── 공통 헬퍼 ─────────────────────────────────────────────────────
def _finite(o):
    """NaN/Infinity float을 None으로 (JSON 직렬화 호환). dict/list 재귀."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def _axis_from_style(style: str) -> str:
    return "max" if style == "safe" else "min"


def _cap_baseline(style: str) -> float:
    # 페르소나 기본 cap: 안전=0.50, 빠름=0.15 (app.py 온보딩과 동일)
    return 0.50 if style == "safe" else 0.15


def assess_time_vs_path(time_left_min: int, path_length_m: float, grade: int):
    """남은 시간 대비 경로 길이 → (cap, 안내문). streamlit_app/app.py 와 동일."""
    speed = WALK_SPEED_BY_GRADE.get(grade, 55)
    estimated_min = path_length_m / speed if speed else 0
    slack = (time_left_min / estimated_min) - 1.0 if estimated_min > 0 else 1.0
    if slack >= 0.50:
        return 0.50, f"약 {estimated_min:.0f}분 거리예요. {time_left_min}분 남아 여유롭게 갈 수 있어요."
    if slack >= 0.15:
        return 0.15, f"약 {estimated_min:.0f}분 거리예요."
    if slack >= 0.0:
        return 0.0, f"약 {estimated_min:.0f}분인데 {time_left_min}분 남았어요. 빠듯해요."
    return 0.0, f"약 {estimated_min:.0f}분 거리예요. 이미 늦었을 수 있어요. 안전하게 가세요."


def _mode_descriptor(alpha_axis: str, cap_eff: float, warning: bool) -> dict:
    """최종 alpha/cap → 프론트 배너용 모드. mobile decideMode 와 호환."""
    if warning or cap_eff <= 0.0:
        return {"mode": "shortest", "mode_label": "빠른 길", "icon": "ti-bolt",
                "banner_class": "banner-danger"}
    if alpha_axis == "max" and cap_eff >= 0.50:
        return {"mode": "safest", "mode_label": "안전 우선", "icon": "ti-shield",
                "banner_class": "banner-info"}
    return {"mode": "balanced", "mode_label": "균형 잡힌 길", "icon": "ti-scale",
            "banner_class": "banner-warning"}


def _school_zone_ratio(route, bundle) -> float:
    in_zone = 0.0
    for u, v, data in route.edges:
        key = (min(u, v), max(u, v))
        if bundle.edge_in_zone.get(key, False):
            in_zone += data["length_m"]
    return in_zone / route.total_length_m if route.total_length_m > 0 else 0.0


def _segment_counts(route) -> dict:
    counts = {"safe": 0, "warn": 0, "danger": 0}
    lengths = {"safe": 0.0, "warn": 0.0, "danger": 0.0}
    for _, _, data in route.edges:
        r = data["risk"]
        key = "safe" if r <= RISK_SAFE else ("warn" if r <= RISK_HIGH else "danger")
        counts[key] += 1
        lengths[key] += data["length_m"]
    return {
        "safe": counts["safe"], "warn": counts["warn"], "danger": counts["danger"],
        "total": len(route.edges),
        "safe_m": round(lengths["safe"]), "warn_m": round(lengths["warn"]),
        "danger_m": round(lengths["danger"]), "total_m": round(sum(lengths.values())),
    }


_CROSSWALK_BASES = frozenset(("case_D_crosswalk", "case_D_crossing"))


def _geometry(route) -> list[dict]:
    """경로 edge → 위험도 색이 입혀진 폴리라인 세그먼트 (Leaflet 용)."""
    segs = []
    for _, _, data in route.edges:
        coords = [(lat, lon) for lon, lat in data["geom"].coords]
        band, color = risk_band(data["risk"])
        basis = data.get("basis", "")
        is_crosswalk = basis in _CROSSWALK_BASES
        seg = {"coords": coords, "risk": round(data["risk"], 3),
               "band": band, "color": color}
        if is_crosswalk:
            seg["is_crosswalk"] = True
            mid = coords[len(coords) // 2]
            seg["crosswalk_mid"] = mid  # [lat, lon] — 마커 위치
        segs.append(seg)
    return segs


def _level_from_band(band: str) -> str:
    if band in ("위험", "매우 위험"):
        return "danger"
    if band == "주의":
        return "warn"
    return "safe"


def _generate_nudge_response(text: str, hits: list, payload: dict, llm) -> str | None:
    """사용자 발화 + 경로 데이터 → Gemini 자연어 응답 (2~3문장). 실패 시 None."""
    if llm is None:
        return None
    risky = payload.get("risky_roads", [])
    first_risky = risky[0] if risky else None
    route_summary = (
        f"거리 {payload['distance_m']}m, "
        f"예상 소요 {payload['duration_min']}분, "
        f"위험·주의 구간 {sum(1 for r in risky if r['level'] in ('danger', 'warn'))}곳"
    )
    risky_note = (
        f"가장 주의할 구간은 '{first_risky['name']}'({'위험' if first_risky['level'] == 'danger' else '주의'} 구간)."
        if first_risky else "이번 경로에는 특별히 위험한 도로 구간이 없어요."
    )
    hit_names = [h.name for h in hits] if hits else []
    alpha_axis = payload.get("alpha_axis", "max")
    cap_eff = payload.get("cap_eff", 0.5)
    mode_desc = "안전 우선 경로" if alpha_axis == "max" else "빠른 경로"
    detour_pct = round(cap_eff * 100)
    prompt = (
        "당신은 초등학생 통학로 안전 안내 챗봇입니다.\n"
        f"사용자 발화: \"{text}\"\n"
        f"적용된 조정: {', '.join(hit_names) if hit_names else '(변경 없음)'}\n"
        f"새 경로 정보: {route_summary}, {mode_desc}, 최단 대비 최대 {detour_pct}% 우회 허용\n"
        f"{risky_note}\n\n"
        "위 정보를 바탕으로 2~3문장으로 자연스럽고 따뜻하게 경로 조정 결과를 설명해주세요.\n"
        "- 첫 문장은 사용자 발화에 직접 반응 (예: '차가 많은 구간을 더 피하도록 조정했어요.')\n"
        "- 경로 수치(거리/시간)를 자연스럽게 포함\n"
        "- 위험 구간이 있으면 간단히 언급\n"
        "- 존댓말, 친근한 톤\n"
        "- 한국어 문장만 출력 (JSON·코드 없이)"
    )
    try:
        resp = llm.generate_content(prompt)
        return resp.text.strip()
    except Exception:
        return None


def _risky_roads(route, rrd, use_llm: bool) -> list[dict]:
    """경로의 위험 구간 리스트. 설명은 use_llm=False 면 템플릿(빠름)."""
    out = []
    for seg in route_danger_segments(route, rrd):
        detail = explain_edge(rrd, seg["edge_id"], LLM if use_llm else None)
        facts = detail["facts"] if detail else None
        tags = []
        if facts:
            for f in facts.get("factors", []):
                tags.append({"icon": FACTOR_ICON.get(f["key"], "ti-alert-circle"),
                             "label": f["label"]})
            if "스쿨존 구간" in facts.get("notes", []):
                tags.append({"icon": "ti-school", "label": "스쿨존"})
        # 지도에서 카드와 짝지을 대표 좌표 (해당 구간 폴리라인의 중간점)
        geom = (detail.get("geom") if detail else None) or []
        coord = list(geom[len(geom) // 2]) if geom else seg.get("mid_coord")
        out.append({
            "edge_id": seg["edge_id"],
            "level": _level_from_band(seg["band"]),
            "name": seg["title"],
            "safety_index": round(seg["risk"], 2),
            "score_pct": facts["score_pct"] if facts else int(seg["risk"] * 100),
            "length_m": seg["length_m"],
            "description": detail["text"] if detail else seg["reason"],
            "tags": tags[:3],
            "coord": coord,  # [lat, lon] | None
        })
    return out


def _gates_payload(bundle, destination: str) -> list:
    """학교의 모든 출입문 [{type, lat, lon}] — 정문/후문 위치·여부 표시용."""
    return [{"type": g["type"], "lat": g["lat"], "lon": g["lon"]}
            for g in bundle.school_gates.get(destination, [])]


def _arrival_gate_type(bundle, destination: str, route) -> str | None:
    """경로가 실제로 도착한 출입문 종류(정문/후문). 매칭 실패 시 None."""
    arrival_node = route.path[-1] if route and route.path else None
    if arrival_node is None:
        return None
    for g in bundle.school_gates.get(destination, []):
        if g["node_id"] == arrival_node:
            return g["type"]
    return None


def _build_route_payload(req: RouteRequest, bundle, rrd, *, alpha_axis: str,
                         cap_override: float | None, use_llm_for_risk: bool) -> dict:
    # 1) 출발지 스냅
    node_id, dist_m = bundle.snap_tree.nearest(req.lat, req.lon)
    if dist_m > R_SNAP_M:
        raise HTTPException(422, f"근처에 보도가 없어요 (가장 가까운 보행로까지 {dist_m:.0f}m). 다른 위치를 선택해주세요.")
    src = int(node_id)
    snapped = bundle.node_coords[src]

    # 2) 도착 학교: 명시 선택이 유효하면 우선, 없으면 학구도 자동 결정
    if req.destination and req.destination in bundle.schools:
        destination = req.destination
    else:
        destination = school_for_point(bundle, req.lat, req.lon)
    if destination is None:
        raise HTTPException(422, "이 위치의 초등학교 학구를 찾지 못했어요. 관악구 안쪽 지점을 선택하거나 도착 학교를 직접 골라주세요.")
    gates = bundle.schools.get(destination, [])
    if not gates:
        raise HTTPException(422, f"{destination}의 출입문 정보를 찾지 못했어요.")
    if req.preferred_gate:
        gate_info = bundle.school_gates.get(destination, [])
        preferred_nodes = [g["node_id"] for g in gate_info if g["type"] == req.preferred_gate]
        if preferred_nodes:
            gates = preferred_nodes

    # 3) 시간 기반 cap + alpha
    short_len = compute_short_path_length(bundle.G, src, gates)
    if short_len is None:
        raise HTTPException(422, "출발지에서 학교까지 도달 가능한 보행 경로가 없어요.")
    cap_from_time, time_msg = assess_time_vs_path(req.time_left_min, short_len, req.grade)
    cap_eff = cap_override if cap_override is not None else cap_from_time
    alpha_eff = alpha_max_for(bundle.r_ref) if alpha_axis == "max" else alpha_min_for(bundle.r_ref)
    alpha_floor = alpha_floor_for(req.grade, bundle.r_ref)

    # 4) 경로 탐색
    route = find_route(G=bundle.G, src=src, gates=gates, alpha_eff=alpha_eff,
                       cap_eff=cap_eff, alpha_floor=alpha_floor)
    if route is None:
        raise HTTPException(422, "조건에 맞는 경로를 만들지 못했어요.")

    speed = WALK_SPEED_BY_GRADE.get(req.grade, 55)
    duration_min = max(1, round(route.total_length_m / speed))
    gate_centroid = bundle.school_centroid.get(destination)

    payload = {
        "origin": {"lat": req.lat, "lon": req.lon,
                   "snapped": {"lat": snapped[0], "lon": snapped[1]},
                   "snap_gap_m": round(dist_m, 1)},
        "destination": {"name": destination,
                        "lat": gate_centroid[0] if gate_centroid else None,
                        "lon": gate_centroid[1] if gate_centroid else None,
                        "gates": _gates_payload(bundle, destination),
                        "arrival_gate": _arrival_gate_type(bundle, destination, route)},
        "distance_m": int(route.total_length_m),
        "duration_min": duration_min,
        "school_zone_ratio": round(_school_zone_ratio(route, bundle), 3),
        "segments": _segment_counts(route),
        "geometry": _geometry(route),
        "risky_roads": _risky_roads(route, rrd, use_llm_for_risk),
        "mode": _mode_descriptor(alpha_axis, cap_eff, route.warning),
        "alpha_axis": alpha_axis,
        "cap_eff": cap_eff,
        "warning": route.warning,
        "time_message": time_msg,
    }
    return _finite(payload)


# ── 엔드포인트 ────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"ok": True, "llm": LLM is not None,
            "bundle_loaded": _BUNDLE is not None}


@app.get("/api/schools")
def schools():
    return [{"name": name, "lat": ll[0], "lon": ll[1],
             "gates": _gates_payload(_BUNDLE, name)}
            for name, ll in _BUNDLE.school_centroid.items()]


@app.get("/api/schoolzones")
def schoolzones():
    """관악구 스쿨존 폴리곤 GeoJSON (모바일 지도 오버레이용)."""
    gdf = _BUNDLE.zones_gdf.explode(index_parts=False)
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    return Response(content=gdf.to_json(), media_type="application/json")


@app.get("/api/school-at")
def school_at(lat: float, lon: float):
    """좌표가 속한 초등학교 학구(도착지). 핀 이동 시 실시간 표시용. 학구 밖이면 null."""
    return {"school": school_for_point(_BUNDLE, lat, lon)}


@app.post("/api/route")
def route(req: RouteRequest):
    """출발 좌표 → 경로. 위험 설명은 빠른 템플릿(탭 시 /api/road 로 상세)."""
    alpha_axis = _axis_from_style(req.style)
    return _build_route_payload(req, _BUNDLE, _RRD, alpha_axis=alpha_axis,
                                cap_override=req.cap_override,
                                use_llm_for_risk=False)


@app.post("/api/nudge")
def nudge(req: NudgeRequest):
    """자연어 발화로 경로 재조정. 규칙 우선 + Gemini 폴백 (core.nudge)."""
    base_axis = _axis_from_style(req.base_style)
    state = NudgeState(
        alpha_axis=_axis_from_style(req.style),
        cap_eff=req.cap_override if req.cap_override is not None else _cap_baseline(req.style),
        base_alpha_axis=base_axis,
        base_cap_eff=_cap_baseline(req.base_style),
        cap_override=req.cap_override,
    )
    hits = process_utterance(req.text, LLM, state)
    payload = _build_route_payload(
        req, _BUNDLE, _RRD,
        alpha_axis=state.alpha_axis,
        cap_override=state.cap_override,   # nudge 가 cap 을 명시했으면 우선
        use_llm_for_risk=False,
    )
    ai_response = _generate_nudge_response(req.text, hits, payload, LLM)
    payload["nudge"] = {
        "messages": [h.sentence for h in hits],
        "alpha_axis": state.alpha_axis,
        "cap_eff": state.cap_eff,
        "cap_override": state.cap_override,
    }
    payload["ai_response"] = ai_response  # None이면 프론트에서 하드코딩 폴백
    return payload


@app.get("/api/road/{edge_id}")
def road(edge_id: int):
    """특정 보행 구간 상세 위험 설명 (Gemini 2~3문장)."""
    detail = explain_edge(_RRD, edge_id, LLM)
    if detail is None:
        raise HTTPException(404, "해당 구간 데이터를 찾지 못했어요.")
    return _finite(detail)


class NearestRoadRequest(BaseModel):
    lat: float
    lon: float


@app.post("/api/road/nearest")
def road_nearest(req: NearestRoadRequest):
    """좌표 → 최근접 보행 구간 위험 설명 (위험도 보기 모드 탭)."""
    eid, dist = _RRD.nearest_edge(req.lat, req.lon)
    if eid is None or dist > SNAP_MAX_M:
        raise HTTPException(404, f"근처에 분석할 도로가 없어요 (가장 가까운 도로까지 {dist:.0f}m).")
    detail = explain_edge(_RRD, eid, LLM)
    detail["snap_gap_m"] = round(dist, 1)
    return _finite(detail)
