"""時鐘介面（CODING_RULES L5、T7）：程式內倒數一律用單調時鐘，測試注入 FakeClock。"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """回傳單調遞增的秒數。"""
        ...


class SystemClock:
    def __init__(self, scale: float = 1.0) -> None:
        # scale 只給 DEV_MODE 的時間加速（CODING_RULES D2）
        self._scale = scale
        self._origin = time.monotonic()

    def now(self) -> float:
        return (time.monotonic() - self._origin) * self._scale


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
