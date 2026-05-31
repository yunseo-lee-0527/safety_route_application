"""
Figure 2. Gwanak-gu pedestrian walking-link safety map (본문 4장)

Produces two outputs:
    figures/fig02_1_walking_risk_map.{pdf,png}
        - continuous RdYlGn percentile gradient over risky links (score > 0)
    figures/fig02_2_walking_safe_map.{pdf,png}
        - only safe / segregated links (score = 0), shown in solid green
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[2]
GEOJSON = ROOT / "02_pedestrian_safety_index" / "output" / "gwanak_walking_edge_safety.geojson"
BND = ROOT / "00_data_collection" / "data" / "raw" / "BND_SIGUNGU_PG.shp"
OUT_DIR = ROOT / "figures"
FONT_DIR = ROOT / "figures" / "fonts"

PLOT_CRS = "EPSG:5186"

CMAP = plt.get_cmap("RdYlGn_r")
COLOR_BND = "#1a1a1a"
COLOR_SAFE = "#1a9850"

LW_LINK = 0.55
LW_SAFE = 0.85
LW_BND = 1.1


def register_fonts() -> str:
    for path in FONT_DIR.glob("NotoSerifKR-*.otf"):
        font_manager.fontManager.addfont(str(path.resolve()))
    return "Noto Serif KR"


def load_walks() -> gpd.GeoDataFrame:
    return gpd.read_file(GEOJSON)


def load_boundary() -> gpd.GeoDataFrame:
    bnd = gpd.read_file(BND, encoding="cp949")
    bnd = bnd[bnd["SIGUNGU_NM"].str.contains("관악", na=False)].copy()
    bnd.set_crs("EPSG:5186", inplace=True, allow_override=True)
    return bnd


def _setup_axes(ax, boundary):
    boundary.plot(ax=ax, facecolor="none", edgecolor=COLOR_BND,
                  linewidth=LW_BND, zorder=1)
    minx, miny, maxx, maxy = boundary.total_bounds
    pad_x = (maxx - minx) * 0.04
    pad_y = (maxy - miny) * 0.04
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal")
    ax.set_axis_off()


def _save(fig, stem):
    pdf_path = OUT_DIR / f"{stem}.pdf"
    png_path = OUT_DIR / f"{stem}.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"saved {pdf_path}")
    print(f"saved {png_path}")


def render_risk_map(risky: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 7.4), dpi=300)
    _setup_axes(ax, boundary)

    norm = Normalize(vmin=0.0, vmax=1.0)
    risky.plot(
        ax=ax,
        column="walking_risk_score_0_1",
        cmap=CMAP,
        norm=norm,
        linewidth=LW_LINK,
        zorder=2,
    )

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(
        sm, ax=ax,
        shrink=0.6, pad=0.015, aspect=26,
        ticks=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    )
    cbar.set_label("보행 위험점수 (0 = 안전, 1 = 위험)",
                   fontsize=9, color="#1a1a1a", labelpad=8)
    cbar.ax.tick_params(labelsize=9, color="#666666",
                        labelcolor="#1a1a1a", width=0.6, length=3)
    cbar.outline.set_edgecolor("#888888")
    cbar.outline.set_linewidth(0.6)

    fig.tight_layout()
    _save(fig, "fig02_1_walking_risk_map")


def render_safe_map(safe: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7.6, 7.4), dpi=300)
    _setup_axes(ax, boundary)

    safe.plot(ax=ax, color=COLOR_SAFE, linewidth=LW_SAFE, zorder=2)

    handle = Line2D(
        [0], [0], color=COLOR_SAFE, linewidth=2.6, solid_capstyle="round",
        label=f"보차 분리·안전 구간 (점수 = 0, n = {len(safe):,})",
    )
    leg = ax.legend(
        handles=[handle],
        loc="lower right",
        frameon=True,
        framealpha=0.92,
        edgecolor="#888888",
        fontsize=9,
        handlelength=2.6,
        handletextpad=0.9,
        borderpad=0.5,
    )
    leg.get_frame().set_linewidth(0.6)
    for text in leg.get_texts():
        text.set_color("#1a1a1a")

    fig.tight_layout()
    _save(fig, "fig02_2_walking_safe_map")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    family = register_fonts()
    mpl.rcParams["font.family"] = family
    mpl.rcParams["font.serif"] = [family]
    mpl.rcParams["axes.unicode_minus"] = False

    walks = load_walks().to_crs(PLOT_CRS)
    boundary = load_boundary().to_crs(PLOT_CRS)

    score = walks["walking_risk_score_0_1"]
    safe = walks[score <= 0.0]
    risky = walks[score > 0.0].sort_values("walking_risk_score_0_1",
                                           ascending=True)

    render_risk_map(risky, boundary)
    render_safe_map(safe, boundary)

    print(f"  safe(score=0)={len(safe)}, risky(score>0)={len(risky)} "
          f"(total {len(walks)})")


if __name__ == "__main__":
    main()
