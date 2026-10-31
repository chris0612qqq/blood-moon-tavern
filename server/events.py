"""領域事件與 apply（CODING_RULES G1–G4）：狀態只能經由這裡改變，事件可完整重播。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from server.enums import DayContext, DeathCause, DisguiseEnd, PauseReason, Step, Winner
from server.state import (
    SCHEMA_VERSION,
    Bet,
    DisguisePeriod,
    GameState,
    NightRecord,
    PauseState,
    Timers,
    VoteRound,
)


class EventType(StrEnum):
    GAME_CREATED = "game_created"
    STEP_ENTERED = "step_entered"
    NIGHT_BEGAN = "night_began"
    ACTOR_DONE = "actor_done"
    DEAL_ACKED = "deal_acked"
    WOLF_PICKED = "wolf_picked"
    WOLF_PICK_CLEARED = "wolf_pick_cleared"
    WOLF_CONFIRMING = "wolf_confirming"
    WOLF_DECIDED = "wolf_decided"
    SEER_CHECKED = "seer_checked"
    WITCH_ACTED = "witch_acted"
    NIGHT_TARGET_CLEARED = "night_target_cleared"
    VOTE_CAST = "vote_cast"
    VOTE_VOIDED = "vote_voided"
    VOTES_REVEALED = "votes_revealed"
    DAWN_ANNOUNCED = "dawn_announced"
    PLAYER_DIED = "player_died"
    PLAYER_REVIVED = "player_revived"
    HUNTER_RESOLVED = "hunter_resolved"
    DISGUISE_CHANGED = "disguise_changed"
    TIMED_OUT = "timed_out"
    TIMERS_SET = "timers_set"
    PAUSED = "paused"
    RESUME_SCHEDULED = "resume_scheduled"
    RESUMED = "resumed"
    NARRATE = "narrate"
    NARRATOR_SET = "narrator_set"
    BET_SET = "bet_set"
    CHAT_SENT = "chat_sent"
    CARD_RESHOWN = "card_reshown"
    GAME_ENDED = "game_ended"
    ROLLED_BACK = "rolled_back"


class Event(BaseModel):
    type: EventType
    ts: float
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION


def _step_entered(state: GameState, data: dict[str, Any]) -> None:
    state.step = Step(data["step"])
    state.step_seq += 1
    state.actors = list(data["actors"])
    state.done = []
    state.timers = Timers(**data["timers"])
    state.line_id = data["line_id"]
    state.timed_out = False
    state.announced = False
    state.current_speaker = data["speaker"]
    state.speak_queue = list(data["speak_queue"])
    if data["clear_last_words"]:
        state.pending_last_words = []


def _night_began(state: GameState, data: dict[str, Any]) -> None:
    state.round_no = data["round_no"]
    state.nights.append(NightRecord(round_no=state.round_no))
    state.votes.append(VoteRound(round_no=state.round_no))
    state.dawn_deaths = []
    state.pending_last_words = []
    state.hunter_shot_done = False
    state.day_context = None


def _actor_done(state: GameState, data: dict[str, Any]) -> None:
    for player_id in data["players"]:
        if player_id not in state.done:
            state.done.append(player_id)


def _deal_acked(state: GameState, data: dict[str, Any]) -> None:
    state.player(data["player"]).acked = True


def _wolf_picked(state: GameState, data: dict[str, Any]) -> None:
    state.night().wolf_picks[data["wolf"]] = data["target"]


def _wolf_pick_cleared(state: GameState, data: dict[str, Any]) -> None:
    for wolf in data["wolves"]:
        state.night().wolf_picks.pop(wolf, None)


def _wolf_confirming(state: GameState, data: dict[str, Any]) -> None:
    state.timers.confirm_until = data["until"]


def _wolf_decided(state: GameState, data: dict[str, Any]) -> None:
    night = state.night()
    night.wolf_decided = True
    night.wolf_target = data["target"]
    state.timers.confirm_until = None


def _seer_checked(state: GameState, data: dict[str, Any]) -> None:
    night = state.night()
    night.seer_target = data["target"]
    night.seer_is_wolf = data["is_wolf"]


def _witch_acted(state: GameState, data: dict[str, Any]) -> None:
    night = state.night()
    night.witch_acted = True
    night.witch_saved = data["save"]
    night.witch_poison = data["poison"]
    state.witch_antidote_used = state.witch_antidote_used or data["save"]
    state.witch_poison_used = state.witch_poison_used or data["poison"] is not None


def _night_target_cleared(state: GameState, data: dict[str, Any]) -> None:
    # SPEC A5.6：目標在步驟中被踢除 → 該選擇清空
    night = state.night()
    player_id = data["player"]
    if night.wolf_target == player_id:
        night.wolf_target = None
    if night.witch_poison == player_id:
        night.witch_poison = None


def _vote_cast(state: GameState, data: dict[str, Any]) -> None:
    round_votes = state.vote_round()
    round_votes.ballots[data["voter"]] = data["target"]
    if data["changed"]:
        round_votes.changed.append(data["voter"])


def _vote_voided(state: GameState, data: dict[str, Any]) -> None:
    # SPEC A5.6：被踢者的票作廢；投給他的票改為棄票
    round_votes = state.vote_round()
    player_id = data["player"]
    round_votes.ballots.pop(player_id, None)
    for voter, target in round_votes.ballots.items():
        if target == player_id:
            round_votes.ballots[voter] = None


def _votes_revealed(state: GameState, data: dict[str, Any]) -> None:
    round_votes = state.vote_round()
    round_votes.revealed = True
    round_votes.exiled = data["exiled"]
    state.day_context = DayContext.REVEAL


def _dawn_announced(state: GameState, data: dict[str, Any]) -> None:
    state.announced = True
    state.day_context = DayContext.DAWN


def _player_died(state: GameState, data: dict[str, Any]) -> None:
    player_id = data["player"]
    player = state.player(player_id)
    player.alive = False
    player.death_cause = DeathCause(data["cause"])
    player.death_round = state.round_no
    state.actors = [a for a in state.actors if a != player_id]
    state.speak_queue = [s for s in state.speak_queue if s != player_id]
    if state.current_speaker == player_id:
        state.current_speaker = None
    if state.hunter_pending == player_id:
        state.hunter_pending = None
    if data["hunter_pending"]:
        state.hunter_pending = player_id
    if data["dawn_death"]:
        state.dawn_deaths.append(player_id)
    if data["last_words"]:
        state.pending_last_words.append(player_id)


def _player_revived(state: GameState, data: dict[str, Any]) -> None:
    player = state.player(data["player"])
    player.alive = True
    player.death_cause = None
    player.death_round = None


def _hunter_resolved(state: GameState, data: dict[str, Any]) -> None:
    state.hunter_pending = None
    state.hunter_shot_done = True


def _disguise_changed(state: GameState, data: dict[str, Any]) -> None:
    disguise = state.disguise
    assert disguise is not None
    reason = data["ended_reason"]
    if reason is not None:
        disguise.previous_target = disguise.target_id
        if disguise.periods and disguise.periods[-1].to_round is None:
            disguise.periods[-1].to_round = state.round_no
            disguise.periods[-1].ended_reason = DisguiseEnd(reason)
        if data["target"] is not None:
            disguise.periods.append(
                DisguisePeriod(target_id=data["target"], from_round=state.round_no)
            )
    disguise.target_id = data["target"]
    disguise.rounds_left = data["rounds_left"]


def _timed_out(state: GameState, data: dict[str, Any]) -> None:
    state.timed_out = True


def _timers_set(state: GameState, data: dict[str, Any]) -> None:
    state.timers = Timers(**data["timers"])


def _paused(state: GameState, data: dict[str, Any]) -> None:
    state.pause = PauseState(reason=PauseReason(data["reason"]), remaining=data["remaining"])


def _resume_scheduled(state: GameState, data: dict[str, Any]) -> None:
    assert state.pause is not None
    state.pause.resume_at = data["at"]


def _resumed(state: GameState, data: dict[str, Any]) -> None:
    state.pause = None
    state.timers = Timers(**data["timers"])


def _narrator_set(state: GameState, data: dict[str, Any]) -> None:
    state.narrator_id = data["player"]


def _bet_set(state: GameState, data: dict[str, Any]) -> None:
    state.bets[data["player"]] = Bet(wolves=data["wolves"], faceless=data["faceless"])


def _chat_sent(state: GameState, data: dict[str, Any]) -> None:
    # 聊天內容不放進狀態（CODING_RULES L23 不回滾、避免狀態膨脹），這裡只記遺言已用
    if data["is_last_words"]:
        state.last_words_sent.append(data["real_author"])


def _game_ended(state: GameState, data: dict[str, Any]) -> None:
    state.step = Step.END
    state.step_seq += 1
    state.winner = Winner(data["winner"])
    state.actors = []
    state.done = []
    state.timers = Timers()
    state.pause = None
    state.current_speaker = None
    state.speak_queue = []
    state.line_id = "win"


def _rolled_back(state: GameState, data: dict[str, Any]) -> None:
    # 整份換回（含存活、千面狼期數、女巫用藥，L23）；step_seq 仍要單調遞增（L2）
    restored = GameState.model_validate(data["state"])
    seq = state.step_seq + 1
    for name in GameState.model_fields:
        setattr(state, name, getattr(restored, name))
    state.step_seq = seq


def _no_state_change(state: GameState, data: dict[str, Any]) -> None:
    return None


_APPLIERS: dict[EventType, Callable[[GameState, dict[str, Any]], None]] = {
    EventType.STEP_ENTERED: _step_entered,
    EventType.NIGHT_BEGAN: _night_began,
    EventType.ACTOR_DONE: _actor_done,
    EventType.DEAL_ACKED: _deal_acked,
    EventType.WOLF_PICKED: _wolf_picked,
    EventType.WOLF_PICK_CLEARED: _wolf_pick_cleared,
    EventType.WOLF_CONFIRMING: _wolf_confirming,
    EventType.WOLF_DECIDED: _wolf_decided,
    EventType.SEER_CHECKED: _seer_checked,
    EventType.WITCH_ACTED: _witch_acted,
    EventType.NIGHT_TARGET_CLEARED: _night_target_cleared,
    EventType.VOTE_CAST: _vote_cast,
    EventType.VOTE_VOIDED: _vote_voided,
    EventType.VOTES_REVEALED: _votes_revealed,
    EventType.DAWN_ANNOUNCED: _dawn_announced,
    EventType.PLAYER_DIED: _player_died,
    EventType.PLAYER_REVIVED: _player_revived,
    EventType.HUNTER_RESOLVED: _hunter_resolved,
    EventType.DISGUISE_CHANGED: _disguise_changed,
    EventType.TIMED_OUT: _timed_out,
    EventType.TIMERS_SET: _timers_set,
    EventType.PAUSED: _paused,
    EventType.RESUME_SCHEDULED: _resume_scheduled,
    EventType.RESUMED: _resumed,
    EventType.NARRATE: _no_state_change,
    EventType.NARRATOR_SET: _narrator_set,
    EventType.BET_SET: _bet_set,
    EventType.CHAT_SENT: _chat_sent,
    EventType.CARD_RESHOWN: _no_state_change,
    EventType.GAME_ENDED: _game_ended,
    EventType.ROLLED_BACK: _rolled_back,
}


def apply(state: GameState, event: Event) -> None:
    """把一個事件套用到狀態（G1）。遊戲建立事件由 `replay` 處理。"""
    _APPLIERS[event.type](state, event.data)


def replay(events: Iterable[Event]) -> GameState:
    """由事件從頭重建狀態（G2）。第一個事件必須是 GAME_CREATED。"""
    iterator = iter(events)
    first = next(iterator)
    if first.type is not EventType.GAME_CREATED:
        raise ValueError("event log must start with game_created")
    state = GameState.model_validate(first.data["state"])
    for event in iterator:
        apply(state, event)
    return state
