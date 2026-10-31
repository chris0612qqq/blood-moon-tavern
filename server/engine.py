"""遊戲引擎（SPEC B4、B5）：轉移表、步驟進出、倒數、不變式。意圖處理在 actions.py。"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from server import actions, balance, config, disguise, narration, rules, timers
from server.clock import Clock
from server.enums import Action, DayContext, DeathCause, Mode, PauseReason, Role, Step, Winner
from server.errors import IllegalTransition, InvariantBroken
from server.events import Event, EventType, apply, replay
from server.modes import Actor, ModePolicy, policy_for
from server.rng import GameRng
from server.roles import is_wolf, night_step_pairs, roles_acting_in
from server.state import GameState, PlayerState, Timers


@dataclass(frozen=True)
class StepRule:
    intents: frozenset[Action]
    exits: frozenset[Step]


def _rule(intents: Sequence[Action], exits: Sequence[Step]) -> StepRule:
    return StepRule(frozenset(intents), frozenset(exits))


# CODING_RULES L6：步驟 → 允許的意圖 → 下一步。任何步驟都可因勝負或中途結束進 END。
TRANSITIONS: Mapping[Step, StepRule] = {
    Step.DEAL: _rule([Action.DEAL_ACK], [Step.NIGHT_START]),
    Step.NIGHT_START: _rule([], [Step.WOLF]),
    Step.WOLF: _rule([Action.WOLF_PICK], [Step.WOLF_END]),
    Step.WOLF_END: _rule([], [Step.SEER, Step.WITCH, Step.DAWN]),
    Step.SEER: _rule([Action.SEER_CHECK, Action.SEER_OK], [Step.SEER_END]),
    Step.SEER_END: _rule([], [Step.WITCH, Step.DAWN]),
    Step.WITCH: _rule([Action.WITCH_ACT], [Step.WITCH_END]),
    Step.WITCH_END: _rule([], [Step.DAWN]),
    Step.DAWN: _rule([], [Step.HUNTER, Step.LAST_WORDS, Step.DAY_SPEAK]),
    Step.HUNTER: _rule([Action.HUNTER_SHOOT], [Step.LAST_WORDS, Step.DAY_SPEAK, Step.NIGHT_START]),
    Step.LAST_WORDS: _rule([Action.SPEAK_END], [Step.LAST_WORDS, Step.DAY_SPEAK, Step.NIGHT_START]),
    Step.DAY_SPEAK: _rule([Action.SPEAK_END], [Step.DAY_SPEAK, Step.VOTE]),
    Step.VOTE: _rule([Action.VOTE_CAST], [Step.REVEAL]),
    Step.REVEAL: _rule([], [Step.HUNTER, Step.LAST_WORDS, Step.NIGHT_START]),
    Step.END: _rule([], []),
}

STEP_LINES: Mapping[Step, str] = {
    Step.NIGHT_START: "night_start",
    Step.WOLF: "wolf_open",
    Step.WOLF_END: "wolf_close",
    Step.SEER: "seer_open",
    Step.SEER_END: "seer_close",
    Step.WITCH: "witch_open",
    Step.WITCH_END: "witch_close",
    Step.DAWN: "dawn",
    Step.HUNTER: "hunter",
    Step.LAST_WORDS: "last_words",
    Step.DAY_SPEAK: "speak",
    Step.VOTE: "vote",
}
LINE_STEPS: Mapping[str, Step] = {line: step for step, line in STEP_LINES.items()}

# 有行動者、全員完成就能結束的步驟
ACTION_STEPS = frozenset(
    {
        Step.DEAL,
        Step.WOLF,
        Step.SEER,
        Step.WITCH,
        Step.HUNTER,
        Step.LAST_WORDS,
        Step.DAY_SPEAK,
        Step.VOTE,
    }
)
# 這些步驟中死亡已生效、尚未判定勝負，存活數可能暫時為 0（SPEC A5.5）
_DEATH_PENDING_STEPS = frozenset({Step.DAWN, Step.HUNTER, Step.REVEAL, Step.END})


def night_sequence() -> list[Step]:
    """夜晚步驟順序，從角色註冊表推導（CODING_RULES G7）。"""
    middle = [step for pair in night_step_pairs() for step in pair]
    return [Step.NIGHT_START, *middle, Step.DAWN]


class Engine:
    """處理意圖與時間，產生事件。不碰網路與資料庫（SPEC B3 第 5 點由 room 保證）。"""

    def __init__(
        self,
        state: GameState,
        clock: Clock,
        rng: GameRng,
        strict: bool = True,
        log: list[Event] | None = None,
    ) -> None:
        self.state = state
        self.clock = clock
        self.rng = rng
        self.strict = strict
        self.policy: ModePolicy = policy_for(state.mode)
        self.log: list[Event] = log if log is not None else []
        self.chat_seq = 0
        self.invariant_error: str | None = None
        self._pending: list[Event] = []
        self._history: deque[tuple[float, dict[str, Any]]] = deque(maxlen=config.SNAPSHOT_KEEP)

    @classmethod
    def create(
        cls,
        players: Sequence[tuple[str, str]],
        mode: Mode,
        history: Mapping[str, rules.RoleRecord],
        clock: Clock,
        rng: GameRng,
        settings: Mapping[str, int] | None = None,
        narrator_id: str | None = None,
        strict: bool = True,
    ) -> Engine:
        """發牌開局（SPEC A8.1）。`players` 為依座位排好的 (id, 名字)。"""
        dealt = rules.deal([pid for pid, _ in players], history, rng)
        state = GameState(
            mode=mode,
            players=[
                PlayerState(id=pid, name=name, seat=seat, role=dealt[pid])
                for seat, (pid, name) in enumerate(players, start=1)
            ],
            settings=dict(settings or {}),
            narrator_id=narrator_id,
        )
        state.disguise = disguise.on_deal(state, rng)
        if state.disguise.target_id is not None:
            actions.open_first_period(state)
        engine = cls(state, clock, rng, strict=strict)
        engine.log.append(
            Event(
                type=EventType.GAME_CREATED,
                ts=clock.now(),
                data={"state": state.model_dump(mode="json")},
            )
        )
        engine._enter(Step.DEAL)
        engine.flush()
        return engine

    @classmethod
    def restore(
        cls, events: Sequence[Event], clock: Clock, rng: GameRng, strict: bool = True
    ) -> Engine:
        """伺服器重啟：重播事件後進入系統暫停（SPEC A11）。L24：剩餘 ≤ 0 視為剛好到期。"""
        state = replay(events)
        engine = cls(state, clock, rng, strict=strict, log=list(events))
        engine.chat_seq = sum(1 for e in events if e.type is EventType.CHAT_SENT)
        if state.step is not Step.END:
            last_ts = events[-1].ts
            remaining = (
                state.pause.remaining if state.pause else timers.to_remaining(state.timers, last_ts)
            )
            engine.emit(
                EventType.PAUSED,
                reason=PauseReason.SYSTEM.value,
                remaining={name: max(left, 0.0) for name, left in remaining.items()},
            )
        engine.flush()
        return engine

    def load_history(self, snapshots: Sequence[tuple[float, dict[str, Any]]]) -> None:
        """重啟後把快照放回，回上一步才接得上（CODING_RULES G3）。"""
        if self.state.mode is Mode.GOD:
            self._history.extend(snapshots)

    # ---- 共用工具 ----

    @property
    def now(self) -> float:
        return self.clock.now()

    def emit(self, event_type: EventType, **data: Any) -> Event:
        """產生事件並立即套用（G1）。"""
        event = Event(type=event_type, ts=self.now, data=data)
        apply(self.state, event)
        self.log.append(event)
        self._pending.append(event)
        return event

    def flush(self) -> list[Event]:
        """取出尚未交給呼叫端的事件，並檢查不變式。"""
        self.check_invariants()
        events, self._pending = self._pending, []
        return events

    def seconds(self, key: str, default: int) -> int:
        """開房設定可覆蓋的倒數秒數（SPEC A2）。"""
        return self.state.settings.get(key, default)

    @property
    def jianghu(self) -> bool:
        return bool(self.state.settings.get("jianghu", 0)) and config.FEATURES["jianghu_narration"]

    def forget_chat(self, count: int) -> None:
        """資料庫寫入成功後，把最近 count 個事件中的聊天移出記憶體（CODING_RULES P11）。

        聊天不影響重播以外的邏輯，留著只會讓記憶體隨訊息數無限成長。
        """
        cut = len(self.log) - count
        self.log[cut:] = [e for e in self.log[cut:] if e.type is not EventType.CHAT_SENT]

    def checkpoint(self) -> tuple[GameState, int, int]:
        """處理意圖前的保存點；寫入失敗時用 revert 復原（CODING_RULES E4）。"""
        return self.state.model_copy(deep=True), len(self.log), self.chat_seq

    def revert(self, point: tuple[GameState, int, int]) -> None:
        state, log_length, chat_seq = point
        self.state = state
        del self.log[log_length:]
        self.chat_seq = chat_seq
        self._pending = []

    # ---- 對外入口 ----

    def handle(
        self,
        actor: Actor,
        action: Action,
        payload: Mapping[str, Any] | None = None,
        step_seq: int | None = None,
    ) -> list[Event]:
        """處理一則意圖（SPEC B4）。驗證順序依 CODING_RULES E2；不合法拋 GameError。"""
        actions.dispatch(self, actor, action, dict(payload or {}), step_seq)
        return self.flush()

    def tick(self) -> list[Event]:
        """時間推進（SPEC B4）。每 250 ms 由 timers 呼叫。"""
        state = self.state
        now = self.now
        if state.step is Step.END:
            return self.flush()
        if state.pause is not None:
            if state.pause.resume_at is not None and now >= state.pause.resume_at:
                self._finish_resume(now)
            return self.flush()
        self._run_time_triggers(now)
        if self.is_step_complete(now):
            next_step = self.next_step()
            if next_step is Step.END or self.policy.should_advance(next_step):
                self.go(next_step)
        return self.flush()

    def system_pause(self, reason: PauseReason) -> list[Event]:
        """系統暫停（SPEC A11）：重啟、多人斷線、主持人斷線。已暫停或已結束則不動作。"""
        if self.state.pause is None and self.state.step is not Step.END:
            self.pause(reason)
        return self.flush()

    def schedule_resume(self) -> list[Event]:
        """開始繼續前的 5 秒倒數（SPEC A8.6）。"""
        if self.state.pause is not None and self.state.pause.resume_at is None:
            self.emit(EventType.RESUME_SCHEDULED, at=self.now + balance.RESUME_COUNTDOWN_SECONDS)
        return self.flush()

    # ---- 暫停 ----

    def pause(self, reason: PauseReason) -> None:
        self.emit(
            EventType.PAUSED,
            reason=reason.value,
            remaining=timers.to_remaining(self.state.timers, self.now),
        )

    def _finish_resume(self, now: float) -> None:
        pause = self.state.pause
        assert pause is not None
        resumed = timers.from_remaining(pause, now)
        self.emit(EventType.RESUMED, timers=resumed.model_dump())
        # SPEC A8.6：無管理員模式自動重念；上帝模式由主持人按重念
        if self.state.mode is Mode.AUTO and self.state.line_id is not None:
            self.narrate_current()

    # ---- 時間觸發 ----

    def _run_time_triggers(self, now: float) -> None:
        state = self.state
        confirm = state.timers.confirm_until
        if state.step is Step.DAWN and not state.announced:
            if state.timers.opens_at is not None and now >= state.timers.opens_at:
                self.announce_dawn()
        elif state.step is Step.WOLF and confirm is not None and now >= confirm:
            actions.decide_wolf(self, state.night().wolf_picks[state.actors[0]])
        if (
            not state.timed_out
            and state.step in ACTION_STEPS
            and state.timers.deadline is not None
            and now >= state.timers.deadline + config.DEADLINE_GRACE_SECONDS
        ):
            self.apply_timeouts()

    def apply_timeouts(self) -> None:
        """時間到：套用預設行動（SPEC A5.6）。"""
        state = self.state
        if state.step is Step.DEAL:
            for pid in state.actors:
                if pid not in state.done:
                    self.emit(EventType.DEAL_ACKED, player=pid)
        elif state.step is Step.WOLF and not state.night().wolf_decided:
            picks = state.night().wolf_picks
            actions.decide_wolf(self, rules.wolf_timeout_choice(picks, state.actors, self.rng))
        elif state.step is Step.WITCH and not state.night().witch_acted:
            self.emit(EventType.WITCH_ACTED, save=False, poison=None)
        elif state.step is Step.HUNTER and state.hunter_pending is not None:
            actions.resolve_hunter(self, state.hunter_pending, None)
        elif state.step is Step.VOTE:
            for pid in state.actors:
                if pid not in state.vote_round().ballots:
                    self.emit(EventType.VOTE_CAST, voter=pid, target=None, changed=False)
        self.emit(EventType.ACTOR_DONE, players=list(state.actors))
        self.emit(EventType.TIMED_OUT)

    def is_step_complete(self, now: float) -> bool:
        """目前步驟是否可以離開（CODING_RULES L7：每步都有全員完成與時間到兩條路）。"""
        state = self.state
        clock_state = state.timers
        if clock_state.opens_at is not None and now < clock_state.opens_at:
            return False
        if clock_state.min_until is not None and now < clock_state.min_until:
            return False
        if state.step is Step.END or (state.step is Step.DAWN and not state.announced):
            return False
        if state.step in ACTION_STEPS:
            if set(state.actors) - set(state.done):
                return False
            return clock_state.grace_until is None or now >= clock_state.grace_until
        return clock_state.deadline is None or now >= clock_state.deadline

    # ---- 轉移 ----

    def should_enter(self, step: Step) -> bool:
        """夜晚步驟是否要進入：該角色無存活者就略過（CODING_RULES L8、SPEC A5.6）。"""
        acting = roles_acting_in(step) or roles_acting_in(_open_step_of(step))
        if not acting:
            return True
        return any(p.alive and p.role in acting for p in self.state.players)

    def next_step(self) -> Step:
        """目前步驟結束後的下一步（SPEC B5）。"""
        state = self.state
        step = state.step
        if step is Step.DEAL:
            return Step.NIGHT_START
        closing = dict(night_step_pairs()).get(step)
        if closing is not None:
            # 已經念過睜眼就一定要念閉眼，即使行動者在步驟中被踢（SPEC A5.6）
            return closing
        sequence = night_sequence()
        if step in sequence and step is not Step.DAWN:
            later = sequence[sequence.index(step) + 1 :]
            return next(s for s in later if self.should_enter(s))
        if step is Step.DAY_SPEAK:
            return Step.DAY_SPEAK if state.speak_queue else Step.VOTE
        if step is Step.VOTE:
            return Step.REVEAL
        if step is Step.LAST_WORDS and state.speak_queue:
            return Step.LAST_WORDS
        return self._after_deaths()

    def _after_deaths(self) -> Step:
        """G9 觸發優先序：狼全滅 → 獵人開槍 → 勝負 → 遺言 → 下一階段（SPEC A5.5）。"""
        state = self.state
        if not rules.alive_wolves(state):
            return Step.END
        if state.hunter_pending is not None:
            return Step.HUNTER
        if rules.check_win(state) is not None:
            return Step.END
        if rules.last_words_queue(state):
            return Step.LAST_WORDS
        return Step.DAY_SPEAK if state.day_context is DayContext.DAWN else Step.NIGHT_START

    def go(self, step: Step, speak: bool = True) -> None:
        """進入下一步。END 另外處理（勝負或中途結束）。"""
        if step is Step.END:
            winner = rules.check_win(self.state)
            assert winner is not None
            self.finish(winner)
            return
        if step not in TRANSITIONS[self.state.step].exits:
            raise IllegalTransition(f"{self.state.step} -> {step}")
        self._enter(step, speak=speak)

    def finish(self, winner: Winner) -> None:
        """結束遊戲（SPEC A8.7）。"""
        state = self.state
        if state.disguise is not None and state.disguise.target_id is not None:
            actions.end_disguise(self)
        self.emit(EventType.GAME_ENDED, winner=winner.value)
        text = narration.render("win", self.jianghu, side=narration.SIDE_NAMES[winner])
        self.emit(EventType.NARRATE, line_id="win", text=text, speak=True)

    def _plan_actors(self, step: Step) -> list[str]:
        state = self.state
        if step is Step.DEAL:
            return [p.id for p in state.players]
        if step is Step.VOTE:
            return [p.id for p in rules.alive_players(state)]
        if step is Step.HUNTER:
            assert state.hunter_pending is not None
            return [state.hunter_pending]
        acting = roles_acting_in(step)
        return [p.id for p in state.players if p.alive and p.role in acting]

    def _action_seconds(self, step: Step) -> int:
        night = self.seconds("night", balance.NIGHT_STEP_SECONDS)
        table = {
            Step.DEAL: self.seconds("deal", balance.DEAL_SECONDS),
            Step.WOLF: night,
            Step.SEER: night,
            Step.WITCH: night,
            Step.HUNTER: self.seconds("hunter", balance.HUNTER_SECONDS),
            Step.LAST_WORDS: self.seconds("last_words", balance.LAST_WORDS_SECONDS),
            Step.DAY_SPEAK: self.seconds("speak", rules.speak_seconds(len(self.state.players))),
            Step.VOTE: self.seconds("vote", balance.VOTE_SECONDS),
        }
        return table.get(step, 0)

    def _enter(self, step: Step, speak: bool = True) -> None:
        """進入步驟：算出時間點與行動者（SPEC A8.2：倒數從旁白念完才開始）。"""
        state = self.state
        same_step = step is state.step
        if step is Step.NIGHT_START:
            self._begin_night()
        queue, speaker = self._speech_queue(step, same_step)
        line_id, text = self._line_for(step, speaker)
        now = self.now
        lead = 0.0 if step is Step.DEAL else self._lead_seconds(line_id, same_step)
        spoken = timers.narration_seconds(text) if text and speak else 0.0
        opens_at = now + lead + spoken
        deadline: float | None = opens_at + self._action_seconds(step)
        min_until = None
        actors = [speaker] if speaker else ([] if step not in ACTION_STEPS else None)
        if actors is None:
            actors = self._plan_actors(step)
        if step is Step.WITCH:
            min_until = opens_at + self.rng.uniform_int(
                balance.WITCH_MIN_SECONDS_LOW, balance.WITCH_MIN_SECONDS_HIGH
            )
            if state.witch_antidote_used and state.witch_poison_used:
                deadline = min_until
        elif step is Step.DAWN:
            deadline = None
        self.emit(
            EventType.STEP_ENTERED,
            step=step.value,
            actors=actors,
            timers=Timers(opens_at=opens_at, deadline=deadline, min_until=min_until).model_dump(),
            line_id=line_id,
            speaker=speaker,
            speak_queue=queue,
            clear_last_words=step is Step.LAST_WORDS,
        )
        if text:
            self.emit(EventType.NARRATE, line_id=line_id, text=text, speak=speak)
        if step is Step.REVEAL:
            self._reveal_votes()
        elif step is Step.HUNTER and not rules.eligible_targets(
            state, actors[0], Action.HUNTER_SHOOT
        ):
            actions.resolve_hunter(self, actors[0], None)  # L16
        if state.mode is Mode.GOD:
            self._history.append((now, state.model_dump(mode="json")))

    def _lead_seconds(self, line_id: str | None, same_step: bool) -> float:
        if line_id is None:
            return 0.0
        if self.state.mode is Mode.GOD:
            return timers.sfx_seconds(line_id)
        return 0.0 if same_step else timers.step_gap(line_id)

    def _begin_night(self) -> None:
        state = self.state
        self.emit(EventType.NIGHT_BEGAN, round_no=state.round_no + 1)
        change = disguise.on_round_start(state, self.rng)
        if change is not None:
            actions.emit_disguise(self, change)

    def _speech_queue(self, step: Step, same_step: bool) -> tuple[list[str], str | None]:
        state = self.state
        if step not in (Step.LAST_WORDS, Step.DAY_SPEAK):
            return [], None
        if same_step:
            queue = list(state.speak_queue)
        elif step is Step.LAST_WORDS:
            queue = rules.last_words_queue(state)
        else:
            queue = rules.speak_order(state)
            if not queue:
                # L18：不該發生，寧可暫停也不要猜（總則 5）
                raise InvariantBroken("speak_order_empty")
        return queue[1:], queue[0]

    def _line_for(self, step: Step, speaker: str | None) -> tuple[str | None, str]:
        if step is Step.REVEAL:
            result = rules.tally(self.state.vote_round().ballots)
            if result.exiled is None:
                return "tie", narration.render("tie", self.jianghu)
            name = self.state.player(result.exiled).name
            return "exile", narration.render("exile", self.jianghu, name=name)
        line_id = STEP_LINES.get(step)
        if line_id is None:
            return None, ""
        params = {"name": self.state.player(speaker).name} if speaker else {}
        return line_id, narration.render(line_id, self.jianghu, **params)

    def narrate_current(self) -> None:
        """重念目前這句。"""
        state = self.state
        line_id = state.line_id
        assert line_id is not None
        if line_id == "tie":
            text = narration.render("tie", self.jianghu)
        elif line_id == "exile":
            exiled = state.vote_round().exiled
            assert exiled is not None
            text = narration.render("exile", self.jianghu, name=state.player(exiled).name)
        else:
            _, text = self._line_for(LINE_STEPS[line_id], state.current_speaker)
        self.emit(EventType.NARRATE, line_id=line_id, text=text, speak=True)

    # ---- 天亮與揭曉 ----

    def announce_dawn(self) -> None:
        """公布夜晚死亡（SPEC A8.3）：死亡在天亮才生效，不公布死因。"""
        state = self.state
        deaths = rules.resolve_night(state.night())
        self.emit(EventType.DAWN_ANNOUNCED, count=len(deaths))
        for player_id, cause in sorted(deaths, key=lambda d: state.player(d[0]).seat):
            if state.player(player_id).alive:
                self.kill(player_id, cause)
        entries = [
            (state.player(pid).name, rules.public_role(state.player(pid).role))
            for pid in state.dawn_deaths
        ]
        if entries:
            line_id = "deaths"
            text = narration.render(
                "deaths", self.jianghu, names_with_roles=narration.names_with_roles(entries)
            )
            show = len(entries) * balance.REVEAL_DEATH_EACH_SECONDS
        else:
            line_id = "peaceful"
            text = narration.render("peaceful", self.jianghu)
            show = balance.PEACEFUL_NIGHT_SECONDS
        auto = state.mode is Mode.AUTO
        self.emit(EventType.NARRATE, line_id=line_id, text=text, speak=auto)
        wait = max(show, timers.narration_seconds(text)) if auto else show
        self.emit(EventType.TIMERS_SET, timers=Timers(deadline=self.now + wait).model_dump())

    def _reveal_votes(self) -> None:
        state = self.state
        ballots = dict(state.vote_round().ballots)
        result = rules.tally(ballots)
        self.emit(EventType.VOTES_REVEALED, exiled=result.exiled, ballots=ballots)
        if result.exiled is not None:
            self.kill(result.exiled, DeathCause.VOTE)
        show = len(ballots) * balance.REVEAL_VOTE_EACH_SECONDS + balance.REVEAL_FOCUS_SECONDS
        timing = state.timers
        assert timing.opens_at is not None
        self.emit(
            EventType.TIMERS_SET,
            timers=Timers(opens_at=timing.opens_at, deadline=timing.opens_at + show).model_dump(),
        )

    def kill(self, player_id: str, cause: DeathCause) -> None:
        """任何死亡都走這裡（SPEC B5）：更新存活、獵人、遺言、千面狼。"""
        state = self.state
        player = state.player(player_id)
        context = state.day_context
        hunter_can_shoot = player.role is Role.HUNTER and rules.can_shoot(cause)
        at_dawn = context is DayContext.DAWN and cause in (
            DeathCause.WOLF,
            DeathCause.POISON,
            DeathCause.HUNTER,
        )
        has_last_words = (
            context is not None
            and cause not in (DeathCause.KICK, DeathCause.MANUAL)
            and rules.gets_last_words(state.round_no, context)
        )
        self.emit(
            EventType.PLAYER_DIED,
            player=player_id,
            cause=cause.value,
            public_role=rules.public_role(player.role).value,
            hunter_pending=hunter_can_shoot,
            dawn_death=at_dawn,
            last_words=has_last_words,
        )
        change = disguise.on_death(state, player_id, self.rng)
        if change is not None:
            actions.emit_disguise(self, change)

    # ---- 不變式 ----

    def check_invariants(self) -> None:
        """CODING_RULES 2.4：測試與開發模式拋例外；正式模式記錄並系統暫停（總則 5）。"""
        problem = self._find_invariant_problem()
        if problem is None:
            return
        if self.strict:
            raise InvariantBroken(problem)
        self.invariant_error = problem
        if self.state.pause is None and self.state.step is not Step.END:
            self.pause(PauseReason.SYSTEM)

    def _find_invariant_problem(self) -> str | None:
        state = self.state
        wolves = sum(1 for p in state.players if p.alive and is_wolf(p.role))
        good = sum(1 for p in state.players if p.alive and not is_wolf(p.role))
        if state.step not in _DEATH_PENDING_STEPS and (wolves == 0 or good == 0):
            return "side_empty"
        if sum(1 for p in state.players if p.role is Role.FACELESS) != 1:
            return "faceless_count"
        target = state.disguise.target_id if state.disguise else None
        if (
            target is not None
            and state.disguise is not None
            and (target == state.disguise.faceless_id or not state.player(target).alive)
        ):
            return "disguise_target"
        for night in state.nights:
            if night.witch_saved and night.witch_poison is not None:
                return "witch_double_use"
        return None


def _open_step_of(end_step: Step) -> Step:
    """閉眼步驟對應的睜眼步驟；其他步驟回傳自己。"""
    return next((s for s, e in night_step_pairs() if e is end_step), end_step)
