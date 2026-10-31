"""千面狼假扮規則（SPEC A6）。純函式：回傳「該怎麼變」，由引擎轉成事件。"""

from __future__ import annotations

from dataclasses import dataclass

from server import balance
from server.enums import DisguiseEnd, Role
from server.rng import GameRng
from server.rules import is_day_step
from server.state import DisguiseState, GameState, PlayerState


@dataclass(frozen=True)
class DisguiseChange:
    """假扮對象的變動。`target_id=None` 表示假扮停用。"""

    target_id: str | None
    rounds_left: int
    ended_reason: DisguiseEnd | None = None


def _faceless(state: GameState) -> PlayerState:
    return next(p for p in state.players if p.role is Role.FACELESS)


def pick_target(state: GameState, rng: GameRng, previous: str | None = None) -> str | None:
    """抽對象：排除自己與死者；優先排除上一期（L12），沒有人可選回 None（L11）。"""
    faceless_id = _faceless(state).id
    candidates = sorted(p.id for p in state.players if p.alive and p.id != faceless_id)
    if not candidates:
        return None
    fresh = [c for c in candidates if c != previous]
    return rng.choice(fresh or candidates)


def on_deal(state: GameState, rng: GameRng) -> DisguiseState:
    """發牌時抽第 1 期（SPEC A6）。"""
    return DisguiseState(
        faceless_id=_faceless(state).id,
        target_id=pick_target(state, rng),
        rounds_left=balance.DISGUISE_PERIOD_ROUNDS,
    )


def on_round_start(state: GameState, rng: GameRng) -> DisguiseChange | None:
    """回合開始（天黑）：第 1 回合不計；剩餘回合減 1，歸零時重抽（SPEC A6）。"""
    disguise = state.disguise
    if disguise is None or state.round_no <= 1 or not _faceless(state).alive:
        return None
    left = disguise.rounds_left - 1
    if left > 0:
        return DisguiseChange(target_id=disguise.target_id, rounds_left=left)
    return DisguiseChange(
        target_id=pick_target(state, rng, previous=disguise.target_id),
        rounds_left=balance.DISGUISE_PERIOD_ROUNDS,
        ended_reason=DisguiseEnd.EXPIRED,
    )


def on_death(state: GameState, player_id: str, rng: GameRng) -> DisguiseChange | None:
    """有人死亡後呼叫（狀態已更新）：千面狼死亡則結束；對象死亡則立刻重抽並重置計數。"""
    disguise = state.disguise
    if disguise is None or disguise.target_id is None:
        return None
    if player_id == disguise.faceless_id:
        return DisguiseChange(target_id=None, rounds_left=0, ended_reason=DisguiseEnd.WOLF_DEAD)
    if player_id != disguise.target_id:
        return None
    return DisguiseChange(
        target_id=pick_target(state, rng, previous=disguise.target_id),
        rounds_left=balance.DISGUISE_PERIOD_ROUNDS,
        ended_reason=DisguiseEnd.TARGET_DEAD,
    )


def can_disguise(state: GameState, player_id: str) -> bool:
    """能否以假扮身分發言（SPEC B8）：存活千面狼、白天（含白天暫停）、有對象。"""
    disguise = state.disguise
    return (
        disguise is not None
        and disguise.faceless_id == player_id
        and disguise.target_id is not None
        and state.player(player_id).alive
        and is_day_step(state.step)
    )
