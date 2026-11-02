"""角色、步驟、死因等固定代號（CODING_RULES R1）。程式中禁止直接寫這些字串常值。"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    WOLF = "wolf"
    FACELESS = "faceless"
    VILLAGER = "villager"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"


class Faction(StrEnum):
    VILLAGE = "village"
    WOLF = "wolf"


class Step(StrEnum):
    """SPEC B5 的步驟。暫停是獨立旗標（`GameState.pause`），不是步驟。"""

    DEAL = "DEAL"
    NIGHT_START = "NIGHT_START"
    WOLF = "WOLF"
    WOLF_END = "WOLF_END"
    SEER = "SEER"
    SEER_END = "SEER_END"
    WITCH = "WITCH"
    WITCH_END = "WITCH_END"
    DAWN = "DAWN"
    HUNTER = "HUNTER"
    LAST_WORDS = "LAST_WORDS"
    DAY_SPEAK = "DAY_SPEAK"
    SUSPECT_VOTE = "SUSPECT_VOTE"
    DEFENSE = "DEFENSE"
    VOTE = "VOTE"
    REVEAL = "REVEAL"
    END = "END"


class DeathCause(StrEnum):
    WOLF = "wolf"
    POISON = "poison"
    VOTE = "vote"
    HUNTER = "hunter"
    MANUAL = "manual"


class Mode(StrEnum):
    GOD = "god"
    AUTO = "auto"


class PauseReason(StrEnum):
    ADMIN = "admin"
    SYSTEM = "system"
    PRESENCE = "presence"
    HOST_OFFLINE = "host_offline"


class Channel(StrEnum):
    PUBLIC = "public"
    WOLF = "wolf"


class ChatKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VOICE = "voice"
    # 打字轉電子音（SPEC v4.24）：沒有錄音，點一下用手機語音念出來
    TTS = "tts"


class DisguiseEnd(StrEnum):
    EXPIRED = "expired"
    TARGET_DEAD = "target_dead"
    WOLF_DEAD = "wolf_dead"
    GAME_END = "game_end"


class Winner(StrEnum):
    VILLAGE = "village"
    WOLF = "wolf"
    NONE = "none"  # 管理員中途結束


class DayContext(StrEnum):
    """目前這批死亡來自哪個時點，決定遺言名單與接下來的步驟（SPEC A5.4）。"""

    DAWN = "dawn"
    REVEAL = "reveal"


class Action(StrEnum):
    """客戶端意圖的代號，與協定訊息類型相同（CODING_RULES 命名：名詞.動詞）。"""

    DEAL_ACK = "deal.ack"
    WOLF_PICK = "wolf.pick"
    SEER_CHECK = "seer.check"
    SEER_OK = "seer.ok"
    WITCH_ACT = "witch.act"
    HUNTER_SHOOT = "hunter.shoot"
    SPEAK_END = "speak.end"
    VOTE_CAST = "vote.cast"
    CHAT_SEND = "chat.send"
    WOLF_SCHEDULE = "wolf.schedule"
    WOLF_UNSCHEDULE = "wolf.unschedule"
    NARRATOR_TAKEOVER = "narrator.takeover"
    ADMIN_END = "admin.end"
    ADMIN_PAUSE = "admin.pause"
    ADMIN_RESUME = "admin.resume"
    ADMIN_NARRATOR = "admin.narrator"
    HOST_LINE = "host.line"
    HOST_REPLAY = "host.replay"
    HOST_NEXT = "host.next"
    HOST_SKIP_SPEAKER = "host.skip_speaker"
    HOST_EXTEND = "host.extend"
    HOST_ROLLBACK = "host.rollback"
    HOST_SET_ALIVE = "host.set_alive"
    HOST_RESHOW_CARD = "host.reshow_card"
