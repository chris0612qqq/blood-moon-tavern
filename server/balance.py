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
RESUME_COUNTDOWN_SECONDS: Final = 5
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

# 主持人同一句按到第幾次開始不耐煩（超過 4 次、超過 8 次）
NAG_PRESSES: Final[tuple[int, ...]] = (5, 9)

# 看真相最多列幾夜（SPEC A8.7）
TRUTH_MAX_NIGHTS: Final = 7

# 押注計分（SPEC A13）
BET_WOLF_HIT: Final = 1
BET_WOLF_MISS: Final = -1
BET_FACELESS_HIT: Final = 2

# 開場音效長度（ART 13.3），決定步驟間隔（SPEC A8.2）
SFX_SECONDS: Final[dict[str, float]] = {
    "night_start": 2.0,
    "wolf_open": 1.8,
    "seer_open": 1.2,
    "witch_open": 1.5,
    "dawn": 1.5,
}
