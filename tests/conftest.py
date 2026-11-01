"""看門狗：測試卡住時不能無聲地一直等。

Playwright 的 evaluate 沒有逾時，頁面裡的 Promise 不結束就會永遠等下去（發生過，空等 100 分鐘）。
超過時限就印出卡在哪個測試、收掉子程序、結束整輪，呼叫端才知道出事了。
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator

import psutil
import pytest

DEFAULT_LIMIT_SECONDS = 600
SLOW_LIMIT_SECONDS = 3600
EXIT_HUNG = 3


def _limit_of(item: pytest.Item) -> float:
    marker = item.get_closest_marker("watchdog")
    if marker is not None:
        return float(marker.args[0])
    return SLOW_LIMIT_SECONDS if item.get_closest_marker("slow") else DEFAULT_LIMIT_SECONDS


def _give_up(test_id: str, limit: float) -> None:
    sys.__stderr__.write(f"\nWATCHDOG: {test_id} 超過 {limit:.0f} 秒，判定卡住，結束這一輪\n")
    sys.__stderr__.flush()
    for child in psutil.Process().children(recursive=True):
        child.kill()
    os._exit(EXIT_HUNG)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Iterator[None]:
    limit = _limit_of(item)
    timer = threading.Timer(limit, _give_up, args=(item.nodeid, limit))
    timer.daemon = True
    timer.start()
    yield
    timer.cancel()
