"""由 server/protocol.py 產生 web/js/protocol.js（CODING_RULES R5）。不要手改產物。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import balance, config, protocol  # noqa: E402
from server.enums import Action, Channel, ChatKind, DeathCause, Mode, PauseReason, Role, Step  # noqa: E402
from server.errors import ErrorCode  # noqa: E402
from server.media import MediaKind  # noqa: E402

TARGET = ROOT / "web" / "js" / "protocol.js"


def render() -> str:
    """回傳 protocol.js 的完整內容。"""
    messages = {
        name: sorted(
            field
            for field in model.model_json_schema(by_alias=True)["properties"]
            if field not in ("t", "msg_id", "step_seq")
        )
        for name, model in protocol.CLIENT_MESSAGES.items()
    }
    data = {
        "PROTOCOL_VERSION": config.PROTOCOL_VERSION,
        "MESSAGES": messages,
        "ROLE_TABLE": {str(n): list(row) for n, row in balance.ROLE_TABLE.items()},
        "NO_HUNTER_PLAYER_COUNT": {"value": balance.NO_HUNTER_PLAYER_COUNT},
        "ACTION": {a.name: a.value for a in Action},
        "CHANNEL": {c.name: c.value for c in Channel},
        "CHAT_KIND": {k.name: k.value for k in ChatKind},
        "DEATH_CAUSE": {c.name: c.value for c in DeathCause},
        "ERROR": {e.name: e.value for e in ErrorCode},
        "MEDIA_KIND": {k.name: k.value for k in MediaKind},
        "MODE": {m.name: m.value for m in Mode},
        "PAUSE_REASON": {r.name: r.value for r in PauseReason},
        "ROLE": {r.name: r.value for r in Role},
        "STEP": {s.name: s.value for s in Step},
        "LIMITS": {
            "NAME_GRAPHEMES": protocol.NAME_GRAPHEMES,
            "PIN_DIGITS": config.PIN_DIGITS,
            "ROOM_PASSWORD_DIGITS": config.ROOM_PASSWORD_DIGITS,
            "CHAT_MAX_CHARS": config.CHAT_MAX_CHARS,
            "MIN_PLAYERS": balance.MIN_PLAYERS,
            "MAX_PLAYERS": balance.MAX_PLAYERS,
            "COUNTDOWN_MIN_SECONDS": balance.COUNTDOWN_MIN_SECONDS,
            "COUNTDOWN_MAX_SECONDS": balance.COUNTDOWN_MAX_SECONDS,
        },
    }
    lines = ["// 由 scripts/gen_protocol.py 產生，不要手改（CODING_RULES R5）。"]
    for key, value in data.items():
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        lines.append(f"export const {key} = Object.freeze({text});")
    return "\n".join(lines) + "\n"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
