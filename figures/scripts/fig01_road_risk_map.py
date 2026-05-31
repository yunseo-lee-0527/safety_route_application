"""
Figure 1. Gwanak-gu road risk map (continuous RdYlGn percentile, 본문 3장 결과)

Output:
    figures/fig01_road_risk_map.pdf
    figures/fig01_road_risk_map.png
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import Normalize
from shapely import wkt

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "01_road_risk_index" / "output" / "gwanak_road_safety_scores_full_remap_service.csv"
BND = ROOT / "00_data_collection" / "data" / "raw" / "BND_SIGUNGU_PG.shp"
OUT_DIR = ROOT / "figures"
FONT_DIR = ROOT / "figures" / "fonts"

PLOT_CRS = "EPSG:5186"

CMAP = plt.get_cmap("RdYlGn_r")
COLOR_BND = "#1a1a1a"

MAJOR_CLASSES = {
    "primary", "primary_link",
    "secondary", "secondary_link",
    "trunk", "trunk_link",
    "busway",
}
LW_MAJOR = 1.4
LW_MINOR = 0.45
LW_BND = 1.1


def load_roads() -> gpd.GeoDataFrame:
    df = pd.read_csv(CSV, encoding="cp949")
    geom = df["geometry_wkt"].map(wkt.loads)
    gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
    gdf["road_risk_pct"] = gdf["local_method_risk_index"].rank(pct=True)
    gdf["is_major"] = gdf["road_class"].isin(MAJOR_CLASSES)
    return gdf


def load_boundary() -> gpd.GeoDataFrame:
    bnd = gpd.read_file(BND, encoding="cp949")
    bnd = bnd[bnd["SIGUNGU_NM"].str.contains("관악", na=False)].copy()
    bnd.set_crs("EPSG:5186", inplace=True, allow_override=True)
    return bnd


def register_fonts() -> str:
    """figures/fonts/ 내부의 Noto Serif KR을 matplotlib에 등록하고 패밀리명을 반환."""
    for path in FONT_DIR.glob("NotoSerifKR-*.otf"):
        font_manager.fontManager.addfont(str(path.resolve()))
    return "Noto Serif KR"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    family = register_fonts()
    mpl.rcParams["font.family"] = family
    mpl.rcParams["font.serif"] = [family]
    mpl.rcParams["axes.unicode_minus"] = False

    roads = load_roads().to_crs(PLOT_CRS)
    boundary = load_boundary().to_crs(PLOT_CRS)

    fig, ax = plt.subplots(figsize=(7.6, 7.4), dpi=300)

    boundary.plot(ax=ax, facecolor="none", edgecolor=COLOR_BND,
                  linewidth=LW_BND, zorder=1)

    norm = Normalize(vmin=0.0, vmax=1.0)

    minor = roads[~roads["is_major"]].sort_values("road_risk_pct")
    major = roads[roads["is_major"]].sort_values("road_risk_pct")

    if not minor.empty:
        minor.plot(
            ax=ax,
            column="road_risk_pct",
            cmap=CMAP,
            norm=norm,
            linewidth=LW_MINOR,
            zorder=2,
        )
    if not major.empty:
        major.plot(
            ax=ax,
            column="road_risk_pct",
            cmap=CMAP,
            norm=norm,
            linewidth=LW_MAJOR,
            zorder=3,
        )

    minx, miny, maxx, maxy = boundary.total_bounds
    pad_x = (maxx - minx) * 0.04
    pad_y = (maxy - miny) * 0.04
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal")
    ax.set_axis_off()

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(
        sm, ax=ax,
        shrink=0.6, pad=0.015, aspect=26,
        ticks=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    )
    cbar.set_label("도로 위험도 percentile",
                   fontsize=9, color="#1a1a1a", labelpad=8)
    cbar.ax.tick_params(labelsize=9, color="#666666",
                        labelcolor="#1a1a1a", width=0.6, length=3)
    cbar.outline.set_edgecolor("#888888")
    cbar.outline.set_linewidth(0.6)

    fig.tight_layout()

    pdf_path = OUT_DIR / "fig01_road_risk_map.pdf"
    png_path = OUT_DIR / "fig01_road_risk_map.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)

    print(f"saved {pdf_path}")
    print(f"saved {png_path}")
    print(f"  n_roads={len(roads)}, major={int(roads['is_major'].sum())}, "
          f"risk_pct in [{roads['road_risk_pct'].min():.3f}, "
          f"{roads['road_risk_pct'].max():.3f}]")


if __name__ == "__main__":
    main()
