"""SPEC D4 情境逐列回歸（SPEC B10 第 4 項、CODING_RULES T3）：每列一個測試，名稱含列號。

已寫在其他檔案的列：#6–10、12、13、16–21、23、24、45 見 test_engine.py；
#44 見 test_rules.py 的輪替統計；#36–38 見 test_api.py。這裡只補其餘各列。
#41（夜晚不震動不發聲）是前端行為，在 P5、P8 驗收。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import balance, config, disguise, rules, timers, views
from server.dev.bots import run_game
from server.enums import Action, Channel, DeathCause, Mode, Role, Step, Winner
from server.errors import ErrorCode, GameError
from server.rng import GameRng
from server.state import DisguiseState
from tests.helpers import EIGHT, make_state
from tests.test_api import Env, Ws, err, join, open_room, player_tokens, start_game
from tests.test_engine import ADMIN, ROLES_8, Game
from tests.test_views import player


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch) -> Game:
    return Game(monkeypatch)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def client(env: Env):  # type: ignore[no-untyped-def]
    from tests.test_api import _OPEN

    with TestClient(env.app) as test_client:
        yield test_client
        for ws in list(_OPEN):
            ws.close()


def test_D4_1_six_players_not_over_after_first_kill() -> None:
    roles = [Role.FACELESS, Role.WOLF, Role.SEER, Role.WITCH, Role.VILLAGER, Role.VILLAGER]
    state = make_state(roles, dead={5: DeathCause.WOLF})
    assert rules.check_win(state) is None
    assert run_game(6, Mode.AUTO, 1, leak_check=False).rounds >= 1


def test_D4_2_twenty_players_speech_bound() -> None:
    assert rules.speak_seconds(20) == 60
    assert run_game(20, Mode.AUTO, 2, leak_check=False).players == 20


def test_D4_3_same_name_rejected(env: Env, client: TestClient) -> None:
    open_room(env, client)
    join(client, "AA")
    assert err(join(client, "AA", device="other")) == "name_taken"


def test_D4_4_one_phone_one_player(env: Env, client: TestClient) -> None:
    open_room(env, client)
    join(client, "AA", device="same")
    assert join(client, "BB", device="same").status_code == 403


def test_D4_5_offline_player_still_dealt_and_auto_acked(env: Env, client: TestClient) -> None:
    open_room(env, client)
    player_tokens(client, 8)  # 全員都沒連 WebSocket，名單標離線
    admin = Ws(client, env.admin_token)
    assert all(row["offline"] for row in env.service.roster_rows())
    assert admin.reply("admin.start")["t"] == "ack"
    engine = env.service.engine
    assert engine is not None
    env.clock.advance(61)
    engine.tick()
    assert all(p.acked for p in engine.state.players)
    admin.close()


def test_wolves_kill_at_most_one_per_night(game: Game) -> None:
    # 狼人選不同人也只死一個；第 1 天第二具屍體只可能來自毒藥或獵人（試玩回饋）
    game.to_wolf_step()
    game.act("p4", Action.WOLF_PICK, target="p1")
    game.act("p5", Action.WOLF_PICK, target="p7")
    game.run(46)
    game.wait_step_after_wolf()
    dead = [p.id for p in game.state.players if not p.alive]
    assert len(dead) == 1 and dead[0] in ("p1", "p7")


def test_narration_is_plain_with_role_names() -> None:
    from server.narration import LINES

    assert LINES["night_start"] == "天黑請閉眼" and LINES["dawn"] == "天亮請睜眼"
    assert LINES["wolf_close"] == "狼人請閉眼" and LINES["seer_close"] == "預言家請閉眼"
    assert LINES["witch_close"] == "女巫請閉眼" and LINES["hunter"] == "獵人請發動技能"


def test_nag_text_tiers() -> None:
    from server.narration import nag_text

    limits = (5, 9)
    assert nag_text("wolf_open", 4, limits) is None
    assert nag_text("wolf_open", 5, limits) == "乾，狼人，睜眼"
    assert nag_text("wolf_open", 9, limits) != nag_text("wolf_open", 5, limits)
    assert nag_text("no_such", 9, limits) is None


def test_narration_rate_is_half_of_original() -> None:
    assert balance.NARRATION_RATE == 0.45
    assert timers.narration_seconds("天黑請閉眼") == pytest.approx(5 * 0.25 / 0.45 + 1)


def test_D4_11_seer_sees_faceless_as_wolf(game: Game) -> None:
    game.to_wolf_step()
    game.wolves_kill("p1")
    game.wait_for(Step.SEER)
    game.act("p2", Action.SEER_CHECK, target="p4")
    checks = views.build(game.state, player("p2"))["me"]["seer_info"]["checks"]
    assert checks[0]["is_wolf"] is True and "faceless" not in str(checks)


def test_D4_14_witch_second_night_sees_self_but_cannot_save() -> None:
    state = make_state(EIGHT, round_no=2)
    state.night().wolf_target = "p3"
    options = rules.witch_options(state, "p3")
    assert options.attacked == "p3" and not options.can_save
    with pytest.raises(GameError):
        rules.validate_witch_act(state, "p3", True, None)


def test_D4_15_witch_cannot_poison_self() -> None:
    with pytest.raises(GameError) as error:
        rules.validate_witch_act(make_state(EIGHT), "p3", False, "p3")
    assert error.value.code is ErrorCode.INVALID_TARGET


def test_D4_22_dead_seat_never_starts_speaking() -> None:
    # v4.12 起點改為隨機；座位 1 已死時當然不會輪到他
    state = make_state(EIGHT, dead={1: DeathCause.VOTE})
    for seed in range(40):
        assert "p1" not in rules.speak_order(state, GameRng(seed))


def test_D4_25_seer_killed_first_night_has_last_words(game: Game) -> None:
    game.to_wolf_step()
    game.night("p2")
    game.wait_for(Step.LAST_WORDS)
    assert game.state.current_speaker == "p2"


def test_D4_26_poisoned_hunter_cannot_shoot_and_cause_is_public(game: Game) -> None:
    # v4.13 起死因公開，大家直接看得到他是被毒死才沒開槍
    game.to_wolf_step()
    game.night(None, witch={"poison": "p6"})
    view = views.build(game.state, player("p1"))
    row = next(p for p in view["players"] if p["id"] == "p6")
    assert row["death_cause"] == "poison" and game.state.hunter_pending is None


def test_D4_27_faceless_may_draw_wolf_ally() -> None:
    state = make_state(EIGHT)
    drawn = {disguise.pick_target(state, GameRng(seed)) for seed in range(100)}
    assert "p5" in drawn


def test_D4_28_target_dies_at_night_redraw_at_dawn(game: Game) -> None:
    assert game.state.disguise is not None
    good_target = next(p.id for p in game.state.players if p.role is Role.VILLAGER and p.id != "p4")
    game.state.disguise.target_id = good_target
    game.state.disguise.periods[0].target_id = good_target
    game.to_wolf_step()
    game.night(good_target)
    assert game.state.disguise.target_id not in (good_target, "p4")
    assert game.state.disguise.rounds_left == balance.DISGUISE_PERIOD_ROUNDS


def test_D4_29_swap_excludes_previous_target() -> None:
    state = make_state(EIGHT, round_no=4)
    state.disguise = DisguiseState(faceless_id="p4", target_id="p1", rounds_left=1)
    for seed in range(50):
        change = disguise.on_round_start(state, GameRng(seed))
        assert change is not None and change.target_id != "p1"


def test_D4_30_disguise_message_identical_for_admin_target(game: Game) -> None:
    # 假扮訊息只帶 display_player_id；徽章由前端依該 id 查名單，所以一定與本人相同
    assert game.state.disguise is not None
    game.state.disguise.target_id = "p1"
    game.to_wolf_step()
    game.night(None)
    events = game.act(
        "p4",
        Action.CHAT_SEND,
        channel=Channel.PUBLIC,
        kind="text",
        content="x",
        **{"as": "disguise"},
    )
    message = views.chat_message({**events[0].data, "ts": 0.0}, player("p2"), game.state)
    assert message is not None and message["display_player_id"] == "p1"
    assert message["is_host_msg"] is False


def test_D4_31_host_is_never_a_disguise_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    god = Game(monkeypatch, mode=Mode.GOD)
    assert god.state.disguise is not None
    assert god.state.disguise.target_id in ROLES_8  # 候選只有本局玩家


def test_D4_32_ally_gets_no_marker_on_disguised_message(game: Game) -> None:
    game.to_wolf_step()
    game.night(None)
    events = game.act(
        "p4",
        Action.CHAT_SEND,
        channel=Channel.PUBLIC,
        kind="text",
        content="x",
        **{"as": "disguise"},
    )
    message = views.chat_message({**events[0].data, "ts": 0.0}, player("p5"), game.state)
    assert message is not None and "real_author" not in message and "mine" not in message


def test_D4_33_faceless_exiled_shows_wolf_and_stops(game: Game) -> None:
    game.to_wolf_step()
    game.night(None)
    game.wait_for(Step.DAY_SPEAK)
    game.finish_speech()
    game.vote_all("p4")
    game.wait_for(Step.REVEAL)
    row = next(r for r in views.build(game.state, player("p1"))["players"] if r["id"] == "p4")
    assert row["public_role"] == "wolf" and "faceless" not in str(row)
    assert game.state.disguise is not None and game.state.disguise.target_id is None
    with pytest.raises(GameError):
        game.act("p4", Action.CHAT_SEND, channel=Channel.PUBLIC, content="x", **{"as": "disguise"})


def test_D4_34_faceless_and_one_good_is_wolf_win() -> None:
    state = make_state(
        [Role.FACELESS, Role.VILLAGER, Role.WOLF, Role.SEER],
        dead={3: DeathCause.VOTE, 4: DeathCause.WOLF},
    )
    assert rules.check_win(state) is Winner.WOLF


def test_D4_35_auto_night_cannot_pause_but_can_end(game: Game) -> None:
    game.to_wolf_step()
    with pytest.raises(GameError):
        game.act(ADMIN, Action.ADMIN_PAUSE)
    game.act(ADMIN, Action.ADMIN_END)
    assert game.state.winner is Winner.NONE


def test_D4_39_auto_admin_offline_does_not_pause(env: Env, client: TestClient) -> None:
    open_room(env, client)
    tokens = player_tokens(client, 8)
    admin = Ws(client, env.admin_token)
    admin.reply("admin.start")
    sockets = [Ws(client, token) for token, _ in tokens]
    admin.close()
    for _ in range(config.HOST_OFFLINE_GRACE_SECONDS + 5):
        env.clock.advance(1)
        for ws in sockets:
            ws.send("ping")
        env.service.tick()
    engine = env.service.engine
    assert engine is not None and engine.state.pause is None
    for ws in sockets:
        ws.close()


def test_D4_40_any_player_can_take_over_narration(game: Game) -> None:
    game.act("p5", Action.NARRATOR_TAKEOVER)
    assert game.state.narrator_id == "p5"


def test_D4_42_auto_step_gap_at_least_4_seconds() -> None:
    assert timers.step_gap("wolf_close") == 4
    assert timers.step_gap("night_start") == 4  # 音效 2 秒＋0.3 秒仍小於 4 秒


def test_D4_43_midgame_end_still_recorded_in_rotation(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    admin.reply("admin.end")
    admin.close()
    assert env.db.rows("SELECT COUNT(*) AS c FROM role_history")[0]["c"] == 8


def test_D4_46_stalemate_has_no_round_cap_until_admin_ends(game: Game) -> None:
    game.to_wolf_step()
    for _ in range(3):
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all(None)
        game.wait_for(Step.WOLF)
    assert game.state.round_no == 4 and game.state.winner is None
    game.act(ADMIN, Action.ADMIN_END)


def test_D4_47_close_deletes_only_keeps_rotation(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    client.delete("/api/admin/room", headers={"Authorization": f"Bearer {env.admin_token}"})
    admin.close()
    assert env.db.rows("SELECT COUNT(*) AS c FROM chat_message")[0]["c"] == 0
    assert env.db.rows("SELECT COUNT(*) AS c FROM role_history")[0]["c"] == 8


def test_L22_seat_requests_are_serialized(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ids = [pid for _, pid in player_tokens(client, 3)]
    admin = Ws(client, env.admin_token)
    admin.reply("admin.seat", order=ids)
    admin.reply("admin.seat", order=ids[::-1])
    assert env.service.players[ids[2]].seat == 1  # 後到者以新座位表為準
    admin.close()
