"""角色註冊表（CODING_RULES G7）：抽牌順序、夜晚步驟都從這裡推導。"""

from __future__ import annotations

from typing import Final

from server.enums import Faction, Role, Step
from server.roles import faceless, guard, hunter, seer, villager, witch, wolf
from server.roles.base import RoleDef

REGISTRY: Final[dict[Role, RoleDef]] = {
    module.ROLE.code: module.ROLE
    for module in (wolf, faceless, villager, seer, witch, guard, hunter)
}


def role_def(role: Role) -> RoleDef:
    """取角色定義。"""
    return REGISTRY[role]


def is_wolf(role: Role) -> bool:
    """是否屬暗夜陣營（狼人與千面狼）。"""
    return REGISTRY[role].faction is Faction.WOLF


def deal_sequence() -> list[Role]:
    """抽牌順序（SPEC A5.7）：千面狼 → 狼人 → 預言家 → 女巫 → 守衛 → 獵人；村民是剩下的人。"""
    drawn = [r for r in REGISTRY.values() if r.deal_order is not None]
    return [r.code for r in sorted(drawn, key=lambda r: r.deal_order or 0)]


def night_step_pairs() -> list[tuple[Step, Step]]:
    """夜晚的（睜眼步驟, 閉眼步驟），依行動順序，同一步驟只列一次。"""
    pairs: dict[Step, tuple[int, Step]] = {}
    for definition in REGISTRY.values():
        if definition.night_step is not None and definition.night_end_step is not None:
            pairs[definition.night_step] = (definition.night_order, definition.night_end_step)
    ordered = sorted(pairs.items(), key=lambda item: item[1][0])
    return [(step, end) for step, (_, end) in ordered]


def roles_acting_in(step: Step) -> list[Role]:
    """該夜晚步驟由哪些角色行動。"""
    return [r.code for r in REGISTRY.values() if r.night_step is step]
