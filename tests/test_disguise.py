"""千面狼規則（SPEC A6、CODING_RULES L11、L12）。"""

from __future__ import annotations

from server import disguise
from server.enums import DeathCause, DisguiseEnd, Role, Step
from server.rng import GameRng
from server.state import DisguiseState
from tests.helpers import EIGHT, make_state


def with_disguise(target: str | None = "p1", left: int = 3, **kwargs: object):  # type: ignore[no-untyped-def]
    state = make_state(EIGHT, **kwargs)  # type: ignore[arg-type]
    state.disguise = DisguiseState(faceless_id="p4", target_id=target, rounds_left=left)
    return state


def test_pick_never_self_or_dead() -> None:
    state = make_state(EIGHT, dead={1: DeathCause.WOLF})
    for seed in range(50):
        assert disguise.pick_target(state, GameRng(seed)) not in ("p4", "p1")


def test_pick_excludes_previous() -> None:
    state = make_state(EIGHT)
    for seed in range(50):
        assert disguise.pick_target(state, GameRng(seed), previous="p2") != "p2"


def test_L11_no_candidates_returns_none() -> None:
    state = make_state([Role.FACELESS, Role.VILLAGER], dead={2: DeathCause.VOTE})
    assert disguise.pick_target(state, GameRng(1)) is None


def test_L12_only_previous_left_is_allowed() -> None:
    state = make_state([Role.FACELESS, Role.VILLAGER])
    assert disguise.pick_target(state, GameRng(1), previous="p2") == "p2"


def test_on_deal_first_period() -> None:
    result = disguise.on_deal(make_state(EIGHT), GameRng(1))
    assert result.faceless_id == "p4" and result.target_id not in (None, "p4")
    assert result.rounds_left == 3


def test_round_start_first_round_not_counted() -> None:
    assert disguise.on_round_start(with_disguise(round_no=1), GameRng(1)) is None


def test_round_start_no_disguise_or_dead_faceless() -> None:
    assert disguise.on_round_start(make_state(EIGHT, round_no=2), GameRng(1)) is None
    state = with_disguise(round_no=2, dead={4: DeathCause.VOTE})
    assert disguise.on_round_start(state, GameRng(1)) is None


def test_round_start_counts_down_then_swaps_at_round_4() -> None:
    state = with_disguise(round_no=2)
    change = disguise.on_round_start(state, GameRng(1))
    assert change is not None and change.rounds_left == 2 and change.target_id == "p1"
    assert change.ended_reason is None

    state = with_disguise(left=1, round_no=4)
    change = disguise.on_round_start(state, GameRng(1))
    assert change is not None and change.ended_reason is DisguiseEnd.EXPIRED
    assert change.rounds_left == 3 and change.target_id != "p1"


def test_on_death_of_target_redraws_and_resets() -> None:
    state = with_disguise(left=1, dead={1: DeathCause.WOLF})
    change = disguise.on_death(state, "p1", GameRng(1))
    assert change is not None and change.ended_reason is DisguiseEnd.TARGET_DEAD
    assert change.rounds_left == 3 and change.target_id not in ("p1", "p4")


def test_on_death_of_faceless_ends() -> None:
    state = with_disguise(dead={4: DeathCause.VOTE})
    change = disguise.on_death(state, "p4", GameRng(1))
    assert change is not None and change.target_id is None
    assert change.ended_reason is DisguiseEnd.WOLF_DEAD


def test_on_death_of_bystander_or_inactive_is_noop() -> None:
    assert disguise.on_death(with_disguise(), "p2", GameRng(1)) is None
    assert disguise.on_death(with_disguise(target=None), "p1", GameRng(1)) is None
    assert disguise.on_death(make_state(EIGHT), "p1", GameRng(1)) is None


def test_can_disguise_conditions() -> None:
    assert disguise.can_disguise(with_disguise(step=Step.DAY_SPEAK), "p4")
    assert not disguise.can_disguise(with_disguise(step=Step.DAY_SPEAK), "p5")
    assert not disguise.can_disguise(with_disguise(step=Step.WOLF), "p4")
    assert not disguise.can_disguise(with_disguise(target=None), "p4")
    assert not disguise.can_disguise(with_disguise(dead={4: DeathCause.VOTE}), "p4")
    assert not disguise.can_disguise(make_state(EIGHT), "p4")
