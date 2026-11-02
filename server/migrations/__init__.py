"""存檔版本升級（CODING_RULES G4）：一版一個函式，讀不懂就拒絕還原，不猜。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from server.state import SCHEMA_VERSION

_KICK = "kick"
_DEATH_FIELDS = frozenset({"cause", "death_cause"})
_REMOVED_EVENTS = frozenset({"bet_set"})  # SPEC v4.20 拿掉押注


def _kick_to_manual(value: Any) -> Any:
    """v1 → v2（SPEC v4.16 拿掉踢人）：舊存檔裡的 kick 死因都當成手動判死。"""
    if isinstance(value, list):
        return [_kick_to_manual(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "manual" if key in _DEATH_FIELDS and item == _KICK else _kick_to_manual(item)
            for key, item in value.items()
        }
    return value


# 舊版本號 → 把該版事件轉成下一版的函式
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _kick_to_manual}


class SchemaTooNew(Exception):
    """存檔版本比程式新或沒有升級路徑，管理員只能中途結束。"""


def upgrade_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """快照和事件用同一套版本號，轉法也一樣。"""
    return upgrade_event(raw)


def upgrade_events(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """整局事件升版，已經拿掉的事件直接略過（它們只影響已拿掉的功能）。"""
    return [upgrade_event(raw) for raw in rows if raw.get("type") not in _REMOVED_EVENTS]


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
