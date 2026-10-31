"""預言家（SPEC A5.2）。"""

from server.enums import Faction, Role, Step
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.SEER,
    faction=Faction.VILLAGE,
    public_role=Role.SEER,
    night_step=Step.SEER,
    night_end_step=Step.SEER_END,
    night_order=20,
    deal_order=30,
)
