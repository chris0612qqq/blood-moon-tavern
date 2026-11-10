"""引擎情境（SPEC B5、D4、CODING_RULES L1–L24、不變式）。名稱含規則編號（T3）。"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from server import actions, balance
from server.clock import FakeClock
from server.engine import ACTION_STEPS, TRANSITIONS, Engine, night_sequence
from server.enums import Action, Channel, DeathCause, Mode, PauseReason, Role, Step, Winner
from server.errors import ErrorCode, GameError, IllegalTransition, InvariantBroken
from server.events import Event, EventType, replay
from server.modes import Actor
from server.rng import GameRng
from server.state import GameState

ADMIN = Actor(is_admin=True)
HOST = Actor(is_admin=True, is_host=True)
ROLES_8 = {
    "p1": Role.VILLAGER,
    "p2": Role.SEER,
    "p3": Role.WITCH,
    "p4": Role.FACELESS,
    "p5": Role.WOLF,
    "p6": Role.HUNTER,
    "p7": Role.VILLAGER,
    "p8": Role.VILLAGER,
}


class Game:
    """固定角色的測試局。以 monkeypatch 式替換 deal，讓情境可讀。"""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        roles: dict[str, Role] | None = None,
        mode: Mode = Mode.AUTO,
        seed: int = 1,
        spoken: dict[str, str] | None = None,
    ) -> None:
        roles = roles or ROLES_8
        self.nominate: tuple[str, ...] = ()
        monkeypatch.setattr("server.rules.deal", lambda ids, history, rng, plan=None: dict(roles))
        self.clock = FakeClock()
        players = [(pid, pid.upper()) for pid in roles]
        narrator = None if mode is Mode.GOD else "p1"
        self.engine = Engine.create(
            players, mode, {}, self.clock, GameRng(seed), narrator_id=narrator, spoken=spoken
        )

    @property
    def state(self) -> GameState:
        return self.engine.state

    def act(self, who: str | Actor, action: Action, /, **payload: Any) -> list[Event]:
        actor = who if isinstance(who, Actor) else Actor(player_id=who)
        return self.engine.handle(actor, action, payload, self.state.step_seq)

    def remove(self, player: str) -> list[Event]:
        """有人中途出局（SPEC A5.6）。上帝模式由主持人手動判死，這裡兩種模式都直接測。"""
        actions.remove_player(self.engine, player, DeathCause.MANUAL)
        return self.engine.flush()

    def run(self, seconds: float) -> None:
        """讓時間前進並持續 tick。"""
        end = self.clock.now() + seconds
        while self.clock.now() < end:
            self.clock.advance(0.25)
            self.engine.tick()

    def wait_for(self, step: Step, limit: float = 600) -> None:
        """等到進入某步驟且已開放操作。"""
        end = self.clock.now() + limit
        while self.state.step is not step or (step in ACTION_STEPS and self._not_open()):
            if self.clock.now() > end:
                raise AssertionError(f"stuck at {self.state.step}, wanted {step}")
            self._pass_first_round(step)
            self.clock.advance(0.25)
            self.engine.tick()

    def _not_open(self) -> bool:
        opens = self.state.timers.opens_at
        return opens is not None and self.clock.now() < opens

    def ack_all(self) -> None:
        for player in list(self.state.actors):
            self.act(player, Action.DEAL_ACK)

    def to_wolf_step(self) -> None:
        self.ack_all()
        self.wait_for(Step.WOLF)

    def wolves_kill(self, target: str | None) -> None:
        for wolf in list(self.state.actors):
            self.act(wolf, Action.WOLF_PICK, target=target)
        self.run(balance.WOLF_CONFIRM_SECONDS + 0.5)

    def night(self, target: str | None, witch: dict[str, Any] | None = None) -> None:
        """從狼人步驟走到天亮公布之後。"""
        self.wolves_kill(target)
        self.wait_step_after_wolf(witch)

    def wait_step_after_wolf(self, witch: dict[str, Any] | None = None) -> None:
        if any(p.alive and p.role is Role.SEER for p in self.state.players):
            self.wait_for(Step.SEER)
            seer = self.state.actors[0]
            target = next(p.id for p in self.state.players if p.alive and p.id != seer)
            self.act(seer, Action.SEER_CHECK, target=target)
            self.act(seer, Action.SEER_OK)
        if any(p.alive and p.role is Role.WITCH for p in self.state.players):
            self.wait_for(Step.WITCH)
            self.act(self.state.actors[0], Action.WITCH_ACT, **(witch or {}))
        self.wait_until_announced()

    def wait_until_announced(self) -> None:
        for _ in range(4000):
            if self.state.step is Step.DAWN and self.state.announced:
                return
            self.clock.advance(0.25)
            self.engine.tick()
        raise AssertionError(f"never announced, at {self.state.step}")

    def _pass_first_round(self, wanted: Step) -> None:
        """要到第二輪的測試不關心第一輪：票分給 3 個人才會進第二輪，被提名者講完申述。"""
        state = self.state
        if wanted not in (Step.VOTE, Step.DEFENSE) or self._not_open():
            return
        if state.step is Step.SUSPECT_VOTE:
            alive = [p.id for p in state.players if p.alive]
            order = [*(p for p in self.nominate if p in alive), *alive]
            voted = {t for t in state.vote_round().ballots.values() if t}
            for voter in list(state.actors):
                if voter not in state.done:
                    # 還沒湊滿 3 個目標就投新的人，湊滿後集中投第一順位
                    fresh = [p for p in order if p != voter and p not in voted]
                    pool = fresh if len(voted) < balance.SECOND_ROUND_MIN_TARGETS else order
                    target = next(p for p in pool if p != voter)
                    voted.add(target)
                    self.act(voter, Action.VOTE_CAST, target=target)
        elif wanted is Step.VOTE and state.step is Step.DEFENSE and state.current_speaker:
            self.act(state.current_speaker, Action.SPEAK_END)

    def finish_speech(self) -> None:
        while self.state.step in (Step.DAY_SPEAK, Step.LAST_WORDS):
            if not self._not_open() and self.state.current_speaker:
                self.act(self.state.current_speaker, Action.SPEAK_END)
            self.clock.advance(0.25)
            self.engine.tick()

    def vote_all(self, target: str | None, skip: tuple[str, ...] = ()) -> None:
        """大家投同一個人：第一輪就直接決定（SPEC A5.4）。"""
        self.wait_for(Step.SUSPECT_VOTE)
        for voter in list(self.state.actors):
            if voter in skip:
                continue
            aimed = target if target != voter else None
            self.act(voter, Action.VOTE_CAST, target=aimed)


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch) -> Game:
    return Game(monkeypatch)


class TestDeal:
    def test_D4_6_deal_auto_after_60_seconds(self, game: Game) -> None:
        assert game.state.step is Step.DEAL
        game.run(balance.DEAL_SECONDS + 1)
        assert game.state.step is not Step.DEAL
        assert all(p.acked for p in game.state.players)

    def test_all_acked_moves_on(self, game: Game) -> None:
        game.ack_all()
        game.wait_for(Step.NIGHT_START)
        assert game.state.round_no == 1

    def test_faceless_first_period_at_deal(self, game: Game) -> None:
        disguise = game.state.disguise
        assert disguise is not None and disguise.target_id not in (None, "p4")
        assert disguise.periods[0].from_round == 1


class TestGuard:
    """守衛（SPEC v4.42）：最先睜眼、只能守別人、不能連兩晚守同一人、守住就是平安夜。"""

    ROLES: ClassVar[dict[str, Role]] = {**ROLES_8, "p8": Role.GUARD}

    def guard_step(self, game: Game) -> str:
        game.wait_for(Step.GUARD)
        return game.state.actors[0]

    def test_guarded_bite_is_a_peaceful_night(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch, roles=self.ROLES)
        game.ack_all()
        guard = self.guard_step(game)
        assert guard == "p8"
        said = [e.data["line_id"] for e in game.engine.log if e.type is EventType.NARRATE]
        assert said[-1] == "guard_open"  # 天黑之後先叫守衛，狼人還沒睜眼
        with pytest.raises(GameError) as err:
            game.act(guard, Action.GUARD_PICK, target=guard)  # 不能守自己
        assert err.value.code is ErrorCode.INVALID_TARGET
        game.act(guard, Action.GUARD_PICK, target="p1")
        with pytest.raises(GameError):
            game.act(guard, Action.GUARD_PICK, target="p2")  # 選了就不能改
        game.wait_for(Step.WOLF)
        game.night("p1")
        assert game.state.player("p1").alive
        lines = [e.data["line_id"] for e in game.engine.log if e.type is EventType.NARRATE]
        assert "peaceful" in lines and "deaths" not in lines  # 不說是誰守的

    def test_cannot_guard_same_person_two_nights(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch, roles=self.ROLES)
        game.ack_all()
        game.act(self.guard_step(game), Action.GUARD_PICK, target="p1")
        game.wait_for(Step.WOLF)
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all(None)
        guard = self.guard_step(game)
        with pytest.raises(GameError) as err:
            game.act(guard, Action.GUARD_PICK, target="p1")
        assert err.value.code is ErrorCode.INVALID_TARGET
        game.act(guard, Action.GUARD_PICK, target="p2")
        assert game.state.night().guard_target == "p2"

    def test_timeout_means_no_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch, roles=self.ROLES)
        game.ack_all()
        self.guard_step(game)
        game.wait_for(Step.WOLF)
        night = game.state.night()
        assert night.guard_acted and night.guard_target is None
        game.night("p1")
        assert not game.state.player("p1").alive

    def test_dead_guard_step_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch, roles=self.ROLES)
        game.ack_all()
        game.act(self.guard_step(game), Action.GUARD_PICK, target=None)
        game.wait_for(Step.WOLF)
        game.night("p8")
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all(None)
        game.wait_for(Step.WOLF)
        steps = [e.data["step"] for e in game.engine.log if e.type is EventType.STEP_ENTERED]
        second_night = steps[len(steps) - 1 - steps[::-1].index(Step.NIGHT_START.value) :]
        assert Step.GUARD.value not in second_night


class TestStepSeq:
    def test_L2_stale_step_rejected(self, game: Game) -> None:
        with pytest.raises(GameError) as err:
            game.engine.handle(Actor(player_id="p1"), Action.DEAL_ACK, {}, game.state.step_seq - 1)
        assert err.value.code is ErrorCode.STALE_STEP

    def test_L2_other_players_action_does_not_expire_mine(self, game: Game) -> None:
        seq = game.state.step_seq
        game.engine.handle(Actor(player_id="p1"), Action.DEAL_ACK, {}, seq)
        game.engine.handle(Actor(player_id="p2"), Action.DEAL_ACK, {}, seq)
        assert game.state.step_seq == seq

    def test_L2_chat_is_not_step_bound(self, game: Game) -> None:
        game.engine.handle(
            Actor(player_id="p1"),
            Action.CHAT_SEND,
            {"channel": Channel.PUBLIC, "content": "hi"},
            None,
        )

    def test_step_seq_monotonic_over_game(self, game: Game) -> None:
        seen = [game.state.step_seq]
        game.ack_all()
        for _ in range(200):
            game.clock.advance(0.25)
            game.engine.tick()
            seen.append(game.state.step_seq)
        assert seen == sorted(seen) and seen[-1] > seen[0]


class TestTransitions:
    def test_L6_illegal_transition_raises(self, game: Game) -> None:
        with pytest.raises(IllegalTransition):
            game.engine.go(Step.VOTE)

    def test_L6_table_covers_all_steps(self) -> None:
        assert set(TRANSITIONS) == set(Step)

    def test_night_sequence_from_registry(self) -> None:
        # 守衛最先（SPEC v4.42），再來狼人
        assert night_sequence()[:5] == [
            Step.NIGHT_START, Step.GUARD, Step.GUARD_END, Step.WOLF, Step.WOLF_END,
        ]  # fmt: skip
        assert night_sequence()[-1] is Step.DAWN

    def test_action_outside_step_forbidden(self, game: Game) -> None:
        with pytest.raises(GameError) as err:
            game.act("p5", Action.WOLF_PICK, target="p1")
        assert err.value.code is ErrorCode.FORBIDDEN

    def test_vote_not_open_during_narration(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        while game.state.step is not Step.SUSPECT_VOTE:
            game.clock.advance(0.25)
            game.engine.tick()
        with pytest.raises(GameError) as err:
            game.act("p1", Action.VOTE_CAST, target="p2")
        assert err.value.code is ErrorCode.STEP_NOT_OPEN

    def test_role_acts_during_narration_and_leaves_when_it_ends(self, game: Game) -> None:
        game.ack_all()
        while game.state.step is not Step.WOLF:
            game.clock.advance(0.25)
            game.engine.tick()
        opens_at = game.state.timers.opens_at
        assert opens_at is not None and game.clock.now() < opens_at
        for wolf in list(game.state.actors):
            game.act(wolf, Action.WOLF_PICK, target="p1")
        game.clock.advance(balance.WOLF_CONFIRM_SECONDS + 0.1)
        game.engine.tick()
        assert game.state.night().wolf_decided
        assert game.clock.now() < opens_at and game.state.step is Step.WOLF  # 還在念，不換步驟
        game.clock.advance(opens_at - game.clock.now() + 0.1)
        game.engine.tick()
        assert game.state.step is Step.WOLF_END

    def test_L4_grace_then_deadline_passed(self, game: Game) -> None:
        game.to_wolf_step()
        deadline = game.state.timers.deadline
        assert deadline is not None
        game.clock.advance(deadline - game.clock.now() + 0.2)
        game.act("p5", Action.WOLF_PICK, target="p1")  # 300 ms 寬限內有效
        game.clock.advance(0.2)
        with pytest.raises(GameError) as err:
            game.act("p4", Action.WOLF_PICK, target="p1")
        assert err.value.code is ErrorCode.DEADLINE_PASSED

    def test_narration_time_not_counted_in_countdown(self, game: Game) -> None:
        game.to_wolf_step()
        timing = game.state.timers
        assert timing.opens_at is not None and timing.deadline is not None
        assert timing.deadline - timing.opens_at == pytest.approx(balance.NIGHT_STEP_SECONDS)


class TestWolf:
    def test_D4_7_confirm_after_3_seconds(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        assert game.state.timers.confirm_until is None
        game.act("p5", Action.WOLF_PICK, target="p1")
        assert game.state.timers.confirm_until is not None
        game.run(2)
        assert not game.state.night().wolf_decided
        game.run(1.5)
        assert game.state.night().wolf_target == "p1"

    def test_D4_7_change_cancels_confirm(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        game.act("p5", Action.WOLF_PICK, target="p1")
        game.run(1)
        game.act("p5", Action.WOLF_PICK, target="p2")
        assert game.state.timers.confirm_until is None
        game.run(5)
        assert not game.state.night().wolf_decided

    def test_clear_pick(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        game.act("p4", Action.WOLF_PICK, clear=True)
        assert "p4" not in game.state.night().wolf_picks

    def test_wolf_can_bite_ally_and_self(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p5")  # 全部狼人一致咬同伴
        dead = game.state.player("p5")
        assert not dead.alive and dead.death_cause is DeathCause.WOLF

    def test_wolf_cannot_pick_dead_or_stranger(self, game: Game) -> None:
        game.to_wolf_step()
        with pytest.raises(GameError) as err:
            game.act("p4", Action.WOLF_PICK, target="nope")
        assert err.value.code is ErrorCode.INVALID_TARGET

    def test_last_wolf_biting_self_means_village_wins(self, game: Game) -> None:
        game.remove("p5")
        game.to_wolf_step()
        game.night("p4")
        game.run(30)
        assert game.state.winner is Winner.VILLAGE

    def test_L13_nobody_picked_is_empty_knife(self, game: Game) -> None:
        game.to_wolf_step()
        game.run(balance.NIGHT_STEP_SECONDS + 1)
        night = game.state.night()
        assert night.wolf_decided and night.wolf_target is None

    def test_cannot_change_after_decided(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        assert game.state.step in (Step.WOLF, Step.WOLF_END)
        if game.state.step is Step.WOLF:
            with pytest.raises(GameError):
                game.act("p4", Action.WOLF_PICK, target="p2")

    def test_D4_8_timeout_disagree_picks_from_top(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        game.act("p5", Action.WOLF_PICK, target=None)
        game.run(balance.NIGHT_STEP_SECONDS + 1)
        assert game.state.night().wolf_target in ("p1", None)
        assert game.state.night().wolf_decided

    def test_L20_removed_wolf_rechecks_consensus(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        game.remove("p5")
        assert game.state.timers.confirm_until is not None

    def test_L20_removed_target_clears_pick(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        game.remove("p1")
        assert "p4" not in game.state.night().wolf_picks


class TestNightResolution:
    def test_D4_10_killed_seer_acts_tonight(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p2")
        game.wait_for(Step.SEER)
        assert game.state.player("p2").alive
        game.act("p2", Action.SEER_CHECK, target="p4")
        assert game.state.night().seer_is_wolf is True  # D4 #11 千面狼也顯示狼人

    def test_D4_12_dead_seer_skipped(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p2")
        assert not game.state.player("p2").alive
        game.finish_speech_or_to_vote()

    def test_D4_13_first_night_self_save(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p3", witch={"save": True})
        assert game.state.player("p3").alive and game.state.witch_antidote_used

    def test_peaceful_night(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        assert all(p.alive for p in game.state.players)

    def test_D4_16_witch_without_potions_step_still_runs(self, game: Game) -> None:
        game.state.witch_antidote_used = True
        game.state.witch_poison_used = True
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        timing = game.state.timers
        assert timing.deadline == timing.min_until
        assert timing.opens_at is not None and timing.min_until is not None
        wait = timing.min_until - timing.opens_at
        assert balance.WITCH_MIN_SECONDS_LOW <= wait <= balance.WITCH_MIN_SECONDS_HIGH
        game.wait_for(Step.WITCH_END)

    def test_witch_min_time_applies_when_quick(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        game.act("p3", Action.WITCH_ACT)
        game.run(3)
        assert game.state.step is Step.WITCH

    def test_D4_17_no_double_use(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        with pytest.raises(GameError):
            game.act("p3", Action.WITCH_ACT, save=True, poison="p7")

    def test_witch_cannot_act_twice(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        game.act("p3", Action.WITCH_ACT)
        with pytest.raises(GameError):
            game.act("p3", Action.WITCH_ACT)

    def test_seer_cannot_check_twice_or_ok_first(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.SEER)
        with pytest.raises(GameError):
            game.act("p2", Action.SEER_OK)
        with pytest.raises(GameError):
            game.act("p2", Action.SEER_CHECK, target="p2")
        game.act("p2", Action.SEER_CHECK, target="p1")
        with pytest.raises(GameError):
            game.act("p2", Action.SEER_CHECK, target="p7")

    def test_L19_D4_18_knifed_and_poisoned_hunter_cannot_shoot(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p6", witch={"poison": "p6"})
        hunter = game.state.player("p6")
        assert hunter.death_cause is DeathCause.POISON and game.state.hunter_pending is None

    def test_witch_timeout_no_potion_used(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        game.run(balance.NIGHT_STEP_SECONDS + 1)
        assert game.state.night().witch_acted and not game.state.witch_antidote_used


class TestDayFlow:
    def test_D4_19_hunter_shoots_before_win_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 2 狼 3 好人（含獵人）；獵人被刀後 2 狼對 2 好人已壓制，但要先開槍
        game = Game(monkeypatch, {
            "p1": Role.HUNTER, "p2": Role.WITCH, "p3": Role.SEER,
            "p4": Role.FACELESS, "p5": Role.WOLF, "p6": Role.VILLAGER, "p7": Role.VILLAGER,
        })  # fmt: skip
        game.state.player("p7").alive = False
        game.state.player("p7").death_cause = DeathCause.VOTE
        game.state.player("p6").alive = False
        game.state.player("p6").death_cause = DeathCause.VOTE
        game.to_wolf_step()
        game.night("p1")
        assert game.state.hunter_pending == "p1"
        game.wait_for(Step.HUNTER)
        game.act("p1", Action.HUNTER_SHOOT, target="p5")
        assert not game.state.player("p5").alive

    def test_wolves_dead_at_dawn_skips_hunter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch)
        game.state.player("p5").alive = False
        game.state.player("p5").death_cause = DeathCause.VOTE
        game.to_wolf_step()
        game.night("p6", witch={"poison": "p4"})
        game.run(30)
        assert game.state.step is Step.END and game.state.winner is Winner.VILLAGE

    def test_D4_21_speak_order_after_hunter_shot(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p6")
        game.wait_for(Step.HUNTER)
        game.act("p6", Action.HUNTER_SHOOT, target="p1")
        game.wait_for(Step.LAST_WORDS)
        assert game.state.current_speaker == "p1"  # 第 1 天，遺言依座位
        game.finish_speech_to(Step.DAY_SPEAK)
        # 順序在開槍後才計算（D4 #21）：被帶走的 p1、p6 都不會在發言名單裡
        speakers = [game.state.current_speaker, *game.state.speak_queue]
        assert "p1" not in speakers and "p6" not in speakers and len(speakers) == 6

    def test_L16_hunter_no_targets_auto_holster(self, game: Game) -> None:
        for pid in ("p1", "p2", "p3", "p4", "p5", "p7", "p8"):
            game.state.player(pid).alive = False
        game.state.player("p6").alive = False
        game.state.hunter_pending = "p6"
        game.engine.strict = False
        game.engine._enter(Step.HUNTER)
        assert game.state.hunter_shot_done and game.state.hunter_pending is None

    def test_D4_20_hunter_may_holster_and_timeout(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p6")
        game.wait_for(Step.HUNTER)
        game.run(balance.HUNTER_SECONDS + 1)
        assert game.state.hunter_pending is None
        assert sum(not p.alive for p in game.state.players) == 1

    def test_hunter_invalid_target(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p6")
        game.wait_for(Step.HUNTER)
        with pytest.raises(GameError):
            game.act("p6", Action.HUNTER_SHOOT, target="p6")

    def test_first_day_last_words_later_days_none(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        game.wait_for(Step.LAST_WORDS)
        assert game.state.current_speaker == "p1"
        game.finish_speech_to(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all(None)
        game.wait_for(Step.WOLF)
        game.night("p7")
        game.run(10)
        assert game.state.step is Step.DAY_SPEAK

    def test_exile_wolf_announced_loud_and_immediately(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all("p5")
        game.run(6)
        assert game.state.step in (Step.REVEAL, Step.LAST_WORDS)
        said = [e.data["text"] for e in game.engine.log if e.type is EventType.NARRATE]
        assert any(t.startswith("成功將狼人放逐") for t in said)

    def test_exile_good_guy_line(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all("p1")
        game.run(6)
        said = [e.data["text"] for e in game.engine.log if e.type is EventType.NARRATE]
        assert any("被自己人放逐" in t for t in said)

    def test_dawn_announces_bite_poison_and_save(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1", witch={"poison": "p7"})
        said = [e.data for e in game.engine.log if e.type is EventType.NARRATE]
        report = next(d for d in said if d["line_id"] == "deaths")
        assert "P1 被狼咬死了" in report["text"] and "女巫毒死了 P7" in report["text"]
        assert report["speak"] is True

    def test_narration_reads_spoken_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """旁白念語音名字，不念帶符號的顯示名字（SPEC v4.40）；沒填的人照念顯示名字。"""
        game = Game(monkeypatch, spoken={"p1": "風花雪月", "p7": "小雨"})
        game.to_wolf_step()
        game.night("p1", witch={"poison": "p7"})
        said = [e.data for e in game.engine.log if e.type is EventType.NARRATE]
        report = next(d for d in said if d["line_id"] == "deaths")["text"]
        assert "風花雪月 被狼咬死了" in report and "女巫毒死了 小雨" in report
        assert game.state.player("p1").name == "P1"  # 畫面上的名字不變
        assert game.state.player("p2").voice() == "P2"

    def test_wolf_bitten_by_wolf_identity_stays_hidden(self, game: Game) -> None:
        # 狼咬狼是戰術：只念名字，不能透露他是狼（使用者試玩回饋）
        game.to_wolf_step()
        game.night("p5")
        said = [e.data for e in game.engine.log if e.type is EventType.NARRATE]
        report = next(d for d in said if d["line_id"] == "deaths")["text"]
        assert "P5 被狼咬死了" in report and "身分" not in report and "狼人" not in report

    def test_saved_night_is_just_peaceful(self, game: Game) -> None:
        """被女巫救只念平安夜，不說咬了誰、也不說被救（SPEC v4.43）。"""
        game.to_wolf_step()
        game.night("p1", witch={"save": True})
        said = [e.data for e in game.engine.log if e.type is EventType.NARRATE]
        assert said[-1]["line_id"] == "peaceful"
        assert not any("救" in d["text"] or "P1" in d["text"] for d in said)

    def test_exiled_gets_last_words(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all("p1")
        game.wait_for(Step.LAST_WORDS)
        assert game.state.current_speaker == "p1"

    def test_no_last_words_when_game_decided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch)
        game.state.player("p4").alive = False
        game.state.player("p4").death_cause = DeathCause.VOTE
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all("p5")
        game.run(30)
        assert game.state.step is Step.END and game.state.winner is Winner.VILLAGE

    def test_speak_timeout_moves_to_next(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        first = game.state.current_speaker
        game.run(balance.SPEAK_SECONDS_BY_PLAYERS[0][1] + 8)
        assert game.state.current_speaker != first

    def test_speak_start_changes_each_day(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        first = game.state.current_speaker
        assert game.state.last_speak_start == first
        game.finish_speech()
        game.vote_all(None)
        game.wait_for(Step.WOLF)
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        assert game.state.current_speaker != first
        # 同一天換下一位時不更新，才不會影響隔天的判斷
        assert game.state.last_speak_start == game.state.current_speaker

    def test_only_current_speaker_can_end(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        with pytest.raises(GameError):
            game.act("p8", Action.SPEAK_END)


class TestVote:
    def _at_vote(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.wait_for(Step.SUSPECT_VOTE)  # 投票規則兩輪相同，用第一輪測

    def _cast_all(self, game: Game, target: str) -> None:
        for voter in list(game.state.actors):
            game.act(voter, Action.VOTE_CAST, target=None if voter == target else target)

    def test_change_once_only(self, game: Game) -> None:
        self._at_vote(game)
        game.act("p1", Action.VOTE_CAST, target="p2")
        game.act("p1", Action.VOTE_CAST, target="p3")
        assert game.state.vote_round().ballots["p1"] == "p3"
        with pytest.raises(GameError):
            game.act("p1", Action.VOTE_CAST, target="p4")

    def test_cannot_vote_self(self, game: Game) -> None:
        self._at_vote(game)
        with pytest.raises(GameError):
            game.act("p1", Action.VOTE_CAST, target="p1")

    def test_all_cast_waits_5_seconds_and_allows_change(self, game: Game) -> None:
        self._at_vote(game)
        self._cast_all(game, "p1")
        assert game.state.timers.grace_until is not None
        game.run(balance.VOTE_ALL_CAST_GRACE_SECONDS - 1)
        assert game.state.step is Step.SUSPECT_VOTE
        game.act("p2", Action.VOTE_CAST, target="p3")
        game.run(2)
        assert game.state.step is Step.REVEAL  # 只有兩個人被投，直接決定
        assert game.state.vote_round().suspect_counts["p3"] == 1

    def test_grace_never_exceeds_deadline(self, game: Game) -> None:
        self._at_vote(game)
        deadline = game.state.timers.deadline
        assert deadline is not None
        game.clock.advance(deadline - game.clock.now() - 1)
        self._cast_all(game, "p1")
        assert game.state.timers.grace_until == deadline

    def test_timeout_is_abstain(self, game: Game) -> None:
        self._at_vote(game)
        game.act("p1", Action.VOTE_CAST, target="p2")
        game.run(balance.VOTE_SECONDS + 1)
        votes = game.state.vote_round()
        assert votes.suspect_counts == {"p2": 1} and votes.direct
        game.wait_for(Step.REVEAL)
        assert game.state.vote_round().exiled == "p2"

    def test_D4_23_tie_no_exile(self, game: Game) -> None:
        self._at_vote(game)
        game.act("p1", Action.VOTE_CAST, target="p2")
        game.act("p2", Action.VOTE_CAST, target="p1")
        game.run(balance.VOTE_SECONDS + 1)
        game.wait_for(Step.VOTE)  # 第一輪兩人同票進第二輪；第二輪同票才無人出局
        game.act("p3", Action.VOTE_CAST, target="p1")
        game.act("p4", Action.VOTE_CAST, target="p2")
        game.run(balance.VOTE_SECONDS + 1)
        assert game.state.vote_round().exiled is None
        assert all(p.alive for p in game.state.players)

    def test_D4_24_removed_voids_votes(self, game: Game) -> None:
        self._at_vote(game)
        game.act("p1", Action.VOTE_CAST, target="p2")
        game.act("p2", Action.VOTE_CAST, target="p1")
        game.remove("p2")
        ballots = game.state.vote_round().ballots
        assert "p2" not in ballots and ballots["p1"] is None

    def test_removed_last_missing_voter_starts_grace(self, game: Game) -> None:
        self._at_vote(game)
        game.vote_all("p2", skip=("p8",))
        game.remove("p8")
        assert game.state.timers.grace_until is not None


class TestKickAndWin:
    def test_D4_45_removed_reveals_and_checks_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch)
        game.remove("p4")
        game.remove("p5")
        assert game.state.step is Step.END and game.state.winner is Winner.VILLAGE

    def test_removed_hunter_cannot_shoot(self, game: Game) -> None:
        game.to_wolf_step()
        game.remove("p6")
        assert game.state.hunter_pending is None

    def test_removed_speaker_moves_on(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        speaker = game.state.current_speaker
        assert speaker is not None
        game.remove(speaker)
        game.run(1)
        assert game.state.current_speaker != speaker

    def test_removed_disguise_target_redraws(self, game: Game) -> None:
        disguise = game.state.disguise
        assert disguise is not None
        target = disguise.target_id
        assert target is not None
        game.remove(target)
        assert game.state.disguise is not None
        assert game.state.disguise.target_id != target
        assert game.state.disguise.periods[0].to_round is not None

    @pytest.mark.parametrize("step", [Step.WOLF, Step.SEER, Step.WITCH])
    def test_L20_removed_actor_mid_step_still_closes(self, game: Game, step: Step) -> None:
        # 壓力測試抓到的 bug：行動者被判死後不能跳過閉眼
        game.ack_all()
        if step is not Step.WOLF:
            game.wait_for(Step.WOLF)
            game.wolves_kill("p1")
        game.wait_for(step)
        if step is Step.WOLF:
            game.remove("p5")
            game.act("p4", Action.WOLF_PICK, target="p1")
        else:
            game.remove(game.state.actors[0])
        closing = {Step.WOLF: Step.WOLF_END, Step.SEER: Step.SEER_END, Step.WITCH: Step.WITCH_END}
        game.wait_for(closing[step], limit=120)

    def test_removed_during_deal_then_acks(self, game: Game) -> None:
        game.remove("p8")
        assert "p8" not in game.state.actors
        game.ack_all()
        game.wait_for(Step.NIGHT_START)

    def test_admin_end(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_END)
        assert game.state.winner is Winner.NONE
        with pytest.raises(GameError):
            game.act(ADMIN, Action.ADMIN_END)

    def test_tick_after_end_is_noop(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_END)
        assert game.engine.tick() == []


class TestPause:
    def test_auto_admin_cannot_pause_at_night(self, game: Game) -> None:
        game.to_wolf_step()
        with pytest.raises(GameError):
            game.act(ADMIN, Action.ADMIN_PAUSE)

    def test_auto_admin_pause_by_day_freezes_and_resumes(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.act(ADMIN, Action.ADMIN_PAUSE)
        assert game.state.pause is not None
        step = game.state.step
        game.run(300)
        assert game.state.step is step
        game.act(ADMIN, Action.ADMIN_RESUME)
        assert game.state.pause is not None
        game.run(balance.RESUME_COUNTDOWN_SECONDS + 1)
        assert game.state.pause is None

    def test_countdown_remaining_survives_pause(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        deadline = game.state.timers.deadline
        assert deadline is not None
        left = deadline - game.clock.now()
        game.act(ADMIN, Action.ADMIN_PAUSE)
        game.clock.advance(1000)
        game.act(ADMIN, Action.ADMIN_RESUME)
        game.clock.advance(balance.RESUME_COUNTDOWN_SECONDS)
        game.engine.tick()
        new_deadline = game.state.timers.deadline
        assert new_deadline is not None
        assert new_deadline - game.clock.now() == pytest.approx(left)

    def test_actions_rejected_while_paused(self, game: Game) -> None:
        game.engine.system_pause(PauseReason.PRESENCE)
        with pytest.raises(GameError):
            game.act("p1", Action.DEAL_ACK)

    def test_system_pause_resume_allowed_at_night(self, game: Game) -> None:
        game.to_wolf_step()
        game.engine.system_pause(PauseReason.SYSTEM)
        game.act(ADMIN, Action.ADMIN_RESUME)
        game.run(balance.RESUME_COUNTDOWN_SECONDS + 1)
        assert game.state.pause is None

    def test_double_pause_and_bad_resume(self, game: Game) -> None:
        with pytest.raises(GameError):
            game.act(ADMIN, Action.ADMIN_RESUME)
        game.engine.system_pause(PauseReason.SYSTEM)
        assert game.engine.system_pause(PauseReason.ADMIN) == []
        with pytest.raises(GameError):
            game.act(ADMIN, Action.ADMIN_PAUSE)

    def test_removed_speaker_while_paused_then_resume(self, game: Game) -> None:
        # 機器人抽樣抓到：重念「請 ○○ 發言」時那個人已被判死，tick 會一直當掉
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        speaker = game.state.current_speaker
        assert speaker is not None
        game.act(ADMIN, Action.ADMIN_PAUSE)
        game.remove(speaker)
        game.act(ADMIN, Action.ADMIN_RESUME)
        game.run(balance.RESUME_COUNTDOWN_SECONDS + 1)
        assert game.state.pause is None
        assert game.state.current_speaker not in (None, speaker)

    @pytest.mark.parametrize("mode", [Mode.AUTO, Mode.GOD])
    @pytest.mark.parametrize("step", [Step.DAY_SPEAK, Step.VOTE])
    def test_resume_says_the_current_step_in_both_modes(
        self, monkeypatch: pytest.MonkeyPatch, mode: Mode, step: Step
    ) -> None:
        game = Game(monkeypatch, mode=mode)
        game.engine.state.step = step
        game.engine.state.line_id = {Step.DAY_SPEAK: "speak", Step.VOTE: "vote"}[step]
        game.engine.state.current_speaker = "p1" if step is Step.DAY_SPEAK else None
        game.act(ADMIN, Action.ADMIN_PAUSE)
        game.act(ADMIN, Action.ADMIN_RESUME)
        game.clock.advance(balance.RESUME_COUNTDOWN_SECONDS + 0.1)
        events = game.engine.tick()
        narrated = [e for e in events if e.type is EventType.NARRATE]
        assert [e.data["line_id"] for e in narrated] == [game.state.line_id]

    def test_auto_resume_renarrates(self, game: Game) -> None:
        game.to_wolf_step()
        game.engine.system_pause(PauseReason.PRESENCE)
        game.engine.schedule_resume()
        game.clock.advance(balance.RESUME_COUNTDOWN_SECONDS + 1)
        events = game.engine.tick()
        assert any(e.type is EventType.NARRATE for e in events)


class TestTwoRoundVote:
    """SPEC A5.4 v4.18：第一輪投嫌疑人、申述、第二輪放逐。"""

    def _at_suspects(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.wait_for(Step.SUSPECT_VOTE)

    def _cast(self, game: Game, target: dict[str, str | None]) -> None:
        for voter in list(game.state.actors):
            game.act(voter, Action.VOTE_CAST, target=target.get(voter))

    def test_flow_and_first_round_ballots_are_not_kept(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p1": "p2", "p3": "p2", "p4": "p2", "p5": "p1", "p6": "p1", "p2": "p3"})
        game.wait_for(Step.DEFENSE)
        votes = game.state.vote_round()
        assert set(votes.nominees or []) == {"p1", "p2"}
        assert votes.suspect_counts == {"p2": 3, "p1": 2}
        assert votes.ballots == {}  # 誰投誰不留
        assert game.state.current_speaker == "p1"  # 依座位
        game.act("p1", Action.SPEAK_END)
        game.run(1)
        game.wait_for(Step.DEFENSE)
        assert game.state.current_speaker == "p2"
        game.act("p2", Action.SPEAK_END)
        game.wait_for(Step.VOTE)
        assert "p1" not in game.state.actors and "p2" not in game.state.actors
        with pytest.raises(GameError):
            game.act("p1", Action.VOTE_CAST, target="p2")  # 被提名者不能投
        with pytest.raises(GameError):
            game.act("p3", Action.VOTE_CAST, target="p4")  # 只能投被提名者
        for voter in list(game.state.actors):
            game.act(voter, Action.VOTE_CAST, target="p2")
        game.wait_for(Step.REVEAL)
        assert game.state.vote_round().exiled == "p2"

    def test_all_abstain_in_first_round_means_no_exile(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {})
        game.wait_for(Step.REVEAL)
        votes = game.state.vote_round()
        assert votes.nominees == [] and votes.exiled is None and votes.ballots == {}
        assert game.state.line_id == "no_nominee"

    def test_one_target_is_exiled_directly(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {p: "p1" for p in game.state.actors if p != "p1"})
        game.wait_for(Step.REVEAL)
        votes = game.state.vote_round()
        assert votes.exiled == "p1" and votes.direct and votes.ballots == {}
        assert votes.suspect_counts == {"p1": len(game.state.players) - 1}

    def test_two_targets_exile_the_higher_directly(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p3": "p1", "p4": "p1", "p5": "p2"})
        game.wait_for(Step.REVEAL)
        votes = game.state.vote_round()
        assert votes.exiled == "p1" and votes.suspect_counts == {"p1": 2, "p2": 1}
        assert votes.ballots == {}  # 誰投誰不留
        assert game.state.step is Step.REVEAL

    def test_two_targets_tied_go_to_second_round(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p3": "p1", "p4": "p2"})
        game.wait_for(Step.DEFENSE)
        votes = game.state.vote_round()
        assert not votes.direct and set(votes.nominees or []) == {"p1", "p2"}
        assert votes.suspect_counts == {"p1": 1, "p2": 1}

    def test_three_targets_go_to_second_round(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p3": "p1", "p4": "p2", "p5": "p6"})
        game.wait_for(Step.DEFENSE)
        votes = game.state.vote_round()
        assert not votes.direct and set(votes.nominees or []) == {"p1", "p2", "p6"}

    def test_second_round_tie_means_no_exile(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p3": "p1", "p4": "p2", "p5": "p6"})
        game.wait_for(Step.VOTE)
        nominees = game.state.vote_round().nominees or []
        voters = [voter for voter in game.state.actors if voter not in nominees]
        half = len(voters) // 2
        for i, voter in enumerate(voters[: half * 2]):  # 單數時多的一人不投
            game.act(voter, Action.VOTE_CAST, target="p1" if i < half else "p2")
        game.run(balance.VOTE_SECONDS + 1)
        game.wait_for(Step.REVEAL)
        assert game.state.vote_round().exiled is None and game.state.line_id == "tie"

    def _finish_defense(self, game: Game) -> None:
        game.wait_for(Step.DEFENSE)
        for _ in range(len(game.state.players)):
            if game.state.step is Step.DEFENSE:
                game.wait_for(Step.DEFENSE)
                game.act(str(game.state.current_speaker), Action.SPEAK_END)
                game.run(1)
        game.wait_for(Step.VOTE)

    def test_three_nominees_vote_each_other_but_not_themselves(self, game: Game) -> None:
        self._at_suspects(game)
        alive = list(game.state.actors)
        self._cast(game, {"p3": "p1", "p4": "p2", "p5": "p6"})
        self._finish_defense(game)
        assert set(game.state.vote_round().nominees or []) == {"p1", "p2", "p6"}
        assert set(game.state.actors) == set(alive)
        with pytest.raises(GameError):
            game.act("p1", Action.VOTE_CAST, target="p1")
        game.act("p1", Action.VOTE_CAST, target="p2")
        assert game.state.vote_round().ballots["p1"] == "p2"

    def test_two_nominees_do_not_vote(self, game: Game) -> None:
        self._at_suspects(game)
        self._cast(game, {"p3": "p1", "p4": "p2"})
        self._finish_defense(game)
        assert not {"p1", "p2"} & set(game.state.actors)

    def test_everyone_nominated_can_still_vote(self, game: Game) -> None:
        self._at_suspects(game)
        alive = list(game.state.actors)
        self._cast(game, {voter: alive[(i + 1) % len(alive)] for i, voter in enumerate(alive)})
        self._finish_defense(game)
        assert set(game.state.actors) == set(alive)


class TestChat:
    def _chat(self, game: Game, who: str | Actor, **kwargs: Any) -> list[Event]:
        payload = {"channel": Channel.PUBLIC, "kind": "text", "content": "x", **kwargs}
        return game.act(who, Action.CHAT_SEND, **payload)

    def test_night_public_read_only_host_excepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        game = Game(monkeypatch, mode=Mode.GOD)
        game.state.step = Step.WOLF
        with pytest.raises(GameError):
            self._chat(game, "p1")
        self._chat(game, HOST)

    def test_night_wolf_channel_works(self, game: Game) -> None:
        game.to_wolf_step()
        self._chat(game, "p4", channel=Channel.WOLF)
        with pytest.raises(GameError):
            self._chat(game, "p1", channel=Channel.WOLF)

    def test_night_pause_still_read_only(self, game: Game) -> None:
        game.to_wolf_step()
        game.engine.system_pause(PauseReason.PRESENCE)
        with pytest.raises(GameError):
            self._chat(game, "p1")
        with pytest.raises(GameError):
            self._chat(game, "p4", **{"as": "disguise"})

    def test_day_pause_allows_chat_and_disguise(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.engine.system_pause(PauseReason.PRESENCE)
        self._chat(game, "p1")
        self._chat(game, "p4", **{"as": "disguise"})

    def test_disguise_rules(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        with pytest.raises(GameError):
            self._chat(game, "p5", **{"as": "disguise"})
        with pytest.raises(GameError):
            self._chat(game, "p4", channel=Channel.WOLF, **{"as": "disguise"})
        events = self._chat(game, "p4", **{"as": "disguise"})
        assert game.state.disguise is not None
        assert events[0].data["display"] == game.state.disguise.target_id

    def test_dead_read_only_except_one_last_word(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        game.wait_for(Step.LAST_WORDS)
        self._chat(game, "p1")
        with pytest.raises(GameError):
            self._chat(game, "p1")
        game.finish_speech_to(Step.DAY_SPEAK)
        with pytest.raises(GameError):
            self._chat(game, "p1")

    def test_last_word_text_only(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        game.wait_for(Step.LAST_WORDS)
        with pytest.raises(GameError):
            self._chat(game, "p1", kind="photo")

    def test_dead_wolf_channel_read_only(self, game: Game) -> None:
        game.to_wolf_step()
        game.remove("p5")
        with pytest.raises(GameError):
            self._chat(game, "p5", channel=Channel.WOLF)

    def test_spectator_read_only_until_end(self, game: Game) -> None:
        with pytest.raises(GameError):
            self._chat(game, "late")
        game.act(ADMIN, Action.ADMIN_END)
        self._chat(game, "late")

    def test_host_can_post_to_wolf_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # SPEC v4.25：上帝主持人可以在狼頻道偷偷提示狼人
        game = Game(monkeypatch, mode=Mode.GOD)
        events = self._chat(game, HOST, channel=Channel.WOLF)
        assert events[0].data["is_host"] and events[0].data["channel"] == "wolf"

    def test_intro_messages(self, game: Game) -> None:
        # SPEC v4.25：開局系統訊息，狼頻道一則、公共頻道一則；這局有千面狼才提假扮
        events = game.engine.post_intro()
        assert [(e.data["channel"], e.data["kind"]) for e in events] == [
            ("wolf", "system"),
            ("public", "system"),
        ]
        has_faceless = any(p.role is Role.FACELESS for p in game.state.players)
        assert events[0].data["content"] == ("intro.wolfFaceless" if has_faceless else "intro.wolf")
        assert events[1].data["content"] == "intro.public"
        assert all(e.data["real_author"] is None for e in events)

    def test_players_cannot_send_system_messages(self) -> None:
        from server import protocol

        frame = {"t": "chat.send", "msg_id": "m1", "channel": "public", "kind": "system"}
        with pytest.raises(GameError):
            protocol.parse_client({**frame, "media_id": "x"})
        with pytest.raises(GameError):
            protocol.parse_client({**frame, "content": "intro.public"})


class TestWolfMask:
    def _mask(self, game: Game, who: str | Actor, **kwargs: Any) -> list[Event]:
        payload = {"channel": Channel.PUBLIC, "kind": "text", "content": "嗷", "as": "wolf"}
        return game.act(who, Action.CHAT_SEND, **{**payload, **kwargs})

    def test_wolf_and_faceless_can_mask_by_day(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        for wolf in ("p5", "p4"):
            events = self._mask(game, wolf)
            assert events[0].data["display"] is None
            assert events[0].data["is_wolf_mask"] is True
            assert events[0].data["real_author"] == wolf

    def test_day_pause_allowed_night_pause_not(self, game: Game) -> None:
        game.to_wolf_step()
        game.engine.system_pause(PauseReason.PRESENCE)
        with pytest.raises(GameError):
            self._mask(game, "p5")
        game.engine.schedule_resume()
        game.run(balance.RESUME_COUNTDOWN_SECONDS + 1)
        game.night(None)
        game.engine.system_pause(PauseReason.PRESENCE)
        self._mask(game, "p5")

    def test_good_dead_spectator_and_wolf_channel_rejected(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        with pytest.raises(GameError):
            self._mask(game, "p1")  # 好人
        with pytest.raises(GameError):
            self._mask(game, "late")  # 旁觀者
        with pytest.raises(GameError):
            self._mask(game, "p5", channel=Channel.WOLF)  # 狼人頻道一律本名
        game.remove("p5")
        with pytest.raises(GameError):
            self._mask(game, "p5")  # 已死

    def test_end_rejects_mask(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_END)
        with pytest.raises(GameError):
            self._mask(game, "p5")

    def test_host_cannot_mask(self, monkeypatch: pytest.MonkeyPatch) -> None:
        god = Game(monkeypatch, mode=Mode.GOD)
        god.state.step = Step.DAY_SPEAK
        with pytest.raises(GameError):
            self._mask(god, HOST)


class TestNarrator:
    def test_takeover(self, game: Game) -> None:
        game.act("p3", Action.NARRATOR_TAKEOVER)
        assert game.state.narrator_id == "p3"
        with pytest.raises(GameError):
            game.act(ADMIN, Action.NARRATOR_TAKEOVER)

    def test_admin_sets(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_NARRATOR, player="p2")
        assert game.state.narrator_id == "p2"
        with pytest.raises(GameError):
            game.act(ADMIN, Action.ADMIN_NARRATOR, player="nope")
        with pytest.raises(GameError):
            game.act("p2", Action.ADMIN_NARRATOR, player="p1")


class TestGodMode:
    @pytest.fixture
    def god(self, monkeypatch: pytest.MonkeyPatch) -> Game:
        return Game(monkeypatch, mode=Mode.GOD)

    def test_waits_for_host_after_deal(self, god: Game) -> None:
        god.ack_all()
        god.run(100)
        assert god.state.step is Step.DEAL
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        assert god.state.step is Step.NIGHT_START

    def test_wrong_line_rejected(self, god: Game) -> None:
        for line in ("wolf_open", "nope"):
            with pytest.raises(GameError):
                god.act(HOST, Action.HOST_LINE, line_id=line)

    def test_speak_false_opens_step_immediately(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start", speak=False)
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open", speak=False)
        timing = god.state.timers
        assert timing.opens_at is not None
        assert timing.opens_at - god.clock.now() == pytest.approx(balance.SFX_SECONDS["wolf_open"])

    def test_timeout_applies_default_but_waits(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_NEXT)
        god.act(HOST, Action.HOST_NEXT)
        god.run(100)
        assert god.state.step is Step.WOLF and god.state.timed_out

    def test_next_with_unfinished_applies_default(self, god: Game) -> None:
        god.act(HOST, Action.HOST_NEXT)
        assert god.state.step is Step.NIGHT_START
        assert all(p.acked for p in god.state.players)

    def test_only_host_can_use(self, god: Game) -> None:
        with pytest.raises(GameError):
            god.act("p1", Action.HOST_NEXT)
        with pytest.raises(GameError):
            god.act(ADMIN, Action.HOST_NEXT)

    def test_auto_mode_rejects_host_commands(self, game: Game) -> None:
        with pytest.raises(GameError):
            game.act(HOST, Action.HOST_NEXT)

    def _to_dawn(self, god: Game, target: str | None = "p1") -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_NEXT)  # NIGHT_START
        god.act(HOST, Action.HOST_NEXT)  # WOLF
        god.run(15)  # 語速變慢，要等旁白念完才開放
        for wolf in list(god.state.actors):
            god.act(wolf, Action.WOLF_PICK, target=target)
        god.run(4)
        for _ in range(6):  # WOLF_END SEER SEER_END WITCH WITCH_END DAWN
            god.act(HOST, Action.HOST_NEXT)

    def test_rollback_restores_death_and_potions(self, god: Game) -> None:
        self._to_dawn(god)
        god.run(25)  # 天亮念完、宣布念完才往下
        assert not god.state.player("p1").alive
        before = god.state.step_seq
        god.act(HOST, Action.HOST_ROLLBACK)
        assert god.state.step_seq == before + 1
        assert god.state.step is Step.DAWN
        assert god.state.player("p1").alive and not god.state.announced

    def test_L23_rollback_across_death_restores(self, god: Game) -> None:
        self._to_dawn(god)
        god.run(25)  # 天亮念完、宣布念完才往下
        god.act(HOST, Action.HOST_NEXT)
        god.act(HOST, Action.HOST_ROLLBACK)
        assert god.state.step is Step.LAST_WORDS and not god.state.player("p1").alive
        god.act(HOST, Action.HOST_ROLLBACK)
        assert god.state.step is Step.DAWN and god.state.player("p1").alive

    def test_rollback_at_start_forbidden(self, god: Game) -> None:
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_ROLLBACK)

    def test_set_alive(self, god: Game) -> None:
        god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=False)
        assert god.state.player("p1").death_cause is DeathCause.MANUAL
        god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=True)
        assert god.state.player("p1").alive
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=True)

    def test_set_alive_can_end_game(self, god: Game) -> None:
        god.act(HOST, Action.HOST_SET_ALIVE, player="p4", alive=False)
        god.act(HOST, Action.HOST_SET_ALIVE, player="p5", alive=False)
        assert god.state.step is Step.END

    def test_reshow_card(self, god: Game) -> None:
        events = god.act(HOST, Action.HOST_RESHOW_CARD, player="p1")
        assert events[0].type is EventType.CARD_RESHOWN
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_RESHOW_CARD, player="nope")

    def test_skip_and_extend_speaker(self, god: Game) -> None:
        self._to_dawn(god, target=None)
        god.run(25)
        god.wait_for(Step.DAY_SPEAK)
        deadline = god.state.timers.deadline
        assert deadline is not None
        god.act(HOST, Action.HOST_EXTEND, s=30)
        assert god.state.timers.deadline == deadline + 30
        first = god.state.current_speaker
        god.act(HOST, Action.HOST_SKIP_SPEAKER)
        god.run(1)
        assert god.state.current_speaker != first

    def test_skip_without_speaker_forbidden(self, god: Game) -> None:
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_SKIP_SPEAKER)

    def test_extend_invalid(self, god: Game) -> None:
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_EXTEND, s=-1)

    def test_replay_line(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_NEXT)
        events = god.act(HOST, Action.HOST_REPLAY, line_id="night_start")
        assert events[0].type is EventType.NARRATE
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_REPLAY, line_id="dawn")
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_REPLAY, line_id="nope")

    def test_host_line_same_as_current_is_replay(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_NEXT)
        seq = god.state.step_seq
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        assert god.state.step_seq == seq

    def test_current_line_repeats_without_advancing(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
        seq = god.state.step_seq
        for _ in range(3):  # 催狼人快一點
            events = god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
            assert [e.type for e in events if e.type is EventType.NARRATE]
        assert god.state.step is Step.WOLF and god.state.step_seq == seq

    def test_close_line_waits_for_host_and_can_repeat(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_close")
        god.run(120)  # 按完閉眼不會自動跳到下一個角色
        assert god.state.step is Step.WOLF_END
        god.act(HOST, Action.HOST_LINE, line_id="wolf_close")
        assert god.state.step is Step.WOLF_END
        god.act(HOST, Action.HOST_LINE, line_id="seer_open")
        assert god.state.step is Step.SEER

    def test_replay_earlier_line_and_self_read(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
        events = god.act(HOST, Action.HOST_LINE, line_id="night_start", speak=False)
        assert events[0].data["speak"] is False and god.state.step is Step.WOLF

    def test_host_line_after_end_rejected(self, god: Game) -> None:
        god.act(ADMIN, Action.ADMIN_END)
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_LINE, line_id="night_start")

    def test_nag_after_four_presses(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open")  # 第 1 次
        said = []
        for _ in range(9):  # 第 2 到第 10 次
            events = god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
            said.append(events[0].data["text"])
        original = "狼人請睜眼，請選擇今晚要殺的人"
        assert said[:3] == [original] * 3  # 第 2–4 次還是原句
        assert said[3] == "乾，狼人，睜眼"  # 超過四次
        assert said[7] != said[3] and "狼人" in said[7]  # 超過八次更不耐煩
        assert god.state.step is Step.WOLF

    def test_nag_counts_reset_each_step_and_night(self, god: Game) -> None:
        god.ack_all()
        god.act(HOST, Action.HOST_LINE, line_id="night_start")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
        for _ in range(5):
            god.act(HOST, Action.HOST_LINE, line_id="wolf_open")
        god.act(HOST, Action.HOST_LINE, line_id="wolf_close")
        events = god.act(HOST, Action.HOST_LINE, line_id="wolf_close")
        assert events[0].data["text"] == "狼人請閉眼"

    def test_pause_any_time(self, god: Game) -> None:
        god.act(HOST, Action.ADMIN_PAUSE)
        assert god.state.pause is not None
        with pytest.raises(GameError):
            god.act(HOST, Action.HOST_NEXT)


class TestReplayAndRestore:
    def test_T9_replay_matches(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1", witch={"poison": "p7"})
        game.act(ADMIN, Action.ADMIN_END)
        rebuilt = replay(game.engine.log)
        assert rebuilt.model_dump(mode="json") == game.state.model_dump(mode="json")

    def test_replay_requires_created_first(self) -> None:
        with pytest.raises(ValueError):
            replay([Event(type=EventType.NARRATE, ts=0.0)])

    def test_restart_restores_into_system_pause(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        deadline = game.state.timers.deadline
        assert deadline is not None
        left = deadline - game.engine.log[-1].ts
        new_clock = FakeClock(5.0)
        engine = Engine.restore(game.engine.log, new_clock, GameRng(2))
        assert engine.state.pause is not None
        assert engine.state.pause.reason is PauseReason.SYSTEM
        assert engine.state.night().wolf_picks == {"p4": "p1"}
        engine.handle(ADMIN, Action.ADMIN_RESUME)
        new_clock.advance(balance.RESUME_COUNTDOWN_SECONDS)
        engine.tick()
        assert engine.state.timers.deadline == pytest.approx(new_clock.now() + left)

    def test_L24_restore_with_expired_timer_fires_after_resume(self, game: Game) -> None:
        game.to_wolf_step()
        game.clock.advance(balance.NIGHT_STEP_SECONDS + 100)
        game.engine.emit(EventType.CARD_RESHOWN, player="p1")
        game.engine.flush()
        clock = FakeClock(5.0)
        engine = Engine.restore(game.engine.log, clock, GameRng(2))
        engine.schedule_resume()
        clock.advance(balance.RESUME_COUNTDOWN_SECONDS + 1)
        engine.tick()
        clock.advance(1)
        engine.tick()
        assert engine.state.night().wolf_decided

    def test_restore_ended_game_stays_ended(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_END)
        engine = Engine.restore(game.engine.log, FakeClock(), GameRng(2))
        assert engine.state.step is Step.END and engine.state.pause is None

    def test_E4_checkpoint_revert(self, game: Game) -> None:
        point = game.engine.checkpoint()
        length = len(game.engine.log)
        game.act("p1", Action.DEAL_ACK)
        game.engine.revert(point)
        assert not game.state.player("p1").acked and len(game.engine.log) == length


class TestInvariants:
    def test_strict_raises(self, game: Game) -> None:
        game.state.players[3].role = Role.VILLAGER
        with pytest.raises(InvariantBroken):
            game.engine.tick()

    def test_non_strict_pauses(self, game: Game) -> None:
        game.engine.strict = False
        game.state.players[3].role = Role.VILLAGER
        game.engine.tick()
        assert game.state.pause is not None
        assert game.engine.invariant_error == "faceless_count"

    @pytest.mark.parametrize("problem", ["side_empty", "disguise_target", "witch_double_use"])
    def test_each_problem_detected(self, game: Game, problem: str) -> None:
        state = game.state
        if problem == "side_empty":
            state.step = Step.WOLF
            state.player("p4").alive = False
            state.player("p5").alive = False
        elif problem == "disguise_target":
            assert state.disguise is not None
            state.disguise.target_id = "p4"
        else:
            state.nights.append(
                __import__("server.state").state.NightRecord(
                    round_no=1, witch_saved=True, witch_poison="p1"
                )
            )
        with pytest.raises(InvariantBroken) as err:
            game.engine.check_invariants()
        assert str(err.value) == problem

    def test_L18_speak_order_empty_raises(self, game: Game) -> None:
        for player in game.state.players:
            player.alive = False
        game.state.step = Step.DAWN
        game.state.announced = True
        with pytest.raises(InvariantBroken):
            game.engine._enter(Step.DAY_SPEAK)


def _attach_helpers() -> None:
    def finish_speech_to(self: Game, step: Step) -> None:
        for _ in range(4000):
            if self.state.step is step and not self._not_open():
                return
            if (
                self.state.step in (Step.DAY_SPEAK, Step.LAST_WORDS)
                and not self._not_open()
                and self.state.current_speaker
            ):
                self.act(self.state.current_speaker, Action.SPEAK_END)
            self.clock.advance(0.25)
            self.engine.tick()
        raise AssertionError(f"never reached {step}")

    def finish_speech_or_to_vote(self: Game) -> None:
        finish_speech_to(self, Step.SUSPECT_VOTE)

    Game.finish_speech_to = finish_speech_to  # type: ignore[attr-defined]
    Game.finish_speech_or_to_vote = finish_speech_or_to_vote  # type: ignore[attr-defined]


_attach_helpers()
