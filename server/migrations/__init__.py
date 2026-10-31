"""存檔版本升級（CODING_RULES G4）：一版一個函式，讀不懂就拒絕還原，不猜。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.state import SCHEMA_VERSION

# 舊版本號 → 把該版事件轉成下一版的函式
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


class SchemaTooNew(Exception):
    """存檔版本比程式新或沒有升級路徑，管理員只能中途結束。"""


def upgrade_event(raw: dict[str, Any]) -> dict[str, Any]:
    """把事件資料升到目前版本。"""
    version = int(raw.get("schema_version", 0))
    while version < SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise SchemaTooNew(str(version))
        raw = MIGRATIONS[version](raw)
        version += 1
        raw["schema_version"] = version
    if version > SCHEMA_VERSION:
        raise SchemaTooNew(str(version))
    return raw
