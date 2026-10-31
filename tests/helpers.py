"""測試用的狀態建構工具。"""

from __future__ import annotations

from server.enums import DeathCause, Mode, Role, Step
from server.state import GameState, NightRecord, PlayerState


def make_state(
    roles: list[Role],
    *,
    dead: dict[int, DeathCause] | None = None,
    round_no: int = 1,
    step: Step = Step.DAY_SPEAK,
    mode: Mode = Mode.AUTO,
) -> GameState:
    """依座位順序建狀態；玩家 id 為 p1、p2…，`dead` 以座位號指定死者與死因。"""
    dead = dead or {}
    players = [
        PlayerState(
            id=f"p{seat}",
            name=f"玩{seat}",
            seat=seat,
            role=role,
            alive=seat not in dead,
            death_cause=dead.get(seat),
            death_round=1 if seat in dead else None,
        )
        for seat, role in enumerate(roles, start=1)
    ]
    state = GameState(mode=mode, players=players, round_no=round_no, step=step)
    state.nights.append(NightRecord(round_no=round_no))
    return state


EIGHT = [
    Role.VILLAGER,
    Role.SEER,
    Role.WITCH,
    Role.FACELESS,
    Role.WOLF,
    Role.HUNTER,
    Role.VILLAGER,
    Role.VILLAGER,
]
