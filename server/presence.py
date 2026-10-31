"""斷線暫停的判斷（SPEC A11、B5）。純邏輯，時間由呼叫端傳入。"""

from __future__ import annotations

from enum import StrEnum

from server import config


class PresenceAction(StrEnum):
    NONE = "none"
    PAUSE = "pause"
    RESUME = "resume"


class PresenceMonitor:
    """存活玩家一半以上離線持續 10 秒 → 暫停；降到一半以下持續 10 秒 → 自動繼續。"""

    def __init__(self) -> None:
        self._over_since: float | None = None
        self._under_since: float | None = None

    def check(
        self, offline: int, alive: int, now: float, paused_by_presence: bool
    ) -> PresenceAction:
        """每 2 秒呼叫一次。"""
        over = alive > 0 and offline / alive >= config.PRESENCE_RATIO
        if over:
            self._under_since = None
            self._over_since = self._over_since if self._over_since is not None else now
            if not paused_by_presence and now - self._over_since >= config.PRESENCE_HOLD_SECONDS:
                return PresenceAction.PAUSE
            return PresenceAction.NONE
        self._over_since = None
        if not paused_by_presence:
            self._under_since = None
            return PresenceAction.NONE
        self._under_since = self._under_since if self._under_since is not None else now
        if now - self._under_since >= config.PRESENCE_HOLD_SECONDS:
            self._under_since = None
            return PresenceAction.RESUME
        return PresenceAction.NONE
