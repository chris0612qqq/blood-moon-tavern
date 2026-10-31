"""兩種模式的差異（SPEC A3、A10、B3 第 4 點）：誰能做什麼、何時推進。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.enums import Action, Mode, PauseReason, Step
from server.rules import is_day_step
from server.state import GameState


@dataclass(frozen=True)
class Actor:
    """發出意圖的人。上帝主持人與管理員操作連線沒有 player_id。"""

    player_id: str | None = None
    is_admin: bool = False
    is_host: bool = False


_ADMIN_ACTIONS = frozenset(
    {Action.ADMIN_KICK, Action.ADMIN_END, Action.ADMIN_PAUSE, Action.ADMIN_RESUME}
)
_HOST_ACTIONS = frozenset(
    {
        Action.HOST_LINE,
        Action.HOST_REPLAY,
        Action.HOST_NEXT,
        Action.HOST_SKIP_SPEAKER,
        Action.HOST_EXTEND,
        Action.HOST_ROLLBACK,
        Action.HOST_SET_ALIVE,
        Action.HOST_RESHOW_CARD,
    }
)
# SPEC A8.2：上帝模式由主持人推進的步驟；其餘（遺言、發言、揭曉）自動
HOST_PUSHED_STEPS = frozenset(
    {
        Step.NIGHT_START,
        Step.WOLF,
        Step.WOLF_END,
        Step.SEER,
        Step.SEER_END,
        Step.WITCH,
        Step.WITCH_END,
        Step.DAWN,
        Step.HUNTER,
        Step.VOTE,
    }
)


class ModePolicy(Protocol):
    mode: Mode

    def can(self, actor: Actor, action: Action, state: GameState) -> bool:
        """這個人能不能做這個動作（不含規則判斷，CODING_RULES E2）。"""
        ...

    def should_advance(self, next_step: Step) -> bool:
        """目前步驟完成後，是否自動進入下一步。"""
        ...

    def can_pause(self, actor: Actor, state: GameState) -> bool:
        """能否按暫停。"""
        ...


def _can_common(actor: Actor, action: Action) -> bool:
    if action in _ADMIN_ACTIONS:
        return actor.is_admin
    return action not in _HOST_ACTIONS


class GodMode:
    mode = Mode.GOD

    def can(self, actor: Actor, action: Action, state: GameState) -> bool:
        if action in _HOST_ACTIONS:
            return actor.is_host
        if action is Action.NARRATOR_TAKEOVER:
            return False
        return _can_common(actor, action)

    def should_advance(self, next_step: Step) -> bool:
        return next_step not in HOST_PUSHED_STEPS

    def can_pause(self, actor: Actor, state: GameState) -> bool:
        return actor.is_admin


class AutoMode:
    mode = Mode.AUTO

    def can(self, actor: Actor, action: Action, state: GameState) -> bool:
        return _can_common(actor, action)

    def should_advance(self, next_step: Step) -> bool:
        return True

    def can_pause(self, actor: Actor, state: GameState) -> bool:
        return actor.is_admin and is_day_step(state.step)


def policy_for(mode: Mode) -> ModePolicy:
    """取模式對應的策略。"""
    return GodMode() if mode is Mode.GOD else AutoMode()


def can_resume(actor: Actor, reason: PauseReason) -> bool:
    """繼續只要是管理員都可以；系統暫停在兩模式都不限白天（SPEC A3、A11）。"""
    return actor.is_admin
