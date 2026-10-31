"""亂數介面（CODING_RULES L27）：其他模組禁止直接 import random 或 secrets。"""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


class GameRng:
    """正式環境用 `secrets.SystemRandom`；傳入種子時改用可重現的 `random.Random`。"""

    def __init__(self, seed: int | None = None) -> None:
        self._rng: random.Random = secrets.SystemRandom() if seed is None else random.Random(seed)

    def randrange(self, stop: int) -> int:
        """回傳 0 到 stop-1 的整數。"""
        return self._rng.randrange(stop)

    def choice(self, items: Sequence[T]) -> T:
        """從序列抽一個。呼叫端要先排序（L25）。"""
        return items[self._rng.randrange(len(items))]

    def uniform_int(self, low: int, high: int) -> int:
        """回傳 low 到 high（含）的整數。"""
        return low + self._rng.randrange(high - low + 1)
