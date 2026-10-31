"""錯誤碼與例外（CODING_RULES 3.3）。錯誤只說「做不到什麼」，不說原因中的秘密（E9）。"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    STALE_STEP = "stale_step"
    STEP_NOT_OPEN = "step_not_open"
    INVALID_TARGET = "invalid_target"
    DEADLINE_PASSED = "deadline_passed"
    ROOM_FULL = "room_full"
    ROOM_CLOSED = "room_closed"
    NO_ROOM = "no_room"
    NAME_INVALID = "name_invalid"
    NAME_TAKEN = "name_taken"
    WRONG_PASSWORD = "wrong_password"
    WRONG_PIN = "wrong_pin"
    LOCKED = "locked"
    BANNED = "banned"
    RATE_LIMITED = "rate_limited"
    STORAGE_FULL = "storage_full"
    FILE_INVALID = "file_invalid"
    FILE_TOO_LARGE = "file_too_large"
    VERSION_MISMATCH = "version_mismatch"
    INTERNAL_ERROR = "internal_error"


class GameError(Exception):
    """預期內的錯誤：回傳錯誤碼給該玩家，連線保持（CODING_RULES E3）。"""

    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(detail or code.value)
        self.code = code


class IllegalTransition(Exception):
    """轉移表外的狀態轉移，屬程式錯誤（CODING_RULES L6）。"""


class InvariantBroken(Exception):
    """不變式被破壞（CODING_RULES 2.4）。訊息只放玩家 id 與步驟，不放秘密（S2）。"""
