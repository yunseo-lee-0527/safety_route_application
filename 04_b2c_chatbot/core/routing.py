"""
routing.py
==========
Lagrangian Dijkstra + 이분탐색 (context.md §2).
Multi-target: 목적지 학교의 모든 게이트 노드에 대해 dijkstra 실행 후 최소 선택.
"""

from dataclasses import dataclass
from typing import Callable

import networkx as nx


BISECTION_EPS = 0.05


def compute_short_path_length(G: nx.Graph, src: int, gates: list) -> float | None:
    """α=0 기준 최단 경로 길이(m). 여러 게이트 중 최소."""
    min_len = float("inf")
    for gate in gates:
        if gate == src:
            return 0.0
        try:
            length = nx.shortest_path_length(G, src, gate, weight="length_m")
            min_len = min(min_len, length)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
    return min_len if min_len < float("inf") else None


@dataclass
class RouteResult:
    path: list                 # [node_id, ...]
    edges: list                # [(u, v, edge_data), ...]
    total_length_m: float
    short_length_m: float      # α=0 baseline
    detour_ratio: float        # total/short - 1
    alpha_used: float
    cap_eff: float
    warning: bool              # cap을 만족 못 하고 floor에서도 초과한 경우


def _weight_fn(alpha: float) -> Callable:
    def w(u, v, data):
        return data["length_m"] * (1.0 + alpha * data["risk"])
    return w


def _path_length(G: nx.Graph, path: list) -> float:
    if not path or len(path) < 2:
        return 0.0
    return sum(G[u][v]["length_m"] for u, v in zip(path[:-1], path[1:]))


def _dijkstra_to_gates(G: nx.Graph, src: int, gates: list,
                       alpha: float) -> tuple[list | None, float | None]:
    """src에서 게이트들 중 가장 가까운 곳까지의 (path, actual_length)."""
    weight = _weight_fn(alpha)
    best_path = None
    best_length = float("inf")
    for gate in gates:
        if gate == src:
            return [src], 0.0
        try:
            _cost, path = nx.single_source_dijkstra(G, src, gate, weight=weight)
        except nx.NetworkXNoPath:
            continue
        except nx.NodeNotFound:
            continue
        plen = _path_length(G, path)
        if plen < best_length:
            best_length = plen
            best_path = path
    if best_path is None:
        return None, None
    return best_path, best_length


def _build_result(G: nx.Graph, path: list, total_len: float,
                  short_len: float, alpha: float, cap_eff: float,
                  warning: bool) -> RouteResult:
    edges = []
    for u, v in zip(path[:-1], path[1:]):
        edges.append((u, v, G[u][v]))
    detour = (total_len / short_len) - 1.0 if short_len > 0 else 0.0
    return RouteResult(
        path=path, edges=edges,
        total_length_m=total_len, short_length_m=short_len,
        detour_ratio=detour, alpha_used=alpha, cap_eff=cap_eff,
        warning=warning,
    )


def find_route(G: nx.Graph, src: int, gates: list,
               alpha_eff: float, cap_eff: float,
               alpha_floor: float,
               eps: float = BISECTION_EPS) -> RouteResult | None:
    """context.md §2 알고리즘 그대로."""
    if not gates:
        return None
    # 1) α=0 기준 최단
    _short_path, short_len = _dijkstra_to_gates(G, src, gates, 0.0)
    if short_len is None:
        return None  # 도달 불가

    # 2) 선호 α에서 cap 만족?
    p_hi, len_hi = _dijkstra_to_gates(G, src, gates, alpha_eff)
    if p_hi is not None and (len_hi / short_len - 1.0) <= cap_eff:
        return _build_result(G, p_hi, len_hi, short_len, alpha_eff, cap_eff, warning=False)

    # 3) floor에서도 cap 초과?
    p_lo, len_lo = _dijkstra_to_gates(G, src, gates, alpha_floor)
    if p_lo is None:
        return None
    if (len_lo / short_len - 1.0) > cap_eff:
        return _build_result(G, p_lo, len_lo, short_len, alpha_floor, cap_eff, warning=True)

    # 4) 이분탐색: cap 만족하는 최대 α
    lo, hi = alpha_floor, alpha_eff
    best_path, best_len, best_alpha = p_lo, len_lo, alpha_floor
    while hi - lo > eps:
        mid = (hi + lo) / 2.0
        p, plen = _dijkstra_to_gates(G, src, gates, mid)
        if p is not None and (plen / short_len - 1.0) <= cap_eff:
            lo, best_path, best_len, best_alpha = mid, p, plen, mid
        else:
            hi = mid
    return _build_result(G, best_path, best_len, short_len, best_alpha, cap_eff, warning=False)
