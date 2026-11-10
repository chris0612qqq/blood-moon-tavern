"""集中設定（CODING_RULES R6）。數值可被房間設定覆蓋；功能開關只放 FEATURES。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent
DATA_DIR: Final = Path(os.environ.get("BMT_DATA_DIR", ROOT / "data"))
UPLOADS_DIR: Final = DATA_DIR / "uploads"
BACKUP_DIR: Final = DATA_DIR / "backup"
LOGS_DIR: Final = DATA_DIR / "logs"
DB_PATH: Final = DATA_DIR / "game.db"
LOCAL_ASSETS_DIR: Final = ROOT / "local_assets"
WEB_DIR: Final = ROOT / "web"
ADMIN_FILE: Final = Path(os.environ.get("BMT_ADMIN_FILE", ROOT / "server" / "admin.local.json"))
VERSION: Final = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

HOST: Final = "127.0.0.1"
PORT: Final = 8765
PROTOCOL_VERSION: Final = 12

DEV_MODE: Final = os.environ.get("DEV_MODE") == "1"
TIME_SCALE: Final = float(os.environ.get("TIME_SCALE", "1")) if DEV_MODE else 1.0

# 功能開關（CODING_RULES R6）：新功能先關著做完、試玩後再打開
FEATURES: Final[dict[str, bool]] = {
    "ambient_sound": True,
}

# 房間與連線
ROOM_CAPACITY: Final = 20
ROOM_END_SECONDS: Final = 600
TICK_SECONDS: Final = 0.25
DEADLINE_GRACE_SECONDS: Final = 0.3
MSG_ID_MEMORY: Final = 50
SNAPSHOT_KEEP: Final = 20
ROOM_PASSWORD_DIGITS: Final = 4
PIN_DIGITS: Final = 4
ALLOWED_ORIGINS: Final = (
    "https://chris0612qqq.github.io",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
)

# 網路（CODING_RULES N7、N8、SPEC B1）
PING_SECONDS: Final = 5
OFFLINE_AFTER_SECONDS: Final = 15
SEND_QUEUE_LIMIT: Final = 200
SEND_TIMEOUT_SECONDS: Final = 2.0
WS_MAX_MESSAGE_BYTES: Final = 64 * 1024
CHAT_HISTORY_PAGE: Final = 100

# 斷線暫停（SPEC A11、B5）
PRESENCE_CHECK_SECONDS: Final = 2
PRESENCE_HOLD_SECONDS: Final = 10
PRESENCE_RATIO: Final = 0.5
HOST_OFFLINE_GRACE_SECONDS: Final = 30

# 安全（SPEC B8、CODING_RULES N13–N14）
LOCK_MAX_FAILS: Final = 5
LOCK_SECONDS: Final = 60
IP_MAX_FAILS_PER_MINUTE: Final = 60
CHAT_PER_SECOND: Final = 3
CHAT_MAX_CHARS: Final = 500
BROADCAST_MAX_INTERVAL_SECONDS: Final = 30
SCRYPT_N: Final = 2**14
SCRYPT_R: Final = 8
SCRYPT_P: Final = 1
SIGNED_URL_SECONDS: Final = 3600

# 上傳（SPEC B8、CODING_RULES E5、P7）
PHOTO_MAX_BYTES: Final = 5 * 1024 * 1024
VOICE_MAX_BYTES: Final = 2 * 1024 * 1024
ROOM_UPLOAD_MAX_BYTES: Final = 300 * 1024 * 1024
MIN_FREE_DISK_BYTES: Final = 200 * 1024 * 1024

# 資料庫（CODING_RULES E4、E5、SPEC A11）
SQLITE_BUSY_DELAYS: Final = (0.05, 0.1, 0.2)
DB_FAILS_BEFORE_PAUSE: Final = 3
BACKUP_INTERVAL_SECONDS: Final = 600
BACKUP_KEEP: Final = 10
