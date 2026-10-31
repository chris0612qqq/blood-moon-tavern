"""機器人整局（CODING_RULES T2、T4、T9、SPEC B10 第 5 項）。"""

from __future__ import annotations

import pytest

from server.dev.bots import (
    LeakFound,
    Simulation,
    assert_replay_matches,
    run_game,
    scan_disguise_leak,
)
from server.enums import Mode, Step
from server.events import Event, EventType
from server.views import Viewer, ViewerKind


def _check(players: int, mode: Mode, seed: int, chaos: bool) -> None:
    sim = Simulation(players, mode, seed, chaos=chaos)
    result = sim.run()
    assert sim.engine.state.step is Step.END
    # 失敗時種子印在斷言訊息裡，可一鍵重跑（T2）
    assert_replay_matches(result, sim.engine.state.model_dump(mode="json"))


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("players", [6, 7, 13, 20])
def test_sample_games_end_without_leak_and_replay(players: int, mode: Mode) -> None:
    _check(players, mode, seed=players, chaos=False)


@pytest.mark.parametrize("mode", list(Mode))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_chaos_sample(seed: int, mode: Mode) -> None:
    _check(8, mode, seed=seed, chaos=True)


def test_T4_scanner_catches_masked_real_author() -> None:
    event = Event(
        type=EventType.CHAT_SENT,
        ts=0.0,
        data={"disguise_period": None, "is_wolf_mask": True, "real_author": "p5"},
    )
    with pytest.raises(LeakFound):
        scan_disguise_leak(event, {"who": "p5"}, Viewer(ViewerKind.PLAYER, "p1"), False)
    scan_disguise_leak(event, {"who": "p5"}, Viewer(ViewerKind.PLAYER, "p5"), False)


def test_same_seed_same_game() -> None:
    a = run_game(10, Mode.AUTO, 99, leak_check=False)
    b = run_game(10, Mode.AUTO, 99, leak_check=False)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]


@pytest.mark.slow
@pytest.mark.parametrize("mode", list(Mode))
def test_full_500_games_per_mode(mode: Mode) -> None:
    """DEV_PLAN P2 通關：兩模式合計 1000 局，涵蓋 6–20 人，一半含踢人、暫停、回上一步。"""
    for seed in range(500):
        players = 6 + seed % 15
        _check(players, mode, seed=seed, chaos=seed % 2 == 1)
