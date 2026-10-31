"""千面狼（SPEC A6）。夜晚與狼人同一步；公開身分一律顯示狼人。"""

from server.enums import Faction, Role, Step
from server.roles.base import RoleDef

ROLE = RoleDef(
    code=Role.FACELESS,
    faction=Faction.WOLF,
    public_role=Role.WOLF,
    night_step=Step.WOLF,
    night_end_step=Step.WOLF_END,
    night_order=10,
    deal_order=10,
)
