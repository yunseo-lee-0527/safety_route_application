"""
app.py — 관악구 안전 통학로 챗봇
"""
from __future__ import annotations
import math, os, sys
from pathlib import Path

# 레포 루트를 import 경로에 추가 (streamlit run 시 cwd가 streamlit_app/ 이어도 core/ 를 찾도록)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folium
from google import genai
import streamlit as st
from branca.element import Element
from folium.features import GeoJson, GeoJsonTooltip
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from core.graph_loader import load_bundle, school_for_point
from core.nudge import NudgeState, process_utterance
from core.personas import alpha_floor_for, alpha_max_for, alpha_min_for
from core.routing import find_route, compute_short_path_length
from core.road_risk import (
    SNAP_MAX_M, explain_edge, load_road_risk, risk_band, route_danger_segments,
)

R_SNAP_M = 100.0
RISK_HIGH = 0.66
GWANAK_CENTER = (37.4784, 126.9516)
WALK_SPEED_BY_GRADE = {1: 45, 2: 45, 3: 55, 4: 55, 5: 65, 6: 65}
def edge_color(risk):
    # 지도 경로 색 = risk_band 단일 기준 (밴드 라벨·위험 카운트와 일치)
    return risk_band(risk)[1]

def _approx_dist_m(ll1, ll2):
    lat1,lon1 = ll1; lat2,lon2 = ll2
    mid = math.radians((lat1+lat2)/2)
    dx = (lon2-lon1)*111000*math.cos(mid)
    dy = (lat2-lat1)*111000
    return math.sqrt(dx*dx+dy*dy)

st.set_page_config(page_title="관악 안전 통학로 챗봇", page_icon="🚸", layout="wide")
API_KEY = os.getenv("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY","")
if not API_KEY:
    st.error("GOOGLE_API_KEY가 설정되지 않았습니다."); st.stop()


class _GeminiWrapper:
    """google-genai 신규 SDK를 기존 generate_content(prompt) 인터페이스로 래핑."""
    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def generate_content(self, prompt: str):
        return self._client.models.generate_content(model=self._model, contents=prompt)


LLM = _GeminiWrapper(genai.Client(api_key=API_KEY), "gemini-2.5-flash")


def init_session():
    ss = st.session_state
    if "initialized" in ss:
        return
    ss.initialized = True
    ss.onboarding_step = "ask_grade"
    ss.persona_alpha_axis = None
    ss.alpha_override = None
    ss.grade = None
    ss.destination = None
    ss.origin_node = None
    ss.origin_latlon = None
    ss.origin_node_latlon = None
    ss.last_pin = None
    ss.route = None
    ss.time_left = 30
    ss.prev_time_left = 30
    ss.time_message = ""
    ss.view_mode = "origin"       # "origin"(출발지 지정) | "risk"(위험도 보기)
    ss.selected_edge = None       # 클릭/선택한 도로 설명 (explain_edge 결과)
    ss.last_risk_pin = None
    ss.nudge_state = NudgeState(alpha_axis="max", cap_eff=0.50, base_alpha_axis="max", base_cap_eff=0.50)
    ss.messages = [{"role":"assistant","content":"안녕하세요! 관악구 통학로 안전경로 챗봇이에요.\n\n아이가 몇 학년인가요?"}]


def assess_time_vs_path(time_left_min, path_length_m, grade):
    speed = WALK_SPEED_BY_GRADE.get(grade, 55)
    estimated_min = path_length_m / speed
    slack = (time_left_min / estimated_min) - 1.0 if estimated_min > 0 else 1.0
    if slack >= 0.50:
        return 0.50, f"⏰ 이 경로는 약 {estimated_min:.0f}분 거리예요. {time_left_min}분 남아서 여유로워요. 가장 안전한 길로 안내할게요."
    elif slack >= 0.15:
        return 0.15, ""
    elif slack >= 0.0:
        return 0.0, f"⏰ 이 경로 약 {estimated_min:.0f}분인데 {time_left_min}분 남았어요. 빠듯해서 가장 짧은 길로 안내할게요."
    else:
        return 0.0, f"⏰ 이 경로 약 {estimated_min:.0f}분 거리예요. 이미 늦었을 수 있어요! 안전하게 가세요."


def get_effective_alpha_axis():
    ss = st.session_state
    if ss.alpha_override is not None:
        return ss.alpha_override
    return ss.nudge_state.alpha_axis


def run_routing(bundle):
    ss = st.session_state
    if ss.origin_node is None or not ss.destination or ss.grade is None:
        return None
    gates = bundle.schools.get(ss.destination, [])
    if not gates:
        return None
    short_len = compute_short_path_length(bundle.G, ss.origin_node, gates)
    if short_len is None:
        ss.route = None
        return None
    cap_from_time, time_msg = assess_time_vs_path(ss.time_left, short_len, ss.grade)
    ss.time_message = time_msg
    cap_eff = ss.nudge_state.cap_override if ss.nudge_state.cap_override is not None else cap_from_time
    alpha_axis = get_effective_alpha_axis()
    alpha_eff = alpha_max_for(bundle.r_ref) if alpha_axis == "max" else alpha_min_for(bundle.r_ref)
    alpha_floor = alpha_floor_for(ss.grade, bundle.r_ref)
    route = find_route(G=bundle.G, src=ss.origin_node, gates=gates, alpha_eff=alpha_eff, cap_eff=cap_eff, alpha_floor=alpha_floor)
    ss.route = route
    return route


def count_risk_runs(route):
    in_run, runs = False, 0
    for _, _, data in route.edges:
        if data["risk"] > RISK_HIGH:
            if not in_run:
                runs += 1; in_run = True
        else:
            in_run = False
    return runs


def school_zone_ratio(route, bundle):
    in_zone = 0.0
    for u, v, data in route.edges:
        key = (min(u,v), max(u,v))
        if bundle.edge_in_zone.get(key, False):
            in_zone += data["length_m"]
    return in_zone / route.total_length_m if route.total_length_m > 0 else 0.0


def stats_sentence(route, bundle):
    speed = WALK_SPEED_BY_GRADE.get(st.session_state.grade, 55)
    minutes = max(1, round(route.total_length_m / speed))
    n_risk = count_risk_runs(route)
    sz = int(school_zone_ratio(route, bundle) * 100)
    return f"총 약 {route.total_length_m:.0f}m, 도보 약 {minutes}분 · 위험 구간 {n_risk}곳 · 스쿨존 {sz}%"


def get_style_message(alpha_axis):
    if alpha_axis == "max":
        return "안전한 길 위주로 안내해 드릴게요 🛡️"
    return "효율적인 경로로 안내해 드릴게요 (위험 도로는 피해요)"


def compose_response(route, bundle, hits):
    ss = st.session_state
    lines = []
    if hits:
        lines.append(hits[0].sentence)
    if route is None:
        lines.append("경로를 만들 정보가 부족해요. 출발지를 설정해주세요.")
        return "\n".join(lines)
    lines.append(stats_sentence(route, bundle))
    if ss.time_message:
        lines.append(ss.time_message); ss.time_message = ""
    if route.warning:
        lines.append("⚠️ 지금 조건으로는 충분히 안전한 길이 없어 가능한 선에서 안내해요.")
    return "\n".join(lines)


LEGEND_HTML = """
<div id="map-legend" style="position:fixed;bottom:40px;right:10px;z-index:9999;background:white;padding:10px 14px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.25);font-size:13px;line-height:1.9;min-width:130px;">
  <div onclick="(function(){var d=document.getElementById('leg-detail');d.style.display=d.style.display==='none'?'block':'none';})()" style="cursor:pointer;" title="클릭해서 설명 보기">
    <b style="font-size:13px;">경로 위험도</b> <span style="font-size:10px;color:#888;">ⓘ</span><br>
    <span style="display:inline-block;width:14px;height:14px;background:#2E7DFF;border-radius:3px;margin-right:6px;vertical-align:middle;"></span>안전<br>
    <span style="display:inline-block;width:14px;height:14px;background:#FFE066;border-radius:3px;margin-right:6px;vertical-align:middle;"></span>주의<br>
    <span style="display:inline-block;width:14px;height:14px;background:#FF9933;border-radius:3px;margin-right:6px;vertical-align:middle;"></span>위험<br>
    <span style="display:inline-block;width:14px;height:14px;background:#E63946;border-radius:3px;margin-right:6px;vertical-align:middle;"></span>매우 위험<br>
    <hr style="margin:5px 0;border-color:#eee;">
    <span style="display:inline-block;width:14px;height:14px;background:#FFE066;opacity:0.6;border-radius:3px;margin-right:6px;vertical-align:middle;border:1px solid #E0B000;"></span>스쿨존
  </div>
  <div id="leg-detail" style="display:none;margin-top:8px;border-top:1px solid #eee;padding-top:8px;font-size:11px;color:#444;max-width:200px;line-height:1.65;">
    <span style="color:#2E7DFF;font-weight:bold;">■ 안전 (0~33%)</span><br>
    &nbsp;보차 분리 인도, 스쿨존 보호 구간<br>
    <span style="color:#ccb000;font-weight:bold;">■ 주의 (33~66%)</span><br>
    &nbsp;좁은 인도 또는 차량 공존 구간<br>
    <span style="color:#FF9933;font-weight:bold;">■ 위험 (66~100%)</span><br>
    &nbsp;인도·차도 경계 불분명<br>
    <span style="color:#E63946;font-weight:bold;">■ 매우 위험</span><br>
    &nbsp;보차 혼합·위험 교차로<br>
    <span style="font-size:10px;color:#aaa;">▲ 다시 클릭해서 닫기</span>
  </div>
</div>
"""



def render_route_card(route, bundle):
    """경로 요약 카드 — 지도 위에 표시."""
    ss = st.session_state
    speed = WALK_SPEED_BY_GRADE.get(ss.grade, 55)
    minutes = max(1, round(route.total_length_m / speed))
    sz = int(school_zone_ratio(route, bundle) * 100)

    safe_len = sum(d["length_m"] for _, _, d in route.edges if d["risk"] <= 0.33)
    safe_pct = int(safe_len / route.total_length_m * 100) if route.total_length_m > 0 else 0

    if safe_pct >= 70:
        s_color, s_bg = "#1B5E20", "#E8F5E9"
    elif safe_pct >= 40:
        s_color, s_bg = "#E65100", "#FFF3E0"
    else:
        s_color, s_bg = "#B71C1C", "#FFEBEE"

    dest = ss.destination or "?"
    dist_m = int(route.total_length_m)
    warn = " ⚠️" if route.warning else ""

    card = f"""
<div style="display:flex;gap:0;border-radius:14px;overflow:hidden;
    box-shadow:0 2px 10px rgba(0,0,0,0.10);margin-bottom:10px;background:white;
    border:1px solid #EEEEEE;">
  <div style="flex:1;padding:12px 0;text-align:center;border-right:1px solid #F5F5F5;">
    <div style="font-size:22px;font-weight:900;color:#E65100;line-height:1.1;">{minutes}분</div>
    <div style="font-size:11px;color:#9E9E9E;margin-top:3px;">도보 예상</div>
  </div>
  <div style="flex:1;padding:12px 0;text-align:center;border-right:1px solid #F5F5F5;background:{s_bg};">
    <div style="font-size:22px;font-weight:900;color:{s_color};line-height:1.1;">{safe_pct}%</div>
    <div style="font-size:11px;color:#9E9E9E;margin-top:3px;">안전 구간{warn}</div>
  </div>
  <div style="flex:1;padding:12px 0;text-align:center;border-right:1px solid #F5F5F5;">
    <div style="font-size:22px;font-weight:900;color:#1565C0;line-height:1.1;">{sz}%</div>
    <div style="font-size:11px;color:#9E9E9E;margin-top:3px;">스쿨존</div>
  </div>
  <div style="flex:1.6;padding:12px 14px;text-align:left;display:flex;flex-direction:column;justify-content:center;">
    <div style="font-size:13px;font-weight:700;color:#424242;line-height:1.3;">{dest}</div>
    <div style="font-size:11px;color:#9E9E9E;margin-top:2px;">{dist_m}m</div>
  </div>
</div>"""
    st.markdown(card, unsafe_allow_html=True)


def build_map(bundle, route, rrd=None):
    ss = st.session_state
    fmap = folium.Map(location=GWANAK_CENTER, zoom_start=14, tiles="cartodbpositron")

    # 위험도 보기 모드: 보행 edge 전체를 위험도 색으로 표시 (클릭 대상이 보이도록)
    if ss.view_mode == "risk" and rrd is not None:
        GeoJson(
            rrd.feature_collection,
            style_function=lambda feat: {
                "color": feat["properties"]["color"], "weight": 3, "opacity": 0.7,
            },
        ).add_to(fmap)

    if not bundle.zones_gdf.empty:
        try:
            zones_poly = bundle.zones_gdf.explode(index_parts=False).reset_index(drop=True)
            zones_poly = zones_poly[zones_poly.geometry.geom_type.isin(["Polygon","MultiPolygon"])]
            if not zones_poly.empty:
                GeoJson(zones_poly.__geo_interface__,
                    style_function=lambda x:{"fillColor":"#FFE066","color":"#E0B000","weight":0.6,"fillOpacity":0.25},
                    tooltip=GeoJsonTooltip(fields=["school_name"],aliases=["스쿨존:"])
                ).add_to(fmap)
        except Exception:
            pass

    for name, latlon in bundle.school_centroid.items():
        is_dst = (name == ss.destination)
        folium.Marker(location=latlon, tooltip=name,
            icon=folium.Icon(color="red" if is_dst else "lightgray",
                icon="graduation-cap" if is_dst else "school", prefix="fa")
        ).add_to(fmap)

    if route is not None:
        for u, v, data in route.edges:
            coords = [(lat,lon) for lon,lat in data["geom"].coords]
            folium.PolyLine(locations=coords, color=edge_color(data["risk"]), weight=6, opacity=0.9).add_to(fmap)

        # 도로망 끝 → 학교 정문 점선 연결
        if ss.destination and route.path:
            last_node_latlon = bundle.node_coords.get(route.path[-1])
            school_gate_latlon = bundle.school_centroid.get(ss.destination)
            if last_node_latlon and school_gate_latlon:
                gap = _approx_dist_m(last_node_latlon, school_gate_latlon)
                if gap > 3:
                    folium.PolyLine(
                        locations=[last_node_latlon, school_gate_latlon],
                        color="#666666", weight=3, opacity=0.8, dash_array="8 5",
                        tooltip=f"학교 입구까지 약 {gap:.0f}m",
                    ).add_to(fmap)

    # 경로가 있으면 전체가 보이도록 자동 확대
    if route is not None and route.path:
        all_coords = []
        for u, v, data in route.edges:
            all_coords.extend([(lat, lon) for lon, lat in data["geom"].coords])
        if ss.origin_node_latlon:
            all_coords.append(ss.origin_node_latlon)
        if ss.destination:
            gate_ll = bundle.school_centroid.get(ss.destination)
            if gate_ll:
                all_coords.append(gate_ll)
        if len(all_coords) >= 2:
            lats = [c[0] for c in all_coords]
            lons = [c[1] for c in all_coords]
            fmap.fit_bounds(
                [(min(lats), min(lons)), (max(lats), max(lons))],
                padding=(40, 40),
            )

    if ss.origin_latlon is not None:
        clicked = ss.origin_latlon
        if ss.origin_node is not None and ss.origin_node_latlon is not None:
            snapped = ss.origin_node_latlon
            snap_gap = _approx_dist_m(clicked, snapped)
            if snap_gap > 10:
                folium.PolyLine(
                    locations=[clicked, snapped],
                    color="#555555", weight=2, opacity=0.55, dash_array="4 5",
                    tooltip=f"보도까지 약 {snap_gap:.0f}m",
                ).add_to(fmap)
            folium.CircleMarker(location=clicked, radius=5, color="#2E7DFF",
                fill=True, fill_color="#2E7DFF", fill_opacity=0.85, weight=2, tooltip="내 위치"
            ).add_to(fmap)
            folium.Marker(location=snapped, tooltip="출발 지점 (경로 시작)",
                icon=folium.Icon(color="green", icon="play", prefix="fa")
            ).add_to(fmap)
        else:
            folium.Marker(location=clicked, tooltip="보도 없음 — 다른 위치를 선택해주세요",
                icon=folium.Icon(color="red", icon="exclamation", prefix="fa")
            ).add_to(fmap)

    # 선택된 도로 강조 (클릭/경로 위험 구간 선택 시)
    sel = ss.selected_edge
    if sel and not sel.get("error") and sel.get("geom"):
        folium.PolyLine(
            locations=sel["geom"], color="#111111", weight=10, opacity=0.35,
        ).add_to(fmap)
        band, color = risk_band(sel["facts"]["score_pct"] / 100)
        folium.PolyLine(
            locations=sel["geom"], color=color, weight=6, opacity=1.0,
            tooltip=f"{sel['facts']['road_name']} · {band}",
        ).add_to(fmap)

    fmap.get_root().html.add_child(Element(LEGEND_HTML))
    return fmap


def handle_grade_selected(grade, bundle):
    ss = st.session_state
    ss.grade = grade
    ss.messages.append({"role":"user","content":f"{grade}학년"})
    if grade <= 3:
        ss.persona_alpha_axis = "max"
        ss.nudge_state.set_baseline("max", 0.50)
        ss.onboarding_step = "done"
        ss.messages.append({"role":"assistant","content":f"{grade}학년이군요! 등굣길 안전이 가장 중요하죠 🛡️\n안전한 길 위주로 안내해 드릴게요.\n\n📍 현재 위치가 자동 감지되거나, 지도를 직접 클릭해 출발지를 정해주세요!"})
        # 온보딩 전에 위치가 이미 감지된 경우 즉시 경로 계산
        if ss.origin_node is not None and ss.destination is not None:
            route = run_routing(bundle)
            if route:
                lines = [f"학구상 도착지는 **{ss.destination}** 이에요.", get_style_message(get_effective_alpha_axis())]
                lines.append(compose_response(route, bundle, hits=[]))
                ss.messages.append({"role": "assistant", "content": "\n".join(lines)})
    else:
        ss.onboarding_step = "ask_style"
        ss.messages.append({"role":"assistant","content":f"{grade}학년이에요! 통학을 어떻게 하고 싶으세요?"})


def handle_style_selected(style, bundle):
    ss = st.session_state
    if style == "safe":
        ss.persona_alpha_axis = "max"; ss.nudge_state.set_baseline("max",0.50)
        label,msg = "안전한 길","안전이 우선이군요! 안전한 길 위주로 안내해 드릴게요 🛡️"
    else:
        ss.persona_alpha_axis = "min"; ss.nudge_state.set_baseline("min",0.15)
        label,msg = "빠른 길","효율적으로 가시는군요! 빠른 길로 안내해 드릴게요 ⚡ (위험 도로는 피해요)"
    ss.messages.append({"role":"user","content":f"{label}이 좋아요"})
    ss.onboarding_step = "done"
    ss.messages.append({"role":"assistant","content":msg+"\n\n📍 현재 위치가 자동 감지되거나, 지도를 직접 클릭해 출발지를 정해주세요!"})
    # 온보딩 전에 위치가 이미 감지된 경우 즉시 경로 계산
    if ss.origin_node is not None and ss.destination is not None:
        route = run_routing(bundle)
        if route:
            lines = [f"학구상 도착지는 **{ss.destination}** 이에요.", get_style_message(get_effective_alpha_axis())]
            lines.append(compose_response(route, bundle, hits=[]))
            ss.messages.append({"role": "assistant", "content": "\n".join(lines)})


def render_onboarding(bundle):
    ss = st.session_state
    if ss.onboarding_step == "ask_grade":
        st.markdown("**아이 학년을 선택해주세요:**")
        cols = st.columns(6)
        for i, col in enumerate(cols, 1):
            if col.button(f"{i}학년", key=f"ob_grade_{i}", use_container_width=True):
                handle_grade_selected(i, bundle); st.rerun()
    elif ss.onboarding_step == "ask_style":
        st.markdown("**어떤 통학 스타일을 선호하세요?**")
        c1, c2 = st.columns(2)
        if c1.button("🛡️ 안전이 우선이에요", use_container_width=True, key="ob_safe"):
            handle_style_selected("safe", bundle); st.rerun()
        if c2.button("⚡ 빠른 길이 좋아요", use_container_width=True, key="ob_fast"):
            handle_style_selected("fast", bundle); st.rerun()


def apply_alpha_override(axis, bundle):
    ss = st.session_state
    ss.alpha_override = axis
    label = "안전 우선" if axis == "max" else "빠른 길"
    msg = get_style_message(axis) + " (추가 요청 적용 중)"
    ss.messages.append({"role":"user","content":f"{label}로 변경"})
    ss.messages.append({"role":"assistant","content":msg})
    if ss.origin_node and ss.destination:
        route = run_routing(bundle)
        if route:
            ss.messages.append({"role":"assistant","content":compose_response(route,bundle,hits=[])})
    st.rerun()



def render_sidebar(bundle):
    ss = st.session_state
    with st.sidebar:
        st.header("🚸 통학로 챗봇")
        if ss.onboarding_step == "done":
            st.markdown("### 📋 현재 설정")
            st.markdown(f"**학년:** {ss.grade}학년")
            alpha = ss.alpha_override or ss.persona_alpha_axis or "max"
            style_label = "🛡️ 안전 우선" if alpha == "max" else "⚡ 효율 우선"
            if ss.alpha_override:
                style_label += " (추가 요청 중)"
            st.markdown(f"**스타일:** {style_label}")
            if ss.destination:
                st.markdown(f"**도착 학교:** {ss.destination}")
            else:
                st.caption("🏫 위치 감지 시 학구에 따라 자동 결정")
            st.caption("⚠️ 학년·스타일 등 모든 설정을 초기화합니다")
            if st.button("🔄 처음부터 다시", use_container_width=True, type="secondary"):
                for k in list(ss.keys()):
                    del ss[k]
                st.rerun()
            st.divider()
            st.markdown("### ⏱️ 등교까지 남은 시간")
            new_time = st.slider("분", min_value=1, max_value=60, value=ss.time_left, step=1, format="%d분", key="time_slider")
            if new_time != ss.prev_time_left:
                ss.time_left = new_time; ss.prev_time_left = new_time
                if ss.origin_node and ss.destination:
                    route = run_routing(bundle)
                    if ss.time_message:
                        ss.messages.append({"role":"assistant","content":ss.time_message}); ss.time_message=""
                    if route:
                        ss.messages.append({"role":"assistant","content":compose_response(route,bundle,hits=[])})
                    st.rerun()
        else:
            st.caption("아래 대화창에서 학년을 선택해주세요.")


def handle_chat(user_text, bundle):
    ss = st.session_state
    ss.messages.append({"role":"user","content":user_text})
    if ss.onboarding_step != "done":
        ss.messages.append({"role":"assistant","content":"먼저 아래 버튼으로 학년을 선택해주세요!"}); return
    if ss.origin_node is None:
        ss.messages.append({"role":"assistant","content":"📍 현재 위치 감지를 허용하거나 지도를 직접 클릭해 출발지를 정해주세요."}); return
    hits = process_utterance(user_text, LLM, ss.nudge_state)
    route = run_routing(bundle)
    ss.messages.append({"role":"assistant","content":compose_response(route,bundle,hits=hits)})


def handle_pin_click(lat, lon, bundle):
    ss = st.session_state
    pin = (round(lat,6), round(lon,6))
    if pin == ss.last_pin:
        return
    ss.last_pin = pin
    ss.origin_latlon = (lat, lon)
    ss.nudge_state.reset_to_baseline()
    ss.alpha_override = None

    node_id, dist_m = bundle.snap_tree.nearest(lat, lon)
    if dist_m > R_SNAP_M:
        ss.origin_node = None
        ss.origin_node_latlon = None
        ss.messages.append({"role":"assistant","content":f"근처에 보도가 없어요 (보행 노드까지 {dist_m:.0f}m). 다른 곳을 찍어주세요."}); return

    ss.origin_node = int(node_id)
    ss.origin_node_latlon = bundle.node_coords[int(node_id)]

    matched = school_for_point(bundle, lat, lon)
    if matched is None:
        ss.destination = None
        ss.messages.append({"role":"assistant","content":"이 위치의 초등학교 학구를 찾지 못했어요. 관악구 안쪽 다른 지점을 찍어볼래요?"}); return
    ss.destination = matched

    if ss.grade is None or ss.onboarding_step != "done":
        ss.messages.append({"role":"assistant","content":f"출발지를 잡았어요. 학구상 도착지는 **{matched}** 이에요. 학년을 먼저 선택해주세요."}); return

    route = run_routing(bundle)
    lines = [f"학구상 도착지는 **{matched}** 이에요.", get_style_message(get_effective_alpha_axis())]
    if route:
        lines.append(compose_response(route, bundle, hits=[]))
    ss.messages.append({"role":"assistant","content":"\n".join(lines)})


def handle_risk_click(lat, lon, rrd):
    """위험도 보기 모드 클릭 → 최근접 보행 edge 설명 생성."""
    ss = st.session_state
    pin = (round(lat, 6), round(lon, 6))
    if pin == ss.last_risk_pin:
        return
    ss.last_risk_pin = pin
    eid, dist = rrd.nearest_edge(lat, lon)
    if eid is None or dist > SNAP_MAX_M:
        ss.selected_edge = {"error": f"근처에 분석할 도로가 없어요 (가장 가까운 도로까지 {dist:.0f}m). 다른 도로를 클릭해주세요."}
        return
    ss.selected_edge = explain_edge(rrd, eid, LLM)


def render_selected_road_card(sel):
    """클릭/선택한 도로의 분석 카드 — 위험도에 따라 색이 다른 박스로 눈에 띄게."""
    if sel.get("error"):
        st.info("📍 " + sel["error"])
        return
    f = sel["facts"]
    band = f["band"]
    head = f"**{f['road_name']}**  ·  {band} {f['score_pct']}/100"
    chips = []
    if not math.isnan(f["speed"]):
        chips.append(f"🚗 추정 {f['speed']:.0f}km/h")
    if not math.isnan(f["lanes"]) and f["lanes"] >= 2:
        chips.append(f"🛣️ {int(round(f['lanes']))}차로")
    body = head + "\n\n" + sel["text"]
    if chips:
        body += "\n\n" + "  ·  ".join(chips)
    if band in ("위험", "매우 위험"):
        st.error(body)
    elif band == "주의":
        st.warning(body)
    else:
        st.success(body)


def render_route_danger_list(rrd):
    """추천 경로의 위험 구간 자동 리스트 (지도 위, 펼쳐진 expander)."""
    ss = st.session_state
    if ss.route is None:
        return
    segs = route_danger_segments(ss.route, rrd)
    if not segs:
        return
    with st.expander(f"🚧 이 경로의 위험 구간 {len(segs)}곳 — 눌러서 이유 보기", expanded=True):
        for i, s in enumerate(segs):
            label = f"⚠️ {s['title']} · {s['band']} · {s['length_m']}m"
            if st.button(label, key=f"dseg_{i}_{s['edge_id']}", use_container_width=True):
                ss.selected_edge = explain_edge(rrd, s["edge_id"], LLM)
                st.rerun()


def main():
    bundle = load_bundle()
    rrd = load_road_risk()
    init_session()
    render_sidebar(bundle)

    st.title("🚸 관악 안전 통학로 챗봇")
    st.caption("현재 위치가 자동으로 감지돼요. 지도를 직접 클릭해 출발지를 변경할 수도 있어요.")
    ss = st.session_state

    geo = get_geolocation()
    if geo and ss.origin_latlon is None:
        handle_pin_click(geo["coords"]["latitude"], geo["coords"]["longitude"], bundle)
        st.rerun()

    col_chat, col_map = st.columns([1, 1.8])
    with col_chat:
        st.subheader("💬 대화")
        chat_box = st.container(height=310)
        with chat_box:
            for msg in ss.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
        if ss.onboarding_step != "done":
            render_onboarding(bundle)
        else:
            alpha = ss.alpha_override or ss.persona_alpha_axis or "max"
            cur = "🛡️ 안전 우선" if alpha == "max" else "⚡ 빠른 길"
            st.caption(f"경로 스타일: **{cur}** — 버튼으로 변경 (다음 위치 클릭 시 초기화)")
            qc1, qc2, qc3 = st.columns(3)
            if qc1.button("🛡️ 안전 우선", use_container_width=True, key="qs_safe"):
                apply_alpha_override("max", bundle)
            if qc2.button("⚡ 빠른 길", use_container_width=True, key="qs_fast"):
                apply_alpha_override("min", bundle)
            if qc3.button("🔄 기본", use_container_width=True, key="qs_reset"):
                ss.alpha_override = None; ss.nudge_state.reset_to_baseline()
                ss.messages.append({"role":"assistant","content":"기본 설정으로 돌아왔어요."})
                if ss.origin_node and ss.destination:
                    route = run_routing(bundle)
                    if route:
                        ss.messages.append({"role":"assistant","content":compose_response(route,bundle,hits=[])})
                st.rerun()
            if user_input := st.chat_input("예: 차가 쌩쌩 다녀서 무서워요"):
                handle_chat(user_input, bundle); st.rerun()

    with col_map:
        st.subheader("🗺️ 경로 지도")
        if ss.route is not None:
            render_route_card(ss.route, bundle)

        # 모드 토글: 출발지 지정 ↔ 위험도 보기
        mc1, mc2 = st.columns(2)
        origin_active = ss.view_mode == "origin"
        if mc1.button("📍 출발지 지정", use_container_width=True, key="mode_origin",
                      type="primary" if origin_active else "secondary"):
            if not origin_active:
                ss.view_mode = "origin"; ss.selected_edge = None; ss.last_risk_pin = None
                st.rerun()
        if mc2.button("🔍 위험도 보기", use_container_width=True, key="mode_risk",
                      type="primary" if not origin_active else "secondary"):
            if origin_active:
                ss.view_mode = "risk"; st.rerun()

        col_cap, col_btn = st.columns([0.65, 0.35])
        with col_cap:
            if ss.view_mode == "risk":
                st.caption("🔍 도로를 클릭하면 아래에 분석이 떠요. (색: 파랑=안전 → 빨강=위험)")
            elif ss.origin_latlon is None and geo is None:
                st.caption("📍 위치 감지 중... 브라우저 권한을 허용해주세요.")
            else:
                st.caption("지도를 클릭해 출발지를 변경할 수 있어요.")
        with col_btn:
            if ss.view_mode == "origin" and st.button("📍 현재 위치 재감지", use_container_width=True, key="regeo_btn"):
                ss.origin_latlon = None; ss.origin_node = None; ss.origin_node_latlon = None
                ss.last_pin = None; ss.destination = None; ss.route = None
                st.rerun()

        # ── 도로 위험 분석 (지도 위에 배치 — 클릭하면 카드가 바로 보임) ──
        st.markdown("##### 🚧 도로 위험 분석")
        if ss.selected_edge:
            render_selected_road_card(ss.selected_edge)
        render_route_danger_list(rrd)
        if ss.selected_edge is None:
            if ss.view_mode == "risk":
                st.caption("지도에서 도로를 클릭하면 여기에 분석 카드가 나타나요.")
            elif ss.route is None:
                st.caption("경로가 생기면 위험 구간을 자동으로 짚어드려요. ‘🔍 위험도 보기’로 도로를 직접 클릭해도 돼요.")

        fmap = build_map(bundle, ss.route, rrd)
        out = st_folium(fmap, height=520, width=None, returned_objects=["last_clicked"], key="main_map")
        if out and out.get("last_clicked"):
            lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
            if ss.view_mode == "risk":
                handle_risk_click(lat, lon, rrd)
            else:
                handle_pin_click(lat, lon, bundle)
            st.rerun()

if __name__ == "__main__":
    main()
