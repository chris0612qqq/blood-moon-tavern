"""女巫（SPEC A5.2）。"""

from server.enums import Faction, Role, Step
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.WITCH,
    faction=Faction.VILLAGE,
    public_role=Role.WITCH,
    night_step=Step.WITCH,
    night_end_step=Step.WITCH_END,
    night_order=30,
    deal_order=40,
)
