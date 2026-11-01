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
NAME_SEPARATOR: Final = "、"
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
    "deaths": "{report}",
    "hunter": "獵人請發動技能",
    "hunter_shot": "獵人 {name} 射死了 {target}，身分是{role}",
    "hunter_holster": "獵人 {name} 選擇不開槍",
    "last_words": "請 {name} 發表遺言",
    "speak": "請 {name} 發言",
    "suspect_vote": "請投出最有嫌疑的人",
    "defense": "請 {name} 申述",
    "defense_first": "最有嫌疑的是 {names}，請 {name} 申述",
    "vote": "請投票，決定要放逐誰",
    "no_nominee": "全部棄票，今天沒有人被放逐",
    "exile": "{name} 被放逐，可憐，被自己人放逐了",
    "exile_wolf": "成功將狼人放逐！{name} 是狼人！",
    "tie": "平票，無人出局",
    "win": "遊戲結束，{side}獲勝",
    "aborted": "遊戲中途結束",
}


def render(line_id: str, **params: str) -> str:
    """回傳台詞文字。未知 line_id 拋 KeyError。"""
    return LINES[line_id].format(**params)


def names_with_roles(entries: list[tuple[str, Role]]) -> str:
    """死者名單文字，例：「小美，身分是預言家、阿志，身分是狼人」。念出來才自然，不用括號。"""
    return "、".join(f"{name}，身分是{ROLE_NAMES[role]}" for name, role in entries)


def dawn_report(bitten: list[str], poisoned: list[tuple[str, Role]], saved: str | None) -> str:
    """天亮宣布（SPEC v4.13）：誰被狼人咬死、誰被女巫毒死、誰被救。

    被咬死的人只念名字：狼咬狼是戰術，念出身分就破功；全部都不念，才不會因為沒念而露餡。
    """
    parts = []
    if bitten:
        parts.append(f"昨晚 {'、'.join(bitten)} 被狼咬死了")
    if saved:
        parts.append(f"狼人咬了 {saved}，但被女巫救回來了")
    if poisoned:
        parts.append(f"女巫毒死了 {names_with_roles(poisoned)}")
    return "。".join(parts)


# 主持人一直按同一句時，第一段是超過 4 次、第二段是超過 8 次（使用者試玩回饋）
NAG_LINES: Final[dict[str, tuple[str, str]]] = {
    "night_start": ("閉眼啦，還在看", "喂！說你啦！眼睛閉起來！"),
    "wolf_open": ("乾，狼人，睜眼", "狼人是睡死了喔？快給我選！"),
    "wolf_close": ("狼人閉眼啦，偷看什麼", "乾，狼人，閉眼！"),
    "seer_open": ("乾，預言家，睜眼", "預言家你是算不出來喔？快點！"),
    "seer_close": ("預言家閉眼啦", "看夠了沒？閉眼！"),
    "witch_open": ("乾，女巫，睜眼", "女巫是在煉什麼？快點！"),
    "witch_close": ("女巫閉眼啦", "藥收一收，閉眼！"),
    "dawn": ("天亮了還睡，起床", "全部起床！太陽曬屁股了！"),
    "hunter": ("獵人拉弓啦", "手斷了喔？快射！"),
    "vote": ("投票啦", "是在等我幫你投嗎？快投！"),
    "speak": ("換你講話啦", "再不講就跳過你囉！"),
    "last_words": ("遺言啦，快講", "人都死了還這麼多猶豫！"),
}


def nag_text(line_id: str, presses: int, thresholds: tuple[int, ...]) -> str | None:
    """按到第 presses 次要念的不耐煩台詞；還沒到門檻或這句沒有就回 None。"""
    variants = NAG_LINES.get(line_id)
    if variants is None:
        return None
    level = sum(presses >= limit for limit in thresholds)
    return variants[min(level, len(variants)) - 1] if level else None
