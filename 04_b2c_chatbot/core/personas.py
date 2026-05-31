"""
personas.py
===========
4 페르소나 (2×2 그리드: α축 × cap축) + 학년별 α_floor.
D_MAX=1.50, D_MIN=0.05, D_FLOOR=0.10 — 실제 교정값. context.md §3도 이 값으로 동기화됨.
"""

from dataclasses import dataclass
from typing import Literal

D_MAX, D_MIN, D_FLOOR = 1.50, 0.05, 0.10
CAP_MENU = (0.50, 0.15)
CAP_EXTREME = 0.0
CAP_LADDER = (0.0, 0.15, 0.50)


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    emoji: str
    alpha_axis: Literal["max", "min"]
    cap: float
    grades_allowed: frozenset


PERSONAS = {
    "timid":     Persona("timid",     "소심한 아이",  "🛡️", "max", 0.50, frozenset({1, 2, 3, 4, 5, 6})),
    "safe_rush": Persona("safe_rush", "안전·쫓김",    "🏃‍♀️", "max", 0.15, frozenset({1, 2, 3, 4, 5, 6})),
    "leisurely": Persona("leisurely", "마이페이스",   "🚶", "min", 0.50, frozenset({4, 5, 6})),
    "default":   Persona("default",   "기본/서두름", "⚡", "min", 0.15, frozenset({4, 5, 6})),
}

DEFAULT_PERSONA_ID = "timid"


def alpha_for(persona: Persona, r_ref: float) -> float:
    base = D_MAX if persona.alpha_axis == "max" else D_MIN
    return base / r_ref


def alpha_max_for(r_ref: float) -> float:
    return D_MAX / r_ref


def alpha_min_for(r_ref: float) -> float:
    return D_MIN / r_ref


def alpha_floor_for(grade: int | None, r_ref: float) -> float:
    if grade is not None and grade in (1, 2, 3):
        return D_FLOOR / r_ref
    return 0.0


def is_persona_allowed(persona_id: str, grade: int | None) -> bool:
    if grade is None:
        return False
    return grade in PERSONAS[persona_id].grades_allowed


def resolve_persona_id(alpha_axis: str, cap: float) -> str:
    """alpha_axis + cap → 백엔드 페르소나 ID (UI 라벨 비노출용)."""
    if cap == 0.0:
        return "safe_rush" if alpha_axis == "max" else "default"
    return {
        ("max", 0.50): "timid",
        ("max", 0.15): "safe_rush",
        ("min", 0.50): "leisurely",
        ("min", 0.15): "default",
    }.get((alpha_axis, cap), "default")


def fallback_persona(persona_id: str) -> str:
    """학년 변경으로 disable된 페르소나의 안전쪽 fallback. cap은 유지."""
    mapping = {"leisurely": "timid", "default": "safe_rush"}
    return mapping.get(persona_id, persona_id)
