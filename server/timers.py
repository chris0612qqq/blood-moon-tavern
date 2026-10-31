"""時間計算與 tick 迴圈（SPEC A8.2、B4、CODING_RULES E15）。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from server import balance, config
from server.state import PauseState, Timers

_TIMER_FIELDS = ("opens_at", "deadline", "min_until", "confirm_until", "grace_until")


def narration_seconds(text: str) -> float:
    """旁白長度估算：字數 × 0.25 秒 ÷ 語速＋1 秒。伺服器不等手機回報（CODING_RULES E15）。"""
    return (
        len(text) * balance.NARRATION_SECONDS_PER_CHAR / balance.NARRATION_RATE
        + balance.NARRATION_PADDING_SECONDS
    )


def sfx_seconds(line_id: str) -> float:
    """該句旁白前的開場音效長度（ART 13.3），沒有則為 0。"""
    return balance.SFX_SECONDS.get(line_id, 0.0)


def step_gap(line_id: str) -> float:
    """自動模式步驟間隔：至少 4 秒；有開場音效時取 音效＋0.3 秒 與 4 秒的大者（SPEC A8.2）。"""
    sfx = sfx_seconds(line_id)
    padded = sfx + balance.SFX_GAP_PADDING_SECONDS if sfx else 0.0
    return max(float(balance.STEP_GAP_SECONDS), padded)


def to_remaining(timers: Timers, now: float) -> dict[str, float]:
    """暫停時把時間點換算成剩餘秒數（L5）。"""
    return {
        name: value - now for name in _TIMER_FIELDS if (value := getattr(timers, name)) is not None
    }


def from_remaining(pause: PauseState, now: float) -> Timers:
    """繼續時由剩餘秒數算回時間點。"""
    return Timers(**{name: now + left for name, left in pause.remaining.items()})


def shifted(timers: Timers, delta: float) -> Timers:
    """把所有時間點平移（回上一步用）。"""
    return Timers(
        **{
            name: value + delta
            for name in _TIMER_FIELDS
            if (value := getattr(timers, name)) is not None
        }
    )


async def run_ticker(on_tick: Callable[[], Awaitable[None]]) -> None:
    """每 250 ms 呼叫一次；只比對記憶體，不碰資料庫（CODING_RULES P3）。"""
    while True:
        await asyncio.sleep(config.TICK_SECONDS)
        await on_tick()
