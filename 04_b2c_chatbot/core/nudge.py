"""
nudge.py
========
규칙 정규식(§4.1) + Gemini 방향 분류(§4.2) + 가드레일(§4.3) + stickiness(§4.4).

상태 모델:
  alpha_axis ∈ {"max", "min"}  ← 페르소나에서 시작, nudge로 토글
  cap_eff    ∈ CAP_LADDER       ← 페르소나에서 시작, nudge로 사다리 이동
"""

import json
import re
from dataclasses import dataclass, field

from .personas import CAP_LADDER, CAP_EXTREME


# ----------------------------------------------------------------
# 규칙 레이어 (결정론, 우선)
# ----------------------------------------------------------------
@dataclass
class RuleHit:
    name: str
    sentence: str  # 응답에 노출용 (§4.5)


RULES = [
    {
        "name": "안전 스냅",
        "pattern": re.compile(
            r"무서|차\s*많|쌩쌩|위험|차도|차량|교통량|"
            r"차가\s*많|차들이\s*많|차\s*많이\s*다녀|"
            r"차가\s*빨라|차가\s*쌩쌩|차가\s*가까워|"
            r"도로가\s*넓|큰\s*도로|대로|간선도로|"
            r"버스|트럭|오토바이|킥보드|"
            r"주정차|불법\s*주정차|주차\s*많|"
            r"사고|교통사고|사고\s*많|사고\s*위험|"
            r"위험한\s*도로|복잡한\s*도로|차도랑\s*가까워|차도\s*옆|"
            r"보도\s*없|인도\s*없|보행로\s*없|"
            r"보차분리|스쿨존|어린이\s*보호구역|보호구역"
        ),
        "effects": [("alpha", "max")],
        "sentence": "위험하게 느껴진다고 하셔서 가장 안전한 길로 안내했어요.",
    },
    {
        "name": "안전 완화",
        "pattern": re.compile(
            r"천천히|시간\s*있|여유|시간\s*많|여유\s*있|여유롭게|"
            r"천천히\s*가|천천히\s*가도\s*돼|"
            r"돌아가도|조금\s*돌아가도|멀어도|멀어도\s*괜찮|"
            r"돌아도\s*괜찮|안전하게|안전\s*우선|"
            r"안전한\s*길|제일\s*안전|가장\s*안전|"
            r"위험\s*적은|차\s*적은|차\s*없는|"
            r"보도\s*있는|인도\s*있는|스쿨존\s*위주|보호구역\s*위주"
        ),
        "effects": [("cap", +1)],
        "sentence": "여유 있게 가셔도 된다고 하셔서 조금 더 안전한 길을 골랐어요.",
    },
    {
        "name": "속도 스텝",
        "pattern": re.compile(
            r"빨리|급해|늦|시간\s*없|시간\s*부족|촉박|"
            r"빠르게|빨리\s*가|빨리\s*도착|급하게|"
            r"서둘러|서둘러야|늦었|늦을\s*것|늦을거|"
            r"빠른\s*길|제일\s*빠른|가장\s*빠른|"
            r"최단|최단거리|가까운\s*길|짧은\s*길|"
            r"바로\s*가|덜\s*돌아|돌아가지\s*말고|"
            r"우회\s*적게|시간\s*줄여"
        ),
        "effects": [("cap", -1)],
        "sentence": "빠르게 가야 한다고 하셔서 더 직선에 가까운 길로 안내했어요.",
    },
    {
        "name": "지각임박",
        "pattern": re.compile(
            r"곧\s*지각|1분\s*남|진짜\s*늦|이미\s*늦|완전\s*늦|"
            r"지각이야|지각할\s*것|지각할거|지각할\s*듯|지각할듯|"
            r"늦었다|큰일났|당장\s*가야|바로\s*가야|"
            r"최대한\s*빨리|제일\s*빨리|무조건\s*빨리|"
            r"시간이\s*하나도\s*없|"
            r"0분\s*남|2분\s*남|3분\s*남|4분\s*남|5분\s*남|"
            r"수업\s*시작|수업\s*곧\s*시작|종\s*쳤|등교시간\s*지났"
        ),
        "effects": [("cap", "extreme")],
        "sentence": "지각이 임박하다고 하셔서 최단 거리로 안내했어요.",
    },
]


def _step_cap(cap: float, direction: int) -> float:
    """cap을 사다리 위에서 1칸 이동. 범위 밖이면 클램프."""
    if cap not in CAP_LADDER:
        # 가장 가까운 사다리 칸으로 스냅
        cap = min(CAP_LADDER, key=lambda c: abs(c - cap))
    idx = CAP_LADDER.index(cap)
    new_idx = max(0, min(len(CAP_LADDER) - 1, idx + direction))
    return CAP_LADDER[new_idx]


# ----------------------------------------------------------------
# Stickiness 상태
# ----------------------------------------------------------------
@dataclass
class NudgeState:
    """세션 latch 상태. baseline은 페르소나에서 옴."""
    alpha_axis: str          # "max" or "min" — 현재 효과
    cap_eff: float           # 현재 효과
    base_alpha_axis: str     # 페르소나 기본
    base_cap_eff: float      # 페르소나 기본
    cap_override: float | None = None  # 자연어 규칙이 명시적으로 설정한 cap
    last_hits: list = field(default_factory=list)

    def reset_to_baseline(self):
        self.alpha_axis = self.base_alpha_axis
        self.cap_eff = self.base_cap_eff
        self.cap_override = None
        self.last_hits = []

    def set_baseline(self, alpha_axis: str, cap_eff: float):
        self.base_alpha_axis = alpha_axis
        self.base_cap_eff = cap_eff
        self.alpha_axis = alpha_axis
        self.cap_eff = cap_eff
        self.cap_override = None
        self.last_hits = []


# ----------------------------------------------------------------
# 메인: 발화 → 상태 업데이트 + 안내 문장
# ----------------------------------------------------------------
def apply_rules(text: str, state: NudgeState) -> list[RuleHit]:
    """정규식 규칙 적용. state 직접 변경. 매치된 RuleHit 리스트 반환."""
    hits = []
    has_safer = False
    has_faster = False
    for rule in RULES:
        if rule["pattern"].search(text):
            hits.append(RuleHit(name=rule["name"], sentence=rule["sentence"]))
            for axis, eff in rule["effects"]:
                if axis == "alpha":
                    state.alpha_axis = eff
                    has_safer = True
                elif axis == "cap":
                    if eff == "extreme":
                        state.cap_eff = CAP_EXTREME
                        state.cap_override = CAP_EXTREME
                        has_faster = True
                    elif eff == +1:
                        state.cap_eff = _step_cap(state.cap_eff, +1)
                        state.cap_override = state.cap_eff
                        has_safer = True
                    elif eff == -1:
                        state.cap_eff = _step_cap(state.cap_eff, -1)
                        state.cap_override = state.cap_eff
                        has_faster = True

    # 같은 축 충돌 시 안전쪽 우선 (§4.1)
    if has_safer and has_faster:
        # 보수적으로 안전쪽으로 되돌림
        state.alpha_axis = "max"
        # cap은 한 칸 위로 (안전쪽)
        if state.cap_eff == CAP_EXTREME:
            state.cap_eff = 0.15
    return hits


def llm_intent(text: str, gemini_model) -> str:
    """Gemini로 방향 분류. 'safer' | 'faster' | 'neutral'."""
    prompt = (
        '사용자 발화를 분류하세요. 더 안전한 길을 원하면 "safer", '
        '더 빠른 길을 원하면 "faster", 둘 다 아니면 "neutral".\n\n'
        f'발화: "{text}"\n\n'
        'JSON으로만 답: {"direction": "safer"} 또는 {"direction": "faster"} 또는 {"direction": "neutral"}'
    )
    try:
        resp = gemini_model.generate_content(prompt)
        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw).get("direction", "neutral")
    except Exception:
        return "neutral"


def apply_llm(direction: str, state: NudgeState) -> RuleHit | None:
    """LLM 결과를 state에 반영. 가드레일(§4.3): faster는 규칙 매치 없이는 무시."""
    if direction == "safer":
        state.alpha_axis = "max"
        return RuleHit(
            name="안전 의도(LLM)",
            sentence="더 안전한 길을 원하신 것 같아 가장 안전한 길로 안내했어요.",
        )
    # faster는 LLM 단독으로 발동 금지
    return None


def process_utterance(text: str, gemini_model, state: NudgeState) -> list[RuleHit]:
    """발화 → 규칙 우선 적용 → 규칙 미스 시 LLM 폴백.
    state 변경. 매치된 RuleHit 리스트 반환 (응답 §4.5에 노출)."""
    hits = apply_rules(text, state)
    if hits:
        state.last_hits = hits
        return hits
    # 규칙 미스: LLM
    direction = llm_intent(text, gemini_model)
    llm_hit = apply_llm(direction, state)
    state.last_hits = [llm_hit] if llm_hit else []
    return state.last_hits
