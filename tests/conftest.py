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

DEFAULT_LIMIT_SECONDS = 1200  # 12 人整局本來就久，電腦忙的時候會超過 10 分鐘
SLOW_LIMIT_SECONDS = 3600
EXIT_HUNG = 3


def _limit_of(item: pytest.Item) -> float:
    marker = item.get_closest_marker("watchdog")
    if marker is not None:
        return float(marker.args[0])
    return SLOW_LIMIT_SECONDS if item.get_closest_marker("slow") else DEFAULT_LIMIT_SECONDS


def _give_up(item: pytest.Item, limit: float) -> None:
    # pytest 把 stderr 導到暫存檔了，不先關掉捕捉，這句話就看不到
    capture = item.config.pluginmanager.getplugin("capturemanager")
    if capture is not None:
        capture.suspend_global_capture(in_=True)
    print(f"\nWATCHDOG: {item.nodeid} 超過 {limit:.0f} 秒，判定卡住，結束這一輪", file=sys.stderr)
    sys.stderr.flush()
    for child in psutil.Process().children(recursive=True):
        child.kill()
    os._exit(EXIT_HUNG)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Iterator[None]:
    limit = _limit_of(item)
    timer = threading.Timer(limit, _give_up, args=(item, limit))
    timer.daemon = True
    timer.start()
    yield
    timer.cancel()
