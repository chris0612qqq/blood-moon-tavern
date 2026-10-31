"""村民（SPEC A5.2）。抽牌時是剩下的人，不參與輪替權重。"""

from server.enums import Faction, Role
from server.roles.base import RoleDef

ROLE = RoleDef(code=Role.VILLAGER, faction=Faction.VILLAGE, public_role=Role.VILLAGER)
