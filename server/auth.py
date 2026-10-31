"""帳密、PIN、token、鎖定（SPEC B8、CODING_RULES S5、N13–N15）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import defaultdict, deque
from pathlib import Path

from server import config
from server.errors import ErrorCode, GameError


def hash_secret(secret: str) -> str:
    """scrypt 雜湊。刻意很慢，呼叫端要丟執行緒池（UI_RULES Q10）。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        secret.encode(),
        salt=salt,
        n=config.SCRYPT_N,
        r=config.SCRYPT_R,
        p=config.SCRYPT_P,
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_secret(secret: str, stored: str) -> bool:
    """常數時間比對（CODING_RULES S5）。"""
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.scrypt(
        secret.encode(), salt=salt, n=config.SCRYPT_N, r=config.SCRYPT_R, p=config.SCRYPT_P
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_token() -> str:
    """32 bytes 隨機 token；伺服器只存雜湊（SPEC B8）。"""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AdminStore:
    """管理員帳號，存本機 JSON，不進 git（SPEC A4）。"""

    def __init__(self, path: Path = config.ADMIN_FILE) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        """讀設定檔；不存在或格式錯誤拋 RuntimeError，伺服器拒絕啟動（CODING_RULES E7）。"""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"username": str(data["username"]), "password_hash": str(data["password_hash"])}
        except (OSError, ValueError, KeyError, TypeError) as err:
            raise RuntimeError(
                "找不到管理員設定，請先執行 python -m server.setup_admin（之後可用 setup.bat）"
            ) from err

    def save(self, username: str, password: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"username": username, "password_hash": hash_secret(password)}
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def verify(self, username: str, password: str) -> bool:
        data = self.load()
        name_ok = hmac.compare_digest(username, data["username"])
        return verify_secret(password, data["password_hash"]) and name_ok


class Lockouts:
    """密碼錯誤鎖定：以裝置＋名字為主，IP 只做寬鬆上限（CODING_RULES N13）。"""

    def __init__(self) -> None:
        self._fails: dict[str, int] = defaultdict(int)
        self._until: dict[str, float] = {}
        self._ip_fails: dict[str, deque[float]] = defaultdict(deque)
        self._ip_until: dict[str, float] = {}

    def check(self, device_id: str, name: str, ip: str, now: float) -> None:
        """被鎖定就拋 locked，訊息帶剩餘秒數。"""
        key = f"{device_id}|{name}"
        until = max(self._until.get(key, 0.0), self._ip_until.get(ip, 0.0))
        if now < until:
            raise GameError(ErrorCode.LOCKED, str(int(until - now) + 1))

    def fail(self, device_id: str, name: str, ip: str, now: float) -> None:
        key = f"{device_id}|{name}"
        self._fails[key] += 1
        if self._fails[key] >= config.LOCK_MAX_FAILS:
            self._until[key] = now + config.LOCK_SECONDS
            self._fails[key] = 0
        recent = self._ip_fails[ip]
        recent.append(now)
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= config.IP_MAX_FAILS_PER_MINUTE:
            self._ip_until[ip] = now + config.LOCK_SECONDS
            recent.clear()

    def success(self, device_id: str, name: str) -> None:
        self._fails.pop(f"{device_id}|{name}", None)
