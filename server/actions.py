"""各意圖的處理（SPEC B7）。由 Engine.handle 呼叫；驗證順序依 CODING_RULES E2。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from server import balance, config, disguise, narration, rules, timers
from server.enums import (
    Action,
    Channel,
    ChatKind,
    DeathCause,
    DisguiseEnd,
    Mode,
    PauseReason,
    Step,
    Winner,
)
from server.errors import ErrorCode, GameError
from server.events import EventType
from server.modes import Actor, can_resume
from server.roles import is_wolf
from server.state import Bet, DisguisePeriod, GameState, Timers

if TYPE_CHECKING:
    from server.engine import Engine

# CODING_RULES L2：只有步驟行動要比對 step_seq
_STEP_BOUND = frozenset(
    {
        Action.DEAL_ACK,
        Action.WOLF_PICK,
        Action.SEER_CHECK,
        Action.SEER_OK,
        Action.WITCH_ACT,
        Action.HUNTER_SHOOT,
        Action.SPEAK_END,
        Action.VOTE_CAST,
        Action.HOST_LINE,
        Action.HOST_NEXT,
        Action.HOST_SKIP_SPEAKER,
        Action.HOST_EXTEND,
        Action.HOST_ROLLBACK,
    }
)
_ACTOR_ACTIONS = frozenset(
    {
        Action.DEAL_ACK,
        Action.WOLF_PICK,
        Action.SEER_CHECK,
        Action.SEER_OK,
        Action.WITCH_ACT,
        Action.HUNTER_SHOOT,
        Action.SPEAK_END,
        Action.VOTE_CAST,
    }
)
# 這些動作不屬於任何步驟，遊戲結束後另外判斷
_INFO_LINES = frozenset({"peaceful", "deaths", "hunter_shot", "hunter_holster", "exile", "tie"})

Handler = Callable[["Engine", Actor, dict[str, Any]], None]


def _fail(code: ErrorCode) -> GameError:
    return GameError(code)


def dispatch(
    engine: Engine, actor: Actor, action: Action, payload: dict[str, Any], step_seq: int | None
) -> None:
    """驗證後執行：身分已由呼叫端確認；步驟序號 → 權限 → 規則。"""
    state = engine.state
    if action in _STEP_BOUND and step_seq != state.step_seq:
        raise _fail(ErrorCode.STALE_STEP)
    if not engine.policy.can(actor, action, state):
        raise _fail(ErrorCode.FORBIDDEN)
    if action in _ACTOR_ACTIONS:
        _check_actor_action(engine, actor, action)
    HANDLERS[action](engine, actor, payload)


def _check_actor_action(engine: Engine, actor: Actor, action: Action) -> None:
    from server.engine import TRANSITIONS

    state = engine.state
    if state.pause is not None or action not in TRANSITIONS[state.step].intents:
        raise _fail(ErrorCode.FORBIDDEN)
    if actor.player_id is None or actor.player_id not in state.actors:
        raise _fail(ErrorCode.FORBIDDEN)
    now = engine.now
    timing = state.timers
    if timing.opens_at is not None and now < timing.opens_at:
        raise _fail(ErrorCode.STEP_NOT_OPEN)
    past_deadline = (
        timing.deadline is not None and now > timing.deadline + config.DEADLINE_GRACE_SECONDS
    )
    if state.timed_out or past_deadline:
        raise _fail(ErrorCode.DEADLINE_PASSED)


def _player_id(actor: Actor) -> str:
    assert actor.player_id is not None
    return actor.player_id


def _mark_done(engine: Engine, player_id: str) -> None:
    engine.emit(EventType.ACTOR_DONE, players=[player_id])


# ---- 玩家行動 ----


def _deal_ack(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = _player_id(actor)
    engine.emit(EventType.DEAL_ACKED, player=player_id)
    _mark_done(engine, player_id)


def _wolf_pick(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    wolf = _player_id(actor)
    state = engine.state
    if state.night().wolf_decided:
        raise _fail(ErrorCode.FORBIDDEN)
    if payload.get("clear"):
        engine.emit(EventType.WOLF_PICK_CLEARED, wolves=[wolf])
    else:
        target = payload.get("target")
        eligible = rules.eligible_targets(state, wolf, Action.WOLF_PICK)
        if target is not None and target not in eligible:
            raise _fail(ErrorCode.INVALID_TARGET)
        engine.emit(EventType.WOLF_PICKED, wolf=wolf, target=target)
    recheck_wolves(engine)


def recheck_wolves(engine: Engine) -> None:
    """依目前選擇更新 3 秒確認（SPEC A5.6）：改選或有人離開都重新判斷。"""
    state = engine.state
    consensus = rules.wolf_consensus(state.night().wolf_picks, state.actors)
    previous = state.timers.confirm_until
    if consensus.agreed:
        # 一致但換了選項（例：全員同時改選）也要重新倒數，所以每次都重設
        engine.emit(EventType.WOLF_CONFIRMING, until=engine.now + balance.WOLF_CONFIRM_SECONDS)
    elif previous is not None:
        engine.emit(EventType.WOLF_CONFIRMING, until=None)


def decide_wolf(engine: Engine, target: str | None) -> None:
    """狼人目標定案。"""
    engine.emit(EventType.WOLF_DECIDED, target=target)
    engine.emit(EventType.ACTOR_DONE, players=list(engine.state.actors))


def _seer_check(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    seer = _player_id(actor)
    state = engine.state
    target = payload.get("target")
    if state.night().seer_target is not None:
        raise _fail(ErrorCode.FORBIDDEN)
    if target not in rules.eligible_targets(state, seer, Action.SEER_CHECK):
        raise _fail(ErrorCode.INVALID_TARGET)
    engine.emit(EventType.SEER_CHECKED, target=target, is_wolf=is_wolf(state.player(target).role))


def _seer_ok(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    if engine.state.night().seer_target is None:
        raise _fail(ErrorCode.FORBIDDEN)
    _mark_done(engine, _player_id(actor))


def _witch_act(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    witch = _player_id(actor)
    state = engine.state
    if state.night().witch_acted:
        raise _fail(ErrorCode.FORBIDDEN)
    save = bool(payload.get("save"))
    poison = payload.get("poison")
    rules.validate_witch_act(state, witch, save, poison)
    engine.emit(EventType.WITCH_ACTED, save=save, poison=poison)
    _mark_done(engine, witch)


def _hunter_shoot(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    hunter = _player_id(actor)
    target = payload.get("target")
    if engine.state.hunter_pending != hunter:
        raise _fail(ErrorCode.FORBIDDEN)
    eligible = rules.eligible_targets(engine.state, hunter, Action.HUNTER_SHOOT)
    if target is not None and target not in eligible:
        raise _fail(ErrorCode.INVALID_TARGET)
    resolve_hunter(engine, hunter, target)


def resolve_hunter(engine: Engine, hunter: str, target: str | None) -> None:
    """獵人開槍或不開槍（SPEC A8.3）：公布結果，念完才往下。"""
    state = engine.state
    name = state.player(hunter).name
    engine.emit(EventType.HUNTER_RESOLVED, hunter=hunter, target=target)
    if target is not None:
        victim = state.player(target)
        role = narration.ROLE_NAMES[rules.public_role(victim.role)]
        text = narration.render(
            "hunter_shot", engine.jianghu, name=name, target=victim.name, role=role
        )
        engine.emit(EventType.NARRATE, line_id="hunter_shot", text=text, speak=True)
        engine.kill(target, DeathCause.HUNTER)
    else:
        text = narration.render("hunter_holster", engine.jianghu, name=name)
        engine.emit(EventType.NARRATE, line_id="hunter_holster", text=text, speak=True)
    timing = state.timers.model_copy()
    timing.min_until = engine.now + timers.narration_seconds(text)
    engine.emit(EventType.TIMERS_SET, timers=timing.model_dump())
    engine.emit(EventType.ACTOR_DONE, players=[hunter])


def _speak_end(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    _mark_done(engine, _player_id(actor))


def _vote_cast(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    voter = _player_id(actor)
    state = engine.state
    target = payload.get("target")
    votes = state.vote_round()
    is_change = voter in votes.ballots
    if is_change and voter in votes.changed:
        raise _fail(ErrorCode.FORBIDDEN)
    if target is not None and target not in rules.eligible_targets(state, voter, Action.VOTE_CAST):
        raise _fail(ErrorCode.INVALID_TARGET)
    engine.emit(EventType.VOTE_CAST, voter=voter, target=target, changed=is_change)
    _mark_done(engine, voter)
    _maybe_start_vote_grace(engine)


def _maybe_start_vote_grace(engine: Engine) -> None:
    """全員投完後再等 5 秒，期間可改票，不超過原截止時間（SPEC A5.4）。"""
    state = engine.state
    timing = state.timers
    if (
        state.step is not Step.VOTE
        or timing.grace_until is not None
        or set(state.actors) - set(state.done)
    ):
        return
    grace = engine.now + balance.VOTE_ALL_CAST_GRACE_SECONDS
    if timing.deadline is not None:
        grace = min(grace, timing.deadline)
    updated = timing.model_copy()
    updated.grace_until = grace
    engine.emit(EventType.TIMERS_SET, timers=updated.model_dump())


def _bet_set(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = actor.player_id
    state = engine.state
    if (
        not config.FEATURES["bets"]
        or player_id is None
        or state.step is Step.END
        or not state.has_player(player_id)
        or not rules.can_bet(state, player_id)
    ):
        raise _fail(ErrorCode.FORBIDDEN)
    bet = Bet(wolves=list(payload.get("wolves", [])), faceless=payload.get("faceless"))
    rules.validate_bet(state, player_id, bet)
    engine.emit(EventType.BET_SET, player=player_id, wolves=bet.wolves, faceless=bet.faceless)


# ---- 聊天 ----


def _can_post(state: GameState, actor: Actor, channel: Channel, kind: ChatKind) -> bool:
    """發言權限（SPEC A9）。夜晚判斷看步驟，所以夜晚暫停也算夜晚。"""
    if actor.is_host:
        return channel is Channel.PUBLIC
    player_id = actor.player_id
    if state.step is Step.END:
        return channel is Channel.PUBLIC
    if player_id is None or not state.has_player(player_id):
        return False
    player = state.player(player_id)
    if channel is Channel.WOLF:
        return player.alive and is_wolf(player.role)
    if rules.is_night_step(state.step):
        return False
    return player.alive or is_last_words_turn(state, player_id, kind)


def is_last_words_turn(state: GameState, player_id: str, kind: ChatKind) -> bool:
    """遺言中的死者可發一則文字（SPEC A5.4）。"""
    return (
        state.step is Step.LAST_WORDS
        and state.current_speaker == player_id
        and kind is ChatKind.TEXT
        and player_id not in state.last_words_sent
    )


def _chat_send(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    state = engine.state
    channel = Channel(payload["channel"])
    kind = ChatKind(payload.get("kind", ChatKind.TEXT))
    as_disguise = payload.get("as") == "disguise"
    if not _can_post(state, actor, channel, kind):
        raise _fail(ErrorCode.FORBIDDEN)
    author = actor.player_id
    display = author
    period = None
    if as_disguise:
        if (
            author is None
            or channel is not Channel.PUBLIC
            or not disguise.can_disguise(state, author)
        ):
            raise _fail(ErrorCode.FORBIDDEN)
        assert state.disguise is not None
        display = state.disguise.target_id
        period = len(state.disguise.periods) - 1
    is_last_words = (
        author is not None
        and channel is Channel.PUBLIC
        and state.has_player(author)
        and not state.player(author).alive
        and state.step is not Step.END
    )
    engine.chat_seq += 1
    engine.emit(
        EventType.CHAT_SENT,
        id=engine.chat_seq,
        channel=channel.value,
        real_author=author,
        display=display,
        is_host=actor.is_host,
        disguise_period=period,
        kind=kind.value,
        content=payload.get("content"),
        media_id=payload.get("media_id"),
        is_last_words=is_last_words,
    )


# ---- 管理員 ----


def _admin_kick(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = payload.get("player")
    state = engine.state
    if (
        not isinstance(player_id, str)
        or not state.has_player(player_id)
        or not state.player(player_id).alive
        or state.step is Step.END
    ):
        raise _fail(ErrorCode.INVALID_TARGET)
    remove_player(engine, player_id, DeathCause.KICK)


def remove_player(engine: Engine, player_id: str, cause: DeathCause) -> None:
    """被踢或手動判死（SPEC A5.6）：公開角色、處理進行中的步驟、立即判定勝負。"""
    state = engine.state
    if state.nights:
        engine.emit(EventType.NIGHT_TARGET_CLEARED, player=player_id)
    if state.step is Step.WOLF:
        night = state.night()
        cleared = [w for w, t in night.wolf_picks.items() if t == player_id or w == player_id]
        if cleared:
            engine.emit(EventType.WOLF_PICK_CLEARED, wolves=cleared)
    if state.step is Step.VOTE:
        engine.emit(EventType.VOTE_VOIDED, player=player_id)
    engine.kill(player_id, cause)
    if state.narrator_id == player_id:
        engine.emit(EventType.NARRATOR_SET, player=None)
    winner = rules.check_win(state)
    if winner is not None:
        engine.finish(winner)
        return
    if state.step is Step.WOLF and not state.night().wolf_decided:
        recheck_wolves(engine)
    _maybe_start_vote_grace(engine)


def _admin_end(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    if engine.state.step is Step.END:
        raise _fail(ErrorCode.FORBIDDEN)
    engine.finish(Winner.NONE)


def _admin_pause(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    state = engine.state
    if state.pause is not None or state.step is Step.END:
        raise _fail(ErrorCode.FORBIDDEN)
    if not engine.policy.can_pause(actor, state):
        raise _fail(ErrorCode.FORBIDDEN)
    engine.pause(PauseReason.ADMIN)


def _admin_resume(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    pause = engine.state.pause
    if pause is None or pause.resume_at is not None or not can_resume(actor, pause.reason):
        raise _fail(ErrorCode.FORBIDDEN)
    engine.schedule_resume()


def _narrator_takeover(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = actor.player_id
    if player_id is None or not engine.state.has_player(player_id):
        raise _fail(ErrorCode.FORBIDDEN)
    engine.emit(EventType.NARRATOR_SET, player=player_id)


def _admin_narrator(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = payload.get("player")
    state = engine.state
    if state.mode is not Mode.AUTO or not actor.is_admin:
        raise _fail(ErrorCode.FORBIDDEN)
    if not isinstance(player_id, str) or not state.has_player(player_id):
        raise _fail(ErrorCode.INVALID_TARGET)
    engine.emit(EventType.NARRATOR_SET, player=player_id)


# ---- 上帝模式 ----


def _host_next(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    _force_next(engine, speak=True)


def _force_next(engine: Engine, speak: bool) -> None:
    """主持人推進（SPEC A8.2）：未完成者套用預設行動，再進下一步。"""
    state = engine.state
    if state.step is Step.END or state.pause is not None:
        raise _fail(ErrorCode.FORBIDDEN)
    if state.step is Step.DAWN and not state.announced:
        engine.announce_dawn()
    now = engine.now
    if not engine.is_step_complete(now):
        _complete_now(engine, now)
    engine.go(engine.next_step(), speak=speak)


def _complete_now(engine: Engine, now: float) -> None:
    from server.engine import ACTION_STEPS

    state = engine.state
    if state.step in ACTION_STEPS and not state.timed_out:
        engine.apply_timeouts()
    # 主持人明確按了下一句，就不再等開放時間與女巫最短時間
    engine.emit(EventType.TIMERS_SET, timers=Timers().model_dump())


def _host_line(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    from server.engine import LINE_STEPS

    state = engine.state
    line_id = payload.get("line_id")
    speak = bool(payload.get("speak", True))
    if not isinstance(line_id, str) or line_id not in narration.LINES:
        raise _fail(ErrorCode.INVALID_TARGET)
    if line_id in _INFO_LINES or (line_id == state.line_id and line_id in LINE_STEPS):
        _replay_line(engine, line_id)
        return
    if state.step is Step.END or LINE_STEPS.get(line_id) is not engine.next_step():
        raise _fail(ErrorCode.INVALID_TARGET)
    _force_next(engine, speak=speak)


def _host_replay(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    line_id = payload.get("line_id")
    if not isinstance(line_id, str) or line_id not in narration.LINES:
        raise _fail(ErrorCode.INVALID_TARGET)
    _replay_line(engine, line_id)


def _replay_line(engine: Engine, line_id: str) -> None:
    """重念（SPEC B9）：只重念最近念過的那句，文字直接取自事件紀錄。"""
    for event in reversed(engine.log):
        if event.type is EventType.NARRATE and event.data["line_id"] == line_id:
            engine.emit(EventType.NARRATE, line_id=line_id, text=event.data["text"], speak=True)
            return
    raise _fail(ErrorCode.INVALID_TARGET)


def _host_skip_speaker(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    state = engine.state
    if state.current_speaker is None:
        raise _fail(ErrorCode.FORBIDDEN)
    _mark_done(engine, state.current_speaker)


def _host_extend(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    state = engine.state
    seconds = payload.get("s", balance.HOST_EXTEND_SECONDS)
    if state.timers.deadline is None or not isinstance(seconds, int) or seconds <= 0:
        raise _fail(ErrorCode.FORBIDDEN)
    updated = state.timers.model_copy()
    assert updated.deadline is not None
    updated.deadline += seconds
    engine.emit(EventType.TIMERS_SET, timers=updated.model_dump())


def _host_rollback(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    """回上一步（SPEC A10、L23）：還原存活、期數、用藥；聊天與輪替不回滾。"""
    history = engine._history
    if engine.state.step is Step.END or len(history) < 2:
        raise _fail(ErrorCode.FORBIDDEN)
    history.pop()
    entered_at, dump = history[-1]
    restored = GameState.model_validate(dump)
    restored.timers = timers.shifted(restored.timers, engine.now - entered_at)
    restored.pause = None
    engine.emit(EventType.ROLLED_BACK, state=restored.model_dump(mode="json"))


def _host_set_alive(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    state = engine.state
    player_id = payload.get("player")
    alive = bool(payload.get("alive"))
    if (
        not isinstance(player_id, str)
        or not state.has_player(player_id)
        or state.player(player_id).alive == alive
        or state.step is Step.END
    ):
        raise _fail(ErrorCode.INVALID_TARGET)
    if alive:
        engine.emit(EventType.PLAYER_REVIVED, player=player_id)
    else:
        remove_player(engine, player_id, DeathCause.MANUAL)


def _host_reshow_card(engine: Engine, actor: Actor, payload: dict[str, Any]) -> None:
    player_id = payload.get("player")
    if not isinstance(player_id, str) or not engine.state.has_player(player_id):
        raise _fail(ErrorCode.INVALID_TARGET)
    engine.emit(EventType.CARD_RESHOWN, player=player_id)


# ---- 千面狼事件 ----


def emit_disguise(engine: Engine, change: disguise.DisguiseChange) -> None:
    """把規則回傳的變動轉成事件。"""
    engine.emit(
        EventType.DISGUISE_CHANGED,
        target=change.target_id,
        rounds_left=change.rounds_left,
        ended_reason=change.ended_reason.value if change.ended_reason else None,
    )


def end_disguise(engine: Engine) -> None:
    """遊戲結束時收掉最後一期（SPEC B6 ended_reason）。"""
    engine.emit(
        EventType.DISGUISE_CHANGED,
        target=None,
        rounds_left=0,
        ended_reason=DisguiseEnd.GAME_END.value,
    )


def open_first_period(state: GameState) -> None:
    """建局時記下第 1 期；此時事件紀錄尚未開始，所以直接寫入初始狀態。"""
    assert state.disguise is not None and state.disguise.target_id is not None
    state.disguise.periods.append(DisguisePeriod(target_id=state.disguise.target_id, from_round=1))


HANDLERS: dict[Action, Handler] = {
    Action.DEAL_ACK: _deal_ack,
    Action.WOLF_PICK: _wolf_pick,
    Action.SEER_CHECK: _seer_check,
    Action.SEER_OK: _seer_ok,
    Action.WITCH_ACT: _witch_act,
    Action.HUNTER_SHOOT: _hunter_shoot,
    Action.SPEAK_END: _speak_end,
    Action.VOTE_CAST: _vote_cast,
    Action.BET_SET: _bet_set,
    Action.CHAT_SEND: _chat_send,
    Action.NARRATOR_TAKEOVER: _narrator_takeover,
    Action.ADMIN_KICK: _admin_kick,
    Action.ADMIN_END: _admin_end,
    Action.ADMIN_PAUSE: _admin_pause,
    Action.ADMIN_RESUME: _admin_resume,
    Action.ADMIN_NARRATOR: _admin_narrator,
    Action.HOST_LINE: _host_line,
    Action.HOST_REPLAY: _host_replay,
    Action.HOST_NEXT: _host_next,
    Action.HOST_SKIP_SPEAKER: _host_skip_speaker,
    Action.HOST_EXTEND: _host_extend,
    Action.HOST_ROLLBACK: _host_rollback,
    Action.HOST_SET_ALIVE: _host_set_alive,
    Action.HOST_RESHOW_CARD: _host_reshow_card,
}
