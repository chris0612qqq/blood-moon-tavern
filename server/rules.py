"""規則核心（SPEC A5、A13）。純函式：不碰網路、資料庫、時間；亂數由呼叫端傳入（總則 3）。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from server import balance
from server.enums import Action, DayContext, DeathCause, Role, Step, Winner
from server.errors import ErrorCode, GameError
from server.rng import GameRng
from server.roles import deal_sequence, is_wolf, role_def
from server.state import GameState, NightRecord, PlayerState

DAY_STEPS = frozenset(
    {
        Step.DAWN,
        Step.HUNTER,
        Step.LAST_WORDS,
        Step.DAY_SPEAK,
        Step.SUSPECT_VOTE,
        Step.DEFENSE,
        Step.VOTE,
        Step.REVEAL,
    }
)
# 兩輪投票共用同一套選票、改票、等 5 秒的邏輯
VOTE_STEPS = frozenset({Step.SUSPECT_VOTE, Step.VOTE})
NIGHT_STEPS = frozenset(
    {
        Step.NIGHT_START,
        Step.GUARD,
        Step.GUARD_END,
        Step.WOLF,
        Step.WOLF_END,
        Step.SEER,
        Step.SEER_END,
        Step.WITCH,
        Step.WITCH_END,
    }
)


@dataclass(frozen=True)
class RoleRecord:
    """某人最近兩局的角色（SPEC A5.7）。"""

    last: Role | None = None
    before: Role | None = None


@dataclass(frozen=True)
class Consensus:
    agreed: bool
    target: str | None = None


@dataclass(frozen=True)
class TallyResult:
    exiled: str | None
    counts: dict[str, int]


@dataclass(frozen=True)
class WitchOptions:
    attacked: str | None
    can_save: bool
    can_poison: bool


def is_day_step(step: Step) -> bool:
    """暫停、夜晚只讀都用這個判斷（SPEC A3）。"""
    return step in DAY_STEPS


def is_night_step(step: Step) -> bool:
    return step in NIGHT_STEPS


def alive_players(state: GameState) -> list[PlayerState]:
    return [p for p in state.players if p.alive]


def alive_wolves(state: GameState) -> list[PlayerState]:
    return [p for p in state.players if p.alive and is_wolf(p.role)]


def alive_with_role(state: GameState, role: Role) -> PlayerState | None:
    """存活的該角色玩家；神職每局最多一人。"""
    return next((p for p in state.players if p.alive and p.role is role), None)


def role_is_public(state: GameState, player: PlayerState) -> bool:
    """出局者的身分遊戲中公不公開（SPEC v4.13）：被狼咬死的不公開，結算才揭曉。

    獵人例外：輪到他開槍時旁白就念了「獵人」，規則也是開槍即公開身分（SPEC A5.2）。
    """
    if player.alive:
        return False
    if player.death_cause is not DeathCause.WOLF:
        return True
    return player.role is Role.HUNTER and (
        state.step is Step.HUNTER or any(s.hunter == player.id for s in state.hunter_shots)
    )


def public_role(role: Role) -> Role:
    """對外顯示的角色：千面狼 → 狼人（SPEC A6）。"""
    return role_def(role).public_role


def role_counts(n: int) -> dict[Role, int]:
    """依人數回傳各角色人數（SPEC A5.1）；人數不在 6–20 時拋 ValueError。"""
    if n not in balance.ROLE_TABLE:
        raise ValueError(f"unsupported player count: {n}")
    wolves, villagers = balance.ROLE_TABLE[n]
    guards = 1 if n >= balance.GUARD_MIN_PLAYERS else 0
    return {
        Role.FACELESS: balance.FACELESS_PER_GAME,
        Role.WOLF: wolves - balance.FACELESS_PER_GAME,
        Role.SEER: 1,
        Role.WITCH: 1,
        Role.GUARD: guards,
        Role.HUNTER: 0 if n == balance.NO_HUNTER_PLAYER_COUNT else 1,
        # 守衛從村民名額扣，總人數不變（SPEC v4.42）
        Role.VILLAGER: villagers - guards,
    }


def _history_group(role: Role) -> Role:
    # SPEC A5.7：抽千面狼與狼人都看「當過狼（含千面狼）」
    return Role.WOLF if is_wolf(role) else role


def role_weight(record: RoleRecord | None, role: Role) -> int:
    """某人抽到某角色的整數權重（SPEC A5.7、CODING_RULES L26）。"""
    if record is None:
        return balance.WEIGHT_DEFAULT
    group = _history_group(role)
    if record.last is not None and _history_group(record.last) is group:
        return balance.WEIGHT_LAST_GAME
    if record.before is not None and _history_group(record.before) is group:
        return balance.WEIGHT_GAME_BEFORE
    return balance.WEIGHT_DEFAULT


def weighted_pick(items: Sequence[str], weights: Sequence[int], rng: GameRng) -> str:
    """依整數權重抽一個（L26）；權重總和為 0 時改等權重（L10）。"""
    total = sum(weights)
    if total == 0:
        return rng.choice(items)
    point = rng.randrange(total)
    for item, weight in zip(items, weights, strict=True):
        if point < weight:
            return item
        point -= weight
    raise AssertionError("point outside total weight")


def plan_fits(n: int, plan: Mapping[str, Role]) -> bool:
    """管理員指定的職業沒超過這個人數能有的數量（SPEC v4.26）。"""
    if n not in balance.ROLE_TABLE:
        return True  # 人數還不夠開局，開局時會再檢查
    counts = role_counts(n)
    return all(list(plan.values()).count(role) <= counts[role] for role in set(plan.values()))


def deal(
    ids: Sequence[str],
    history: Mapping[str, RoleRecord],
    rng: GameRng,
    plan: Mapping[str, Role] | None = None,
) -> dict[str, Role]:
    """依序抽特殊角色，剩下為村民（SPEC A5.7）。先排序確保同種子結果相同（L25）。

    plan 是管理員事先指定的職業（SPEC v4.26），先發給他們，剩下的名額才抽。
    """
    counts = role_counts(len(ids))
    fixed = {pid: role for pid, role in (plan or {}).items() if pid in ids}
    if not plan_fits(len(ids), fixed):
        raise ValueError("role plan exceeds role counts")
    for role in fixed.values():
        counts[role] -= 1
    pool = sorted(pid for pid in ids if pid not in fixed)
    roles: dict[str, Role] = dict(fixed)
    for role in deal_sequence():
        for _ in range(counts[role]):
            weights = [role_weight(history.get(p), role) for p in pool]
            chosen = weighted_pick(pool, weights, rng)
            pool.remove(chosen)
            roles[chosen] = role
    return roles | dict.fromkeys(pool, Role.VILLAGER)


def eligible_targets(state: GameState, actor_id: str, action: Action) -> list[str]:
    """該行動可選的目標，依座位排序（CODING_RULES G5：前端直接用這份）。"""
    # 狼人可以咬同伴，也可以選自己（使用者試玩回饋，SPEC v4.13）；其他行動不能選自己
    include_self = action is Action.WOLF_PICK
    others = [p for p in state.players if p.alive and (include_self or p.id != actor_id)]
    if action is Action.VOTE_CAST and state.step is Step.VOTE:
        nominated = state.vote_round().nominees or []
        others = [p for p in others if p.id in nominated]
    if action is Action.GUARD_PICK:
        # 守衛只能守別人，也不能連兩晚守同一個人（SPEC v4.42）
        others = [p for p in others if p.id != last_guarded(state)]
    return [p.id for p in sorted(others, key=lambda p: p.seat)]


def last_guarded(state: GameState) -> str | None:
    """前一晚守衛守的人；今晚不能再守他（SPEC v4.42）。"""
    earlier = [n for n in state.nights if n.round_no < state.round_no]
    return earlier[-1].guard_target if earlier else None


def wolf_consensus(picks: Mapping[str, str | None], alive_wolf_ids: Sequence[str]) -> Consensus:
    """全部存活狼都選了同一選項才算一致；空刀（None）也是一個選項（SPEC A5.6）。"""
    if not alive_wolf_ids or any(w not in picks for w in alive_wolf_ids):
        return Consensus(agreed=False)
    choices = {picks[w] for w in alive_wolf_ids}
    if len(choices) != 1:
        return Consensus(agreed=False)
    return Consensus(agreed=True, target=choices.pop())


def wolf_timeout_choice(
    picks: Mapping[str, str | None], alive_wolf_ids: Sequence[str], rng: GameRng
) -> str | None:
    """時間到仍不一致：最多人選的選項中抽一個，含空刀；都沒選＝空刀（L13、L14）。"""
    votes = Counter(picks[w] for w in alive_wolf_ids if w in picks)
    if not votes:
        return None
    top = max(votes.values())
    # None 排在最前面，排序後抽籤才可重現（L25）
    tied = sorted((c for c, n in votes.items() if n == top), key=lambda c: c or "")
    return tied[rng.randrange(len(tied))]


def witch_options(state: GameState, witch_id: str) -> WitchOptions:
    """女巫今晚能做什麼（SPEC A5.2、C8.3）。解藥用掉後不告知被殺者。"""
    night = state.night()
    antidote_left = not state.witch_antidote_used
    attacked = night.wolf_target if antidote_left else None
    can_self_save = state.round_no == 1
    can_save = attacked is not None and (attacked != witch_id or can_self_save)
    return WitchOptions(
        attacked=attacked, can_save=can_save, can_poison=not state.witch_poison_used
    )


def validate_witch_act(state: GameState, witch_id: str, save: bool, poison: str | None) -> None:
    """驗證女巫用藥；不合法一律拋 invalid_target（CODING_RULES E9）。"""
    options = witch_options(state, witch_id)
    if save and poison is not None:
        raise GameError(ErrorCode.INVALID_TARGET)
    if save and not options.can_save:
        raise GameError(ErrorCode.INVALID_TARGET)
    if poison is not None and (
        not options.can_poison or poison not in eligible_targets(state, witch_id, Action.WITCH_ACT)
    ):
        raise GameError(ErrorCode.INVALID_TARGET)


def resolve_night(night: NightRecord) -> list[tuple[str, DeathCause]]:
    """夜晚死亡名單（SPEC A5.3）：同一人被刀又被毒算一次，死因為毒（L19）。

    被守衛守住或被女巫救的人不會被咬死；兩個都有也照樣活著。守衛擋不住毒（SPEC v4.42）。
    """
    deaths: dict[str, DeathCause] = {}
    protected = night.witch_saved or night.guard_target == night.wolf_target
    if night.wolf_target is not None and not protected:
        deaths[night.wolf_target] = DeathCause.WOLF
    if night.witch_poison is not None:
        deaths[night.witch_poison] = DeathCause.POISON
    return sorted(deaths.items())


def can_shoot(cause: DeathCause) -> bool:
    """獵人能否開槍：被毒、手動修正都不能（SPEC A5.2、A5.6）。"""
    return cause in (DeathCause.WOLF, DeathCause.VOTE, DeathCause.HUNTER)


def nominees(votes: Mapping[str, str | None]) -> dict[str, int]:
    """第一輪：取最高票與第二高票的所有人，同票都進第二輪（SPEC A5.4）。全棄回空。"""
    counts = Counter(target for target in votes.values() if target is not None)
    levels = sorted(set(counts.values()), reverse=True)
    if not levels:
        return {}
    top = levels[0]
    if sum(1 for n in counts.values() if n == top) >= 2 or len(levels) == 1:
        keep = {top}
    else:
        keep = {top, levels[1]}
    return {target: n for target, n in sorted(counts.items()) if n in keep}


def needs_second_round(votes: Mapping[str, str | None]) -> bool:
    """第一輪至少 3 個人被投，或兩人同票，才要申述和第二輪（SPEC A5.4）。"""
    counts = Counter(target for target in votes.values() if target is not None)
    return len(counts) >= balance.SECOND_ROUND_MIN_TARGETS or (
        len(counts) > 1 and plurality(counts) is None
    )


def plurality(counts: Mapping[str, int]) -> str | None:
    """唯一最高票的人；平票或沒有票回 None（L15）。"""
    if not counts:
        return None
    top = max(counts.values())
    leaders = [target for target, n in counts.items() if n == top]
    return leaders[0] if len(leaders) == 1 else None


def tally(votes: Mapping[str, str | None]) -> TallyResult:
    """計票（SPEC A5.4）：平票或全部棄票＝無人出局（L15）。"""
    counts = Counter(target for target in votes.values() if target is not None)
    return TallyResult(exiled=plurality(counts), counts=dict(counts))


def check_win(state: GameState) -> Winner | None:
    """人數壓制判定（SPEC A2）。狼全滅優先於壓制。"""
    wolves = len(alive_wolves(state))
    if wolves == 0:
        return Winner.VILLAGE
    if wolves >= len(alive_players(state)) - wolves:
        return Winner.WOLF
    return None


def speak_order(state: GameState, rng: GameRng) -> list[str]:
    """發言順序（SPEC A5.4）：隨機起點，順著座位輪；不和上一天同一個人開始（只剩一人時例外）。"""
    alive = sorted(alive_players(state), key=lambda p: p.seat)
    if not alive:
        return []
    fresh = [p for p in alive if p.id != state.last_speak_start]
    start = rng.choice(fresh or alive)
    index = alive.index(start)
    return [p.id for p in alive[index:] + alive[:index]]


def gets_last_words(round_no: int, context: DayContext) -> bool:
    """這批死亡有沒有遺言（SPEC A5.4）：第 1 天天亮的死者、被放逐者與之後被帶走者才有。"""
    return context is DayContext.REVEAL or round_no == 1


def last_words_queue(state: GameState) -> list[str]:
    """遺言順序依座位（SPEC A5.4）；L17 空名單由引擎跳過。"""
    queue = [state.player(pid) for pid in state.pending_last_words]
    return [p.id for p in sorted(queue, key=lambda p: p.seat)]


def speak_seconds(n: int) -> int:
    """發言秒數依人數（SPEC A5.4）。"""
    for limit, seconds in balance.SPEAK_SECONDS_BY_PLAYERS:
        if n <= limit:
            return seconds
    return balance.SPEAK_SECONDS_BY_PLAYERS[-1][1]


def can_wolf_mask(state: GameState, player_id: str) -> bool:
    """能否以匿名「狼人」身分發言（SPEC A9、B8）：存活的狼人或千面狼、白天（含白天暫停）。"""
    player = state.player(player_id)
    return player.alive and is_wolf(player.role) and is_day_step(state.step)
