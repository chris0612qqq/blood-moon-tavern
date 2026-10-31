"""SQLite 存取（SPEC B6、CODING_RULES E4–E5、P4–P5、P8）。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

from server import config
from server.enums import Role
from server.events import Event
from server.rules import RoleRecord

T = TypeVar("T")
_SECONDS_PER_DAY = 86400

_SCHEMA = """
CREATE TABLE IF NOT EXISTS role_history(
  device_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, played_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_history_device ON role_history(device_id);
CREATE INDEX IF NOT EXISTS idx_history_name ON role_history(name);
CREATE TABLE IF NOT EXISTS room(
  id TEXT PRIMARY KEY, mode TEXT NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL,
  settings_json TEXT NOT NULL, admin_player_id TEXT, state TEXT NOT NULL,
  created_at REAL NOT NULL, ended_at REAL, seed INTEGER, narrator_id TEXT);
CREATE TABLE IF NOT EXISTS banned_device(room_id TEXT NOT NULL, device_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_banned_room ON banned_device(room_id);
CREATE TABLE IF NOT EXISTS player(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL, device_id TEXT NOT NULL, name TEXT NOT NULL,
  avatar_media_id TEXT, pin_hash TEXT NOT NULL, seat INTEGER NOT NULL,
  is_spectator INTEGER NOT NULL, kicked INTEGER NOT NULL, prep_json TEXT NOT NULL,
  join_order INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_player_room ON player(room_id);
CREATE TABLE IF NOT EXISTS session(
  token_hash TEXT PRIMARY KEY, room_id TEXT NOT NULL, player_id TEXT, is_admin INTEGER NOT NULL,
  device_id TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_session_room ON session(room_id);
CREATE TABLE IF NOT EXISTS game(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL,
  winner TEXT);
CREATE INDEX IF NOT EXISTS idx_game_room ON game(room_id);
CREATE TABLE IF NOT EXISTS chat_message(
  id INTEGER PRIMARY KEY, room_id TEXT NOT NULL, channel TEXT NOT NULL, real_author_id TEXT,
  is_last_words INTEGER NOT NULL, display_player_id TEXT, is_host INTEGER NOT NULL,
  disguise_period_id INTEGER, kind TEXT NOT NULL, content TEXT, media_id TEXT, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chat_room_ts ON chat_message(room_id, ts);
CREATE TABLE IF NOT EXISTS media(
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
  bytes INTEGER NOT NULL, mime TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_media_room ON media(room_id);
CREATE TABLE IF NOT EXISTS event_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, ts REAL NOT NULL,
  type TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_event_game ON event_log(game_id);
CREATE TABLE IF NOT EXISTS snapshot(
  id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, ts REAL NOT NULL,
  state_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_snapshot_game ON snapshot(game_id);
"""
_ROOM_TABLES = ("banned_device", "player", "session", "game", "chat_message", "media", "room")


class Database:
    """單一連線，只在遊戲 worker 中使用；備份另開連線（CODING_RULES P8）。"""

    def __init__(self, path: Path = config.DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def _with_retry(self, operation: Callable[[], T]) -> T:
        """SQLITE_BUSY 重試 3 次（CODING_RULES E5）。其他錯誤往外丟，由呼叫端處理。"""
        for delay in config.SQLITE_BUSY_DELAYS:
            try:
                return operation()
            except sqlite3.OperationalError as err:
                if "locked" not in str(err) and "busy" not in str(err):
                    raise
                time.sleep(delay)
        return operation()

    def write(self, statements: Iterable[tuple[str, tuple[Any, ...]]]) -> None:
        """多筆寫入放同一交易（CODING_RULES P5、總則 4）。失敗則全部不生效。"""
        items = list(statements)

        def run() -> None:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in items:
                    self.conn.execute(sql, params)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

        self._with_retry(run)

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    # ---- 遊戲事件 ----

    @staticmethod
    def event_statements(
        game_id: str, events: Iterable[Event]
    ) -> list[tuple[str, tuple[Any, ...]]]:
        """把事件轉成 INSERT，和其他寫入放同一交易。"""
        return [
            (
                "INSERT INTO event_log(game_id, ts, type, payload_json) VALUES(?,?,?,?)",
                (game_id, event.ts, event.type.value, event.model_dump_json()),
            )
            for event in events
        ]

    @staticmethod
    def snapshot_statements(
        game_id: str, ts: float, state_json: str
    ) -> list[tuple[str, tuple[Any, ...]]]:
        """寫快照並刪除超過 20 份的舊快照（CODING_RULES P5）。"""
        return [
            (
                "INSERT INTO snapshot(game_id, ts, state_json) VALUES(?,?,?)",
                (game_id, ts, state_json),
            ),
            (
                "DELETE FROM snapshot WHERE game_id=? AND id NOT IN "
                "(SELECT id FROM snapshot WHERE game_id=? ORDER BY id DESC LIMIT ?)",
                (game_id, game_id, config.SNAPSHOT_KEEP),
            ),
        ]

    def load_event_rows(self, game_id: str) -> list[dict[str, Any]]:
        rows = self.rows(
            "SELECT payload_json FROM event_log WHERE game_id=? ORDER BY id", (game_id,)
        )
        return [json.loads(row["payload_json"]) for row in rows]

    def load_snapshots(self, game_id: str) -> list[tuple[float, dict[str, Any]]]:
        rows = self.rows(
            "SELECT ts, state_json FROM snapshot WHERE game_id=? ORDER BY id", (game_id,)
        )
        return [(row["ts"], json.loads(row["state_json"])) for row in rows]

    # ---- 角色輪替（SPEC A5.7） ----

    def load_role_history(
        self, players: Iterable[tuple[str, str, str]], now: float
    ) -> dict[str, RoleRecord]:
        """(玩家 id, 裝置 id, 名字) → 最近兩局角色。裝置 ID 找不到時以名字備援。"""
        cutoff = now - config_role_history_seconds()
        result: dict[str, RoleRecord] = {}
        for player_id, device_id, name in players:
            rows = self.rows(
                "SELECT role FROM role_history WHERE device_id=? AND played_at>=? "
                "ORDER BY played_at DESC LIMIT 2",
                (device_id, cutoff),
            ) or self.rows(
                "SELECT role FROM role_history WHERE name=? AND played_at>=? "
                "ORDER BY played_at DESC LIMIT 2",
                (name, cutoff),
            )
            if rows:
                roles = [Role(row["role"]) for row in rows]
                result[player_id] = RoleRecord(
                    last=roles[0], before=roles[1] if len(roles) > 1 else None
                )
        return result

    def role_history_statements(
        self, entries: Iterable[tuple[str, str, Role]], now: float
    ) -> list[tuple[str, tuple[Any, ...]]]:
        """發牌即記錄（SPEC A5.7），順便刪除過期與超過 2 局的紀錄。"""
        statements: list[tuple[str, tuple[Any, ...]]] = [
            ("DELETE FROM role_history WHERE played_at<?", (now - config_role_history_seconds(),))
        ]
        for device_id, name, role in entries:
            statements.append(
                (
                    "INSERT INTO role_history(device_id, name, role, played_at) VALUES(?,?,?,?)",
                    (device_id, name, role.value, now),
                )
            )
            statements.append(
                (
                    "DELETE FROM role_history WHERE device_id=? AND rowid NOT IN "
                    "(SELECT rowid FROM role_history WHERE device_id=? "
                    "ORDER BY played_at DESC, rowid DESC LIMIT 2)",
                    (device_id, device_id),
                )
            )
        return statements

    # ---- 關房與備份 ----

    def delete_room(self, room_id: str) -> None:
        """關房：刪除該房全部資料，輪替紀錄除外（SPEC A2、A4）。"""
        games = [row["id"] for row in self.rows("SELECT id FROM game WHERE room_id=?", (room_id,))]
        statements: list[tuple[str, tuple[Any, ...]]] = []
        for game_id in games:
            statements.append(("DELETE FROM event_log WHERE game_id=?", (game_id,)))
            statements.append(("DELETE FROM snapshot WHERE game_id=?", (game_id,)))
        for table in _ROOM_TABLES:
            column = "id" if table == "room" else "room_id"
            statements.append((f"DELETE FROM {table} WHERE {column}=?", (room_id,)))
        self.write(statements)
        self.conn.execute("VACUUM")

    def backup_to(self, target: Path) -> None:
        """用 SQLite backup API，另開連線，可在背景執行緒跑（CODING_RULES P8）。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.path)
        try:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()


def config_role_history_seconds() -> int:
    from server import balance

    return balance.ROLE_HISTORY_DAYS * _SECONDS_PER_DAY


def is_healthy(path: Path) -> bool:
    """資料庫檔是否可讀（CODING_RULES E5）。"""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return row is not None and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def restore_latest_backup(path: Path, backup_dir: Path) -> bool:
    """資料庫損毀時從最新備份還原（CODING_RULES E5）。沒有可用備份回 False。"""
    candidates = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if is_healthy(candidate):
            for suffix in ("", "-wal", "-shm"):
                Path(f"{path}{suffix}").unlink(missing_ok=True)
            shutil.copy2(candidate, path)
            return True
    return False
