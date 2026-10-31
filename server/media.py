"""上傳檔與簽章網址（SPEC B1、B8、CODING_RULES E5、E8、P7、N21）。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import shutil
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from server import config
from server.errors import ErrorCode, GameError


class MediaKind(StrEnum):
    PHOTO = "photo"
    VOICE = "voice"
    AVATAR = "avatar"


@dataclass(frozen=True)
class StoredMedia:
    id: str
    kind: MediaKind
    path: Path
    size: int
    mime: str


_MAX_BYTES = {
    MediaKind.PHOTO: config.PHOTO_MAX_BYTES,
    MediaKind.AVATAR: config.PHOTO_MAX_BYTES,
    MediaKind.VOICE: config.VOICE_MAX_BYTES,
}


def sniff_mime(head: bytes, kind: MediaKind) -> str | None:
    """依檔頭判斷實際格式（SPEC B8），不信任檔名與前端宣告。"""
    if kind is MediaKind.VOICE:
        if head[4:8] == b"ftyp":
            return "audio/mp4"
        if head[:4] == b"\x1aE\xdf\xa3":
            return "audio/webm"
        if head[:4] == b"OggS":
            return "audio/ogg"
        return None
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def save_upload(
    data: bytes,
    kind: MediaKind,
    used_bytes: int,
    uploads_dir: Path = config.UPLOADS_DIR,
    min_free: int = config.MIN_FREE_DISK_BYTES,
) -> StoredMedia:
    """先寫暫存檔，驗證後才搬到正式位置；任何一步失敗都刪暫存檔（CODING_RULES E8）。"""
    uploads_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(uploads_dir).free < min_free:
        raise GameError(ErrorCode.STORAGE_FULL)
    if len(data) > _MAX_BYTES[kind]:
        raise GameError(ErrorCode.FILE_TOO_LARGE)
    if used_bytes + len(data) > config.ROOM_UPLOAD_MAX_BYTES:
        raise GameError(ErrorCode.STORAGE_FULL)
    media_id = uuid.uuid4().hex
    temp = uploads_dir / f"{media_id}.tmp"
    temp.write_bytes(data)
    try:
        mime = sniff_mime(data[:16], kind)
        if mime is None:
            raise GameError(ErrorCode.FILE_INVALID)
        final = uploads_dir / media_id
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)
    return StoredMedia(id=media_id, kind=kind, path=final, size=len(data), mime=mime)


class Signer:
    """簽章短效網址（SPEC B1）。金鑰每次啟動重新產生；舊網址失效時前端會重取（N21）。"""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or secrets.token_bytes(32)

    def _digest(self, resource: str, exp: int) -> str:
        message = f"{resource}|{exp}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def query(self, resource: str, now: float) -> str:
        """回傳 `exp=...&sig=...`。"""
        exp = int(now) + config.SIGNED_URL_SECONDS
        return f"exp={exp}&sig={self._digest(resource, exp)}"

    def verify(self, resource: str, exp: int, sig: str, now: float) -> bool:
        return now <= exp and hmac.compare_digest(self._digest(resource, exp), sig)
