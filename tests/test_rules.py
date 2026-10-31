"""規則單元測試（SPEC A5、A13、CODING_RULES L9–L19）。名稱含規則編號（T3）。"""

from __future__ import annotations

from collections import Counter

import pytest

from server import balance, rules
from server.enums import Action, DayContext, DeathCause, Role, Step, Winner
from server.errors import ErrorCode, GameError
from server.rng import GameRng
from server.roles import deal_sequence, is_wolf, night_step_pairs, role_def, roles_acting_in
from server.rules import Consensus, RoleRecord
from server.state import Bet, NightRecord
from tests.helpers import EIGHT, make_state


class TestRoleCounts:
    @pytest.mark.parametrize("n", range(6, 21))
    def test_counts_sum_and_one_faceless(self, n: int) -> None:
        counts = rules.role_counts(n)
        assert sum(counts.values()) == n
        assert counts[Role.FACELESS] == 1

    def test_L9_six_has_no_hunter_seven_has(self) -> None:
        assert rules.role_counts(6)[Role.HUNTER] == 0
        assert rules.role_counts(7)[Role.HUNTER] == 1

    @pytest.mark.parametrize("n", [5, 21])
    def test_L9_out_of_range_rejected(self, n: int) -> None:
        with pytest.raises(ValueError):
            rules.role_counts(n)

    def test_registry_derived_orders(self) -> None:
        assert deal_sequence() == [Role.FACELESS, Role.WOLF, Role.SEER, Role.WITCH, Role.HUNTER]
        assert night_step_pairs() == [
            (Step.WOLF, Step.WOLF_END),
            (Step.SEER, Step.SEER_END),
            (Step.WITCH, Step.WITCH_END),
        ]
        assert set(roles_acting_in(Step.WOLF)) == {Role.WOLF, Role.FACELESS}
        assert role_def(Role.HUNTER).shoots_on_death


class TestDeal:
    @pytest.mark.parametrize("n", range(6, 21))
    def test_everyone_gets_the_table_roles(self, n: int) -> None:
        ids = [f"p{i}" for i in range(n)]
        dealt = rules.deal(ids, {}, GameRng(n))
        assert set(dealt) == set(ids)
        counts = Counter(dealt.values())
        for role, expected in rules.role_counts(n).items():
            assert counts[role] == expected

    def test_L25_same_seed_same_result_regardless_of_input_order(self) -> None:
        ids = [f"p{i}" for i in range(10)]
        assert rules.deal(ids, {}, GameRng(5)) == rules.deal(ids[::-1], {}, GameRng(5))

    def test_weights_per_spec(self) -> None:
        record = RoleRecord(last=Role.WITCH, before=Role.FACELESS)
        assert rules.role_weight(None, Role.WOLF) == balance.WEIGHT_DEFAULT
        assert rules.role_weight(record, Role.WITCH) == balance.WEIGHT_LAST_GAME
        assert rules.role_weight(record, Role.WOLF) == balance.WEIGHT_GAME_BEFORE
        assert rules.role_weight(record, Role.FACELESS) == balance.WEIGHT_GAME_BEFORE
        assert rules.role_weight(record, Role.SEER) == balance.WEIGHT_DEFAULT
        assert (
            rules.role_weight(RoleRecord(last=Role.FACELESS), Role.WOLF) == balance.WEIGHT_LAST_GAME
        )

    def test_L10_zero_total_weight_falls_back_to_equal(self) -> None:
        seen = {rules.weighted_pick(["a", "b"], [0, 0], GameRng(i)) for i in range(40)}
        assert seen == {"a", "b"}

    def test_weighted_pick_impossible_point_raises(self) -> None:
        class BrokenRng(GameRng):
            def randrange(self, stop: int) -> int:
                return stop + 1

        with pytest.raises(AssertionError):
            rules.weighted_pick(["a"], [1], BrokenRng(1))

    @pytest.mark.slow
    @pytest.mark.parametrize(("n", "wolves"), [(8, 2), (10, 3), (20, 7)])
    def test_rotation_statistics_wolf_multi_slot(self, n: int, wolves: int) -> None:
        # SPEC B10：多名額下依序抽牌，實測約 27–31%
        ids = [f"p{i:02d}" for i in range(n)]
        history = {pid: RoleRecord(last=Role.WOLF) for pid in ids[:wolves]}
        rng = GameRng(1)
        trials = 100_000 // n
        again = other = 0
        for _ in range(trials):
            dealt = rules.deal(ids, history, rng)
            again += sum(is_wolf(dealt[p]) for p in ids[:wolves])
            other += sum(is_wolf(dealt[p]) for p in ids[wolves:])
        ratio = (again / wolves) / (other / (n - wolves))
        assert 0.24 <= ratio <= 0.33

    @pytest.mark.slow
    def test_rotation_statistics_single_slot(self) -> None:
        ids = [f"p{i}" for i in range(10)]
        history = {"p0": RoleRecord(last=Role.SEER)}
        rng = GameRng(2)
        counts: Counter[str] = Counter()
        for _ in range(100_000):
            dealt = rules.deal(ids, history, rng)
            seer = next(p for p, r in dealt.items() if r is Role.SEER)
            counts[seer] += 1
        others = sum(v for k, v in counts.items() if k != "p0") / 9
        assert 0.22 <= counts["p0"] / others <= 0.30


class TestTargets:
    def test_wolf_cannot_pick_pack(self) -> None:
        state = make_state(EIGHT)
        assert rules.eligible_targets(state, "p5", Action.WOLF_PICK) == [
            "p1",
            "p2",
            "p3",
            "p6",
            "p7",
            "p8",
        ]

    def test_others_exclude_self_and_dead(self) -> None:
        state = make_state(EIGHT, dead={1: DeathCause.WOLF})
        targets = rules.eligible_targets(state, "p2", Action.SEER_CHECK)
        assert "p1" not in targets and "p2" not in targets and "p4" in targets

    def test_L16_hunter_with_no_targets(self) -> None:
        state = make_state([Role.HUNTER], dead={1: DeathCause.WOLF})
        assert rules.eligible_targets(state, "p1", Action.HUNTER_SHOOT) == []


class TestWolfConsensus:
    def test_needs_all_wolves(self) -> None:
        assert rules.wolf_consensus({"a": "x"}, ["a", "b"]) == Consensus(agreed=False)
        assert rules.wolf_consensus({}, []) == Consensus(agreed=False)

    def test_disagree(self) -> None:
        assert not rules.wolf_consensus({"a": "x", "b": "y"}, ["a", "b"]).agreed

    def test_agree_on_target_and_on_empty(self) -> None:
        assert rules.wolf_consensus({"a": "x", "b": "x"}, ["a", "b"]) == Consensus(True, "x")
        assert rules.wolf_consensus({"a": None, "b": None}, ["a", "b"]) == Consensus(True, None)

    def test_dead_wolf_pick_ignored(self) -> None:
        assert rules.wolf_consensus({"a": "x", "dead": "y"}, ["a"]) == Consensus(True, "x")

    def test_L13_nobody_picked_is_empty_knife(self) -> None:
        assert rules.wolf_timeout_choice({}, ["a", "b"], GameRng(1)) is None

    def test_L14_tie_includes_empty_knife(self) -> None:
        picks = {"a": "x", "b": None}
        seen = {rules.wolf_timeout_choice(picks, ["a", "b"], GameRng(i)) for i in range(40)}
        assert seen == {"x", None}

    def test_most_picked_wins(self) -> None:
        picks = {"a": "x", "b": "x", "c": "y"}
        assert rules.wolf_timeout_choice(picks, ["a", "b", "c"], GameRng(1)) == "x"


class TestWitch:
    def test_first_night_self_save(self) -> None:
        state = make_state(EIGHT)
        state.night().wolf_target = "p3"
        options = rules.witch_options(state, "p3")
        assert options.can_save and options.attacked == "p3" and options.can_poison

    def test_later_night_no_self_save_but_told(self) -> None:
        state = make_state(EIGHT, round_no=2)
        state.night().wolf_target = "p3"
        options = rules.witch_options(state, "p3")
        assert not options.can_save and options.attacked == "p3"

    def test_later_night_can_save_others(self) -> None:
        state = make_state(EIGHT, round_no=2)
        state.night().wolf_target = "p1"
        assert rules.witch_options(state, "p3").can_save

    def test_antidote_used_not_told(self) -> None:
        state = make_state(EIGHT)
        state.witch_antidote_used = True
        state.night().wolf_target = "p1"
        options = rules.witch_options(state, "p3")
        assert options.attacked is None and not options.can_save

    def test_empty_knife_nothing_to_save(self) -> None:
        options = rules.witch_options(make_state(EIGHT), "p3")
        assert options.attacked is None and not options.can_save

    def test_poison_used(self) -> None:
        state = make_state(EIGHT)
        state.witch_poison_used = True
        assert not rules.witch_options(state, "p3").can_poison

    def _rejected(self, state: object, save: bool, poison: str | None) -> None:
        with pytest.raises(GameError) as err:
            rules.validate_witch_act(state, "p3", save, poison)  # type: ignore[arg-type]
        assert err.value.code is ErrorCode.INVALID_TARGET

    def test_no_double_use_same_night(self) -> None:
        state = make_state(EIGHT)
        state.night().wolf_target = "p1"
        self._rejected(state, True, "p2")

    def test_save_rejected_when_nothing_to_save(self) -> None:
        self._rejected(make_state(EIGHT), True, None)

    def test_cannot_poison_self_or_dead_or_without_poison(self) -> None:
        state = make_state(EIGHT, dead={1: DeathCause.WOLF})
        self._rejected(state, False, "p3")
        self._rejected(state, False, "p1")
        state.witch_poison_used = True
        self._rejected(state, False, "p2")

    def test_valid_acts_pass(self) -> None:
        state = make_state(EIGHT)
        state.night().wolf_target = "p1"
        rules.validate_witch_act(state, "p3", True, None)
        rules.validate_witch_act(state, "p3", False, "p2")
        rules.validate_witch_act(state, "p3", False, None)


class TestResolveNight:
    def test_empty(self) -> None:
        assert rules.resolve_night(NightRecord(round_no=1)) == []

    def test_kill_save_poison(self) -> None:
        assert rules.resolve_night(NightRecord(round_no=1, wolf_target="a")) == [
            ("a", DeathCause.WOLF)
        ]
        saved = NightRecord(round_no=1, wolf_target="a", witch_saved=True)
        assert rules.resolve_night(saved) == []
        both = NightRecord(round_no=1, wolf_target="a", witch_poison="b")
        assert rules.resolve_night(both) == [("a", DeathCause.WOLF), ("b", DeathCause.POISON)]

    def test_L19_knifed_and_poisoned_counts_once_as_poison(self) -> None:
        night = NightRecord(round_no=1, wolf_target="a", witch_poison="a")
        assert rules.resolve_night(night) == [("a", DeathCause.POISON)]

    @pytest.mark.parametrize(
        ("cause", "expected"),
        [
            (DeathCause.WOLF, True),
            (DeathCause.VOTE, True),
            (DeathCause.POISON, False),
            (DeathCause.KICK, False),
            (DeathCause.MANUAL, False),
        ],
    )
    def test_can_shoot(self, cause: DeathCause, expected: bool) -> None:
        assert rules.can_shoot(cause) is expected


class TestTally:
    def test_L15_all_abstain(self) -> None:
        assert rules.tally({"a": None, "b": None}).exiled is None

    def test_L15_single_vote_is_top(self) -> None:
        assert rules.tally({"a": "x", "b": None}).exiled == "x"

    def test_tie_nobody_out(self) -> None:
        assert rules.tally({"a": "x", "b": "y"}).exiled is None

    def test_majority(self) -> None:
        result = rules.tally({"a": "x", "b": "x", "c": "y"})
        assert result.exiled == "x" and result.counts == {"x": 2, "y": 1}


class TestCheckWin:
    def test_ongoing(self) -> None:
        assert rules.check_win(make_state(EIGHT)) is None

    def test_wolves_dead(self) -> None:
        state = make_state(EIGHT, dead={4: DeathCause.VOTE, 5: DeathCause.VOTE})
        assert rules.check_win(state) is Winner.VILLAGE

    def test_parity(self) -> None:
        dead = {i: DeathCause.WOLF for i in (1, 2, 3, 6)}
        assert rules.check_win(make_state(EIGHT, dead=dead)) is Winner.WOLF


class TestSpeakOrder:
    def test_peaceful_night_from_first_alive_seat(self) -> None:
        state = make_state(EIGHT, dead={1: DeathCause.VOTE})
        assert rules.speak_order(state)[0] == "p2"
        assert len(rules.speak_order(state)) == 7

    def test_after_smallest_dead_seat_and_wraps(self) -> None:
        state = make_state(EIGHT, dead={3: DeathCause.WOLF, 6: DeathCause.POISON})
        state.dawn_deaths = ["p6", "p3"]
        assert rules.speak_order(state) == ["p4", "p5", "p7", "p8", "p1", "p2"]

    def test_last_seat_dead_starts_from_first(self) -> None:
        state = make_state(EIGHT, dead={8: DeathCause.WOLF})
        state.dawn_deaths = ["p8"]
        assert rules.speak_order(state)[0] == "p1"


class TestLastWords:
    def test_who_gets_last_words(self) -> None:
        assert rules.gets_last_words(1, DayContext.DAWN)
        assert not rules.gets_last_words(2, DayContext.DAWN)
        assert rules.gets_last_words(2, DayContext.REVEAL)

    def test_L17_queue_by_seat_without_kicked(self) -> None:
        state = make_state(
            EIGHT, dead={2: DeathCause.WOLF, 1: DeathCause.HUNTER, 3: DeathCause.KICK}
        )
        state.pending_last_words = ["p2", "p1", "p3"]
        assert rules.last_words_queue(state) == ["p1", "p2"]
        state.pending_last_words = []
        assert rules.last_words_queue(state) == []


@pytest.mark.parametrize(("n", "s"), [(6, 90), (10, 90), (11, 75), (15, 75), (16, 60), (20, 60)])
def test_speak_seconds(n: int, s: int) -> None:
    assert rules.speak_seconds(n) == s


def test_speak_seconds_beyond_table_uses_last() -> None:
    assert rules.speak_seconds(99) == 60


class TestPublicHelpers:
    def test_public_role_hides_faceless(self) -> None:
        assert rules.public_role(Role.FACELESS) is Role.WOLF
        assert rules.public_role(Role.SEER) is Role.SEER

    def test_step_classes(self) -> None:
        assert rules.is_day_step(Step.VOTE) and not rules.is_day_step(Step.WOLF)
        assert rules.is_night_step(Step.WOLF) and not rules.is_night_step(Step.VOTE)

    def test_alive_with_role(self) -> None:
        state = make_state(EIGHT, dead={2: DeathCause.WOLF})
        assert rules.alive_with_role(state, Role.SEER) is None
        witch = rules.alive_with_role(state, Role.WITCH)
        assert witch is not None and witch.id == "p3"


def test_can_wolf_mask_only_alive_wolves_by_day() -> None:
    day = make_state(EIGHT, step=Step.DAY_SPEAK, dead={5: DeathCause.VOTE})
    assert rules.can_wolf_mask(day, "p4")  # 千面狼也可以
    assert not rules.can_wolf_mask(day, "p5")  # 已死
    assert not rules.can_wolf_mask(day, "p1")  # 好人
    assert not rules.can_wolf_mask(make_state(EIGHT, step=Step.WOLF), "p4")  # 夜晚


class TestBets:
    def test_can_bet_only_dead_village_not_kicked(self) -> None:
        state = make_state(EIGHT, dead={1: DeathCause.WOLF, 4: DeathCause.VOTE, 7: DeathCause.KICK})
        assert rules.can_bet(state, "p1")
        assert not rules.can_bet(state, "p2")  # 還活著
        assert not rules.can_bet(state, "p4")  # 狼陣營
        assert not rules.can_bet(state, "p7")  # 被踢

    @pytest.mark.parametrize(
        "bet",
        [
            Bet(wolves=["p2", "p3", "p4"]),  # 超過狼人總數
            Bet(wolves=["p2", "p2"]),  # 重複
            Bet(wolves=["p1"]),  # 自己
            Bet(faceless="p1"),  # 自己
            Bet(wolves=["nope"]),  # 不是玩家
        ],
    )
    def test_validate_rejects(self, bet: Bet) -> None:
        with pytest.raises(GameError):
            rules.validate_bet(make_state(EIGHT), "p1", bet)

    def test_validate_accepts(self) -> None:
        rules.validate_bet(make_state(EIGHT), "p1", Bet(wolves=["p4", "p5"], faceless="p4"))

    def test_score_and_ties(self) -> None:
        roles = {"w1": Role.FACELESS, "w2": Role.WOLF, "v": Role.VILLAGER, "s": Role.SEER}
        scores = rules.score_bets(
            {
                "a": Bet(wolves=["w1", "w2"], faceless="w1"),  # 2 + 2
                "b": Bet(wolves=["w2", "v"], faceless="w2"),  # 1 - 1
                "c": Bet(wolves=["v", "s"]),  # -2 → 0
                "d": Bet(wolves=["w2"]),  # 1
                "e": Bet(wolves=["w1"]),  # 1
            },
            roles,
        )
        assert [(s.player_id, s.score, s.rank) for s in scores] == [
            ("a", 4, 1),
            ("d", 1, 2),
            ("e", 1, 2),
            ("b", 0, 4),
            ("c", 0, 4),
        ]
