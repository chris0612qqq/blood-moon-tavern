"""狼人（SPEC A5.2）。"""

from server.enums import Faction, Role, Step
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.WOLF,
    faction=Faction.WOLF,
    public_role=Role.WOLF,
    night_step=Step.WOLF,
    night_end_step=Step.WOLF_END,
    night_order=10,
    deal_order=20,
)
