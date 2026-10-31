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
from server.state import Bet, GameState, NightRecord, PlayerState

DAY_STEPS = frozenset(
    {Step.DAWN, Step.HUNTER, Step.LAST_WORDS, Step.DAY_SPEAK, Step.VOTE, Step.REVEAL}
)
NIGHT_STEPS = frozenset(
    {
        Step.NIGHT_START,
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


@dataclass(frozen=True)
class BetScore:
    player_id: str
    score: int
    rank: int


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


def public_role(role: Role) -> Role:
    """對外顯示的角色：千面狼 → 狼人（SPEC A6）。"""
    return role_def(role).public_role


def role_counts(n: int) -> dict[Role, int]:
    """依人數回傳各角色人數（SPEC A5.1）；人數不在 6–20 時拋 ValueError。"""
    if n not in balance.ROLE_TABLE:
        raise ValueError(f"unsupported player count: {n}")
    wolves, villagers = balance.ROLE_TABLE[n]
    return {
        Role.FACELESS: balance.FACELESS_PER_GAME,
        Role.WOLF: wolves - balance.FACELESS_PER_GAME,
        Role.SEER: 1,
        Role.WITCH: 1,
        Role.HUNTER: 0 if n == balance.NO_HUNTER_PLAYER_COUNT else 1,
        Role.VILLAGER: villagers,
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


def deal(ids: Sequence[str], history: Mapping[str, RoleRecord], rng: GameRng) -> dict[str, Role]:
    """依序抽特殊角色，剩下為村民（SPEC A5.7）。先排序確保同種子結果相同（L25）。"""
    counts = role_counts(len(ids))
    pool = sorted(ids)
    roles: dict[str, Role] = {}
    for role in deal_sequence():
        for _ in range(counts[role]):
            weights = [role_weight(history.get(p), role) for p in pool]
            chosen = weighted_pick(pool, weights, rng)
            pool.remove(chosen)
            roles[chosen] = role
    return roles | dict.fromkeys(pool, Role.VILLAGER)


def eligible_targets(state: GameState, actor_id: str, action: Action) -> list[str]:
    """該行動可選的目標，依座位排序（CODING_RULES G5：前端直接用這份）。"""
    others = [p for p in state.players if p.alive and p.id != actor_id]
    if action is Action.WOLF_PICK:
        others = [p for p in others if not is_wolf(p.role)]
    return [p.id for p in sorted(others, key=lambda p: p.seat)]


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
    """夜晚死亡名單（SPEC A5.3）：同一人被刀又被毒算一次，死因為毒（L19）。"""
    deaths: dict[str, DeathCause] = {}
    if night.wolf_target is not None and not night.witch_saved:
        deaths[night.wolf_target] = DeathCause.WOLF
    if night.witch_poison is not None:
        deaths[night.witch_poison] = DeathCause.POISON
    return sorted(deaths.items())


def can_shoot(cause: DeathCause) -> bool:
    """獵人能否開槍：被毒、被踢、手動修正都不能（SPEC A5.2、A5.6）。"""
    return cause in (DeathCause.WOLF, DeathCause.VOTE, DeathCause.HUNTER)


def tally(votes: Mapping[str, str | None]) -> TallyResult:
    """計票（SPEC A5.4）：平票或全部棄票＝無人出局（L15）。"""
    counts = Counter(target for target in votes.values() if target is not None)
    if not counts:
        return TallyResult(exiled=None, counts={})
    top = max(counts.values())
    leaders = [t for t, n in counts.items() if n == top]
    return TallyResult(exiled=leaders[0] if len(leaders) == 1 else None, counts=dict(counts))


def check_win(state: GameState) -> Winner | None:
    """人數壓制判定（SPEC A2）。狼全滅優先於壓制。"""
    wolves = len(alive_wolves(state))
    if wolves == 0:
        return Winner.VILLAGE
    if wolves >= len(alive_players(state)) - wolves:
        return Winner.WOLF
    return None


def speak_order(state: GameState) -> list[str]:
    """發言順序（SPEC A5.4）：昨夜死者中座位最小者之後的第一位存活者起；平安夜從座位 1 起。"""
    alive = sorted(alive_players(state), key=lambda p: p.seat)
    if not state.dawn_deaths:
        return [p.id for p in alive]
    start = min(state.player(pid).seat for pid in state.dawn_deaths)
    after = [p for p in alive if p.seat > start]
    before = [p for p in alive if p.seat <= start]
    return [p.id for p in after + before]


def gets_last_words(round_no: int, context: DayContext) -> bool:
    """這批死亡有沒有遺言（SPEC A5.4）：第 1 天天亮的死者、被放逐者與之後被帶走者才有。"""
    return context is DayContext.REVEAL or round_no == 1


def last_words_queue(state: GameState) -> list[str]:
    """遺言順序依座位（SPEC A5.4）；被踢者不留遺言（L17 空名單由引擎跳過）。"""
    queue = [
        state.player(pid)
        for pid in state.pending_last_words
        if state.player(pid).death_cause is not DeathCause.KICK
    ]
    return [p.id for p in sorted(queue, key=lambda p: p.seat)]


def speak_seconds(n: int) -> int:
    """發言秒數依人數（SPEC A5.4）。"""
    for limit, seconds in balance.SPEAK_SECONDS_BY_PLAYERS:
        if n <= limit:
            return seconds
    return balance.SPEAK_SECONDS_BY_PLAYERS[-1][1]


def can_bet(state: GameState, player_id: str) -> bool:
    """押注資格（SPEC A13）：已出局的好人陣營，被踢者不行。"""
    player = state.player(player_id)
    return (
        not player.alive and not is_wolf(player.role) and player.death_cause is not DeathCause.KICK
    )


def validate_bet(state: GameState, player_id: str, bet: Bet) -> None:
    """驗證押注內容（SPEC B8）：人數不超過狼人總數、不含自己、不重複、都是本局玩家。"""
    wolf_total = sum(1 for p in state.players if is_wolf(p.role))
    picks = [*bet.wolves, *([bet.faceless] if bet.faceless is not None else [])]
    if (
        len(bet.wolves) > wolf_total
        or len(set(bet.wolves)) != len(bet.wolves)
        or player_id in picks
        or not all(state.has_player(p) for p in picks)
    ):
        raise GameError(ErrorCode.INVALID_TARGET)


def score_bets(bets: Mapping[str, Bet], roles: Mapping[str, Role]) -> list[BetScore]:
    """押注計分與排名（SPEC A13）：同分並列，最低 0 分；沒押的人不在 bets 內。"""
    scores: dict[str, int] = {}
    for player_id, bet in bets.items():
        score = sum(
            balance.BET_WOLF_HIT if is_wolf(roles[p]) else balance.BET_WOLF_MISS for p in bet.wolves
        )
        if bet.faceless is not None and roles[bet.faceless] is Role.FACELESS:
            score += balance.BET_FACELESS_HIT
        scores[player_id] = max(0, score)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    results: list[BetScore] = []
    for index, (player_id, score) in enumerate(ordered):
        tied_with_previous = results and results[-1].score == score
        rank = results[-1].rank if tied_with_previous else index + 1
        results.append(BetScore(player_id=player_id, score=score, rank=rank))
    return results
