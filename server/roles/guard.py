"""守衛（SPEC v4.42）：每晚最先行動，守一個別人。"""

from server.enums import Faction, Role, Step
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.GUARD,
    faction=Faction.VILLAGE,
    public_role=Role.GUARD,
    night_step=Step.GUARD,
    night_end_step=Step.GUARD_END,
    night_order=5,
    deal_order=45,
)
