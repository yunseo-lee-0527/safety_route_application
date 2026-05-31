"""
어린이보호구역 우선검토 분석시스템 · 관악구 시범
- 후보 지도 / 후보 상세 / 용량 시뮬레이션 / 리포트
"""
import io
import json
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

DATA = Path("data")

st.set_page_config(
    page_title="어린이보호구역 우선검토",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

:root {
  --krds-primary: #1F3D7A;
  --krds-primary-dark: #163063;
  --krds-primary-light: #E8EBF0;
  --krds-track-a: #B91C1C;
  --krds-track-a-bg: #FCE8E8;
  --krds-track-b: #C97A0E;
  --krds-track-b-bg: #FDF1DF;
  --krds-neutral: #767676;
  --krds-bg: #F5F7FA;
  --krds-border: #D6D9DC;
  --krds-text: #1A1A1A;
  --krds-text-sub: #4A4A4A;
  --krds-text-caption: #767676;
}

html, body, [class*="css"], [class*="st-"] {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif !important;
  color: var(--krds-text);
}

section[data-testid="stSidebar"] { display: none !important; }
header[data-testid="stHeader"] { display: none !important; }

.block-container {
  padding-top: 1.2rem;
  padding-bottom: 0;
  max-width: 1400px;
}

h1 { font-size: 26px !important; font-weight: 700 !important; letter-spacing: -0.5px; margin: 0 !important; }
h2 { font-size: 20px !important; font-weight: 700 !important; }
h3 { font-size: 16px !important; font-weight: 600 !important; color: var(--krds-text) !important; }

hr { margin: 0.6rem 0 !important; border-color: var(--krds-border) !important; }

.krds-header {
  background: #fff;
  border-bottom: 3px solid var(--krds-primary);
  padding: 16px 4px 14px 4px;
  margin: 0 0 4px 0;
}
.krds-header .title {
  font-size: 26px;
  font-weight: 700;
  color: var(--krds-text);
  letter-spacing: -0.5px;
  line-height: 1.2;
}
.krds-header .subtitle {
  font-size: 13px;
  color: var(--krds-text-caption);
  margin-top: 4px;
}

.krds-summary {
  background: var(--krds-bg);
  border: 1px solid var(--krds-border);
  border-radius: 2px;
  padding: 12px 18px;
  margin: 14px 0 18px 0;
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  font-size: 13px;
  align-items: center;
}
.krds-summary .item { display: flex; align-items: baseline; gap: 6px; }
.krds-summary .label { color: var(--krds-text-caption); font-size: 12px; }
.krds-summary .value { color: var(--krds-text); font-weight: 600; }

.kpi {
  background: #fff;
  border: 1px solid var(--krds-border);
  border-left: 4px solid var(--krds-neutral);
  border-radius: 2px;
  padding: 12px 14px;
  min-height: 72px;
  display: flex; flex-direction: column; justify-content: center;
}
.kpi-v { font-size: 1.7rem; font-weight: 700; line-height: 1.15; color: var(--krds-text); white-space: nowrap; }
.kpi-l { font-size: 12px; color: var(--krds-text-caption); margin-top: 4px; }
.kpi.kpi-a { border-left-color: var(--krds-track-a); }
.kpi.kpi-b { border-left-color: var(--krds-track-b); }
.kpi.kpi-primary { border-left-color: var(--krds-primary); }
.kpi.kpi-neutral { border-left-color: var(--krds-neutral); }

.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 2px;
  font-size: 11px;
  margin-right: 4px;
  margin-bottom: 3px;
  border: 1px solid var(--krds-track-a);
  color: var(--krds-track-a);
  background: var(--krds-track-a-bg);
  font-weight: 500;
}

.chip {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  border-radius: 2px;
  letter-spacing: 0.3px;
}
.chip-a { background: var(--krds-track-a); }
.chip-b { background: var(--krds-track-b); }
.chip-wait { background: var(--krds-neutral); }

.legend-row {
  display: flex; gap: 18px; flex-wrap: wrap; align-items: center;
  font-size: 12px; color: var(--krds-text-sub);
  margin: 10px 0 8px 0;
}
.legend-row .sw {
  display: inline-block; width: 22px; height: 6px;
  vertical-align: middle; margin-right: 6px;
  border: 1px solid var(--krds-border);
}

.stTabs [data-baseweb="tab-list"] {
  gap: 0 !important;
  border-bottom: 1px solid var(--krds-border);
  background: var(--krds-bg);
}
.stTabs [data-baseweb="tab"] {
  background: var(--krds-bg);
  color: var(--krds-text-sub);
  padding: 10px 28px !important;
  font-size: 15px !important;
  font-weight: 500;
  border-radius: 0 !important;
  border-right: 1px solid var(--krds-border);
  height: auto !important;
}
.stTabs [data-baseweb="tab"]:first-child {
  border-left: 1px solid var(--krds-border);
}
.stTabs [aria-selected="true"] {
  background: #fff !important;
  color: var(--krds-primary) !important;
  font-weight: 700 !important;
  border-bottom: 3px solid var(--krds-primary) !important;
  margin-bottom: -1px;
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 16px; }

[data-testid="stDataFrame"] thead tr th {
  background: var(--krds-primary-light) !important;
  color: var(--krds-primary) !important;
  font-weight: 600 !important;
  border-bottom: 2px solid var(--krds-primary) !important;
}
[data-testid="stDataFrame"] tbody tr td {
  border-bottom: 1px solid var(--krds-border);
  font-size: 13px;
}

[data-testid="stMetricLabel"] {
  font-size: 12px !important;
  color: var(--krds-text-caption) !important;
}
[data-testid="stMetricValue"] {
  font-size: 1.5rem !important;
  color: var(--krds-text) !important;
  font-weight: 700 !important;
}

.stButton button, .stDownloadButton button {
  border-radius: 2px !important;
  background: var(--krds-primary) !important;
  border: 1px solid var(--krds-primary) !important;
  font-weight: 500 !important;
}
.stButton button, .stButton button *,
.stDownloadButton button, .stDownloadButton button * {
  color: #fff !important;
}
.stButton button:hover, .stDownloadButton button:hover {
  background: var(--krds-primary-dark) !important;
  border-color: var(--krds-primary-dark) !important;
}
.stButton button:hover *, .stDownloadButton button:hover * {
  color: #fff !important;
}

.stRadio > div { gap: 4px; }
.stRadio label {
  background: #fff;
  border: 1px solid var(--krds-border);
  border-radius: 2px;
  padding: 4px 10px;
}

.krds-footer {
  border-top: 1px solid var(--krds-border);
  margin-top: 32px;
  padding: 18px 4px 24px 4px;
  font-size: 12px;
  color: var(--krds-text-caption);
  display: grid;
  grid-template-columns: 1.2fr 1.4fr 1fr;
  gap: 28px;
}
.krds-footer .col-title {
  color: var(--krds-text-sub);
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 12px;
  border-left: 3px solid var(--krds-primary);
  padding-left: 8px;
}
.krds-footer .col-body { line-height: 1.6; padding-left: 11px; }

.note { font-size: 12px; color: var(--krds-text-caption); margin: 6px 0 12px 0; }
</style>
""", unsafe_allow_html=True)

LEGAL_CHECKS = [
    "학교 출입문 통학로 300m 이내",
    "현장 보행안전 확인",
    "관할 경찰서 협의 예정",
    "주민 의견 수렴 계획",
    "도로관리청 협의",
]


# ── PDF ───────────────────────────────────────────────────────────────────────
def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
        return "Malgun"
    except Exception:
        return "Helvetica"


def _styles(font):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    return {
        "h1": ParagraphStyle("h1", fontName=font, fontSize=14, spaceAfter=6,
                             textColor=colors.HexColor("#1F3D7A")),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=11, spaceAfter=4,
                             textColor=colors.HexColor("#4A4A4A")),
        "body": ParagraphStyle("body", fontName=font, fontSize=9, spaceAfter=3),
        "cap": ParagraphStyle("cap", fontName=font, fontSize=8,
                              textColor=colors.grey, spaceAfter=6),
    }


def generate_candidate_pdf(row, track: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle)
    from reportlab.lib import colors

    font = _font()
    s = _styles(font)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    story = []
    action = "지정·확대 검토" if track == "A" else "시설 개선 검토"
    story.append(Paragraph(f"{row['link_id']} · {action}", s["h1"]))
    story.append(Paragraph(
        f"트랙 {row['track_label']}  ·  배치순위 #{int(row['deploy_rank'])}",
        s["h2"],
    ))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("ECR 분해", s["h2"]))
    ecr_data = [
        ["E", "R", "Rbar", "ECR"],
        [f"{row['E']:.2f}", f"{row['R']:.2f}", f"{row['Rbar']:.4f}",
         f"{row['ECR']:.2f}"],
    ]
    t = Table(ecr_data, colWidths=[42*mm] * 4)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EBF0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F3D7A")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D6D9DC")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t)
    story.append(Spacer(1, 4*mm))

    if row["cctv_status"] == "연동":
        story.append(Paragraph("CCTV 진단", s["h2"]))
        story.append(Paragraph(
            f"상충: {', '.join(row['conflict_tags'])}", s["body"]))
        story.append(Paragraph(row["risk_description"], s["body"]))
        story.append(Spacer(1, 3*mm))

        if row["recommended_measures"]:
            story.append(Paragraph("권고 대책", s["h2"]))
            mdata = [["대책", "1−CMF", "출처", "비용(만원)", "CE"]]
            for m in row["recommended_measures"]:
                ce_str = f"{m['CE']:.3f}" if m["CE"] else "—"
                mdata.append([
                    m["measure"],
                    str(m["effect_reduction"]) if m["effect_reduction"] else "—",
                    m["source"],
                    str(m["cost_만원"]) if m["cost_만원"] else "—",
                    ce_str,
                ])
            mt = Table(mdata, colWidths=[50*mm, 18*mm, 35*mm, 22*mm, 22*mm])
            mt.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EBF0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F3D7A")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6D9DC")),
            ]))
            story.append(mt)

    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        "최종 결정은 현장조사·관할 경찰서 협의·주민 의견·법정 기준 검토를 거칩니다.",
        s["cap"],
    ))
    doc.build(story)
    return buf.getvalue()


def generate_master_pdf(metrics, n_a, n_b, n_cctv, gate_lift) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle)
    from reportlab.lib import colors

    font = _font()
    s = _styles(font)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    story = []
    story.append(Paragraph("어린이보호구역 우선검토 분석 · 관악구", s["h1"]))
    story.append(Paragraph("기준일 2026-05-26", s["body"]))
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("요약", s["h2"]))
    kdata = [
        ["항목", "수치"],
        ["전체 도로 링크", str(metrics["n_links"])],
        ["gate 후보", str(metrics["n_candidates"])],
        ["트랙 A", str(n_a)],
        ["트랙 B", str(n_b)],
        ["CCTV 연동", str(n_cctv)],
        ["사고 집중도 (후보군/기저)", f"{gate_lift}배"],
    ]
    kt = Table(kdata, colWidths=[90*mm, 50*mm])
    kt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EBF0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F3D7A")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6D9DC")),
    ]))
    story.append(kt)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("검증", s["h2"]))
    story.append(Paragraph(
        f"우선검토군의 어린이사고 집중도 {gate_lift}배 · "
        f"R AUC {metrics['auc']['R']} · E AUC {metrics['auc']['E']}",
        s["body"],
    ))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "ECR은 참고지표이며 사고확률이 아닙니다. 트랙 분류는 시스템 권고이며, "
        "최종 지정은 현장조사·관할 경찰서 협의·법정 기준 검토를 거칩니다.",
        s["cap"],
    ))
    doc.build(story)
    return buf.getvalue()


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data
def load_candidates():
    gdf = gpd.read_file(DATA / "candidates_full.geojson")
    gdf["conflict_tags"] = gdf["conflict_tags_csv"].apply(
        lambda x: [t for t in x.split(",") if t] if isinstance(x, str) else []
    )
    gdf["recommended_measures"] = gdf["recommended_measures"].apply(
        lambda x: x if isinstance(x, list)
        else (json.loads(x) if isinstance(x, str) else [])
    )
    return gdf


@st.cache_data
def load_all_links():
    return gpd.read_file(DATA / "all_links.geojson")


@st.cache_data
def load_metrics():
    with open(DATA / "b2g_metrics.json", encoding="utf-8") as f:
        return json.load(f)


gdf = load_candidates()
metrics = load_metrics()

n_gate = metrics["n_candidates"]
n_a = int((gdf["track"] == "A").sum())
n_b = int((gdf["track"] == "B").sum())
n_cctv = int((gdf["cctv_status"] == "연동").sum())
gate_lift = metrics["auc"]["gate_lift"]

_cctv_gdf = gdf[gdf["cctv_status"] == "연동"]
THR_ECR = float(gdf["ECR"].quantile(2 / 3))
THR_CONFLICT = float(_cctv_gdf["cctv_conflict_type_count"].quantile(2 / 3))
THR_MEASURE = float(_cctv_gdf["recommended_measure_count"].quantile(2 / 3))
THR_CE = float(_cctv_gdf["max_cost_eff"].quantile(2 / 3))

TRACK_COLOR = {"A": "#B91C1C", "B": "#C97A0E", "대기": "#A8A8A8"}
TRACK_WEIGHT = {"A": 5, "B": 4, "대기": 2.5}


# ── 헤더 ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="krds-header">
  <div class="title">어린이보호구역 우선검토 분석시스템</div>
  <div class="subtitle">관악구 시범 · 기준일 2026-05-26 · 도로교통법 제12조</div>
</div>
""", unsafe_allow_html=True)

# ── 분석 개요 박스 ────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="krds-summary">
  <div class="item"><span class="label">전체 도로 링크</span><span class="value">{metrics["n_links"]:,}</span></div>
  <div class="item"><span class="label">gate N(노출 상위)</span><span class="value">{metrics["gate"]["N"]*100:.0f}%</span></div>
  <div class="item"><span class="label">gate M(위험 상위)</span><span class="value">{metrics["gate"]["M"]*100:.0f}%</span></div>
  <div class="item"><span class="label">R AUC</span><span class="value">{metrics["auc"]["R"]}</span></div>
  <div class="item"><span class="label">E AUC</span><span class="value">{metrics["auc"]["E"]}</span></div>
  <div class="item"><span class="label">후보군 사고 집중도</span><span class="value">{gate_lift}배</span></div>
  <div class="item"><span class="label">트랙 A 임계값(상위 1/3)</span><span class="value">ECR≥{THR_ECR:.1f} · 상충≥{THR_CONFLICT:.0f} · 대책≥{THR_MEASURE:.0f} · CE≥{THR_CE:.3f}</span></div>
</div>
""", unsafe_allow_html=True)


# ── 탭 ────────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "후보 지도",
    "후보 상세",
    "용량 시뮬레이션",
    "리포트",
])


# ════════════════════════════════════════════════════════════════════════════
# 후보 지도
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    c = st.columns(5)
    for col, num, label, klass in [
        (c[0], n_gate, "gate 후보", "kpi-primary"),
        (c[1], n_a, "트랙 A · 지정·확대 검토", "kpi-a"),
        (c[2], n_b, "트랙 B · 시설 개선 검토", "kpi-b"),
        (c[3], n_cctv, "CCTV 연동", "kpi-primary"),
        (c[4], f"{gate_lift}배", "후보군 사고 집중도", "kpi-neutral"),
    ]:
        col.markdown(
            f'<div class="kpi {klass}"><div class="kpi-v">{num}</div>'
            f'<div class="kpi-l">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="legend-row">'
        '<span><span class="sw" style="background:#DCDCDC"></span>비-gate 도로</span>'
        '<span><span class="sw" style="background:#A8A8A8"></span>대기</span>'
        '<span><span class="sw" style="background:#C97A0E"></span>트랙 B · 시설 개선</span>'
        '<span><span class="sw" style="background:#B91C1C"></span>트랙 A · 지정·확대</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    m = folium.Map(location=[37.478, 126.952], zoom_start=14,
                   tiles="CartoDB positron", prefer_canvas=True)

    folium.GeoJson(
        load_all_links().__geo_interface__,
        style_function=lambda _: {"color": "#DCDCDC", "weight": 1, "opacity": 0.6},
        interactive=False,
    ).add_to(m)

    for _, row in gdf.iterrows():
        track = row["track"]
        color = TRACK_COLOR.get(track, "#A8A8A8")
        weight = TRACK_WEIGHT.get(track, 2.5)
        tags_str = ", ".join(row["conflict_tags"]) if row["conflict_tags"] else "—"

        if row["recommended_measures"]:
            mrows = ""
            for mv in row["recommended_measures"]:
                ce_str = f"{mv['CE']:.3f}" if mv["CE"] else "—"
                eff_str = str(mv["effect_reduction"]) if mv["effect_reduction"] else "—"
                mrows += (f"<tr><td>{mv['measure']}</td>"
                          f"<td>{eff_str}</td><td>{ce_str}</td></tr>")
            measures_html = (
                "<div style='margin-top:6px'><b>대책</b></div>"
                "<table style='font-size:11px;border-collapse:collapse;width:100%'>"
                "<tr style='background:#E8EBF0;color:#1F3D7A'>"
                "<th>대책</th><th>1−CMF</th><th>CE</th></tr>"
                + mrows + "</table>"
            )
        else:
            measures_html = ""

        track_chip = (
            "<span style='background:#B91C1C;color:#fff;padding:1px 6px;"
            "border-radius:2px;font-size:11px;font-weight:600'>A</span>"
            if track == "A"
            else "<span style='background:#C97A0E;color:#fff;padding:1px 6px;"
                 "border-radius:2px;font-size:11px;font-weight:600'>B</span>"
            if track == "B"
            else "<span style='background:#A8A8A8;color:#fff;padding:1px 6px;"
                 "border-radius:2px;font-size:11px;font-weight:600'>대기</span>"
        )

        popup_html = (
            f"<div style='min-width:260px;font-family:Pretendard,sans-serif;font-size:12px'>"
            f"<b style='font-size:13px;color:#1A1A1A'>{row['link_id']}</b> {track_chip}"
            f"<div style='color:#767676;font-size:11px;margin-top:2px'>"
            f"{row['track_label']} · 배치 #{int(row['deploy_rank'])}</div>"
            f"<hr style='border-color:#D6D9DC'>"
            f"<table style='border-collapse:collapse;width:100%;font-size:11px'>"
            f"<tr><td>E</td><td align='right'>{row['E']:.2f}</td>"
            f"<td>R</td><td align='right'>{row['R']:.2f}</td></tr>"
            f"<tr><td>Rbar</td><td align='right'>{row['Rbar']:.4f}</td>"
            f"<td><b>ECR</b></td><td align='right'><b>{row['ECR']:.2f}</b></td></tr>"
            f"</table>"
            f"<hr style='border-color:#D6D9DC'>"
            f"<div style='font-size:11px'>"
            f"<b>CCTV</b> {row['cctv_status']}<br>"
            f"<b>상충</b> {tags_str}<br>"
            f"<b>진단</b> {row['risk_description']}"
            f"</div>"
            + measures_html
            + "</div>"
        )

        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=color, w=weight: {
                "color": c, "weight": w, "opacity": 0.9
            },
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"{row['link_id']} · {row['track_label']} · ECR {row['ECR']:.1f}",
        ).add_to(m)

    st_folium(m, width="100%", height=620, returned_objects=[])


# ════════════════════════════════════════════════════════════════════════════
# 후보 상세
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    left, right = st.columns([1, 2])

    with left:
        f = st.radio(
            "필터",
            ["전체", "A", "B", "CCTV 미연동"],
            horizontal=True,
            label_visibility="collapsed",
        )
        view = {
            "A": gdf[gdf["track"] == "A"],
            "B": gdf[gdf["track"] == "B"],
            "CCTV 미연동": gdf[gdf["cctv_status"] == "미연동"],
        }.get(f, gdf)

        df_view = view[[
            "link_id", "track_label", "ECR", "cctv_status",
            "cctv_conflict_type_count", "recommended_measure_count",
        ]].copy()
        df_view.columns = ["링크", "트랙", "ECR", "CCTV", "상충", "대책"]
        df_view = df_view.reset_index(drop=True)

        sel = st.dataframe(
            df_view,
            use_container_width=True,
            height=540,
            on_select="rerun",
            selection_mode="single-row",
            hide_index=True,
        )

    with right:
        rows = sel.get("selection", {}).get("rows", [])
        if not rows:
            st.info("좌측 표에서 후보를 선택하세요.")
        else:
            row = view.iloc[rows[0]]
            track = row["track"]

            chip_class = ("chip-a" if track == "A"
                          else "chip-b" if track == "B" else "chip-wait")
            head_label = ("A · 지정·확대 검토" if track == "A"
                          else "B · 시설 개선 검토" if track == "B"
                          else "대기 · CCTV 미연동")
            st.markdown(
                f"<div style='display:flex;align-items:baseline;gap:12px;margin-bottom:8px'>"
                f"<h3 style='margin:0'>{row['link_id']}</h3>"
                f"<span class='chip {chip_class}'>{head_label}</span>"
                f"<span style='color:#767676;font-size:13px'>"
                f"{row['track_label']} · 배치 #{int(row['deploy_rank'])}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("E", f"{row['E']:.2f}")
            mc2.metric("R", f"{row['R']:.2f}")
            mc3.metric("Rbar", f"{row['Rbar']:.4f}")
            mc4.metric("ECR", f"{row['ECR']:.2f}")

            if row["cctv_status"] == "연동":
                tags_html = " ".join(
                    f'<span class="tag">{t}</span>' for t in row["conflict_tags"]
                )
                st.markdown("**상충 태그**", unsafe_allow_html=True)
                st.markdown(tags_html, unsafe_allow_html=True)
                st.markdown(f"**진단**  {row['risk_description']}")

                st.markdown("**트랙 A 분류 기준 통과 여부**")
                axes_data = {
                    "지표": ["ECR", "상충유형수", "대책수", "max_CE"],
                    "값": [
                        f"{row['ECR']:.2f}",
                        str(row["cctv_conflict_type_count"]),
                        str(row["recommended_measure_count"]),
                        f"{row['max_cost_eff']:.4f}" if row["max_cost_eff"] else "—",
                    ],
                    "기준값": [
                        f"{THR_ECR:.2f}", f"{THR_CONFLICT:.1f}",
                        f"{THR_MEASURE:.1f}", f"{THR_CE:.4f}",
                    ],
                    "통과": [
                        "○" if row["ECR"] >= THR_ECR else "—",
                        "○" if (row["cctv_conflict_type_count"] or 0) >= THR_CONFLICT else "—",
                        "○" if (row["recommended_measure_count"] or 0) >= THR_MEASURE else "—",
                        "○" if (row["max_cost_eff"] or 0) >= THR_CE else "—",
                    ],
                }
                st.dataframe(pd.DataFrame(axes_data),
                             use_container_width=True, hide_index=True)

                if row["recommended_measures"]:
                    st.markdown("**권고 대책**")
                    mdf = pd.DataFrame(row["recommended_measures"])
                    valid = mdf[mdf["effect_reduction"].notna()]
                    notes = [""] * len(mdf)
                    if not valid.empty:
                        be = valid["effect_reduction"].idxmax()
                        bce_v = valid[valid["CE"].notna()]
                        if not bce_v.empty:
                            bce = bce_v["CE"].idxmax()
                            if be == bce:
                                notes[be] = "효과·가성비 최대"
                            else:
                                notes[be] = "효과 최대"
                                notes[bce] = "가성비 최대"
                        else:
                            notes[be] = "효과 최대"
                    mdf["비고"] = notes
                    mdf = mdf.rename(columns={
                        "measure": "대책", "effect_reduction": "1−CMF",
                        "source": "출처", "cost_만원": "비용(만원)", "CE": "CE",
                    })
                    st.dataframe(mdf, use_container_width=True, hide_index=True)

                if track == "A":
                    st.markdown("**법정 체크리스트** (행안부 어린이보호구역 지정 규칙)")
                    cks = st.columns(2)
                    for i, c in enumerate(LEGAL_CHECKS):
                        cks[i % 2].checkbox(c, key=f"chk2_{row['link_id']}_{i}")
            else:
                st.info("CCTV 미연동 후보. 영상 진단 후 축 2~4 확정.")


# ════════════════════════════════════════════════════════════════════════════
# 용량 시뮬레이션
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    ic1, ic2, ic3 = st.columns(3)
    budget_억 = ic1.number_input("예산 (억원)", 1, 100, 20, 1)
    unit_cost_만 = ic2.number_input(
        "후보 1건당 평균 검토·조치 비용 (만원/건)",
        500, 10_000, 1_800, 100,
        help="시설별 실제 공사비가 아니라 후보 1곳을 검토하고 기본 조치까지 진행하는 평균 행정 단위비용입니다.",
    )
    work_cap = ic3.number_input("인력 (건/분기)", 1, 50, 11, 1)

    budget = int(budget_억) * 100_000_000
    unit_cost = int(unit_cost_만) * 10_000
    budget_cap = int(budget // unit_cost)
    n_admin = min(budget_cap, int(work_cap))
    bottleneck = "예산" if budget_cap <= work_cap else "인력"

    priority = gdf.sort_values("ECR", ascending=False).head(n_admin)
    n_admin_a = int((priority["track"] == "A").sum())
    n_admin_b = int((priority["track"] == "B").sum())
    n_wait = n_gate - n_admin

    r = st.columns(4)
    r[0].metric("예산 가용", budget_cap, help="floor(예산 / 후보 1건당 평균 검토·조치 비용)")
    r[1].metric("인력 가용", int(work_cap))
    r[2].metric("N_admin", n_admin, help="min(예산, 인력)")
    r[3].metric("병목", bottleneck)

    k = st.columns(4)
    for col, val, label, klass in [
        (k[0], n_admin_a, "트랙 A · 지정·확대 검토", "kpi-a"),
        (k[1], n_admin_b, "트랙 B · 시설 개선 검토", "kpi-b"),
        (k[2], n_admin, "우선검토군", "kpi-primary"),
        (k[3], n_wait, "대기", "kpi-neutral"),
    ]:
        col.markdown(
            f'<div class="kpi {klass}"><div class="kpi-v">{val}</div>'
            f'<div class="kpi-l">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("**우선검토군** (ECR 상위 N_admin)")
    tbl = priority[[
        "link_id", "track_label", "deploy_rank", "E", "R", "ECR",
        "cctv_status", "cctv_conflict_type_count", "recommended_measure_count",
    ]].rename(columns={
        "link_id": "링크", "track_label": "트랙", "deploy_rank": "배치",
        "cctv_status": "CCTV", "cctv_conflict_type_count": "상충",
        "recommended_measure_count": "대책",
    }).reset_index(drop=True)
    st.dataframe(tbl, use_container_width=True, hide_index=True)

    st.markdown("**민감도 분석** (분류 기준 변경 시 트랙 A 후보 수)")
    sens_rows = []
    for q, label in [(0.75, "상위 1/4"), (2/3, "상위 1/3 (현행)"), (0.5, "상위 1/2")]:
        te = gdf["ECR"].quantile(q)
        tc = _cctv_gdf["cctv_conflict_type_count"].quantile(q)
        tm = _cctv_gdf["recommended_measure_count"].quantile(q)
        tce = _cctv_gdf["max_cost_eff"].quantile(q)
        cnt = sum(
            1 for _, rr in gdf.iterrows()
            if rr["cctv_status"] == "연동"
            and rr["ECR"] >= te
            and (rr["cctv_conflict_type_count"] or 0) >= tc
            and (rr["recommended_measure_count"] or 0) >= tm
            and (rr["max_cost_eff"] or 0) >= tce
        )
        sens_rows.append({
            "기준 분위": label, "트랙 A": cnt,
            "ECR 기준값": f"{te:.1f}",
            "상충 기준값": f"{tc:.1f}",
            "대책 기준값": f"{tm:.1f}",
            "CE 기준값": f"{tce:.4f}",
        })
    st.dataframe(pd.DataFrame(sens_rows), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# 리포트
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    rep, dl = st.columns([2, 1])

    with dl:
        report_type = st.radio(
            "유형",
            ["트랙 A 후보", "트랙 B 후보", "통합 마스터"],
            label_visibility="collapsed",
        )
        sel_cand = None
        if report_type in ("트랙 A 후보", "트랙 B 후보"):
            tk = "A" if "A" in report_type else "B"
            opts = gdf[gdf["track"] == tk].sort_values(
                "ECR", ascending=False)["link_id"].tolist()
            if opts:
                sel_cand = st.selectbox("후보", opts)
            else:
                st.warning(f"트랙 {tk} 후보 없음")
        gen = st.button("생성", type="primary", use_container_width=True)

    with rep:
        if not gen:
            st.info("좌측에서 유형·후보 선택 후 [생성]을 클릭하세요.")
        elif report_type == "통합 마스터":
            st.markdown("### 어린이보호구역 우선검토 분석 · 관악구")
            st.caption("기준일 2026-05-26")

            st.dataframe(pd.DataFrame({
                "항목": ["전체 도로 링크", "gate 후보", "트랙 A", "트랙 B", "CCTV 연동"],
                "수치": [metrics["n_links"], n_gate, n_a, n_b, n_cctv],
            }), use_container_width=True, hide_index=True)

            st.markdown(
                f"**검증**  사고 집중도 {gate_lift}배 · "
                f"R AUC {metrics['auc']['R']} · E AUC {metrics['auc']['E']}"
            )

            for tk, lab in [("A", "트랙 A 후보"), ("B", "트랙 B 후보")]:
                st.markdown(f"**{lab}**")
                tdf = gdf[gdf["track"] == tk][[
                    "link_id", "track_label", "ECR",
                    "cctv_conflict_type_count", "recommended_measure_count",
                ]].rename(columns={
                    "link_id": "링크", "track_label": "트랙",
                    "cctv_conflict_type_count": "상충",
                    "recommended_measure_count": "대책",
                })
                st.dataframe(tdf, use_container_width=True, hide_index=True)

            pdf = generate_master_pdf(metrics, n_a, n_b, n_cctv, gate_lift)
            st.download_button("PDF 다운로드", data=pdf,
                               file_name="b2g_master.pdf",
                               mime="application/pdf",
                               use_container_width=True)

        elif sel_cand:
            row = gdf[gdf["link_id"] == sel_cand].iloc[0]
            track = row["track"]
            action = "지정·확대 검토" if track == "A" else "시설 개선 검토"

            st.markdown(f"### {sel_cand} · {action}")
            st.caption(f"트랙 {row['track_label']} · 배치 #{int(row['deploy_rank'])}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("E", f"{row['E']:.2f}")
            c2.metric("R", f"{row['R']:.2f}")
            c3.metric("Rbar", f"{row['Rbar']:.4f}")
            c4.metric("ECR", f"{row['ECR']:.2f}")

            if row["cctv_status"] == "연동":
                st.markdown(f"**상충** &nbsp; {', '.join(row['conflict_tags'])}")
                st.markdown(f"**진단** &nbsp; {row['risk_description']}")

                if row["recommended_measures"] and track == "B":
                    mdf = pd.DataFrame(row["recommended_measures"]).rename(columns={
                        "measure": "대책", "effect_reduction": "1−CMF",
                        "source": "출처", "cost_만원": "비용(만원)", "CE": "CE",
                    })
                    st.dataframe(mdf, use_container_width=True, hide_index=True)

                if track == "A":
                    st.markdown("**법정 체크리스트**")
                    cks = st.columns(2)
                    for i, c in enumerate(LEGAL_CHECKS):
                        cks[i % 2].checkbox(c, key=f"chk4_{sel_cand}_{i}")

            pdf = generate_candidate_pdf(row, track)
            st.download_button("PDF 다운로드", data=pdf,
                               file_name=f"b2g_{sel_cand}.pdf",
                               mime="application/pdf",
                               use_container_width=True)


# ── 푸터 ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="krds-footer">
  <div>
    <div class="col-title">데이터 출처</div>
    <div class="col-body">
      도로명주소 도로구간 · TAAS 어린이보행자사고<br>
      서울 열린데이터광장 어린이보호구역 CCTV<br>
      교육부 학교 위치 · KOSIS 어린이 인구<br>
      기준일 2026-05-26
    </div>
  </div>
  <div>
    <div class="col-title">면책</div>
    <div class="col-body">
      ECR은 참고지표이며 사고확률이 아닙니다. 트랙 분류는 시스템 권고로 담당자가 변경할 수 있으며,
      최종 지정은 현장조사 · 관할 경찰서 협의 · 주민 의견 수렴 · 도로교통법 제12조 및 행정안전부 어린이보호구역 지정 규칙에 따른 법정 기준 검토를 거칩니다.
    </div>
  </div>
  <div>
    <div class="col-title">시스템 정보</div>
    <div class="col-body">
      어린이보호구역 우선검토 분석시스템 v1.0<br>
      관악구 시범<br>
      © 2026 제 8회 교육 공공데이터 AI활용대회
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
