"""房間服務（SPEC A4、A11、B4、CODING_RULES L1、E3–E4、P11）。

所有狀態改變都排進同一個 worker 依序處理（L1）；一次意圖固定是
驗證 → 計算 → 單一交易寫入 → 成功才廣播（總則 4）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from server import auth, config, media, protocol, rules, views
from server.clock import Clock, SystemClock
from server.db import Database
from server.engine import STEP_LINES, Engine
from server.enums import Action, Channel, ChatKind, Mode, PauseReason, Role, Step
from server.errors import ErrorCode, GameError
from server.events import Event, EventType
from server.hub import Connection, Session, Socket
from server.migrations import SchemaTooNew, upgrade_events, upgrade_snapshot
from server.modes import Actor
from server.presence import PresenceAction, PresenceMonitor
from server.rng import GameRng

log = logging.getLogger("bmt")
T = TypeVar("T")
ChatRow = dict[str, Any]

_LOBBY = "lobby"
_PLAYING = "playing"
_ENDED = "ended"
_MEMORY_CHAT = 200


@dataclass
class Paths:
    uploads: Path = config.UPLOADS_DIR
    backups: Path = config.BACKUP_DIR
    logs: Path = config.LOGS_DIR
    assets: Path = config.LOCAL_ASSETS_DIR


@dataclass
class RoomPlayer:
    id: str
    device_id: str
    name: str
    pin_hash: str
    seat: int
    join_order: int
    is_spectator: bool = False
    avatar_media_id: str | None = None
    prep: dict[str, bool] = field(default_factory=dict)


@dataclass
class Room:
    id: str
    mode: Mode
    name: str
    password: str
    settings: dict[str, int]
    state: str = _LOBBY
    admin_player_id: str | None = None
    narrator_id: str | None = None
    created_at: float = 0.0
    ended_at: float | None = None
    seed: int | None = None
    closes_at: float | None = None
    game_id: str | None = None
    unrestorable: bool = False


_SPEAKER_LINES = frozenset({"speak", "last_words", "defense"})


class RoomService:
    """伺服器一次只有一個房間（SPEC A1）。"""

    def __init__(
        self,
        db: Database,
        admin: auth.AdminStore,
        clock: Clock | None = None,
        wall: Callable[[], float] = time.time,
        paths: Paths | None = None,
        tick_seconds: float = config.TICK_SECONDS,
        strict: bool = config.DEV_MODE,
    ) -> None:
        self.db = db
        self.admin = admin
        self.clock: Clock = clock or SystemClock(config.TIME_SCALE)
        self.wall = wall
        self.paths = paths or Paths()
        self.tick_seconds = tick_seconds
        self.strict = strict
        self.signer = media.Signer()
        self.lockouts = auth.Lockouts()
        self.room: Room | None = None
        self.engine: Engine | None = None
        self.players: dict[str, RoomPlayer] = {}
        self.pending_broadcasts: list[tuple[float, str, dict[str, Any]]] = []
        self.sessions: dict[str, Session] = {}
        self.admin_tokens: set[str] = set()
        self.conns: list[Connection] = []
        self.chat: deque[ChatRow] = deque(maxlen=_MEMORY_CHAT)
        self.disguised_chat: list[ChatRow] = []
        self.media_rows: dict[str, media.StoredMedia] = {}
        self.chat_seq = 0
        self.role_plan: dict[str, Role] = {}  # 開局前管理員指定的職業（SPEC v4.26）
        self.chat_times: dict[str, deque[float]] = {}
        self.db_fails = 0
        self.presence = PresenceMonitor()
        self.next_presence = 0.0
        self.next_backup = 0.0
        self.host_gone_since: float | None = None
        self.last_offline: frozenset[str] = frozenset()
        self.queue: asyncio.Queue[tuple[Callable[[], Any], asyncio.Future[Any]]] | None = None
        self.tasks: list[asyncio.Task[None]] = []
        self.backup_task: asyncio.Future[None] | None = None
        self.bot_ids: list[str] = []
        self.bot_brain: Any = None

    # ---- 生命週期 ----

    async def start(self) -> None:
        """啟動 worker 與計時器，並還原上次的房間（SPEC A11）。"""
        self.queue = asyncio.Queue()
        self.tasks = [
            asyncio.create_task(self._worker()),
            asyncio.create_task(self._ticker()),
        ]
        await self.submit(self.restore)

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for conn in self.conns:
            conn.close()
        senders = [conn.sender for conn in self.conns if conn.sender is not None]
        if senders:
            await asyncio.wait(senders, timeout=1)
        self.tasks = []

    async def submit(self, operation: Callable[[], T]) -> T:
        """把工作排進單一 worker（CODING_RULES L1），等它做完。"""
        assert self.queue is not None
        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        await self.queue.put((operation, future))
        return await future

    async def in_thread(self, operation: Callable[[], T]) -> T:
        """慢的運算（scrypt、備份）不放在遊戲 worker（UI_RULES Q10）。"""
        return await asyncio.get_running_loop().run_in_executor(None, operation)

    async def _worker(self) -> None:
        assert self.queue is not None
        while True:
            operation, future = await self.queue.get()
            try:
                result = operation()
            except Exception as err:
                if not isinstance(err, GameError):
                    log.exception("worker error")
                if not future.done():
                    future.set_exception(err)
            else:
                if not future.done():
                    future.set_result(result)

    async def _ticker(self) -> None:
        async def on_tick() -> None:
            try:
                await self.submit(self.tick)
            except Exception:
                log.exception("tick error")

        while True:
            await asyncio.sleep(self.tick_seconds)
            await on_tick()

    @property
    def now(self) -> float:
        return self.clock.now()

    # ---- 開房與關房 ----

    def open_room(self, body: protocol.OpenRoom) -> Room:
        """開房（SPEC A4）。同時只有一間。"""
        if self.room is not None:
            raise GameError(ErrorCode.FORBIDDEN)
        password = body.password or f"{secrets.randbelow(10**config.ROOM_PASSWORD_DIGITS):04d}"
        seed = body.seed if config.DEV_MODE else None
        self.room = Room(
            id=uuid.uuid4().hex,
            mode=body.mode,
            name=body.name,
            password=password,
            settings=dict(body.settings),
            created_at=self.wall(),
            seed=seed,
        )
        self.db.write([_room_statement(self.room)])
        self.next_backup = self.now + config.BACKUP_INTERVAL_SECONDS
        self._room_log(f"room opened mode={body.mode.value}")
        return self.room

    def close_room(self) -> None:
        """關房（SPEC A4）：刪除資料庫內容、上傳檔、備份、該房紀錄檔；輪替紀錄保留。"""
        room = self.room
        if room is None:
            raise GameError(ErrorCode.NO_ROOM)
        for conn in list(self.conns):
            conn.send({"t": "room.closed"}, self.now)
            conn.close()
        self.db.delete_room(room.id)
        for folder in (self.paths.uploads, self.paths.backups):
            shutil.rmtree(folder, ignore_errors=True)
        (self.paths.logs / f"{room.id}.log").unlink(missing_ok=True)
        self._reset_memory()

    def _reset_memory(self) -> None:
        """關房時清空所有房間相關的快取與連線（CODING_RULES P11）。"""
        self.room = None
        self.engine = None
        self.players = {}
        self.pending_broadcasts = []
        self.sessions = {
            key: session for key, session in self.sessions.items() if key in self.admin_tokens
        }
        self.conns = []
        self.chat = deque(maxlen=_MEMORY_CHAT)
        self.disguised_chat = []
        self.media_rows = {}
        self.chat_seq = 0
        self.role_plan = {}
        self.chat_times = {}
        self.db_fails = 0
        self.presence = PresenceMonitor()
        self.host_gone_since = None
        self.last_offline = frozenset()
        self.bot_ids = []
        self.bot_brain = None

    def require_room(self) -> Room:
        if self.room is None:
            raise GameError(ErrorCode.NO_ROOM)
        return self.room

    # ---- 加入 ----

    def precheck_join(self, body: protocol.Join, name: str, ip: str) -> None:
        """加入前的快速檢查；通過才做昂貴的 scrypt。錯誤鎖定以裝置計（N13）。"""
        room = self.require_room()
        self.lockouts.check(body.device_id, name, ip, self.now)
        if not secrets.compare_digest(body.password, room.password):
            self.lockouts.fail(body.device_id, name, ip, self.now)
            raise GameError(ErrorCode.WRONG_PASSWORD)
        self._check_can_join(body.device_id, name)

    def _check_can_join(self, device_id: str, name: str) -> None:
        if len(self.players) >= config.ROOM_CAPACITY:
            raise GameError(ErrorCode.ROOM_FULL)
        if any(p.name == name for p in self.players.values()):
            raise GameError(ErrorCode.NAME_TAKEN)
        if any(p.device_id == device_id for p in self.players.values()):
            # 一支手機只能是一名玩家（SPEC A4）；要回原位請走「我回來了」
            raise GameError(ErrorCode.FORBIDDEN)

    def finish_join(
        self, body: protocol.Join, name: str, pin_hash: str, admin_token_hash: str | None
    ) -> dict[str, Any]:
        room = self.require_room()
        self._check_can_join(body.device_id, name)
        is_admin = admin_token_hash in self.admin_tokens and room.mode is Mode.AUTO
        seat = len([p for p in self.players.values() if not p.is_spectator]) + 1
        player = RoomPlayer(
            id=uuid.uuid4().hex[:12],
            device_id=body.device_id,
            name=name,
            pin_hash=pin_hash,
            seat=seat,
            join_order=max((p.join_order for p in self.players.values()), default=0) + 1,
            is_spectator=room.state != _LOBBY,
        )
        statements = [_player_statement(room.id, player)]
        if is_admin:
            room.admin_player_id = player.id
            room.narrator_id = room.narrator_id or player.id
            statements.append(_room_statement(room))
        self.players[player.id] = player
        token = auth.new_token()
        session = Session(auth.token_hash(token), player.id, is_admin, body.device_id)
        statements.append(_session_statement(room.id, session, self.wall()))
        self.db.write(statements)
        self.sessions[session.token_hash] = session
        self.broadcast_roster()
        return {
            "token": token,
            "player_id": player.id,
            "seat": seat,
            "is_spectator": player.is_spectator,
            "room": self.room_info(),
        }

    def lookup_rejoin(self, body: protocol.Rejoin, name: str, ip: str) -> str:
        """回傳該名字的 PIN 雜湊，讓呼叫端在執行緒池比對。"""
        self.require_room()
        self.lockouts.check(body.device_id, name, ip, self.now)
        player = self._player_by_name(name)
        if player is None:
            self.lockouts.fail(body.device_id, name, ip, self.now)
            raise GameError(ErrorCode.WRONG_PIN)
        return player.pin_hash

    def _player_by_name(self, name: str) -> RoomPlayer | None:
        return next((p for p in self.players.values() if p.name == name), None)

    def finish_rejoin(
        self, body: protocol.Rejoin, name: str, pin_ok: bool, new_hash: str | None, ip: str
    ) -> dict[str, Any]:
        """回原位：後登入擠掉前一台（SPEC A2）；管理員裝置同時取回管理權（B7）。"""
        room = self.require_room()
        player = self._player_by_name(name)
        if player is None or not pin_ok:
            self.lockouts.fail(body.device_id, name, ip, self.now)
            raise GameError(ErrorCode.WRONG_PIN)
        self.lockouts.success(body.device_id, name)
        for key, session in list(self.sessions.items()):
            if session.player_id == player.id:
                del self.sessions[key]
                self._close_session_conns(session, "replaced")
        player.device_id = body.device_id
        if new_hash is not None:
            player.pin_hash = new_hash
        token = auth.new_token()
        session = Session(
            auth.token_hash(token),
            player.id,
            room.admin_player_id == player.id,
            body.device_id,
        )
        self.db.write(
            [
                ("DELETE FROM session WHERE player_id=?", (player.id,)),
                _player_statement(room.id, player),
                _session_statement(room.id, session, self.wall()),
            ]
        )
        self.sessions[session.token_hash] = session
        return {
            "token": token,
            "player_id": player.id,
            "seat": player.seat,
            "is_spectator": player.is_spectator,
            "room": self.room_info(),
        }

    def _close_session_conns(self, session: Session, reason: str) -> None:
        for conn in list(self.conns):
            if conn.session is session:
                conn.send({"t": reason}, self.now)
                conn.close()

    # ---- 連線 ----

    def session_for(self, token: str) -> Session | None:
        return self.sessions.get(auth.token_hash(token))

    def connect(self, socket: Socket, session: Session) -> Connection:
        """WebSocket 認證通過後加入廣播名單，並送完整狀態（CODING_RULES P1）。"""
        viewer = self._viewer_of(session)
        conn = Connection(socket, session, viewer, self.now)
        conn.start()
        self.conns.append(conn)
        self._send_state(conn)
        self.broadcast_roster()
        return conn

    def disconnect(self, conn: Connection) -> None:
        conn.close()
        if conn in self.conns:
            self.conns.remove(conn)
            self.broadcast_roster()

    def _viewer_of(self, session: Session) -> views.Viewer:
        mode = self.room.mode if self.room else Mode.AUTO
        return views.viewer_for_mode(mode, session.player_id, session.is_admin)

    def _actor_of(self, session: Session) -> Actor:
        mode = self.room.mode if self.room else Mode.AUTO
        is_host = session.is_admin and session.player_id is None and mode is Mode.GOD
        return Actor(player_id=session.player_id, is_admin=session.is_admin, is_host=is_host)

    # ---- 訊息處理 ----

    def on_message(self, conn: Connection, raw: Any) -> None:
        """一則 WebSocket 訊息。例外不讓連線斷掉（CODING_RULES E3）。"""
        conn.last_seen = self.now
        msg_id = raw.get("msg_id") if isinstance(raw, dict) else None
        session = conn.session
        if isinstance(msg_id, str) and msg_id in session.recent:
            self._reply(conn, msg_id, session.recent[msg_id])  # L3：重複的回上次結果
            return
        code: ErrorCode | None = None
        try:
            frame = protocol.parse_client(raw)
            self._route(conn, frame)
        except GameError as err:
            code = err.code
        except Exception:
            log.exception("handler error")
            code = ErrorCode.INTERNAL_ERROR
        if isinstance(msg_id, str):
            session.remember(msg_id, code)
        self._reply(conn, msg_id if isinstance(msg_id, str) else None, code)

    def _reply(self, conn: Connection, msg_id: str | None, code: ErrorCode | None) -> None:
        if code is None:
            conn.send({"t": "ack", "msg_id": msg_id}, self.now)
        else:
            conn.send({"t": "error", "msg_id": msg_id, "code": code.value}, self.now)

    def _route(self, conn: Connection, frame: protocol.ClientFrame) -> None:
        kind = frame.t
        if kind == "ping":
            return
        if kind == "state.request":
            self._send_state(conn)
        elif kind == "prep.report":
            assert isinstance(frame, protocol.PrepReport)
            self._prep(conn, frame)
        elif kind == "chat.send":
            assert isinstance(frame, protocol.ChatSend)
            self._chat(conn, frame)
        elif kind == "wolf.schedule":
            assert isinstance(frame, protocol.WolfScheduleFrame)
            payload = {"slot": frame.slot, "due": next_clock_time(frame.time, self.wall()),
                       "text": frame.text}  # fmt: skip
            self._to_engine(conn, Action.WOLF_SCHEDULE, payload, None)
        elif kind == "chat.history":
            assert isinstance(frame, protocol.ChatHistory)
            self._chat_history(conn, frame)
        elif kind == "media.refresh":
            assert isinstance(frame, protocol.MediaRefresh)
            self._media_refresh(conn, frame)
        elif kind == "admin.seat":
            assert isinstance(frame, protocol.AdminSeat)
            self._admin_seat(conn, frame)
        elif kind == "admin.role":
            assert isinstance(frame, protocol.AdminRole)
            self._admin_role(conn, frame)
        elif kind == "admin.broadcast":
            assert isinstance(frame, protocol.AdminBroadcast)
            self._require_admin(conn.session)
            self.broadcast_to(
                frame.targets,
                frame.text,
                speak=frame.speak,
                sound=frame.sound,
                interval_s=frame.interval_s,
            )
        elif kind == "admin.start":
            self._admin_start(conn)
        elif kind == "admin.reset_pin":
            assert isinstance(frame, protocol.PlayerRef)
            self._admin_reset_pin(conn, frame)
        elif kind == "admin.narrator" and self.engine is None:
            assert isinstance(frame, protocol.PlayerRef)
            self._lobby_narrator(conn, frame)
        else:
            self._to_engine(conn, Action(kind), protocol.payload_of(frame), frame.step_seq)

    def _to_engine(
        self, conn: Connection, action: Action, payload: dict[str, Any], step_seq: int | None
    ) -> None:
        engine = self.engine
        if engine is None:
            raise GameError(ErrorCode.FORBIDDEN)
        actor = self._actor_of(conn.session)
        self._commit(lambda: engine.handle(actor, action, payload, step_seq))

    def _commit(self, compute: Callable[[], list[Event]]) -> None:
        """先在保存點上計算，交易成功才廣播；失敗則復原（CODING_RULES E4、總則 4）。"""
        engine = self.engine
        assert engine is not None
        point = engine.checkpoint()
        try:
            events = compute()
        except GameError:
            engine.revert(point)
            raise
        if not events:
            return
        try:
            self._persist(events)
        except Exception as err:
            log.exception("db write failed")
            engine.revert(point)
            self.db_fails += 1
            if self.db_fails >= config.DB_FAILS_BEFORE_PAUSE:
                self._pause_after_db_failure()
            raise GameError(ErrorCode.INTERNAL_ERROR) from err
        self.db_fails = 0
        self._after_events(events)
        self._broadcast_events(events)
        engine.forget_chat(len(events))

    def _pause_after_db_failure(self) -> None:
        """連續 3 次寫入失敗 → 系統暫停並警示（CODING_RULES E4）。"""
        engine = self.engine
        assert engine is not None
        log.error("資料庫連續寫入失敗，遊戲已系統暫停")
        events = engine.system_pause(PauseReason.SYSTEM)
        try:
            self._persist(events)
        except Exception:
            log.exception("db write failed while pausing")
        self._broadcast_events(events)

    def _persist(self, events: list[Event]) -> None:
        room = self.room
        engine = self.engine
        assert room is not None and engine is not None and room.game_id is not None
        statements = Database.event_statements(room.game_id, events)
        for event in events:
            if event.type is EventType.CHAT_SENT:
                statements.append(_chat_statement(room.id, {**event.data, "ts": event.ts}))
        if any(e.type is EventType.STEP_ENTERED for e in events):
            statements += Database.snapshot_statements(
                room.game_id, self.now, engine.state.model_dump_json()
            )
        if any(e.type is EventType.GAME_ENDED for e in events):
            winner = engine.state.winner
            assert winner is not None
            room.state = _ENDED
            room.ended_at = self.wall()
            statements.append(_room_statement(room))
            statements.append(
                (
                    "UPDATE game SET ended_at=?, winner=? WHERE id=?",
                    (room.ended_at, winner.value, room.game_id),
                )
            )
        self.db.write(statements)

    def _after_events(self, events: list[Event]) -> None:
        for event in events:
            if event.type is EventType.CHAT_SENT:
                row = {**event.data, "ts": event.ts}
                self.chat.append(row)
                self.chat_seq = max(self.chat_seq, row["id"])
                if row["disguise_period"] is not None or row["is_wolf_mask"]:
                    self.disguised_chat.append(row)
            elif event.type is EventType.NARRATE:
                self._notify_speaker(event.data)
            elif event.type is EventType.STEP_ENTERED:
                self._room_log(f"step {event.data['step']}")
            elif event.type is EventType.GAME_ENDED:
                self._room_log("game ended")
                self._schedule_close()
            elif event.type is EventType.PAUSED:
                self._request_backup()
            elif event.type is EventType.NARRATOR_SET and self.room is not None:
                self.room.narrator_id = event.data["player"]

    def _room_log(self, line: str) -> None:
        """每房間紀錄檔，關房一併刪除（CODING_RULES S7）。只寫步驟與 id，不寫秘密（S2）。"""
        room = self.room
        if room is None:
            return
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        with (self.paths.logs / f"{room.id}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{self.wall():.0f} {line}" + chr(10))

    def _schedule_close(self) -> None:
        room = self.require_room()
        room.closes_at = self.now + config.ROOM_END_SECONDS
        for conn in self.conns:
            conn.send({"t": "room.closing", "at": room.closes_at}, self.now)

    # ---- 廣播 ----

    def _decorate(self, message: dict[str, Any]) -> dict[str, Any]:
        """媒體只送簽章網址（CODING_RULES P6）。"""
        if message.get("t") == "chat.msg" and message.get("media_id"):
            message = {**message, "media_url": self.media_url(message["media_id"])}
        if message.get("t") == "state":
            message["chat"] = [self._decorate(m) for m in message.get("chat", [])]
            if "host" in message:
                message["host"]["next_line"] = self._next_host_line()
        if message.get("t") == "host.progress":
            message = {**message, "next_line": self._next_host_line()}
        return message

    def _next_host_line(self) -> str | None:
        """上帝控制台要高亮的下一句（SPEC C4 S20）；下一步是自動進行時回 None。"""
        engine = self.engine
        if engine is None or engine.state.step is Step.END:
            return None
        next_step = engine.next_step()
        if next_step is Step.END or engine.policy.should_advance(next_step):
            return None
        return STEP_LINES[next_step]

    def _broadcast_events(self, events: Iterable[Event]) -> None:
        engine = self.engine
        assert engine is not None
        state = engine.state
        now = self.now
        for event in events:
            public = views.public_messages(event, state)  # 每個事件只算一次（P2）
            full = event.type in (
                EventType.RESUMED,
                EventType.NOMINEES_SET,  # 選票清空，自己的已投狀態也要跟著換
                EventType.ROLLED_BACK,
                EventType.GAME_ENDED,
            )
            for conn in self.conns:
                if full:
                    self._send_state(conn)
                    continue
                messages = public + views.private_messages(event, conn.viewer, state)
                for message in messages:
                    conn.send(self._decorate(message), now)

    def _state_message(self, conn: Connection) -> dict[str, Any]:
        room = self.room
        chat = list(self.chat)[-config.CHAT_HISTORY_PAGE :]
        info = self.room_info() if room else None
        if self.engine is None:
            message = views.lobby_state(
                info, self.roster_rows(), conn.viewer, chat, conn.session.is_admin
            )
            if conn.session.is_admin:
                message |= views.role_plan_block(self.role_plan)
        else:
            message = views.build(
                self.engine.state, conn.viewer, chat, truth_chat=self.disguised_chat
            )
            message["phase"] = "game"
            message["room"] = info
            message["roster"] = self.roster_rows()
            message["is_admin"] = conn.session.is_admin
            if room is not None and room.closes_at is not None:
                message["closes_at"] = room.closes_at
        return self._fit(self._decorate(message))

    @staticmethod
    def _fit(message: dict[str, Any], key: str = "chat") -> dict[str, Any]:
        """單則不超過 64 KB（CODING_RULES N9）：太大就少帶舊聊天，用 chat.history 補。"""
        chat = message.get(key, [])
        while chat and len(json.dumps(message, ensure_ascii=False)) > config.WS_MAX_MESSAGE_BYTES:
            del chat[: max(1, len(chat) // 4)]
        return message

    def _send_state(self, conn: Connection) -> None:
        conn.send(self._state_message(conn), self.now)

    def room_info(self) -> dict[str, Any] | None:
        """房間公開資訊（不含密碼）。"""
        room = self.room
        if room is None:
            return None
        return {
            "id": room.id,
            "name": room.name,
            "mode": room.mode.value,
            "state": room.state,
            "settings": room.settings,
            "admin_player_id": room.admin_player_id,
            "narrator_id": room.narrator_id,
            "capacity": config.ROOM_CAPACITY,
        }

    def roster_rows(self) -> list[dict[str, Any]]:
        """玩家名單（SPEC C3）：只有離線標記，沒有最後上線時間（A9）。"""
        offline = self._offline_ids()
        rows = []
        for player in sorted(self.players.values(), key=lambda p: (p.is_spectator, p.seat)):
            avatar = player.avatar_media_id
            rows.append(
                {
                    "id": player.id,
                    "name": player.name,
                    "seat": player.seat,
                    "join_order": player.join_order,
                    "is_spectator": player.is_spectator,
                    "offline": player.id in offline,
                    "is_admin": self.room is not None and self.room.admin_player_id == player.id,
                    "prep": dict(player.prep),
                    "avatar_url": self.media_url(avatar) if avatar else None,
                }
            )
        return rows

    def broadcast_roster(self) -> None:
        rows = self.roster_rows()
        for conn in self.conns:
            conn.send(views.roster_message(rows), self.now)

    def media_url(self, media_id: str) -> str:
        resource = f"media/{media_id}"
        return f"/api/{resource}?{self.signer.query(resource, self.wall())}"

    # ---- 大廳與管理員 ----

    @staticmethod
    def _require_admin(session: Session) -> None:
        if not session.is_admin:
            raise GameError(ErrorCode.FORBIDDEN)

    def _admin_seat(self, conn: Connection, frame: protocol.AdminSeat) -> None:
        """排座位（SPEC A4）。L22：併發由 worker 序列化，後到者覆蓋。"""
        self._require_admin(conn.session)
        room = self.require_room()
        seated = {p.id for p in self.players.values() if not p.is_spectator}
        if room.state != _LOBBY or set(frame.order) != seated or len(frame.order) != len(seated):
            raise GameError(ErrorCode.INVALID_TARGET)
        for seat, player_id in enumerate(frame.order, start=1):
            self.players[player_id].seat = seat
        self.db.write([_player_statement(room.id, self.players[p]) for p in frame.order])
        self.broadcast_roster()

    def _seated_ids(self) -> list[str]:
        return [p.id for p in self.players.values() if not p.is_spectator]

    def _admin_role(self, conn: Connection, frame: protocol.AdminRole) -> None:
        """開局前指定玩家職業，沒指定的開局時隨機（SPEC v4.26）。

        只有管理員看得到（views.lobby_state），只存在記憶體：大廳時伺服器重啟就要重設。
        """
        self._require_admin(conn.session)
        room = self.require_room()
        seated = self._seated_ids()
        if room.state != _LOBBY or self.engine is not None or frame.player not in seated:
            raise GameError(ErrorCode.INVALID_TARGET)
        plan = {pid: role for pid, role in self.role_plan.items() if pid in seated}
        if frame.role is None:
            plan.pop(frame.player, None)
        else:
            plan[frame.player] = frame.role
        if not rules.plan_fits(len(seated), plan):
            raise GameError(ErrorCode.ROLE_PLAN_FULL)
        self.role_plan = plan
        for other in self.conns:
            if other.session.is_admin:
                self._send_state(other)

    def _notify_speaker(self, narrated: dict[str, Any]) -> None:
        """輪到誰發言，本人手機也念一次（SPEC C4）。他就是旁白主機時已經念過了。"""
        engine = self.engine
        if engine is None or narrated["line_id"] not in _SPEAKER_LINES or not narrated["speak"]:
            return
        speaker = engine.state.current_speaker
        if speaker is not None and speaker != engine.state.narrator_id:
            self.broadcast_to([speaker], narrated["text"])

    def broadcast_to(
        self,
        targets: Sequence[str],
        text: str,
        *,
        speak: bool = True,
        sound: str | None = None,
        interval_s: float = 0.0,
    ) -> None:
        """定向廣播（SPEC C4）：只送到指定玩家的手機，interval_s > 0 時依序一支接一支。

        管理員分頁與之後的遊戲場景都呼叫這裡。不影響遊戲狀態，所以不記事件；
        排隊中的廣播在伺服器重啟後就不送了，反正已經過時。對象不存在拋 invalid_target。
        夜晚只對部分玩家發可能洩漏身分，自動呼叫時要自己注意（SPEC A7）。
        """
        self.require_room()
        ordered = list(dict.fromkeys(targets))
        if any(player_id not in self.players for player_id in ordered):
            raise GameError(ErrorCode.INVALID_TARGET)
        message = views.broadcast_message(text, speak, sound)
        now = self.now
        for index, player_id in enumerate(ordered):
            if index and interval_s:
                due = now + index * interval_s
                self.pending_broadcasts.append((due, player_id, message))
            else:
                self._send_broadcast(player_id, message)

    def _send_broadcast(self, player_id: str, message: dict[str, Any]) -> None:
        for conn in self.conns:
            if conn.session.player_id == player_id:
                conn.send(message, self.now)

    def _flush_broadcasts(self, now: float) -> None:
        due = [item for item in self.pending_broadcasts if item[0] <= now]
        if due:
            self.pending_broadcasts = [i for i in self.pending_broadcasts if i[0] > now]
            for _, player_id, message in due:
                self._send_broadcast(player_id, message)

    def _admin_reset_pin(self, conn: Connection, frame: protocol.PlayerRef) -> None:
        """重設 PIN（SPEC A10）：清空後，他下次「我回來了」輸入的就是新 PIN。"""
        self._require_admin(conn.session)
        room = self.require_room()
        player = self.players.get(frame.player)
        if player is None:
            raise GameError(ErrorCode.INVALID_TARGET)
        player.pin_hash = ""
        self.db.write([_player_statement(room.id, player)])

    def _lobby_narrator(self, conn: Connection, frame: protocol.PlayerRef) -> None:
        self._require_admin(conn.session)
        room = self.require_room()
        if room.mode is not Mode.AUTO or frame.player not in self.players:
            raise GameError(ErrorCode.INVALID_TARGET)
        room.narrator_id = frame.player
        self.db.write([_room_statement(room)])
        for other in self.conns:
            other.send(views.narrator_message(frame.player), self.now)

    def _prep(self, conn: Connection, frame: protocol.PrepReport) -> None:
        player_id = conn.session.player_id
        if player_id is None or player_id not in self.players:
            return
        player = self.players[player_id]
        player.prep = {"wakelock": frame.wakelock, "pwa": frame.pwa}
        self.db.write([_player_statement(self.require_room().id, player)])
        self.broadcast_roster()

    def _pick_narrator(self, room: Room, seated: list[RoomPlayer]) -> str | None:
        """旁白主機：指定的 → 管理員 → 第一位真人。夜晚大家閉眼只能靠聲音，不能沒有人念。"""
        humans = [p.id for p in seated if p.id not in self.bot_ids]
        return room.narrator_id or room.admin_player_id or (humans[0] if humans else None)

    def _admin_start(self, conn: Connection) -> None:
        """開始遊戲（SPEC A8.1）：依當下人數發牌，人數鎖定；發牌即記入輪替（A5.7）。"""
        self._require_admin(conn.session)
        room = self.require_room()
        seated = sorted(
            (p for p in self.players.values() if not p.is_spectator), key=lambda p: p.seat
        )
        if room.state != _LOBBY or self.engine is not None:
            raise GameError(ErrorCode.FORBIDDEN)
        if not 6 <= len(seated) <= 20:
            raise GameError(ErrorCode.FORBIDDEN)
        wall = self.wall()
        history = self.db.load_role_history(((p.id, p.device_id, p.name) for p in seated), wall)
        plan = {p.id: self.role_plan[p.id] for p in seated if p.id in self.role_plan}
        # 指定後有人離開、人數變少，名額可能不夠了：請管理員先調整（SPEC v4.26）
        if not rules.plan_fits(len(seated), plan):
            raise GameError(ErrorCode.ROLE_PLAN_FULL)
        narrator = None if room.mode is Mode.GOD else self._pick_narrator(room, seated)
        engine = Engine.create(
            [(p.id, p.name) for p in seated],
            room.mode,
            history,
            self.clock,
            GameRng(room.seed),
            settings=room.settings,
            narrator_id=narrator,
            strict=self.strict,
            role_plan=plan,
        )
        self.role_plan = {}  # 只用在這一局，下一局重新隨機
        engine.chat_seq = self.chat_seq
        game_id = uuid.uuid4().hex
        room.game_id = game_id
        room.state = _PLAYING
        entries = [(p.device_id, p.name, engine.state.player(p.id).role) for p in seated]
        self.db.write(
            [
                _room_statement(room),
                (
                    "INSERT INTO game(id, room_id, started_at) VALUES(?,?,?)",
                    (game_id, room.id, wall),
                ),
                *self.db.role_history_statements(entries, wall),
                *Database.event_statements(game_id, engine.log),
                *Database.snapshot_statements(game_id, self.now, engine.state.model_dump_json()),
            ]
        )
        self.engine = engine
        for other in self.conns:
            self._send_state(other)
        self._commit(engine.post_intro)

    # ---- 聊天 ----

    def _chat(self, conn: Connection, frame: protocol.ChatSend) -> None:
        room = self.require_room()
        author = conn.session.player_id
        self._rate_limit(author or "host")
        if frame.media_id is not None and frame.media_id not in self.media_rows:
            raise GameError(ErrorCode.INVALID_TARGET)
        if self.engine is not None:
            self._to_engine(conn, Action.CHAT_SEND, protocol.payload_of(frame), None)
            return
        self._lobby_chat(room, conn, frame)

    def _lobby_chat(self, room: Room, conn: Connection, frame: protocol.ChatSend) -> None:
        """大廳：所有人可在公共頻道發言（SPEC A9）。"""
        if frame.channel is not Channel.PUBLIC:
            raise GameError(ErrorCode.FORBIDDEN)
        self.chat_seq += 1
        author = conn.session.player_id
        row: ChatRow = {
            "id": self.chat_seq,
            "channel": Channel.PUBLIC.value,
            "real_author": author,
            "display": author,
            "is_host": author is None,
            "disguise_period": None,
            "is_wolf_mask": False,
            "kind": ChatKind(frame.kind).value,
            "content": frame.content,
            "media_id": frame.media_id,
            "is_last_words": False,
            "ts": self.now,
        }
        self.db.write([_chat_statement(room.id, row)])
        self.chat.append(row)
        for other in self.conns:
            other.send(self._decorate(views.lobby_chat_message(row, other.viewer)), self.now)

    def _rate_limit(self, key: str) -> None:
        """每人每秒 3 則，以玩家計不以 IP 計（CODING_RULES N14）。"""
        times = self.chat_times.setdefault(key, deque())
        now = self.now
        while times and now - times[0] >= 1.0:
            times.popleft()
        if len(times) >= config.CHAT_PER_SECOND:
            raise GameError(ErrorCode.RATE_LIMITED)
        times.append(now)

    def _chat_history(self, conn: Connection, frame: protocol.ChatHistory) -> None:
        """往上捲動取更舊訊息（CODING_RULES P6）。"""
        room = self.require_room()
        rows = self.db.rows(
            "SELECT * FROM chat_message WHERE room_id=? AND channel=? AND id<? "
            "ORDER BY id DESC LIMIT ?",
            (room.id, frame.channel.value, frame.before_id, config.CHAT_HISTORY_PAGE),
        )
        visible = []
        for row in reversed(rows):
            message = self._view_chat(_chat_row(row), conn.viewer)
            if message is not None:
                visible.append(self._decorate(message))
        page = {"t": "chat.history", "channel": frame.channel.value, "messages": visible}
        conn.send(self._fit(page, "messages"), self.now)

    def _view_chat(self, row: ChatRow, viewer: views.Viewer) -> dict[str, Any] | None:
        if self.engine is None:
            return views.lobby_chat_message(row, viewer)
        return views.chat_message(row, viewer, self.engine.state)

    def _media_refresh(self, conn: Connection, frame: protocol.MediaRefresh) -> None:
        """簽章網址過期時重取（CODING_RULES N21）。"""
        if frame.media_id not in self.media_rows:
            raise GameError(ErrorCode.INVALID_TARGET)
        conn.send(
            {"t": "media.url", "media_id": frame.media_id, "url": self.media_url(frame.media_id)},
            self.now,
        )

    # ---- 媒體 ----

    def uploaded_bytes(self) -> int:
        return sum(row.size for row in self.media_rows.values())

    def register_media(self, session: Session, stored: media.StoredMedia) -> dict[str, Any]:
        room = self.require_room()
        self.media_rows[stored.id] = stored
        statements: list[tuple[str, tuple[Any, ...]]] = [
            (
                "INSERT INTO media(id, room_id, kind, path, bytes, mime) VALUES(?,?,?,?,?,?)",
                (stored.id, room.id, stored.kind.value, str(stored.path), stored.size, stored.mime),
            )
        ]
        if stored.kind is media.MediaKind.AVATAR and session.player_id in self.players:
            player = self.players[session.player_id]
            player.avatar_media_id = stored.id
            statements.append(_player_statement(room.id, player))
        self.db.write(statements)
        if stored.kind is media.MediaKind.AVATAR:
            self.broadcast_roster()
        return {"id": stored.id, "url": self.media_url(stored.id)}

    # ---- 計時 ----

    def tick(self) -> None:
        """每 250 ms：引擎時間推進、斷線判斷、結算倒數、定期備份（SPEC B4）。"""
        room = self.room
        if room is None:
            return
        now = self.now
        self._flush_broadcasts(now)
        if room.closes_at is not None and now >= room.closes_at:
            self.close_room()
            return
        engine = self.engine
        if engine is not None and not room.unrestorable:
            try:
                self._commit(engine.tick)
                if engine.state.wolf_schedules:
                    wall = self.wall()
                    self._commit(lambda: engine.send_wolf_schedules(wall))
            except GameError:
                log.warning("tick not persisted")
        if self.bot_ids:
            self._run_bots()
        if self.room is None:
            return
        if now >= self.next_presence:
            self.next_presence = now + config.PRESENCE_CHECK_SECONDS
            self._check_presence(now)
        if now >= self.next_backup:
            self._request_backup()

    # ---- 機器人：管理員在大廳加（SPEC v4.23 起正式店也開放） ----

    def _ensure_bot_brain(self, room: Room) -> None:
        from server.dev.bots import BotBrain

        if self.bot_brain is None:
            self.bot_brain = BotBrain(
                GameRng(room.seed),
                lambda: self.now,
                self._bot_send,
                speak_rate=0.05,
                chat_rate=0.0005,
            )

    def add_bots(self, count: int) -> list[str]:
        """加入 N 個機器人。名字用「機」加一個字元，符合 2 字規則。"""
        room = self.require_room()
        if room.state != _LOBBY:
            raise GameError(ErrorCode.FORBIDDEN)
        self._ensure_bot_brain(room)
        added = []
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        taken = {p.name for p in self.players.values()}
        names = (f"機{ch}" for ch in alphabet if f"機{ch}" not in taken)
        for _ in range(count):
            if len(self.players) >= config.ROOM_CAPACITY:
                break
            name = next(names)
            player = RoomPlayer(
                id=uuid.uuid4().hex[:12],
                device_id=f"bot-{name}",
                name=name,
                pin_hash="",
                seat=len([p for p in self.players.values() if not p.is_spectator]) + 1,
                join_order=max((p.join_order for p in self.players.values()), default=0) + 1,
            )
            self.players[player.id] = player
            self.bot_ids.append(player.id)
            added.append(player.id)
        self.db.write([_player_statement(room.id, self.players[p]) for p in added])
        self.broadcast_roster()
        return added

    def _run_bots(self) -> None:
        engine = self.engine
        if engine is None or engine.state.pause is not None or engine.state.step is Step.END:
            return
        for player_id in self.bot_ids:
            if self.engine is None or self.engine.state.step is Step.END:
                return
            viewer = views.Viewer(views.ViewerKind.PLAYER, player_id)
            self.bot_brain.turn(player_id, views.build(self.engine.state, viewer))

    def _bot_send(self, actor: Actor, action: Action, payload: dict[str, Any] | None) -> bool:
        engine = self.engine
        assert engine is not None
        step_seq = engine.state.step_seq
        try:
            self._commit(lambda: engine.handle(actor, action, payload or {}, step_seq))
        except GameError:
            return False
        return True

    def dev_state(self) -> dict[str, Any]:
        """狀態檢視器（CODING_RULES D4）。"""
        engine = self.engine
        return {
            "room": self.room_info(),
            "state": engine.state.model_dump(mode="json") if engine else None,
            "events": [e.model_dump(mode="json") for e in engine.log[-50:]] if engine else [],
        }

    def _offline_ids(self) -> frozenset[str]:
        now = self.now
        online = {
            conn.session.player_id
            for conn in self.conns
            if not conn.closed and now - conn.last_seen < _offline_after()
        }
        return frozenset(p for p in self.players if p not in online and p not in self.bot_ids)

    def _check_presence(self, now: float) -> None:
        offline = self._offline_ids()
        if offline != self.last_offline:
            self.last_offline = offline
            self.broadcast_roster()
        engine = self.engine
        if engine is None or engine.state.step is Step.END:
            return
        alive = [p.id for p in engine.state.players if p.alive]
        pause = engine.state.pause
        by_presence = pause is not None and pause.reason is PauseReason.PRESENCE
        action = self.presence.check(
            sum(1 for p in alive if p in offline), len(alive), now, by_presence
        )
        if action is PresenceAction.PAUSE:
            self._commit(lambda: engine.system_pause(PauseReason.PRESENCE))
        elif action is PresenceAction.RESUME:
            self._commit(engine.schedule_resume)
        self._check_host(engine, now)

    def _check_host(self, engine: Engine, now: float) -> None:
        """上帝主持人斷線超過 30 秒寬限自動暫停（SPEC A11）。"""
        if engine.state.mode is not Mode.GOD:
            return
        host_online = any(
            conn.viewer.kind is views.ViewerKind.HOST
            and not conn.closed
            and now - conn.last_seen < _offline_after()
            for conn in self.conns
        )
        if host_online:
            self.host_gone_since = None
            return
        if self.host_gone_since is None:
            self.host_gone_since = now
        if now - self.host_gone_since >= config.HOST_OFFLINE_GRACE_SECONDS:
            self._commit(lambda: engine.system_pause(PauseReason.HOST_OFFLINE))

    def _request_backup(self) -> None:
        """每 10 分鐘及每次暫停備份，保留 10 份（SPEC A11）；在背景執行緒做（P8）。"""
        self.next_backup = self.now + config.BACKUP_INTERVAL_SECONDS
        if self.room is None or (self.backup_task is not None and not self.backup_task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._backup_now()
            return
        self.backup_task = loop.run_in_executor(None, self._backup_now)

    def _backup_now(self) -> None:
        folder = self.paths.backups
        folder.mkdir(parents=True, exist_ok=True)
        self.db.backup_to(folder / f"{int(self.wall() * 1000)}.db")
        files = sorted(folder.glob("*.db"), key=lambda p: p.name)
        for old in files[: -config.BACKUP_KEEP]:
            old.unlink(missing_ok=True)

    # ---- 重啟還原 ----

    def restore(self) -> None:
        """重啟還原（SPEC A11）：讀事件重播 → 系統暫停。讀不懂就拒絕還原（G4）。"""
        rows = self.db.rows("SELECT * FROM room ORDER BY created_at DESC LIMIT 1")
        if not rows:
            return
        row = rows[0]
        room = Room(
            id=row["id"],
            mode=Mode(row["mode"]),
            name=row["name"],
            password=row["password"],
            settings=json.loads(row["settings_json"]),
            state=row["state"],
            admin_player_id=row["admin_player_id"],
            narrator_id=row["narrator_id"],
            created_at=row["created_at"],
            ended_at=row["ended_at"],
            seed=row["seed"],
        )
        self.room = room
        self._restore_people(room)
        self._restore_chat_and_media(room)
        game_rows = self.db.rows(
            "SELECT id FROM game WHERE room_id=? ORDER BY started_at DESC LIMIT 1", (room.id,)
        )
        if game_rows:
            room.game_id = game_rows[0]["id"]
            self._restore_engine(room)
        if room.state == _ENDED:
            room.closes_at = self.now + config.ROOM_END_SECONDS
        self.next_backup = self.now + config.BACKUP_INTERVAL_SECONDS

    def _restore_people(self, room: Room) -> None:
        for row in self.db.rows("SELECT * FROM player WHERE room_id=?", (room.id,)):
            self.players[row["id"]] = RoomPlayer(
                id=row["id"],
                device_id=row["device_id"],
                name=row["name"],
                pin_hash=row["pin_hash"],
                seat=row["seat"],
                join_order=row["join_order"],
                is_spectator=bool(row["is_spectator"]),
                avatar_media_id=row["avatar_media_id"],
                prep=json.loads(row["prep_json"]),
            )
        # 機器人名單只在記憶體：重啟後要認回來，否則被當成斷線的真人，觸發斷線暫停且解不開
        self.bot_ids = [p.id for p in self.players.values() if _is_bot(p)]
        if self.bot_ids:
            self._ensure_bot_brain(room)
        for row in self.db.rows("SELECT * FROM session WHERE room_id=?", (room.id,)):
            self.sessions[row["token_hash"]] = Session(
                row["token_hash"], row["player_id"], bool(row["is_admin"]), row["device_id"]
            )

    def _restore_chat_and_media(self, room: Room) -> None:
        for row in self.db.rows("SELECT * FROM media WHERE room_id=?", (room.id,)):
            self.media_rows[row["id"]] = media.StoredMedia(
                id=row["id"],
                kind=media.MediaKind(row["kind"]),
                path=Path(row["path"]),
                size=row["bytes"],
                mime=row["mime"],
            )
        rows = self.db.rows(
            "SELECT * FROM chat_message WHERE room_id=? ORDER BY id DESC LIMIT ?",
            (room.id, _MEMORY_CHAT),
        )
        for row in reversed(rows):
            self.chat.append(_chat_row(row))
        top = self.db.rows("SELECT MAX(id) AS m FROM chat_message WHERE room_id=?", (room.id,))
        self.chat_seq = top[0]["m"] or 0
        disguised = self.db.rows(
            "SELECT * FROM chat_message WHERE room_id=? "
            "AND (disguise_period_id IS NOT NULL OR is_wolf_mask=1) "
            "ORDER BY id",
            (room.id,),
        )
        self.disguised_chat = [_chat_row(row) for row in disguised]

    def _restore_engine(self, room: Room) -> None:
        assert room.game_id is not None
        try:
            events = [
                Event.model_validate(raw)
                for raw in upgrade_events(self.db.load_event_rows(room.game_id))
            ]
        except SchemaTooNew:
            room.unrestorable = True
            log.error("存檔版本不相容，無法還原；請管理員關房")
            return
        engine = Engine.restore(events, self.clock, GameRng(room.seed), strict=self.strict)
        engine.chat_seq = self.chat_seq
        engine.load_history(
            [(ts, upgrade_snapshot(raw)) for ts, raw in self.db.load_snapshots(room.game_id)]
        )
        new_events = engine.log[len(events) :]
        if new_events:
            self.db.write(Database.event_statements(room.game_id, new_events))
        self.engine = engine


def _offline_after() -> float:
    """離線門檻。時間加速時手機的 ping 仍是真實秒數，門檻要跟著放大（CODING_RULES D2）。"""
    return config.OFFLINE_AFTER_SECONDS * config.TIME_SCALE


def _room_statement(room: Room) -> tuple[str, tuple[Any, ...]]:
    return (
        "INSERT OR REPLACE INTO room(id, mode, name, password, settings_json, admin_player_id, "
        "state, created_at, ended_at, seed, narrator_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            room.id,
            room.mode.value,
            room.name,
            room.password,
            json.dumps(room.settings),
            room.admin_player_id,
            room.state,
            room.created_at,
            room.ended_at,
            room.seed,
            room.narrator_id,
        ),
    )


def next_clock_time(hhmm: str, wall: float) -> float:
    """「22:35」換成下一次到這個時刻的 epoch 秒；今天已經過了就是明天（家裡電腦的時區）。"""
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.fromtimestamp(wall)
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due.timestamp() <= wall:
        due += timedelta(days=1)
    return due.timestamp()


def _is_bot(player: RoomPlayer) -> bool:
    """機器人沒有 PIN；真人加入一定要設 PIN，所以光改裝置 ID 冒充不了。"""
    return player.pin_hash == "" and player.device_id.startswith("bot-")


def _player_statement(room_id: str, player: RoomPlayer) -> tuple[str, tuple[Any, ...]]:
    return (
        "INSERT OR REPLACE INTO player(id, room_id, device_id, name, avatar_media_id, pin_hash, "
        "seat, is_spectator, prep_json, join_order) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            player.id,
            room_id,
            player.device_id,
            player.name,
            player.avatar_media_id,
            player.pin_hash,
            player.seat,
            int(player.is_spectator),
            json.dumps(player.prep),
            player.join_order,
        ),
    )


def _session_statement(
    room_id: str, session: Session, created_at: float
) -> tuple[str, tuple[Any, ...]]:
    return (
        "INSERT INTO session(token_hash, room_id, player_id, is_admin, device_id, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (
            session.token_hash,
            room_id,
            session.player_id,
            int(session.is_admin),
            session.device_id,
            created_at,
        ),
    )


def _chat_statement(room_id: str, row: ChatRow) -> tuple[str, tuple[Any, ...]]:
    return (
        "INSERT INTO chat_message(id, room_id, channel, real_author_id, is_last_words, "
        "display_player_id, is_host, disguise_period_id, is_wolf_mask, kind, content, media_id, "
        "ts) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["id"],
            room_id,
            row["channel"],
            row["real_author"],
            int(row["is_last_words"]),
            row["display"],
            int(row["is_host"]),
            row["disguise_period"],
            int(row["is_wolf_mask"]),
            row["kind"],
            row["content"],
            row["media_id"],
            row["ts"],
        ),
    )


def _chat_row(row: Any) -> ChatRow:
    return {
        "id": row["id"],
        "channel": row["channel"],
        "real_author": row["real_author_id"],
        "display": row["display_player_id"],
        "is_host": bool(row["is_host"]),
        "disguise_period": row["disguise_period_id"],
        "is_wolf_mask": bool(row["is_wolf_mask"]),
        "kind": row["kind"],
        "content": row["content"],
        "media_id": row["media_id"],
        "is_last_words": bool(row["is_last_words"]),
        "ts": row["ts"],
    }
