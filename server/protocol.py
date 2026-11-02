"""訊息格式的唯一來源（CODING_RULES R5、E1）。多餘欄位、型別錯誤一律 bad_request。

web/js/protocol.js 由 scripts/gen_protocol.py 依本檔產生，不手改。
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from server import balance, config
from server.enums import Channel, ChatKind, Mode
from server.errors import ErrorCode, GameError

Id = Annotated[str, Field(min_length=1, max_length=64)]
NAME_GRAPHEMES: Final = 2
_ZERO_WIDTH = frozenset("​‌‍⁠﻿")


def clean_text(text: str) -> str:
    """去掉前後空白、零寬字元與控制字元（UI_RULES K9）。"""
    kept = (
        ch
        for ch in text
        if ch not in _ZERO_WIDTH and (unicodedata.category(ch) != "Cc" or ch == "\n")
    )
    return "".join(kept).strip()


def _is_name_char(ch: str) -> bool:
    # 只允許中日韓文字、英文字母、數字；組合字元與 emoji 都不是這些類別（SPEC B8、L21）
    if ch.isascii():
        return ch.isalnum()
    return unicodedata.category(ch) == "Lo" and "CJK" in unicodedata.name(ch, "")


def validate_name(raw: str) -> str:
    """名字驗證（SPEC B8、CODING_RULES L21）：清理、正規化後恰 2 字且字元合法。"""
    name = unicodedata.normalize("NFKC", clean_text(raw))
    if len(name) != NAME_GRAPHEMES or not all(_is_name_char(ch) for ch in name):
        raise GameError(ErrorCode.NAME_INVALID)
    return name


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ClientFrame(_Strict):
    """客戶端訊息外框（SPEC B7）。"""

    t: str
    msg_id: Id
    step_seq: int | None = None


class AuthMsg(_Strict):
    t: str = "auth"
    token: str = Field(min_length=1, max_length=256)
    client_version: int


class Empty(ClientFrame):
    """沒有其他欄位的訊息。"""


class PrepReport(ClientFrame):
    wakelock: bool = False
    pwa: bool = False


class ChatSend(ClientFrame):
    channel: Channel
    as_: str = Field(default="self", alias="as", pattern="^(self|disguise|wolf)$")
    kind: ChatKind = ChatKind.TEXT
    content: str | None = Field(default=None, max_length=config.CHAT_MAX_CHARS * 2)
    media_id: Id | None = None

    @field_validator("content")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value)


class WolfScheduleFrame(ClientFrame):
    """狼人定時電子音：時間用 HH:MM，伺服器換成下一次到的現實時間（SPEC v4.24）。"""

    slot: int = Field(ge=0, lt=balance.WOLF_SCHEDULE_SLOTS)
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    text: str = Field(min_length=1, max_length=config.CHAT_MAX_CHARS * 2)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned or len(cleaned) > config.CHAT_MAX_CHARS:
            raise ValueError("empty")
        return cleaned


class SlotRef(ClientFrame):
    slot: int = Field(ge=0, lt=balance.WOLF_SCHEDULE_SLOTS)


class AdminBroadcast(ClientFrame):
    targets: list[Id] = Field(min_length=1, max_length=config.ROOM_CAPACITY)
    text: str = Field(min_length=1, max_length=config.CHAT_MAX_CHARS)
    speak: bool = True
    sound: Id | None = None  # 音效代號，P8 有素材才用；手機端目前略過
    interval_s: float = Field(default=0, ge=0, le=config.BROADCAST_MAX_INTERVAL_SECONDS)

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("empty")
        return cleaned


class ChatHistory(ClientFrame):
    channel: Channel
    before_id: int


class MediaRefresh(ClientFrame):
    media_id: Id


class WolfPick(ClientFrame):
    target: Id | None = None
    clear: bool = False


class Target(ClientFrame):
    target: Id


class OptionalTarget(ClientFrame):
    target: Id | None = None


class WitchAct(ClientFrame):
    save: bool = False
    poison: Id | None = None


class PlayerRef(ClientFrame):
    player: Id


class AdminSeat(ClientFrame):
    order: list[Id] = Field(max_length=config.ROOM_CAPACITY)


class HostLine(ClientFrame):
    line_id: Id
    speak: bool = True


class HostReplay(ClientFrame):
    line_id: Id


class HostExtend(ClientFrame):
    s: int = Field(default=balance.HOST_EXTEND_SECONDS, gt=0, le=balance.COUNTDOWN_MAX_SECONDS)


class HostSetAlive(ClientFrame):
    player: Id
    alive: bool


CLIENT_MESSAGES: Final[dict[str, type[ClientFrame]]] = {
    "ping": Empty,
    "state.request": Empty,
    "deal.ack": Empty,
    "prep.report": PrepReport,
    "narrator.takeover": Empty,
    "chat.send": ChatSend,
    "wolf.schedule": WolfScheduleFrame,
    "wolf.unschedule": SlotRef,
    "chat.history": ChatHistory,
    "media.refresh": MediaRefresh,
    "wolf.pick": WolfPick,
    "seer.check": Target,
    "seer.ok": Empty,
    "witch.act": WitchAct,
    "hunter.shoot": OptionalTarget,
    "speak.end": Empty,
    "vote.cast": OptionalTarget,
    "admin.seat": AdminSeat,
    "admin.start": Empty,
    "admin.end": Empty,
    "admin.pause": Empty,
    "admin.resume": Empty,
    "admin.narrator": PlayerRef,
    "admin.broadcast": AdminBroadcast,
    "admin.reset_pin": PlayerRef,
    "host.line": HostLine,
    "host.replay": HostReplay,
    "host.next": Empty,
    "host.skip_speaker": Empty,
    "host.extend": HostExtend,
    "host.rollback": Empty,
    "host.set_alive": HostSetAlive,
    "host.reshow_card": PlayerRef,
}


def parse_client(raw: Any) -> ClientFrame:
    """解析客戶端訊息；格式不對拋 bad_request（CODING_RULES E1）。"""
    if not isinstance(raw, dict) or raw.get("t") not in CLIENT_MESSAGES:
        raise GameError(ErrorCode.BAD_REQUEST)
    try:
        model = CLIENT_MESSAGES[raw["t"]].model_validate(raw)
    except ValidationError as err:
        raise GameError(ErrorCode.BAD_REQUEST) from err
    if isinstance(model, ChatSend):
        _check_chat(model)
    return model


def _check_chat(msg: ChatSend) -> None:
    if msg.kind in (ChatKind.TEXT, ChatKind.TTS):
        if not msg.content or len(msg.content) > config.CHAT_MAX_CHARS or msg.media_id:
            raise GameError(ErrorCode.BAD_REQUEST)
    elif msg.media_id is None or msg.content:
        raise GameError(ErrorCode.BAD_REQUEST)


def payload_of(msg: ClientFrame) -> dict[str, Any]:
    """去掉外框後的內容，交給引擎。"""
    return msg.model_dump(mode="json", by_alias=True, exclude={"t", "msg_id", "step_seq"})


# ---- HTTP ----


class AdminLogin(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    device_id: Id = "admin"


class OpenRoom(_Strict):
    mode: Mode
    name: str = Field(min_length=1, max_length=20)
    password: str | None = Field(default=None, pattern=r"^\d{4}$")
    settings: dict[str, int] = Field(default_factory=dict)
    seed: int | None = None

    @field_validator("settings")
    @classmethod
    def _clamp(cls, value: dict[str, int]) -> dict[str, int]:
        # UI_RULES 2.2：每項 10–300 秒
        allowed = {"night", "speak", "vote", "hunter", "last_words", "deal"}
        out: dict[str, int] = {}
        for key, seconds in value.items():
            if key in allowed:
                low, high = balance.COUNTDOWN_MIN_SECONDS, balance.COUNTDOWN_MAX_SECONDS
                out[key] = max(low, min(high, seconds))
            else:
                raise ValueError(f"unknown setting {key}")
        return out


class ChangePassword(_Strict):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class Join(_Strict):
    password: str = Field(pattern=r"^\d{4}$")
    name: str = Field(min_length=1, max_length=32)
    pin: str = Field(pattern=r"^\d{4}$")
    device_id: Id


class Rejoin(_Strict):
    name: str = Field(min_length=1, max_length=32)
    pin: str = Field(pattern=r"^\d{4}$")
    device_id: Id
