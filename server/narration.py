"""旁白台詞（SPEC B9、ART 13.2）。中文只放在這裡（CODING_RULES R2）。"""

from __future__ import annotations

from typing import Final

from server.enums import Role, Winner

ROLE_NAMES: Final[dict[Role, str]] = {
    Role.WOLF: "狼人",
    Role.FACELESS: "千面狼",
    Role.VILLAGER: "村民",
    Role.SEER: "預言家",
    Role.WITCH: "女巫",
    Role.HUNTER: "獵人",
}
SIDE_NAMES: Final[dict[Winner, str]] = {
    Winner.VILLAGE: "好人陣營",
    Winner.WOLF: "狼人陣營",
}

# 白話，角色一律叫本名，閉著眼也聽得懂（使用者試玩回饋，SPEC v4.10）
LINES: Final[dict[str, str]] = {
    "night_start": "天黑請閉眼",
    "wolf_open": "狼人請睜眼，請選擇今晚要殺的人",
    "wolf_close": "狼人請閉眼",
    "seer_open": "預言家請睜眼，請選擇要查驗的人",
    "seer_close": "預言家請閉眼",
    "witch_open": "女巫請睜眼",
    "witch_close": "女巫請閉眼",
    "dawn": "天亮請睜眼",
    "peaceful": "昨晚是平安夜",
    "deaths": "昨晚死亡的是 {names_with_roles}",
    "hunter": "獵人請發動技能",
    "hunter_shot": "獵人 {name} 帶走了 {target}（{role}）",
    "hunter_holster": "獵人 {name} 選擇不開槍",
    "last_words": "請 {name} 發表遺言",
    "speak": "請 {name} 發言",
    "vote": "請開始投票",
    "exile": "{name} 被放逐",
    "tie": "平票，無人出局",
    "win": "遊戲結束，{side}獲勝",
    "aborted": "遊戲中途結束",
}


def render(line_id: str, **params: str) -> str:
    """回傳台詞文字。未知 line_id 拋 KeyError。"""
    return LINES[line_id].format(**params)


def names_with_roles(entries: list[tuple[str, Role]]) -> str:
    """死者名單文字，例：「小美（預言家）、阿志（狼人）」。"""
    return "、".join(f"{name}（{ROLE_NAMES[role]}）" for name, role in entries)
