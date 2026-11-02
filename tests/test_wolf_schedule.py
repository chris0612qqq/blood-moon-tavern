"""狼人定時電子音與電子音訊息（SPEC v4.24）。"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from server import actions, protocol, views
from server.enums import Action, ChatKind, DeathCause, Step
from server.errors import GameError
from server.events import EventType
from server.room import next_clock_time
from server.views import HOST_VIEWER, Viewer, ViewerKind
from tests.test_engine import ADMIN, Game

WOLF = "p5"
OTHER_WOLF = "p4"
WALL = 1_000_000.0


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch) -> Game:
    return Game(monkeypatch)


def schedule(game: Game, slot: int = 0, due: float = WALL + 60, text: str = "嗷嗚") -> None:
    game.act(WOLF, Action.WOLF_SCHEDULE, slot=slot, due=due, text=text)


def tts_events(game: Game) -> list[dict[str, object]]:
    # 聊天內容不在狀態裡（CODING_RULES L23），從事件紀錄找
    return [
        e.data
        for e in game.engine.log
        if e.type is EventType.CHAT_SENT and e.data["kind"] == ChatKind.TTS.value
    ]


def sent(game: Game) -> list[object]:
    return [data["content"] for data in tts_events(game)]


def test_wolf_schedules_up_to_two_villager_cannot(game: Game) -> None:
    schedule(game, 0)
    schedule(game, 1, text="第二則")
    assert [s.slot for s in game.state.wolf_schedules[WOLF]] == [0, 1]
    schedule(game, 0, text="改過")  # 同一格覆蓋
    assert game.state.wolf_schedules[WOLF][0].text == "改過"
    with pytest.raises(GameError):
        schedule(game, 2)
    with pytest.raises(GameError):
        game.act("p1", Action.WOLF_SCHEDULE, slot=0, due=WALL, text="x")
    game.act(WOLF, Action.WOLF_UNSCHEDULE, slot=1)
    assert [s.slot for s in game.state.wolf_schedules[WOLF]] == [0]


def test_sent_in_daytime_as_anonymous_wolf_voice(game: Game) -> None:
    game.to_wolf_step()
    game.night(None)
    game.wait_for(Step.DAY_SPEAK)
    schedule(game, due=WALL + 60)
    game.engine.send_wolf_schedules(WALL + 59)
    assert sent(game) == []
    game.engine.send_wolf_schedules(WALL + 60)
    message = tts_events(game)[-1]
    assert message["is_wolf_mask"] and message["display"] is None and message["content"] == "嗷嗚"
    assert WOLF not in game.state.wolf_schedules


def test_waits_through_night_and_pause(game: Game) -> None:
    game.to_wolf_step()
    schedule(game, due=WALL)
    game.engine.send_wolf_schedules(WALL + 10)  # 晚上公共頻道不能發
    assert sent(game) == []
    game.night(None)
    game.wait_for(Step.DAY_SPEAK)
    game.act(ADMIN, Action.ADMIN_PAUSE)
    game.engine.send_wolf_schedules(WALL + 20)  # 暫停中也先不發
    assert sent(game) == []
    game.act(ADMIN, Action.ADMIN_RESUME)
    game.run(5)
    game.engine.send_wolf_schedules(WALL + 30)
    assert sent(game) == ["嗷嗚"]


def test_cancelled_when_wolf_dies(game: Game) -> None:
    schedule(game)
    actions.remove_player(game.engine, WOLF, DeathCause.MANUAL)
    game.engine.flush()
    assert WOLF not in game.state.wolf_schedules


def test_only_the_owner_sees_the_schedule(game: Game) -> None:
    schedule(game, text="秘密排程")
    mine = views.build(game.state, Viewer(ViewerKind.PLAYER, WOLF))["me"]["wolf_schedules"]
    assert mine[0]["text"] == "秘密排程"
    for viewer in (
        Viewer(ViewerKind.PLAYER, OTHER_WOLF),
        Viewer(ViewerKind.PLAYER, "p1"),
        HOST_VIEWER,
    ):
        assert "秘密排程" not in json.dumps(views.build(game.state, viewer), ensure_ascii=False)


def test_clock_time_is_the_next_one() -> None:
    noon = datetime(2026, 11, 29, 12, 0).timestamp()
    assert next_clock_time("12:30", noon) == datetime(2026, 11, 29, 12, 30).timestamp()
    assert next_clock_time("11:30", noon) == datetime(2026, 11, 30, 11, 30).timestamp()


@pytest.mark.parametrize("time", ["24:00", "9:30", "12:60", ""])
def test_bad_clock_time_rejected(time: str) -> None:
    with pytest.raises(GameError):
        protocol.parse_client(
            {"t": "wolf.schedule", "msg_id": "m1", "slot": 0, "time": time, "text": "x"}
        )


def test_voice_message_needs_text() -> None:
    frame = {"t": "chat.send", "msg_id": "m1", "channel": "public", "kind": "tts"}
    with pytest.raises(GameError):
        protocol.parse_client(frame)
    assert protocol.parse_client({**frame, "content": "大家好"}).kind is ChatKind.TTS  # type: ignore[attr-defined]
