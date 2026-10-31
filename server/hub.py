"""連線與送出佇列（CODING_RULES N5、N8、UI_RULES Q11）：慢的手機不能拖累大家。"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from server import config
from server.errors import ErrorCode
from server.views import Viewer


class Socket(Protocol):
    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass
class Session:
    token_hash: str
    player_id: str | None
    is_admin: bool
    device_id: str
    recent: OrderedDict[str, ErrorCode | None] = field(default_factory=OrderedDict)

    def remember(self, msg_id: str, result: ErrorCode | None) -> None:
        """記住最近的 msg_id（CODING_RULES L3），有上限（P11）。"""
        self.recent[msg_id] = result
        while len(self.recent) > config.MSG_ID_MEMORY:
            self.recent.popitem(last=False)


class Connection:
    """一條 WebSocket。seq 每條連線各自編號，跳號才不會洩漏私密事件（SPEC B7）。"""

    def __init__(self, socket: Socket, session: Session, viewer: Viewer, now: float) -> None:
        self.socket = socket
        self.session = session
        self.viewer = viewer
        self.last_seen = now
        self.seq = 0
        self.closed = False
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=config.SEND_QUEUE_LIMIT)
        self.sender: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.sender = asyncio.create_task(self._send_loop())

    def send(self, message: dict[str, Any], server_ts: float) -> None:
        """排入送出佇列；滿了就斷開，讓它重連後取完整狀態（CODING_RULES N8）。"""
        if self.closed:
            return
        self.seq += 1
        frame = {**message, "seq": self.seq, "server_ts": server_ts}
        try:
            self.queue.put_nowait(json.dumps(frame, ensure_ascii=False))
        except asyncio.QueueFull:
            self.close()

    def close(self) -> None:
        """關閉連線；已排入的訊息會先送完。"""
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            if self.sender is not None:
                self.sender.cancel()

    async def _send_loop(self) -> None:
        try:
            while True:
                text = await self.queue.get()
                if text is None:
                    break
                await asyncio.wait_for(
                    self.socket.send_text(text), timeout=config.SEND_TIMEOUT_SECONDS
                )
        except (TimeoutError, RuntimeError, OSError, asyncio.CancelledError):
            self.closed = True
        except Exception:  # websockets 斷線的例外種類很多，一律視為斷線（CODING_RULES E3）
            self.closed = True
        finally:
            try:
                await asyncio.wait_for(self.socket.close(), timeout=config.SEND_TIMEOUT_SECONDS)
            except Exception:
                self.closed = True
