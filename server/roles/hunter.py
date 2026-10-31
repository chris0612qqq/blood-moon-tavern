"""獵人（SPEC A5.2）。夜晚無行動，死亡時可開槍。"""

from server.enums import Faction, Role
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.HUNTER,
    faction=Faction.VILLAGE,
    public_role=Role.HUNTER,
    shoots_on_death=True,
    deal_order=50,
)
