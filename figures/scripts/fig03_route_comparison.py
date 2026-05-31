"""
Figure 3. Three-mode comparison (Safest / Balanced / Fastest).

Mode parameters follow the real chatbot code:
    core/routing.py  : find_route(G, src, gates, alpha_eff, cap_eff, alpha_floor)
                       cost: length_m * (1 + alpha * risk)
    api/main.py      : _mode_descriptor mapping (alpha_axis, cap_eff)

This script does not define separate cost functions per mode. It calls
find_route() three times with different (alpha_eff, cap_eff) pairs that
correspond to the three mode labels the chatbot actually emits.

Case:
    Origin      : 세은트리움빌 (37.487193, 126.956303)
    Destination : 서울봉현초 정문 (37.490410, 126.954502)

Output:
    figures/fig03_route_comparison.pdf
    figures/fig03_route_comparison.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager, patheffects
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.transforms import ScaledTranslation
from shapely.geometry import LineString, MultiLineString, box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "04_b2c_chatbot"))

from core.graph_loader import load_bundle  # noqa: E402
from core.personas import D_MAX, D_MIN     # noqa: E402
from core.routing import find_route        # noqa: E402

OUT_DIR = ROOT / "figures"
FONT_DIR = ROOT / "figures" / "fonts"
CACHE_DIR = OUT_DIR / "cache"
BASEMAP_CACHE = CACHE_DIR / "fig03_cartodb_positron_z17.tif"
PLOT_CRS = "EPSG:5186"

SCHOOL = "서울봉현초등학교"
ORIGIN_LABEL = "출발지(세은트리움빌)"
DEST_LABEL = "서울봉현초 정문"
ORIGIN_LATLON = (37.487193, 126.956303)
DEST_LATLON = (37.490410, 126.954502)
SNAP_MAX_M = 300.0

CMAP = plt.get_cmap("RdYlGn_r")

COLOR_SAFEST = "#4895ef"
COLOR_BALANCED = "#FF7A3D"
COLOR_SHORTEST = "#fc3f93"
COLOR_ORIGIN = "#1a1a1a"
COLOR_SCHOOL = "#1a1a1a"

LW_BG = 1.0
LW_ROUTE = 5.0
BALANCED_OVERLAP_OFFSET_PT = 4.5
PAD_M = 160.0


def register_fonts() -> str:
    for path in FONT_DIR.glob("NotoSerifKR-*.otf"):
        font_manager.fontManager.addfont(str(path.resolve()))
    return "Noto Serif KR"


def edges_to_gdf(G):
    rows = []
    for u, v, d in G.edges(data=True):
        geom = d.get("geom")
        if geom is None:
            continue
        rows.append({
            "u": u,
            "v": v,
            "risk": float(d.get("risk", 0.0)),
            "geometry": geom,
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def path_to_multiline(G, path):
    geoms = []
    for u, v in zip(path[:-1], path[1:]):
        geom = G[u][v].get("geom")
        if geom is not None:
            geoms.append(geom)
    if not geoms:
        return None
    return MultiLineString(geoms) if len(geoms) > 1 else LineString(geoms[0])


def route_edge_keys(path) -> set[tuple[int, int]]:
    return {(min(u, v), max(u, v)) for u, v in zip(path[:-1], path[1:])}


def plot_route_edges(ax, fig, path, color, edge_geoms, *, zorder,
                     overlap_keys=frozenset(), offset_pts=(0.0, 0.0)):
    offset_transform = ax.transData + ScaledTranslation(
        offset_pts[0] / 72.0,
        offset_pts[1] / 72.0,
        fig.dpi_scale_trans,
    )
    for u, v in zip(path[:-1], path[1:]):
        key = (min(u, v), max(u, v))
        geom = edge_geoms.get(key)
        if geom is None:
            continue
        pieces = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        transform = offset_transform if key in overlap_keys else ax.transData
        for piece in pieces:
            xs, ys = piece.xy
            ax.plot(
                list(xs),
                list(ys),
                color=color,
                linewidth=LW_ROUTE,
                solid_capstyle="round",
                solid_joinstyle="round",
                transform=transform,
                zorder=zorder,
            )


def ensure_basemap_cache(bounds_5186) -> Path:
    if BASEMAP_CACHE.exists():
        return BASEMAP_CACHE

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    minx, miny, maxx, maxy = bounds_5186
    bounds_3857 = (
        gpd.GeoSeries([box(minx, miny, maxx, maxy)], crs=PLOT_CRS)
        .to_crs("EPSG:3857")
        .total_bounds
    )
    cx.bounds2raster(
        *bounds_3857,
        path=str(BASEMAP_CACHE),
        zoom=17,
        source=cx.providers.CartoDB.Positron,
        n_connections=1,
        use_cache=True,
    )
    return BASEMAP_CACHE


def add_cached_basemap(ax, bounds_5186) -> None:
    cache_path = ensure_basemap_cache(bounds_5186)
    cx.add_basemap(ax, crs=PLOT_CRS, source=str(cache_path),
                   attribution=False, zorder=0)


def snap_required(bundle, latlon, label):
    node_id, dist_m = bundle.snap_tree.nearest(*latlon)
    if dist_m > SNAP_MAX_M:
        raise RuntimeError(
            f"{label} is {dist_m:.1f} m from the nearest graph node "
            f"(limit: {SNAP_MAX_M:.0f} m)."
        )
    return int(node_id), dist_m


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    family = register_fonts()
    mpl.rcParams["font.family"] = family
    mpl.rcParams["font.serif"] = [family]
    mpl.rcParams["axes.unicode_minus"] = False

    bundle = load_bundle()
    G = bundle.G
    r_ref = bundle.r_ref

    origin_node, origin_snap_m = snap_required(bundle, ORIGIN_LATLON, ORIGIN_LABEL)
    dest_node, dest_snap_m = snap_required(bundle, DEST_LATLON, DEST_LABEL)
    gates = [dest_node]
    gate_info = [{
        "node_id": dest_node,
        "type": DEST_LABEL,
        "lat": DEST_LATLON[0],
        "lon": DEST_LATLON[1],
    }]

    print(f"origin_node={origin_node} snap={origin_snap_m:.1f} m")
    print(f"dest_node={dest_node} snap={dest_snap_m:.1f} m")

    alpha_max = D_MAX / r_ref
    alpha_min = D_MIN / r_ref

    modes = [
        ("safest", COLOR_SAFEST, alpha_max, 0.50, "-"),
        ("balanced", COLOR_BALANCED, alpha_max, 0.15, "-"),
        ("fastest", COLOR_SHORTEST, alpha_min, 0.15, "-"),
    ]

    routes = {}
    for name, color, a_eff, c_eff, ls in modes:
        route = find_route(
            G=G,
            src=origin_node,
            gates=gates,
            alpha_eff=a_eff,
            cap_eff=c_eff,
            alpha_floor=0.0,
        )
        if route is None:
            raise RuntimeError(f"No route found for mode: {name}")
        routes[name] = route
        print(f"{name:9s}: {route.total_length_m:6.0f} m  "
              f"alpha_used={route.alpha_used:.3f}  "
              f"detour={route.detour_ratio:.3f}  "
              f"terminal_node={route.path[-1]}")

    edges_gdf = edges_to_gdf(G).to_crs(PLOT_CRS)
    edge_geoms = {
        (min(int(row.u), int(row.v)), max(int(row.u), int(row.v))): row.geometry
        for row in edges_gdf.itertuples()
    }

    route_records = []
    for name, color, _, _, ls in modes:
        route = routes[name]
        line = path_to_multiline(G, route.path)
        route_records.append({
            "label": name,
            "color": color,
            "linestyle": ls,
            "length": route.total_length_m,
            "geometry": line,
        })
    routes_gdf = gpd.GeoDataFrame(
        route_records,
        geometry="geometry",
        crs="EPSG:4326",
    ).to_crs(PLOT_CRS)

    origin_pt = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([ORIGIN_LATLON[1]], [ORIGIN_LATLON[0]]),
        crs="EPSG:4326",
    ).to_crs(PLOT_CRS)
    school_pt = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([DEST_LATLON[1]], [DEST_LATLON[0]]),
        crs="EPSG:4326",
    ).to_crs(PLOT_CRS)

    bbox_geoms = list(routes_gdf.geometry) + list(origin_pt.geometry) + list(school_pt.geometry)
    bbox = gpd.GeoSeries(bbox_geoms, crs=PLOT_CRS).total_bounds
    minx, miny, maxx, maxy = bbox
    minx -= PAD_M
    maxx += PAD_M
    miny -= PAD_M
    maxy += PAD_M

    bg = edges_gdf.cx[minx:maxx, miny:maxy]

    fig, ax = plt.subplots(figsize=(7.2, 7.0), dpi=300)

    norm = Normalize(vmin=0.0, vmax=1.0)
    bg.sort_values("risk").plot(
        ax=ax,
        column="risk",
        cmap=CMAP,
        norm=norm,
        linewidth=LW_BG,
        alpha=0.75,
        zorder=1,
    )

    safest_edges = route_edge_keys(routes["safest"].path)
    balanced_edges = route_edge_keys(routes["balanced"].path)
    balanced_overlap = safest_edges & balanced_edges

    plot_route_edges(ax, fig, routes["fastest"].path, COLOR_SHORTEST,
                     edge_geoms, zorder=3)
    plot_route_edges(ax, fig, routes["safest"].path, COLOR_SAFEST,
                     edge_geoms, zorder=4)
    plot_route_edges(
        ax, fig, routes["balanced"].path, COLOR_BALANCED, edge_geoms,
        zorder=5,
        overlap_keys=balanced_overlap,
        offset_pts=(BALANCED_OVERLAP_OFFSET_PT, -BALANCED_OVERLAP_OFFSET_PT),
    )

    origin_pt.plot(ax=ax, color=COLOR_ORIGIN, markersize=110,
                   marker="o", zorder=6, edgecolor="white", linewidth=1.4)
    school_pt.plot(ax=ax, color=COLOR_SCHOOL, markersize=220,
                   marker="*", zorder=6, edgecolor="white", linewidth=1.0)

    label_pts = gpd.GeoDataFrame(
        gate_info,
        geometry=gpd.points_from_xy([g["lon"] for g in gate_info],
                                    [g["lat"] for g in gate_info]),
        crs="EPSG:4326",
    ).to_crs(PLOT_CRS)
    label_halo = [patheffects.withStroke(linewidth=2.4, foreground="white")]
    for _, row in label_pts.iterrows():
        ax.annotate(row["type"], xy=(row.geometry.x, row.geometry.y),
                    xytext=(7, 7), textcoords="offset points",
                    fontsize=9, color="#1a1a1a",
                    path_effects=label_halo, zorder=7)
    origin_xy = origin_pt.geometry.iloc[0]
    ax.annotate(ORIGIN_LABEL, xy=(origin_xy.x, origin_xy.y),
                xytext=(8, -10), textcoords="offset points",
                fontsize=9, color="#1a1a1a",
                path_effects=label_halo, zorder=7)

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")
    ax.set_axis_off()

    try:
        add_cached_basemap(ax, (minx, miny, maxx, maxy))
    except Exception as exc:
        print(f"warning: basemap cache/load failed ({exc}); saving without basemap.")

    l_safe = routes["safest"].total_length_m
    l_bal = routes["balanced"].total_length_m
    l_fast = routes["fastest"].total_length_m
    a_safe = routes["safest"].alpha_used
    a_bal = routes["balanced"].alpha_used

    legend_handles = [
        Line2D([0], [0], color=COLOR_SAFEST, linewidth=2.8, solid_capstyle="round",
               label=f"Safest  ({l_safe:.0f} m, alpha={a_safe:.2f})"),
        Line2D([0], [0], color=COLOR_BALANCED, linewidth=2.8, solid_capstyle="round",
               label=f"Balanced  ({l_bal:.0f} m, alpha={a_bal:.2f})"),
        Line2D([0], [0], color=COLOR_SHORTEST, linewidth=2.8, solid_capstyle="round",
               label=f"Fastest  ({l_fast:.0f} m, alpha=min)"),
        Line2D([0], [0], marker="o", color="white", markerfacecolor=COLOR_ORIGIN,
               markersize=8, markeredgecolor="white", markeredgewidth=0.8,
               linewidth=0, label=ORIGIN_LABEL),
        Line2D([0], [0], marker="*", color="white", markerfacecolor=COLOR_SCHOOL,
               markersize=12, markeredgecolor="white", markeredgewidth=0.8,
               linewidth=0, label=DEST_LABEL),
    ]
    leg = ax.legend(handles=legend_handles, loc="lower left",
                    frameon=True, framealpha=0.92, edgecolor="#888888",
                    fontsize=9, handlelength=2.6, handletextpad=0.9,
                    labelspacing=0.9, borderpad=0.5)
    leg.get_frame().set_linewidth(0.6)
    for text in leg.get_texts():
        text.set_color("#1a1a1a")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.015, aspect=26,
                        ticks=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    cbar.set_label("보행 위험점수 (0 = 안전, 1 = 위험)",
                   fontsize=9, color="#1a1a1a", labelpad=8)
    cbar.ax.tick_params(labelsize=9, color="#666666",
                        labelcolor="#1a1a1a", width=0.6, length=3)
    cbar.outline.set_edgecolor("#888888")
    cbar.outline.set_linewidth(0.6)

    fig.tight_layout()

    pdf_path = OUT_DIR / "fig03_route_comparison.pdf"
    png_path = OUT_DIR / "fig03_route_comparison.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)

    print(f"\nsaved {pdf_path}")
    print(f"saved {png_path}")


if __name__ == "__main__":
    main()
