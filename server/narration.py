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
    Winner.WOLF: "暗夜陣營",
    Winner.NONE: "無人",
}

# line_id → (標準, 江湖)
LINES: Final[dict[str, tuple[str, str]]] = {
    "night_start": ("天黑請閉眼", "血月東升，諸位閉目歇息"),
    "wolf_open": ("狼人請睜眼，請選擇今晚要殺的人", "噬月狼群，現身吧——今夜，取誰性命？"),
    "wolf_close": ("狼人請閉眼", "狼群隱入黑暗"),
    "seer_open": ("預言家請睜眼，請選擇要查驗的人", "觀星者，睜開你的慧眼"),
    "seer_close": ("預言家請閉眼", "天機已現，閉眼"),
    "witch_open": ("女巫請睜眼", "毒谷傳人，你的藥箱在此"),
    "witch_close": ("女巫請閉眼", "藥香散去"),
    "dawn": ("天亮請睜眼", "雞鳴破曉，眾人醒來"),
    "peaceful": ("昨晚是平安夜", "昨夜風平浪靜，無人遇害"),
    "deaths": ("昨晚死亡的是 {names_with_roles}", "昨夜，{names_with_roles} 永遠閉上了眼"),
    "hunter": ("獵人請發動技能", "神射手，拉開你最後一弓"),
    "hunter_shot": (
        "獵人 {name} 帶走了 {target}（{role}）",
        "神射手 {name} 一箭帶走了 {target}（{role}）",
    ),
    "hunter_holster": ("獵人 {name} 選擇不開槍", "神射手 {name} 收起了弓"),
    "last_words": ("請 {name} 發表遺言", "{name}，留下你最後的話吧"),
    "speak": ("請 {name} 發言", "{name}，請說"),
    "vote": ("請開始投票", "擊鼓！眾人投票"),
    "exile": ("{name} 被放逐", "{name} 被逐出酒館"),
    "tie": ("平票，無人出局", "眾說紛紜，無人出局"),
    "win": ("遊戲結束，{side}獲勝", "塵埃落定——{side}笑到最後"),
}


def render(line_id: str, jianghu: bool = False, **params: str) -> str:
    """回傳台詞文字。未知 line_id 拋 KeyError。"""
    standard, flavored = LINES[line_id]
    return (flavored if jianghu else standard).format(**params)


def names_with_roles(entries: list[tuple[str, Role]]) -> str:
    """死者名單文字，例：「小美（預言家）、阿志（狼人）」。"""
    return "、".join(f"{name}（{ROLE_NAMES[role]}）" for name, role in entries)
