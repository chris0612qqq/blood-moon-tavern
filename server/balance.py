"""平衡數值（CODING_RULES G8）：調平衡只改這裡，不改邏輯。"""

from __future__ import annotations

from typing import Final

MIN_PLAYERS: Final = 6
MAX_PLAYERS: Final = 20

# SPEC A5.1：人數 → (狼人數（含千面狼）, 村民數)；神職另計
ROLE_TABLE: Final[dict[int, tuple[int, int]]] = {
    6: (2, 2),
    7: (2, 2),
    8: (2, 3),
    9: (3, 3),
    10: (3, 4),
    11: (4, 4),
    12: (4, 5),
    13: (4, 6),
    14: (5, 6),
    15: (5, 7),
    16: (5, 8),
    17: (6, 8),
    18: (6, 9),
    19: (6, 10),
    20: (7, 10),
}
NO_HUNTER_PLAYER_COUNT: Final = 6
FACELESS_PER_GAME: Final = 1

# CODING_RULES L26：輪替權重用整數，對應 0.25／0.5／1
WEIGHT_LAST_GAME: Final = 1
WEIGHT_GAME_BEFORE: Final = 2
WEIGHT_DEFAULT: Final = 4
ROLE_HISTORY_DAYS: Final = 2

# 千面狼（SPEC A6）
DISGUISE_PERIOD_ROUNDS: Final = 2

# 可於開房時調整的倒數預設（SPEC A2）
NIGHT_STEP_SECONDS: Final = 45
VOTE_SECONDS: Final = 30
DEFENSE_SECONDS: Final = 30
HUNTER_SECONDS: Final = 30
LAST_WORDS_SECONDS: Final = 60
DEAL_SECONDS: Final = 60
# SPEC A5.4：人數上限 → 發言秒數，依序比對
SPEAK_SECONDS_BY_PLAYERS: Final[tuple[tuple[int, int], ...]] = ((10, 90), (15, 75), (20, 60))
COUNTDOWN_MIN_SECONDS: Final = 10
COUNTDOWN_MAX_SECONDS: Final = 300

# 固定數值（SPEC A2、A5.4、A5.6、A8.6）
WOLF_CONFIRM_SECONDS: Final = 3
STEP_GAP_SECONDS: Final = 4
SFX_GAP_PADDING_SECONDS: Final = 0.3
WITCH_MIN_SECONDS_LOW: Final = 8
WITCH_MIN_SECONDS_HIGH: Final = 15
VOTE_ALL_CAST_GRACE_SECONDS: Final = 5
# 第一輪被投的人少於這個數就不進第二輪，直接照票數決定；兩人同票例外（SPEC A5.4）
SECOND_ROUND_MIN_TARGETS: Final = 3
# 每隻狼同時能排幾則定時電子音（SPEC v4.24）
WOLF_SCHEDULE_SLOTS: Final = 2
# 第二輪被提名到這個人數，被提名者也能互投（不能投自己），投票人才不會只剩一兩個（SPEC A5.4）
MUTUAL_VOTE_MIN_NOMINEES: Final = 3
RESUME_COUNTDOWN_SECONDS: Final = 2.5
HOST_EXTEND_SECONDS: Final = 30

# 演出長度（SPEC C9.2 #13）：伺服器等動畫播完才推進
REVEAL_DEATH_EACH_SECONDS: Final = 1.5
REVEAL_VOTE_EACH_SECONDS: Final = 0.4
REVEAL_FOCUS_SECONDS: Final = 1.0
PEACEFUL_NIGHT_SECONDS: Final = 1.5

# 旁白長度估算（CODING_RULES E15、ART 13.1）
NARRATION_SECONDS_PER_CHAR: Final = 0.25
NARRATION_RATE: Final = 0.45
NARRATION_PADDING_SECONDS: Final = 1.0
# 天亮、公布死者、請人發言這段接得快一點（使用者試玩回饋）：間隔和停留除以這個倍率，語速不變
DAY_PACE: Final = 1.5
DAY_PACE_LINES: Final = frozenset({"dawn", "peaceful", "deaths", "last_words", "speak"})

# 主持人同一句按到第幾次開始不耐煩（超過 4 次、超過 8 次）
NAG_PRESSES: Final[tuple[int, ...]] = (5, 9)

# 看真相最多列幾夜（SPEC A8.7）
TRUTH_MAX_NIGHTS: Final = 7


# 開場音效長度（ART 13.3），決定步驟間隔（SPEC A8.2）
SFX_SECONDS: Final[dict[str, float]] = {
    "night_start": 2.0,
    "wolf_open": 1.8,
    "seer_open": 1.2,
    "witch_open": 1.5,
    "dawn": 2.6,  # 雞鳴錄音 2.22 秒，放完稍停 0.3 秒（SPEC v4.36）
}
