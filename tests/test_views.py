"""保密視圖（SPEC A7、B10 第 3 項、CODING_RULES T4）。"""

from __future__ import annotations

import json

import pytest

from server import views
from server.dev.bots import LeakFound, allowed_tokens, scan_disguise_leak, scan_for_leaks
from server.enums import Action, Channel, Mode, PauseReason, Role, Step
from server.events import EventType
from server.modes import Actor
from server.state import GameState
from server.views import HOST_VIEWER, OBSERVER_VIEWER, Viewer, ViewerKind
from tests.test_engine import ADMIN, HOST, Game


def player(pid: str) -> Viewer:
    return Viewer(ViewerKind.PLAYER, pid)


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch) -> Game:
    return Game(monkeypatch)


@pytest.fixture
def god(monkeypatch: pytest.MonkeyPatch) -> Game:
    return Game(monkeypatch, mode=Mode.GOD)


def text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


class TestBuild:
    def test_alive_others_roles_hidden(self, game: Game) -> None:
        view = views.build(game.state, player("p1"))
        assert view["me"]["role"] == "villager"
        row = next(p for p in view["players"] if p["id"] == "p2")
        assert "role" not in row and "public_role" not in row
        assert '"seer"' not in text(view) and '"faceless"' not in text(view)

    def test_dead_shows_public_role_only(self, game: Game) -> None:
        game.act(ADMIN, Action.ADMIN_KICK, player="p4")
        view = views.build(game.state, player("p1"))
        row = next(p for p in view["players"] if p["id"] == "p4")
        assert row["public_role"] == "wolf"
        assert '"faceless"' not in text(view)

    def test_wolf_pack_known_but_not_faceless(self, game: Game) -> None:
        view = views.build(game.state, player("p5"))
        assert set(view["me"]["wolf_pack"]["pack"]) == {"p4", "p5"}
        assert '"faceless"' not in text(view) and "disguise_info" not in view["me"]

    def test_faceless_sees_disguise(self, game: Game) -> None:
        me = views.build(game.state, player("p4"))["me"]
        assert game.state.disguise is not None
        assert me["disguise_info"]["target"] == game.state.disguise.target_id
        assert me["disguise_info"]["rounds_left"] == 2

    def test_observer_has_no_me_or_secrets(self, game: Game) -> None:
        view = views.build(game.state, OBSERVER_VIEWER)
        assert "me" not in view and "host" not in view
        assert views.build(game.state, Viewer(ViewerKind.PLAYER, "late")).get("me") is None

    def test_host_sees_everything_except_bets(self, god: Game) -> None:
        god.state.bets["p1"] = __import__("server.state").state.Bet(wolves=["p4"])
        view = views.build(god.state, HOST_VIEWER)
        assert view["host"]["disguise"]["faceless_id"] == "p4"
        assert {p["role"] for p in view["host"]["players"]} >= {"faceless", "seer"}
        assert "bets" not in view["host"] and "my_bet" not in text(view)

    def test_night_clock_hidden_from_non_actors(self, game: Game) -> None:
        game.to_wolf_step()
        assert "deadline" not in views.build(game.state, player("p1"))
        assert views.build(game.state, player("p4"))["deadline"] is not None
        assert views.build(game.state, HOST_VIEWER)["deadline"] is not None

    def test_day_clock_public(self, game: Game) -> None:
        assert "deadline" in views.build(game.state, player("p1"))

    def test_wolf_picks_only_alive_wolves(self, game: Game) -> None:
        game.to_wolf_step()
        game.act("p4", Action.WOLF_PICK, target="p1")
        assert views.build(game.state, player("p5"))["me"]["wolf_pack"]["picks"] == {"p4": "p1"}
        assert "wolf_pack" not in views.build(game.state, player("p2"))["me"]
        game.act(ADMIN, Action.ADMIN_KICK, player="p5")
        assert "picks" not in views.build(game.state, player("p5"))["me"]["wolf_pack"]

    def test_wolf_decision_stays_visible_after_step_ends(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WOLF_END)
        pack = views.build(game.state, player("p5"))["me"]["wolf_pack"]
        assert pack["decided"] is True and pack["decided_target"] == "p1"
        assert "wolf_pack" not in views.build(game.state, player("p2"))["me"]

    def test_seer_result_only_to_seer(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.SEER)
        game.act("p2", Action.SEER_CHECK, target="p4")
        checks = views.build(game.state, player("p2"))["me"]["seer_info"]["checks"]
        assert checks == [{"round_no": 1, "target": "p4", "is_wolf": True}]
        assert "seer_info" not in views.build(game.state, player("p1"))["me"]

    def test_witch_told_attacked_until_antidote_used(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.WITCH)
        info = views.build(game.state, player("p3"))["me"]["witch_info"]
        assert info["attacked"] == "p1" and info["can_save"]
        assert "witch_info" not in views.build(game.state, player("p1"))["me"]
        game.state.witch_antidote_used = True
        assert views.build(game.state, player("p3"))["me"]["witch_info"]["attacked"] is None

    def test_witch_info_outside_step_has_no_attack(self, game: Game) -> None:
        info = views.build(game.state, player("p3"))["me"]["witch_info"]
        assert "attacked" not in info

    def test_eligible_targets_only_for_actor(self, game: Game) -> None:
        game.to_wolf_step()
        me = views.build(game.state, player("p4"))["me"]
        assert "p5" not in me["eligible_targets"] and "p1" in me["eligible_targets"]
        assert "eligible_targets" not in views.build(game.state, player("p1"))["me"]

    def test_death_cause_not_public(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1", witch={"poison": "p7"})
        for viewer in (player("p8"), player("p1"), player("p7"), OBSERVER_VIEWER):
            payload = text(views.build(game.state, viewer))
            assert '"poison"' not in payload and "death_cause" not in payload

    def test_host_sees_death_cause(self, god: Game) -> None:
        god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=False)
        rows = views.build(god.state, HOST_VIEWER)["host"]["players"]
        assert next(r for r in rows if r["id"] == "p1")["death_cause"] == "manual"

    def test_vote_details_hidden_until_reveal(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.wait_for(Step.VOTE)
        game.act("p1", Action.VOTE_CAST, target="p2")
        view = views.build(game.state, player("p3"))
        assert view["progress"] == {"done": 1, "total": 8}
        assert "ballots" not in text(view)
        mine = views.build(game.state, player("p1"))["me"]["my_vote"]
        assert mine == {"target": "p2", "can_change": True}
        assert views.build(game.state, HOST_VIEWER)["host"]["votes"][0]["ballots"] == {"p1": "p2"}

    def test_bet_only_own(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        game.act("p1", Action.BET_SET, wolves=["p4"], faceless="p5")
        assert views.build(game.state, player("p1"))["me"]["my_bet"]["faceless_guess"] == "p5"
        assert "my_bet" not in views.build(game.state, player("p2"))["me"]

    def test_end_reveals_truth_to_all(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        game.act("p1", Action.BET_SET, wolves=["p4"], faceless="p4")
        game.act(ADMIN, Action.ADMIN_END)
        view = views.build(game.state, OBSERVER_VIEWER)
        assert view["truth"]["roles"]["p4"] == "faceless"
        assert view["truth"]["death_causes"]["p1"] == "wolf"
        assert view["truth"]["bets"][0]["score"] == 3
        assert next(p for p in view["players"] if p["id"] == "p4")["role"] == "faceless"

    def test_truth_limits_to_seven_nights(self, game: Game) -> None:
        for number in range(1, 10):
            game.state.nights.append(__import__("server.state").state.NightRecord(round_no=number))
            game.state.votes.append(__import__("server.state").state.VoteRound(round_no=number))
        game.state.round_no = 9
        game.state.step = Step.END
        truth = views.truth_block(game.state)
        assert truth["nights_hidden"] is True and truth["max_nights"] == 7
        assert max(n["round_no"] for n in truth["nights"]) == 7
        assert max(v["round_no"] for v in truth["votes"]) == 7

    def test_truth_has_hunter_shots_and_death_rounds_only_at_end(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p6")
        game.wait_for(Step.HUNTER)
        game.act("p6", Action.HUNTER_SHOOT, target="p1")
        # 遊戲中不能外洩（死因與回合結算才公開）
        assert "hunter_shots" not in text(views.build(game.state, player("p2")))
        assert "death_causes" not in text(views.build(game.state, player("p2")))
        assert views.build(game.state, HOST_VIEWER)["host"]["hunter_shots"][0]["target"] == "p1"
        game.act(ADMIN, Action.ADMIN_END)
        truth = views.build(game.state, player("p2"))["truth"]
        assert truth["hunter_shots"] == [{"round_no": 1, "hunter": "p6", "target": "p1"}]
        assert truth["death_rounds"] == {"p6": 1, "p1": 1} and truth["nights_hidden"] is False

    def test_paused_block(self, game: Game) -> None:
        game.engine.system_pause(PauseReason.HOST_OFFLINE)
        assert views.build(game.state, player("p1"))["paused"]["reason"] == "host_offline"


class TestChatFilter:
    def _disguised(self, game: Game) -> dict[str, object]:
        game.to_wolf_step()
        game.night(None)
        events = game.act(
            "p4",
            Action.CHAT_SEND,
            channel=Channel.PUBLIC,
            kind="text",
            content="騙你的",
            **{"as": "disguise"},
        )
        return {**events[0].data, "ts": events[0].ts}

    def test_disguised_message_has_no_real_author_for_others(self, game: Game) -> None:
        msg = self._disguised(game)
        assert game.state.disguise is not None
        target = game.state.disguise.target_id
        for viewer in (player("p1"), player("p5"), player(str(target)), OBSERVER_VIEWER):
            out = views.chat_message(msg, viewer, game.state)
            assert out is not None
            assert "p4" not in text(out) and "real_author" not in out
            assert out["display_player_id"] == target
            assert "mine" not in out

    def test_faceless_sees_own_marker(self, game: Game) -> None:
        out = views.chat_message(self._disguised(game), player("p4"), game.state)
        assert out is not None and out["mine"] and out["disguised_by_me"]

    def test_host_and_end_see_real_author(self, game: Game) -> None:
        msg = self._disguised(game)
        host_view = views.chat_message(msg, HOST_VIEWER, game.state)
        assert host_view is not None and host_view["real_author"] == "p4"
        game.act(ADMIN, Action.ADMIN_END)
        ended = views.chat_message(msg, player("p1"), game.state)
        assert ended is not None and ended["real_author"] == "p4"
        truth = views.build(game.state, player("p1"), [msg])["truth"]
        assert truth["disguised_messages"][0]["real_author"] == "p4"

    def test_wolf_channel_only_wolves(self, game: Game) -> None:
        game.to_wolf_step()
        events = game.act("p4", Action.CHAT_SEND, channel=Channel.WOLF, kind="text", content="刀誰")
        msg = {**events[0].data, "ts": events[0].ts}
        assert views.chat_message(msg, player("p5"), game.state) is not None
        assert views.chat_message(msg, player("p1"), game.state) is None
        assert views.chat_message(msg, OBSERVER_VIEWER, game.state) is None
        assert views.chat_message(msg, HOST_VIEWER, game.state) is not None
        chat = views.build(game.state, player("p1"), [msg])["chat"]
        assert chat == []

    def test_plain_message_mine_flag(self, game: Game) -> None:
        events = game.act("p1", Action.CHAT_SEND, channel=Channel.PUBLIC, kind="text", content="x")
        msg = {**events[0].data, "ts": events[0].ts}
        out = views.chat_message(msg, player("p1"), game.state)
        assert out is not None and out["mine"] and "disguised_by_me" not in out


class TestWolfMaskFilter:
    def _masked(self, game: Game) -> dict[str, object]:
        game.to_wolf_step()
        game.night(None)
        events = game.act(
            "p5",
            Action.CHAT_SEND,
            channel=Channel.PUBLIC,
            kind="text",
            content="嗷嗚",
            **{"as": "wolf"},
        )
        return {**events[0].data, "ts": events[0].ts}

    def test_nobody_can_tell_who(self, game: Game) -> None:
        msg = self._masked(game)
        # 連狼同伴也不知道（SPEC A9）
        for viewer in (player("p1"), player("p4"), OBSERVER_VIEWER):
            out = views.chat_message(msg, viewer, game.state)
            assert out is not None
            assert out["is_wolf_mask"] is True and out["display_player_id"] is None
            assert "p5" not in text(out) and "real_author" not in out and "mine" not in out

    def test_author_marked_host_and_end_see_real(self, game: Game) -> None:
        msg = self._masked(game)
        own = views.chat_message(msg, player("p5"), game.state)
        assert own is not None and own["mine"] and own["masked_by_me"]
        host_view = views.chat_message(msg, HOST_VIEWER, game.state)
        assert host_view is not None and host_view["real_author"] == "p5"
        game.act(ADMIN, Action.ADMIN_END)
        ended = views.chat_message(msg, player("p1"), game.state)
        assert ended is not None and ended["real_author"] == "p5"
        truth = views.build(game.state, player("p1"), [msg])["truth"]
        assert truth["disguised_messages"][0] == {
            "id": msg["id"],
            "real_author": "p5",
            "display": None,
        }

    def test_me_block_flag(self, game: Game) -> None:
        game.to_wolf_step()
        assert views.build(game.state, player("p5"))["me"]["can_wolf_mask"] is False
        game.night(None)
        assert views.build(game.state, player("p5"))["me"]["can_wolf_mask"] is True
        assert "can_wolf_mask" not in views.build(game.state, player("p1"))["me"]

    def test_lobby_message_has_flag(self) -> None:
        row = {"id": 1, "channel": "public", "display": "a", "is_host": False, "kind": "text",
               "content": "x", "media_id": None, "ts": 0.0, "real_author": "a"}  # fmt: skip
        assert views.lobby_chat_message(row, player("b"))["is_wolf_mask"] is False


class TestEvents:
    def _types(self, game: Game, viewer: Viewer, events: list) -> list[str]:  # type: ignore[type-arg]
        return [m["t"] for e in events for m in views.filter_event(e, viewer, game.state)]

    def test_step_message_has_no_actors_at_night(self, game: Game) -> None:
        game.ack_all()
        game.clock.advance(5)
        step_events = []
        for _ in range(200):
            game.clock.advance(0.25)
            step_events += game.engine.tick()
            if game.state.step is Step.WOLF:
                break
        event = next(e for e in step_events if e.type is EventType.STEP_ENTERED)
        out = views.filter_event(event, player("p1"), game.state)
        step_msg = next(m for m in out if m["t"] == "step")
        assert step_msg["public_actors"] == []

    def test_wolf_picks_event_routing(self, game: Game) -> None:
        game.to_wolf_step()
        events = game.act("p4", Action.WOLF_PICK, target="p1")
        assert "wolf.picks" in self._types(game, player("p5"), events)
        assert "wolf.picks" not in self._types(game, player("p1"), events)

    def test_seer_result_routing(self, game: Game) -> None:
        game.to_wolf_step()
        game.wolves_kill("p1")
        game.wait_for(Step.SEER)
        events = game.act("p2", Action.SEER_CHECK, target="p4")
        assert views.filter_event(events[0], player("p1"), game.state) == []
        assert views.filter_event(events[0], player("p2"), game.state)[0]["t"] == "me"

    def test_death_event_no_cause(self, game: Game) -> None:
        events = game.act(ADMIN, Action.ADMIN_KICK, player="p4")
        died = next(e for e in events if e.type is EventType.PLAYER_DIED)
        msg = views.filter_event(died, player("p1"), game.state)[0]
        assert msg == {"t": "death", "players": [{"id": "p4", "public_role": "wolf"}]}

    def test_disguise_change_routing(self, game: Game) -> None:
        assert game.state.disguise is not None
        target = game.state.disguise.target_id
        assert target is not None
        events = game.act(ADMIN, Action.ADMIN_KICK, player=target)
        change = next(e for e in events if e.type is EventType.DISGUISE_CHANGED)
        assert views.filter_event(change, player("p5"), game.state) == []
        msg = views.filter_event(change, player("p4"), game.state)[0]
        assert msg["t"] == "disguise" and msg["silent"] is False

    def test_disguise_change_at_night_is_silent(self, game: Game) -> None:
        game.to_wolf_step()
        assert game.state.disguise is not None
        events = game.act(ADMIN, Action.ADMIN_KICK, player=str(game.state.disguise.target_id))
        change = next(e for e in events if e.type is EventType.DISGUISE_CHANGED)
        assert views.filter_event(change, player("p4"), game.state)[0]["silent"] is True

    def test_vote_cast_only_progress_to_others(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.wait_for(Step.VOTE)
        events = game.act("p1", Action.VOTE_CAST, target="p2")
        cast = next(e for e in events if e.type is EventType.VOTE_CAST)
        others = views.filter_event(cast, player("p3"), game.state)
        assert others == [{"t": "progress", "done": 1, "total": 8}]
        assert "me" in [m["t"] for m in views.filter_event(cast, player("p1"), game.state)]

    def test_vote_reveal_public(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        game.wait_for(Step.DAY_SPEAK)
        game.finish_speech()
        game.vote_all("p1")
        collected = []
        for _ in range(100):
            game.clock.advance(0.25)
            collected += game.engine.tick()
            if game.state.step is Step.REVEAL:
                break
        reveal = next(e for e in collected if e.type is EventType.VOTES_REVEALED)
        msg = views.filter_event(reveal, player("p2"), game.state)[0]
        assert msg["t"] == "vote.reveal" and msg["exiled"] == "p1"

    def test_end_event_full_state_with_truth(self, game: Game) -> None:
        events = game.act(ADMIN, Action.ADMIN_END)
        ended = next(e for e in events if e.type is EventType.GAME_ENDED)
        msg = views.filter_event(ended, player("p1"), game.state)[0]
        assert msg["t"] == "state" and "truth" in msg

    def test_resume_sends_full_state(self, game: Game) -> None:
        game.engine.system_pause(PauseReason.SYSTEM)
        paused = game.engine.schedule_resume()
        assert views.filter_event(paused[0], player("p1"), game.state)[0]["t"] == "paused"
        game.clock.advance(6)
        events = game.engine.tick()
        resumed = next(e for e in events if e.type is EventType.RESUMED)
        assert views.filter_event(resumed, player("p1"), game.state)[0]["t"] == "state"

    def test_host_gets_progress_each_event(self, god: Game) -> None:
        events = god.act("p1", Action.DEAL_ACK)
        assert "host.progress" in self._types(god, HOST_VIEWER, events)
        assert "host.progress" not in self._types(god, player("p2"), events)

    def test_narrate_public(self, god: Game) -> None:
        god.ack_all()
        events = god.act(HOST, Action.HOST_NEXT)
        narrate = next(e for e in events if e.type is EventType.NARRATE)
        out = views.filter_event(narrate, HOST_VIEWER, god.state)
        assert out[0]["t"] == "narrate" and len(out) == 1

    def test_card_reshow_only_to_that_player(self, god: Game) -> None:
        events = god.act(HOST, Action.HOST_RESHOW_CARD, player="p1")
        assert "card.reshow" in self._types(god, player("p1"), events)
        assert "card.reshow" not in self._types(god, player("p2"), events)

    def test_other_public_events(self, god: Game) -> None:
        god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=False)
        events = god.act(HOST, Action.HOST_SET_ALIVE, player="p1", alive=True)
        assert views.filter_event(events[0], player("p2"), god.state)[0]["t"] == "revive"

    def test_narrator_set_public(self, game: Game) -> None:
        events = game.act("p2", Action.NARRATOR_TAKEOVER)
        assert views.filter_event(events[0], player("p3"), game.state) == [
            {"t": "roster.narrator", "player": "p2"}
        ]

    def test_bet_event_private(self, game: Game) -> None:
        game.to_wolf_step()
        game.night("p1")
        events = game.act("p1", Action.BET_SET, wolves=[], faceless=None)
        assert views.filter_event(events[0], player("p2"), game.state) == []
        assert views.filter_event(events[0], player("p1"), game.state)[0]["t"] == "me"

    def test_actor_done_goes_to_actor(self, game: Game) -> None:
        events = game.act("p1", Action.DEAL_ACK)
        done = next(e for e in events if e.type is EventType.ACTOR_DONE)
        assert views.filter_event(done, player("p1"), game.state)[0]["t"] == "me"

    def test_chat_event_filtered(self, game: Game) -> None:
        events = game.act("p4", Action.CHAT_SEND, channel=Channel.WOLF, kind="text", content="x")
        assert views.filter_event(events[0], player("p1"), game.state) == []
        assert views.filter_event(events[0], player("p5"), game.state)[0]["t"] == "chat.msg"


class TestLeakScanner:
    """掃描器本身要真的抓得到洩漏，否則保密測試形同虛設。"""

    def test_catches_role_token(self, game: Game) -> None:
        with pytest.raises(LeakFound):
            scan_for_leaks({"x": "seer"}, game.engine, player("p1"))

    def test_catches_poison_token(self, game: Game) -> None:
        with pytest.raises(LeakFound):
            scan_for_leaks({"cause": "poison"}, game.engine, player("p1"))

    def test_own_role_and_dead_public_role_allowed(self, game: Game) -> None:
        scan_for_leaks({"x": "villager"}, game.engine, player("p1"))
        game.act(ADMIN, Action.ADMIN_KICK, player="p2")
        scan_for_leaks({"x": "seer"}, game.engine, player("p1"))
        assert allowed_tokens(game.engine, HOST_VIEWER) is None

    def test_catches_real_author(self, game: Game) -> None:
        game.to_wolf_step()
        game.night(None)
        events = game.act(
            "p4", Action.CHAT_SEND, channel=Channel.PUBLIC, content="x", **{"as": "disguise"}
        )
        with pytest.raises(LeakFound):
            scan_disguise_leak(events[0], {"who": "p4"}, player("p1"), False)
        scan_disguise_leak(events[0], {"who": "p4"}, player("p4"), False)
        scan_disguise_leak(events[0], {"who": "p4"}, HOST_VIEWER, False)
        scan_disguise_leak(events[0], {"who": "p4"}, player("p1"), True)


def test_viewer_for_mode() -> None:
    assert views.viewer_for_mode(Mode.GOD, None, True) is HOST_VIEWER
    assert views.viewer_for_mode(Mode.AUTO, "p1", True) == player("p1")
    assert views.viewer_for_mode(Mode.AUTO, None, False) is OBSERVER_VIEWER


def test_night_plan_drops_dead_roles(game: Game) -> None:
    assert views.night_plan(game.state) == ["WOLF", "SEER", "WITCH"]
    game.act(ADMIN, Action.ADMIN_KICK, player="p2")
    assert views.night_plan(game.state) == ["WOLF", "WITCH"]


def test_public_history_excludes_causes(game: Game) -> None:
    game.to_wolf_step()
    game.night("p1")
    assert views.public_history(game.state)[0]["deaths"] == ["p1"]


_ = (Actor, GameState, Role)
