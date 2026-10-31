"""角色定義的形狀（CODING_RULES G7）。"""

from __future__ import annotations

from dataclasses import dataclass

from server.enums import Faction, Role, Step


@dataclass(frozen=True)
class RoleDef:
    code: Role
    faction: Faction
    public_role: Role
    night_step: Step | None = None
    night_end_step: Step | None = None
    night_order: int = 0
    shoots_on_death: bool = False
    deal_order: int | None = None
