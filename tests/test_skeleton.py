"""骨架檢查：基礎模組可載入，私密路徑確實被 .gitignore 擋住（DEV_PLAN P0）。"""

import subprocess

import pytest

from server import balance, clock, config, rng


def test_role_table_sums_to_player_count() -> None:
    for n, (wolves, villagers) in balance.ROLE_TABLE.items():
        gods = 2 if n == balance.NO_HUNTER_PLAYER_COUNT else 3
        assert wolves + villagers + gods == n


def test_rng_seed_is_reproducible() -> None:
    a, b = rng.GameRng(7), rng.GameRng(7)
    assert [a.randrange(1000) for _ in range(5)] == [b.randrange(1000) for _ in range(5)]
    assert 8 <= a.uniform_int(8, 15) <= 15
    assert a.choice(["x"]) == "x"
    assert 0 <= rng.GameRng().randrange(10) < 10


def test_clocks() -> None:
    fake = clock.FakeClock(10.0)
    fake.advance(5)
    assert fake.now() == 15.0
    assert clock.SystemClock().now() >= 0


def test_dev_mode_off_by_default() -> None:
    assert config.TIME_SCALE == 1.0 or config.DEV_MODE


@pytest.mark.parametrize(
    "path",
    ["data/game.db", "local_assets/roles/wolf.png", "server/admin.local.json", ".venv/x"],
)
def test_private_paths_are_ignored(path: str) -> None:
    result = subprocess.run(["git", "check-ignore", path], capture_output=True, check=False)
    assert result.returncode == 0
