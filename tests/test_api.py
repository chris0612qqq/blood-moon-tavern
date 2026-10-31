"""HTTP／WebSocket 整合與故障注入（DEV_PLAN P3、CODING_RULES T5、SPEC B10）。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import auth, config, media, presence, protocol
from server.clock import FakeClock, SystemClock
from server.db import Database, is_healthy, restore_latest_backup
from server.engine import Engine
from server.enums import Mode, PauseReason, Role, Step
from server.errors import ErrorCode, GameError
from server.main import build_default_service, create_app
from server.migrations import MIGRATIONS, SchemaTooNew, upgrade_event
from server.room import Paths, RoomService
from server.state import SCHEMA_VERSION

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF0000WEBP" + b"0" * 64
MP4 = b"0000ftypM4A " + b"0" * 64
WEBM = b"\x1aE\xdf\xa3" + b"0" * 64
OGG = b"OggS" + b"0" * 64
NAMES = [f"A{i}" for i in range(10)] + [f"B{i}" for i in range(10)] + ["C0", "C1", "C2"]


class Env:
    def __init__(self, tmp: Path, clock: Any = None, tick: float = 3600.0) -> None:
        self.tmp = tmp
        self.store = auth.AdminStore(tmp / "admin.json")
        self.store.save("boss", "password1")
        self.db = Database(tmp / "game.db")
        self.paths = Paths(tmp / "uploads", tmp / "backup", tmp / "logs", tmp / "assets")
        self.clock = clock or FakeClock()
        self.service = self.make_service(tick)
        self.app = create_app(self.service)
        self.admin_token = ""

    def make_service(self, tick: float = 3600.0) -> RoomService:
        return RoomService(
            self.db, self.store, clock=self.clock, paths=self.paths, tick_seconds=tick, strict=True
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def client(env: Env) -> Iterator[TestClient]:
    with TestClient(env.app) as test_client:
        try:
            yield test_client
        finally:
            # 測試中途失敗時，沒關的連線會讓 TestClient 收尾卡住
            for ws in list(_OPEN):
                with contextlib.suppress(Exception):
                    ws.close()


def admin_headers(env: Env, client: TestClient) -> dict[str, str]:
    if not env.admin_token:
        res = client.post("/api/admin/login", json={"username": "boss", "password": "password1"})
        assert res.status_code == 200
        env.admin_token = res.json()["token"]
    return {"Authorization": f"Bearer {env.admin_token}"}


def open_room(env: Env, client: TestClient, mode: str = "auto", **extra: Any) -> dict[str, Any]:
    res = client.post(
        "/api/admin/room",
        headers=admin_headers(env, client),
        json={"mode": mode, "name": "test", "password": "1234", **extra},
    )
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


def join(
    client: TestClient,
    name: str,
    device: str | None = None,
    password: str = "1234",
    pin: str = "1111",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return client.post(
        "/api/join",
        json={"password": password, "name": name, "pin": pin, "device_id": device or f"d-{name}"},
        headers=headers or {},
    )


def err(res: httpx.Response) -> str:
    value: str = res.json()["error"]
    return value


_OPEN: list[Ws] = []


class Ws:
    """同步的測試 WebSocket 客戶端。"""

    def __init__(self, client: TestClient, token: str) -> None:
        self.ctx = client.websocket_connect("/ws")
        self.ws = self.ctx.__enter__()
        _OPEN.append(self)
        self.ws.send_text(
            json.dumps({"t": "auth", "token": token, "client_version": config.PROTOCOL_VERSION})
        )
        self.state: dict[str, Any] = self.until("state")

    def until(self, kind: str, limit: int = 200) -> dict[str, Any]:
        for _ in range(limit):
            message: dict[str, Any] = json.loads(self.ws.receive_text())
            if message["t"] == kind:
                return message
        raise AssertionError(f"never saw {kind}")

    def send(self, msg_type: str, /, msg_id: str | None = None, **fields: Any) -> str:
        msg_id = msg_id or uuid.uuid4().hex
        self.ws.send_text(json.dumps({"t": msg_type, "msg_id": msg_id, **fields}))
        return msg_id

    def reply(self, msg_type: str, /, msg_id: str | None = None, **fields: Any) -> dict[str, Any]:
        """送出並等對應的 ack 或 error。"""
        wanted = self.send(msg_type, msg_id, **fields)
        for _ in range(500):
            message: dict[str, Any] = json.loads(self.ws.receive_text())
            if message["t"] in ("ack", "error") and message["msg_id"] == wanted:
                return message
        raise AssertionError("no reply")

    def close(self) -> None:
        if self in _OPEN:
            _OPEN.remove(self)
            self.ctx.__exit__(None, None, None)


def player_tokens(client: TestClient, count: int) -> list[tuple[str, str]]:
    out = []
    for name in NAMES[:count]:
        res = join(client, name)
        assert res.status_code == 200, res.text
        out.append((res.json()["token"], res.json()["player_id"]))
    return out


def start_game(env: Env, client: TestClient, mode: str = "auto", count: int = 8) -> Ws:
    open_room(env, client, mode)
    player_tokens(client, count)
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.start")["t"] == "ack"
    return admin


# ---- 健康檢查、管理員 ----


def test_health_no_room(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.json()["room"] is None and res.json()["protocol"] == config.PROTOCOL_VERSION
    assert res.headers["cache-control"] == "no-store"  # N19


def test_cors_preflight_cache(client: TestClient) -> None:
    res = client.options(
        "/api/health",
        headers={
            "Origin": "https://chris0612qqq.github.io",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers["access-control-max-age"] == "600"  # N20


def test_admin_login_and_lockout(env: Env, client: TestClient) -> None:
    body = {"username": "boss", "password": "wrong", "device_id": "x"}
    for _ in range(config.LOCK_MAX_FAILS):
        assert err(client.post("/api/admin/login", json=body)) == "wrong_password"
    res = client.post("/api/admin/login", json={**body, "password": "password1"})
    assert err(res) == "locked" and res.status_code == 423


def test_admin_endpoints_require_token(client: TestClient) -> None:
    assert client.get("/api/admin/room").status_code == 401
    assert (
        client.delete("/api/admin/room", headers={"Authorization": "Bearer x"}).status_code == 401
    )


def test_change_password(env: Env, client: TestClient) -> None:
    headers = admin_headers(env, client)
    bad = {"old_password": "nope", "new_password": "newpassword"}
    assert err(client.post("/api/admin/password", json=bad, headers=headers)) == "wrong_password"
    good = {"old_password": "password1", "new_password": "newpassword"}
    assert client.post("/api/admin/password", json=good, headers=headers).status_code == 200
    assert env.store.verify("boss", "newpassword")


def test_E7_missing_admin_file_refuses_start(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        auth.AdminStore(tmp_path / "none.json").load()
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError):
        auth.AdminStore(tmp_path / "bad.json").load()


def test_verify_secret_rejects_malformed() -> None:
    assert not auth.verify_secret("x", "not-a-hash")


def test_default_service_refuses_without_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.AdminStore, "load", lambda self: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        build_default_service()


# ---- 開房 ----


def test_open_room_only_one(env: Env, client: TestClient) -> None:
    open_room(env, client)
    res = client.post(
        "/api/admin/room", headers=admin_headers(env, client), json={"mode": "auto", "name": "x"}
    )
    assert res.status_code == 403
    assert client.get("/api/health").json()["room"]["state"] == "lobby"


def test_generated_room_password_is_4_digits(env: Env, client: TestClient) -> None:
    res = client.post(
        "/api/admin/room", headers=admin_headers(env, client), json={"mode": "god", "name": "x"}
    )
    assert len(res.json()["password"]) == config.ROOM_PASSWORD_DIGITS


def test_admin_can_reread_password(env: Env, client: TestClient) -> None:
    open_room(env, client)
    room = client.get("/api/admin/room", headers=admin_headers(env, client)).json()
    assert room["password"] == "1234"


def test_settings_clamped_and_unknown_rejected(env: Env, client: TestClient) -> None:
    room = open_room(env, client, settings={"vote": 5, "speak": 999})
    assert room["settings"] == {"vote": 10, "speak": 300}
    client.delete("/api/admin/room", headers=admin_headers(env, client))
    res = client.post(
        "/api/admin/room",
        headers=admin_headers(env, client),
        json={"mode": "auto", "name": "x", "settings": {"nope": 1}},
    )
    assert err(res) == "bad_request"


def test_no_room_errors(client: TestClient) -> None:
    assert err(join(client, "AB")) == "no_room"
    res = client.post("/api/rejoin", json={"name": "AB", "pin": "1111", "device_id": "d"})
    assert err(res) == "no_room"


# ---- 加入 ----


@pytest.mark.parametrize("name", ["小美", "AJ", "a1", "ＡＢ", " 小美 ", "小​美"])
def test_L21_valid_names(env: Env, client: TestClient, name: str) -> None:
    open_room(env, client)
    assert join(client, name).status_code == 200


@pytest.mark.parametrize("name", ["小", "小美人", "😀😀", "A B", "éa", "小!", "ㄒㄧ"])
def test_L21_invalid_names(env: Env, client: TestClient, name: str) -> None:
    open_room(env, client)
    assert err(join(client, name)) == "name_invalid"


def test_name_taken_and_device_taken(env: Env, client: TestClient) -> None:
    open_room(env, client)
    assert join(client, "AA").status_code == 200
    assert err(join(client, "AA", device="other")) == "name_taken"
    assert join(client, "BB", device="d-AA").status_code == 403


def test_wrong_password_locks_by_device_only(env: Env, client: TestClient) -> None:
    open_room(env, client)
    for _ in range(config.LOCK_MAX_FAILS):
        assert err(join(client, "AA", password="9999")) == "wrong_password"
    assert err(join(client, "AA")) == "locked"
    assert join(client, "BB").status_code == 200  # N13 同 IP 其他人不受影響


def test_ip_limit_is_loose() -> None:
    locks = auth.Lockouts()
    for i in range(config.IP_MAX_FAILS_PER_MINUTE):
        locks.check(f"d{i}", "n", "ip", 0.0)
        locks.fail(f"d{i}", "n", "ip", 0.0)
    with pytest.raises(GameError):
        locks.check("new", "n", "ip", 1.0)
    locks.fail("d", "n", "other", 0.0)
    locks.fail("d", "n", "other", 100.0)


def test_L9_room_capacity(env: Env, client: TestClient) -> None:
    open_room(env, client)
    player_tokens(client, 20)
    assert err(join(client, "ZZ")) == "room_full"


def test_bad_pin_format(env: Env, client: TestClient) -> None:
    open_room(env, client)
    assert err(join(client, "AA", pin="12")) == "bad_request"


def test_late_joiner_is_spectator(env: Env, client: TestClient) -> None:
    start_game(env, client).close()
    res = join(client, "ZZ")
    assert res.json()["is_spectator"] is True
    late = Ws(client, res.json()["token"])
    assert late.state["phase"] == "game" and "me" not in late.state
    assert late.reply("chat.send", channel="public", content="hi")["code"] == "forbidden"
    late.close()


def test_rejoin_replaces_old_device(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    old = Ws(client, token)
    bad = client.post("/api/rejoin", json={"name": "AA", "pin": "9999", "device_id": "n"})
    assert err(bad) == "wrong_pin"
    assert (
        err(client.post("/api/rejoin", json={"name": "ZZ", "pin": "1111", "device_id": "n"}))
        == "wrong_pin"
    )
    res = client.post("/api/rejoin", json={"name": "AA", "pin": "1111", "device_id": "n"})
    assert res.status_code == 200
    assert old.until("replaced")["t"] == "replaced"
    old.close()
    new = Ws(client, res.json()["token"])
    assert new.state["me"]["id"] == res.json()["player_id"]
    new.close()


def test_auto_admin_player_keeps_admin_on_rejoin(env: Env, client: TestClient) -> None:
    open_room(env, client)
    res = join(client, "AA", headers=admin_headers(env, client))
    assert (
        client.get("/api/admin/room", headers=admin_headers(env, client)).json()["admin_player_id"]
        == res.json()["player_id"]
    )
    again = client.post("/api/rejoin", json={"name": "AA", "pin": "1111", "device_id": "n"})
    ws = Ws(client, again.json()["token"])
    assert ws.state["is_admin"] is True
    ws.close()


def test_reset_pin(env: Env, client: TestClient) -> None:
    open_room(env, client)
    player = join(client, "AA").json()["player_id"]
    admin = Ws(client, admin_headers(env, client)["Authorization"][7:])
    assert admin.reply("admin.reset_pin", player=player)["t"] == "ack"
    assert admin.reply("admin.reset_pin", player="nope")["code"] == "invalid_target"
    admin.close()
    res = client.post("/api/rejoin", json={"name": "AA", "pin": "4321", "device_id": "n"})
    assert res.status_code == 200
    res = client.post("/api/rejoin", json={"name": "AA", "pin": "1111", "device_id": "n"})
    assert err(res) == "wrong_pin"
    res = client.post("/api/rejoin", json={"name": "AA", "pin": "4321", "device_id": "n"})
    assert res.status_code == 200


# ---- WebSocket ----


def test_ws_unauthorized_and_version(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps({"t": "auth", "token": "x", "client_version": config.PROTOCOL_VERSION})
        )
        assert json.loads(ws.receive_text())["code"] == "unauthorized"
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"t": "auth", "token": "x", "client_version": 999}))
        assert json.loads(ws.receive_text())["code"] == "version_mismatch"  # M7
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_ws_origin_rejected(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", headers={"origin": "https://evil.example"}),
    ):
        pass
    with client.websocket_connect(
        "/ws", headers={"origin": "https://chris0612qqq.github.io"}
    ) as ws:
        ws.send_text(
            json.dumps({"t": "auth", "token": "x", "client_version": config.PROTOCOL_VERSION})
        )
        ws.receive_text()


def test_E1_E3_bad_messages_keep_connection(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    assert ws.reply("no.such", msg_id="m1")["code"] == "bad_request"
    assert ws.reply("wolf.pick", msg_id="m2", extra_field=1)["code"] == "bad_request"
    ws.ws.send_text("garbage")
    assert ws.until("error")["code"] == "bad_request"
    ws.ws.send_text("x" * (config.WS_MAX_MESSAGE_BYTES + 1))
    assert ws.until("error")["code"] == "bad_request"
    assert ws.reply("ping")["t"] == "ack"
    ws.close()


def test_E3_unexpected_exception_keeps_connection(
    env: Env, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    monkeypatch.setattr(env.service, "_prep", lambda *_: 1 / 0)
    assert ws.reply("prep.report")["code"] == "internal_error"
    assert ws.reply("ping")["t"] == "ack"
    ws.close()


def test_T5_L3_duplicate_message_runs_once(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    assert ws.reply("chat.send", msg_id="same", channel="public", content="hi")["t"] == "ack"
    assert ws.reply("chat.send", msg_id="same", channel="public", content="hi")["t"] == "ack"
    assert len(env.service.chat) == 1
    ws.close()


def test_msg_id_memory_is_bounded(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    ws = Ws(client, token)
    for i in range(config.MSG_ID_MEMORY + 5):
        ws.reply("ping", msg_id=f"m{i}")
    session = env.service.session_for(token)
    assert session is not None and len(session.recent) == config.MSG_ID_MEMORY
    ws.close()


def test_T5_stale_step(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    assert admin.reply("deal.ack", step_seq=-1)["code"] == "stale_step"
    admin.close()


def test_chat_rate_limit_by_player(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    for _ in range(config.CHAT_PER_SECOND):
        assert ws.reply("chat.send", channel="public", content="x")["t"] == "ack"
    assert ws.reply("chat.send", channel="public", content="x")["code"] == "rate_limited"
    env.clock.advance(1.1)
    assert ws.reply("chat.send", channel="public", content="x")["t"] == "ack"
    ws.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"channel": "public", "content": "   "},
        {"channel": "public", "content": "​"},
        {"channel": "public", "content": "x" * (config.CHAT_MAX_CHARS + 1)},
        {"channel": "public", "kind": "photo"},
        {"channel": "public", "kind": "photo", "media_id": "m", "content": "x"},
        {"channel": "public", "content": "x", "media_id": "m"},
    ],
)
def test_chat_validation(env: Env, client: TestClient, fields: dict[str, Any]) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    assert ws.reply("chat.send", **fields)["code"] == "bad_request"
    ws.close()


def test_lobby_chat_and_history(env: Env, client: TestClient) -> None:
    open_room(env, client)
    a = Ws(client, join(client, "AA").json()["token"])
    b = Ws(client, join(client, "BB").json()["token"])
    a.send("chat.send", channel="public", content="哈囉")
    got = b.until("chat.msg")
    assert got["content"] == "哈囉" and "mine" not in got and "real_author" not in got
    assert a.until("chat.msg")["mine"] is True
    assert a.reply("chat.send", channel="wolf", content="x")["code"] == "forbidden"
    b.send("chat.history", channel="public", before_id=999)
    page = b.until("chat.history")
    assert [m["content"] for m in page["messages"]] == ["哈囉"]
    late = Ws(client, join(client, "CC").json()["token"])
    assert late.state["chat"][0]["content"] == "哈囉"
    for ws in (a, b, late):
        ws.close()


def test_chat_goes_through_views_in_game(env: Env, client: TestClient) -> None:
    open_room(env, client)
    tokens = player_tokens(client, 8)
    admin = Ws(client, env.admin_token)
    admin.reply("admin.start")
    engine = env.service.engine
    assert engine is not None
    wolf_id = next(p.id for p in engine.state.players if p.role is Role.WOLF)
    good_id = next(p.id for p in engine.state.players if p.role is Role.VILLAGER)
    by_id = {pid: token for token, pid in tokens}
    wolf = Ws(client, by_id[wolf_id])
    good = Ws(client, by_id[good_id])
    assert wolf.reply("chat.send", channel="wolf", content="秘密")["t"] == "ack"
    assert good.reply("chat.send", channel="wolf", content="x")["code"] == "forbidden"
    good.send("chat.history", channel="wolf", before_id=999)
    assert good.until("chat.history")["messages"] == []
    for ws in (wolf, good, admin):
        ws.close()


def test_T4_state_over_wire_has_no_secret_roles(env: Env, client: TestClient) -> None:
    open_room(env, client)
    tokens = player_tokens(client, 8)
    admin = Ws(client, env.admin_token)
    admin.reply("admin.start")
    engine = env.service.engine
    assert engine is not None
    villager = next(p.id for p in engine.state.players if p.role is Role.VILLAGER)
    token = dict((pid, tok) for tok, pid in tokens)[villager]
    ws = Ws(client, token)
    text = json.dumps(ws.state)
    for secret in ('"faceless"', '"seer"', '"witch"', '"hunter"', '"wolf"'):
        assert secret not in text
    assert ws.state["me"]["role"] == "villager"
    assert "password" not in text
    ws.close()
    admin.close()


# ---- 大廳 ----


def test_seat_change_and_validation(env: Env, client: TestClient) -> None:
    open_room(env, client)
    tokens = player_tokens(client, 3)
    ids = [pid for _, pid in tokens]
    ws = Ws(client, tokens[0][0])
    assert ws.reply("admin.seat", order=ids)["code"] == "forbidden"
    ws.close()
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.seat", order=ids[:2])["code"] == "invalid_target"
    assert admin.reply("admin.seat", order=[ids[0], ids[0], ids[1]])["code"] == "invalid_target"
    assert admin.reply("admin.seat", order=ids[::-1])["t"] == "ack"
    assert env.service.players[ids[0]].seat == 3
    admin.close()


def test_kick_in_lobby_bans_device(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token, pid = player_tokens(client, 1)[0]
    victim = Ws(client, token)
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.kick", player="nope")["code"] == "invalid_target"
    assert admin.reply("admin.kick", player=pid)["t"] == "ack"
    assert victim.until("kicked")["t"] == "kicked"
    victim.close()
    admin.close()
    assert err(join(client, "XX", device=f"d-{NAMES[0]}")) == "banned"
    res = client.post(
        "/api/rejoin", json={"name": NAMES[0], "pin": "1111", "device_id": f"d-{NAMES[0]}"}
    )
    assert err(res) == "banned"


def test_kick_in_game_kills_and_bans(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    engine = env.service.engine
    assert engine is not None
    target = engine.state.players[0].id
    assert admin.reply("admin.kick", player=target)["t"] == "ack"
    assert not engine.state.player(target).alive
    # 已死的人再踢一次只補封鎖，不會壞
    assert admin.reply("admin.kick", player=target)["t"] == "ack"
    admin.close()


def test_kick_spectator_removes(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    res = join(client, "ZZ")
    assert admin.reply("admin.kick", player=res.json()["player_id"])["t"] == "ack"
    assert res.json()["player_id"] not in env.service.players
    admin.close()


def test_start_needs_six(env: Env, client: TestClient) -> None:
    open_room(env, client)
    player_tokens(client, 5)
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.start")["code"] == "forbidden"
    join(client, "ZZ")
    assert admin.reply("admin.start")["t"] == "ack"
    assert admin.reply("admin.start")["code"] == "forbidden"
    admin.close()


def test_auto_room_always_has_a_narrator(env: Env, client: TestClient) -> None:
    # 管理員沒加入就開始（舊流程的破口）：也要有人當旁白主機，不能整局沒聲音
    open_room(env, client)
    tokens = player_tokens(client, 6)
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.start")["t"] == "ack"
    engine = env.service.engine
    assert engine is not None and engine.state.narrator_id == tokens[0][1]
    admin.close()


def test_only_admin_starts(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, player_tokens(client, 6)[0][0])
    assert ws.reply("admin.start")["code"] == "forbidden"
    ws.close()


def test_engine_action_before_start_forbidden(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    assert ws.reply("deal.ack")["code"] == "forbidden"
    ws.close()


def test_prep_report_updates_roster(env: Env, client: TestClient) -> None:
    open_room(env, client)
    ws = Ws(client, join(client, "AA").json()["token"])
    ws.send("prep.report", audio=True, wakelock=True, pwa=False)
    roster = ws.until("roster")
    for _ in range(5):
        if roster["players"][0]["prep"].get("audio"):
            break
        roster = ws.until("roster")
    assert roster["players"][0]["prep"]["audio"] is True
    ws.close()


def test_host_prep_report_ignored(env: Env, client: TestClient) -> None:
    open_room(env, client, "god")
    admin = Ws(client, env.admin_token)
    assert admin.reply("prep.report")["t"] == "ack"
    admin.close()


def test_lobby_narrator(env: Env, client: TestClient) -> None:
    open_room(env, client)
    pid = join(client, "AA").json()["player_id"]
    admin = Ws(client, env.admin_token)
    assert admin.reply("admin.narrator", player="nope")["code"] == "invalid_target"
    assert admin.reply("admin.narrator", player=pid)["t"] == "ack"
    room = env.service.room
    assert room is not None and room.narrator_id == pid
    admin.close()


# ---- 媒體 ----


@pytest.mark.parametrize(
    ("kind", "data", "mime"),
    [
        (media.MediaKind.PHOTO, JPEG, "image/jpeg"),
        (media.MediaKind.PHOTO, PNG, "image/png"),
        (media.MediaKind.AVATAR, WEBP, "image/webp"),
        (media.MediaKind.VOICE, MP4, "audio/mp4"),
        (media.MediaKind.VOICE, WEBM, "audio/webm"),
        (media.MediaKind.VOICE, OGG, "audio/ogg"),
    ],
)
def test_sniff_mime(kind: media.MediaKind, data: bytes, mime: str) -> None:
    assert media.sniff_mime(data[:16], kind) == mime


def _upload(client: TestClient, token: str, data: bytes, kind: str = "photo") -> httpx.Response:
    return client.post(
        f"/api/media?kind={kind}", content=data, headers={"Authorization": f"Bearer {token}"}
    )


def test_E8_invalid_upload_leaves_no_file(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    assert err(_upload(client, token, b"not an image")) == "file_invalid"
    assert err(_upload(client, token, b"not audio", "voice")) == "file_invalid"
    assert list(env.paths.uploads.iterdir()) == []


def test_upload_requires_login_and_limits(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    assert client.post("/api/media?kind=photo", content=JPEG).status_code == 401
    assert (
        err(_upload(client, token, MP4[:4] + b"0" * config.VOICE_MAX_BYTES, "voice"))
        == "file_too_large"
    )


def test_E5_low_disk_and_room_quota(tmp_path: Path) -> None:
    with pytest.raises(GameError) as low:
        media.save_upload(JPEG, media.MediaKind.PHOTO, 0, tmp_path, min_free=10**18)
    assert low.value.code is ErrorCode.STORAGE_FULL
    with pytest.raises(GameError) as quota:
        media.save_upload(JPEG, media.MediaKind.PHOTO, config.ROOM_UPLOAD_MAX_BYTES, tmp_path)
    assert quota.value.code is ErrorCode.STORAGE_FULL


def test_media_signed_url_range_and_expiry(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    res = _upload(client, token, JPEG)
    url = res.json()["url"]
    assert client.get(url).content == JPEG
    ranged = client.get(url, headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206 and ranged.content == JPEG[:4]  # P7 iOS 需要
    assert client.get(url.replace("sig=", "sig=0")).status_code == 403
    media_id = res.json()["id"]
    assert client.get(f"/api/media/{media_id}?exp=1&sig=x").status_code == 403
    assert client.get("/api/media/none?exp=1&sig=x").status_code == 403
    ws = Ws(client, token)
    ws.send("media.refresh", media_id=media_id)
    assert ws.until("media.url")["media_id"] == media_id
    assert ws.reply("media.refresh", media_id="none")["code"] == "invalid_target"
    ws.close()


def test_signer_expiry() -> None:
    signer = media.Signer(b"k" * 32)
    query = signer.query("media/x", 1000.0)
    exp = int(query.split("&")[0][4:])
    sig = query.split("sig=")[1]
    assert signer.verify("media/x", exp, sig, 1000.0)
    assert not signer.verify("media/x", exp, sig, exp + 1.0)
    assert not signer.verify("media/y", exp, sig, 1000.0)


def test_avatar_updates_roster(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    assert _upload(client, token, WEBP, "avatar").status_code == 200
    rows = env.service.roster_rows()
    assert rows[0]["avatar_url"].startswith("/api/media/")


def test_chat_with_photo_carries_signed_url(env: Env, client: TestClient) -> None:
    open_room(env, client)
    token = join(client, "AA").json()["token"]
    media_id = _upload(client, token, JPEG).json()["id"]
    ws = Ws(client, token)
    assert ws.reply("chat.send", channel="public", kind="photo", media_id="nope")["code"] == (
        "invalid_target"
    )
    ws.send("chat.send", channel="public", kind="photo", media_id=media_id)
    assert "sig=" in ws.until("chat.msg")["media_url"]
    env.clock.advance(2)
    ws.reply("state.request")
    ws.close()


def test_assets_listing_and_traversal(env: Env, client: TestClient) -> None:
    roles = env.paths.assets / "roles"
    roles.mkdir(parents=True)
    (roles / "wolf.png").write_bytes(PNG)
    (env.paths.assets / "secret.txt").write_text("x")
    assets = client.get("/api/assets").json()["assets"]
    assert set(assets) == {"roles/wolf.png"}
    assert client.get(assets["roles/wolf.png"]).content == PNG
    assert client.get("/api/asset/roles/wolf.png?exp=9999999999&sig=x").status_code == 403
    signer = env.service.signer
    resource = "asset/../secret.txt"
    query = signer.query(resource, time.time())
    assert client.get(f"/api/asset/%2E%2E/secret.txt?{query}").status_code == 403


# ---- 關房 ----


def test_close_room_deletes_everything_but_history(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    room = env.service.room
    assert room is not None
    token = next(iter(env.service.sessions))
    assert token
    env.paths.uploads.mkdir(exist_ok=True)
    (env.paths.uploads / "file").write_bytes(b"x")
    env.paths.backups.mkdir(exist_ok=True)
    (env.paths.backups / "1.db").write_bytes(b"x")
    env.paths.logs.mkdir(exist_ok=True)
    (env.paths.logs / f"{room.id}.log").write_text("x")
    res = client.delete("/api/admin/room", headers=admin_headers(env, client))
    assert res.status_code == 200
    assert admin.until("room.closed")["t"] == "room.closed"
    admin.close()
    assert env.service.room is None and env.service.engine is None
    for table in ("room", "player", "session", "game", "chat_message", "media", "event_log"):
        assert env.db.rows(f"SELECT COUNT(*) AS c FROM {table}")[0]["c"] == 0
    # 遊戲中關房仍記錄輪替（SPEC A4）
    assert env.db.rows("SELECT COUNT(*) AS c FROM role_history")[0]["c"] == 8
    assert not env.paths.uploads.exists() and not env.paths.backups.exists()
    assert not (env.paths.logs / f"{room.id}.log").exists()


def test_close_without_room(env: Env, client: TestClient) -> None:
    assert err(client.delete("/api/admin/room", headers=admin_headers(env, client))) == "no_room"


def test_reopen_same_settings(env: Env, client: TestClient) -> None:
    open_room(env, client, settings={"vote": 20})
    join(client, "AA")
    res = client.post("/api/admin/room/reopen", headers=admin_headers(env, client))
    assert res.json()["settings"] == {"vote": 20}
    assert env.service.players == {}


def test_end_schedules_close_after_10_minutes(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    assert admin.reply("admin.end")["t"] == "ack"
    room = env.service.room
    assert room is not None and room.state == "ended" and room.closes_at is not None
    assert admin.state is not None
    env.clock.advance(config.ROOM_END_SECONDS + 1)
    env.app.state.service.tick()
    assert env.service.room is None
    admin.close()


def test_S7_room_log_has_no_secrets(env: Env, client: TestClient) -> None:
    admin = start_game(env, client)
    room = env.service.room
    assert room is not None
    assert admin.reply("admin.end")["t"] == "ack"
    text = (env.paths.logs / f"{room.id}.log").read_text(encoding="utf-8")
    assert "game ended" in text
    for secret in ("faceless", "seer", "witch", "hunter", "1234"):
        assert secret not in text
    admin.close()


def test_P11_chat_does_not_grow_engine_log(env: Env, client: TestClient) -> None:
    admin = start_game(env, client, "god")
    engine = env.service.engine
    assert engine is not None
    before = len(engine.log)
    for _ in range(5):
        env.clock.advance(1.1)
        admin.reply("chat.send", channel="public", content="x")
    assert len(engine.log) == before
    assert env.db.rows("SELECT COUNT(*) AS c FROM event_log WHERE type='chat_sent'")[0]["c"] == 5
    admin.close()


def test_tick_without_room_is_noop(env: Env, client: TestClient) -> None:
    env.service.tick()


# ---- 輪替 ----


def test_role_history_rotation_and_expiry(env: Env) -> None:
    db = env.db
    now = 1_000_000.0
    db.write(db.role_history_statements([("d1", "AA", Role.WITCH)], now - 100))
    db.write(db.role_history_statements([("d1", "AA", Role.WOLF)], now - 50))
    db.write(db.role_history_statements([("d1", "AA", Role.SEER)], now))
    record = db.load_role_history([("p", "d1", "AA")], now)["p"]
    assert record.last is Role.SEER and record.before is Role.WOLF
    # 裝置不見時以名字備援（SPEC A5.7）
    assert db.load_role_history([("p", "new", "AA")], now)["p"].last is Role.SEER
    assert db.load_role_history([("p", "new", "ZZ")], now) == {}
    later = now + 3 * 86400
    assert db.load_role_history([("p", "d1", "AA")], later) == {}
    db.write(db.role_history_statements([], later))
    assert db.rows("SELECT COUNT(*) AS c FROM role_history")[0]["c"] == 0


def test_start_uses_history(env: Env, client: TestClient) -> None:
    env.db.write(env.db.role_history_statements([("d-A0", "A0", Role.WITCH)], time.time()))
    start_game(env, client).close()
    # 8 人各一筆，加上 A0 上一局的紀錄（每人保留 2 局）
    assert env.db.rows("SELECT COUNT(*) AS c FROM role_history")[0]["c"] == 9


# ---- 故障注入（T5） ----


def _break_writes(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(env.db, "write", fail)


def test_T5_E4_write_failure_reverts_memory(
    env: Env, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = start_game(env, client)
    engine = env.service.engine
    assert engine is not None
    target = engine.state.players[0]
    with monkeypatch.context() as patch:
        _break_writes(env, patch)
        reply = admin.reply("admin.kick", player=target.id)
    assert reply["code"] == "internal_error"
    assert env.service.engine is not None
    assert env.service.engine.state.player(target.id).alive
    admin.close()


def test_T5_three_write_failures_system_pause(
    env: Env, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = start_game(env, client)
    engine = env.service.engine
    assert engine is not None
    with monkeypatch.context() as patch:
        _break_writes(env, patch)
        for _ in range(config.DB_FAILS_BEFORE_PAUSE):
            assert admin.reply("admin.end")["code"] == "internal_error"
    pause = env.service.engine
    assert pause is not None and pause.state.pause is not None
    assert pause.state.pause.reason is PauseReason.SYSTEM
    admin.close()


def test_E5_busy_retry_then_success(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    monkeypatch.setattr(config, "SQLITE_BUSY_DELAYS", (0.0, 0.0, 0.0))
    assert env.db._with_retry(flaky) == "ok"
    with pytest.raises(sqlite3.OperationalError):
        env.db._with_retry(lambda: (_ for _ in ()).throw(sqlite3.OperationalError("other")))


def test_write_rolls_back_whole_transaction(env: Env) -> None:
    with pytest.raises(sqlite3.Error):
        env.db.write(
            [
                ("INSERT INTO banned_device(room_id, device_id) VALUES(?,?)", ("r", "d")),
                ("INSERT INTO no_such_table VALUES(?)", (1,)),
            ]
        )
    assert env.db.rows("SELECT COUNT(*) AS c FROM banned_device")[0]["c"] == 0


def test_T5_restart_restores_game_and_sessions(env: Env) -> None:
    with TestClient(env.app) as client:
        open_room(env, client)
        tokens = player_tokens(client, 8)
        admin = Ws(client, env.admin_token)
        admin.reply("admin.start")
        ws = Ws(client, tokens[0][0])
        assert ws.reply("deal.ack", step_seq=ws.state["step_seq"])["t"] == "ack"
        ws.reply("chat.send", channel="public", content="重啟前")
        step_seq = env.service.engine.state.step_seq  # type: ignore[union-attr]
        roles = {p.id: p.role for p in env.service.engine.state.players}  # type: ignore[union-attr]
        ws.close()
        admin.close()
    service = env.make_service()
    with TestClient(create_app(service)) as client:
        engine = service.engine
        assert engine is not None
        assert engine.state.pause is not None and engine.state.pause.reason is PauseReason.SYSTEM
        assert {p.id: p.role for p in engine.state.players} == roles
        assert engine.state.step_seq == step_seq
        assert engine.state.player(tokens[0][1]).acked
        ws = Ws(client, tokens[0][0])  # 舊 token 還能用
        assert ws.state["paused"]["reason"] == "system"
        assert any(m["content"] == "重啟前" for m in ws.state["chat"])
        # 無管理員模式管理員手機不在時，任何裝置登入管理員選單可按繼續（SPEC A11）
        env.admin_token = ""
        admin = Ws(client, admin_headers(env, client)["Authorization"][7:])
        assert admin.reply("admin.resume")["t"] == "ack"
        assert "me" not in admin.state  # 只能操作，看不到秘密
        admin.close()
        ws.close()


def test_masked_chat_survives_restart_and_stays_secret(env: Env) -> None:
    with TestClient(env.app) as client:
        open_room(env, client)
        tokens = dict((pid, token) for token, pid in player_tokens(client, 8))
        admin = Ws(client, env.admin_token)
        admin.reply("admin.start")
        engine = env.service.engine
        assert engine is not None
        wolf = next(p.id for p in engine.state.players if p.role is Role.WOLF)
        good = next(p.id for p in engine.state.players if p.role is Role.VILLAGER)
        engine.state.step = Step.DAY_SPEAK  # 直接放到白天，只測聊天
        ws = Ws(client, tokens[wolf])
        assert ws.reply("chat.send", channel="public", content="嗷", **{"as": "wolf"})["t"] == "ack"
        ws.close()
        admin.close()
    service = env.make_service()
    with TestClient(create_app(service)) as client:
        assert service.disguised_chat[0]["is_wolf_mask"] is True
        viewer = Ws(client, tokens[good])
        msg = next(m for m in viewer.state["chat"] if m["content"] == "嗷")
        assert msg["is_wolf_mask"] is True and msg["display_player_id"] is None
        assert wolf not in json.dumps(msg)
        viewer.close()


def test_old_database_gets_mask_column(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    # v4.8 的欄位（沒有 is_wolf_mask）
    old.execute(
        "CREATE TABLE chat_message(id INTEGER PRIMARY KEY, room_id TEXT NOT NULL, "
        "channel TEXT NOT NULL, real_author_id TEXT, is_last_words INTEGER NOT NULL, "
        "display_player_id TEXT, is_host INTEGER NOT NULL, disguise_period_id INTEGER, "
        "kind TEXT NOT NULL, content TEXT, media_id TEXT, ts REAL NOT NULL)"
    )
    old.commit()
    old.close()
    db = Database(path)
    columns = {row["name"] for row in db.rows("PRAGMA table_info(chat_message)")}
    assert "is_wolf_mask" in columns


def test_restart_lobby_room(env: Env) -> None:
    with TestClient(env.app) as client:
        open_room(env, client)
        token = join(client, "AA").json()["token"]
        media_id = _upload(client, token, JPEG).json()["id"]
    service = env.make_service()
    with TestClient(create_app(service)) as client:
        assert service.room is not None and service.engine is None
        assert media_id in service.media_rows
        assert client.get("/api/health").json()["room"]["state"] == "lobby"


def test_restart_ended_room_reschedules_close(env: Env) -> None:
    with TestClient(env.app) as client:
        admin = start_game(env, client)
        admin.reply("admin.end")
        admin.close()
    service = env.make_service()
    with TestClient(create_app(service)):
        assert service.room is not None and service.room.closes_at is not None


def test_G4_unknown_schema_refuses_restore(env: Env) -> None:
    with TestClient(env.app) as client:
        start_game(env, client).close()
    env.db.conn.execute(
        "UPDATE event_log SET payload_json = json_set(payload_json, '$.schema_version', 999)"
    )
    service = env.make_service()
    with TestClient(create_app(service)):
        assert service.room is not None and service.room.unrestorable and service.engine is None
        service.tick()


def test_migrations_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    assert upgrade_event({"schema_version": SCHEMA_VERSION})["schema_version"] == SCHEMA_VERSION
    with pytest.raises(SchemaTooNew):
        upgrade_event({"schema_version": 0})
    with pytest.raises(SchemaTooNew):
        upgrade_event({"schema_version": SCHEMA_VERSION + 1})
    monkeypatch.setitem(MIGRATIONS, 0, lambda raw: {**raw, "seen": True})
    assert upgrade_event({"schema_version": 0})["seen"] is True


def test_god_rollback_works_after_restart(env: Env) -> None:
    with TestClient(env.app) as client:
        admin = start_game(env, client, "god")
        engine = env.service.engine
        assert engine is not None
        admin.reply("host.next", step_seq=engine.state.step_seq)
        admin.close()
    service = env.make_service()
    with TestClient(create_app(service)):
        assert service.engine is not None
        assert len(service.engine._history) >= 2


def test_E5_corrupt_db_restored_from_backup(tmp_path: Path) -> None:
    db = Database(tmp_path / "game.db")
    db.write([("INSERT INTO banned_device(room_id, device_id) VALUES(?,?)", ("r", "d"))])
    backups = tmp_path / "backup"
    db.backup_to(backups / "1.db")
    (backups / "0.db").write_bytes(b"garbage" * 1000)
    db.close()
    (tmp_path / "game.db").write_bytes(b"garbage" * 1000)
    assert not is_healthy(tmp_path / "game.db")
    assert restore_latest_backup(tmp_path / "game.db", backups)
    assert Database(tmp_path / "game.db").rows("SELECT * FROM banned_device")
    assert not restore_latest_backup(tmp_path / "x.db", tmp_path / "none")


def test_backup_rotation(env: Env, client: TestClient) -> None:
    open_room(env, client)
    for _ in range(config.BACKUP_KEEP + 3):
        env.service._backup_now()
        time.sleep(0.002)
    assert len(list(env.paths.backups.glob("*.db"))) == config.BACKUP_KEEP
    backups = sorted(env.paths.backups.glob("*.db"))
    assert is_healthy(backups[-1])


def test_pause_requests_backup(env: Env, client: TestClient) -> None:
    admin = start_game(env, client, "god")
    assert admin.reply("admin.pause")["t"] == "ack"
    task = env.service.backup_task
    assert task is not None
    deadline = time.time() + 5
    while not task.done() and time.time() < deadline:
        time.sleep(0.01)
    assert list(env.paths.backups.glob("*.db"))
    admin.close()


# ---- 斷線暫停（SPEC A11、B5） ----


def test_presence_monitor_logic() -> None:
    monitor = presence.PresenceMonitor()
    act = presence.PresenceAction
    assert monitor.check(0, 10, 0.0, False) is act.NONE
    assert monitor.check(5, 10, 1.0, False) is act.NONE
    assert monitor.check(5, 10, 10.9, False) is act.NONE
    assert monitor.check(5, 10, 11.0, False) is act.PAUSE
    assert monitor.check(5, 10, 12.0, True) is act.NONE
    assert monitor.check(4, 10, 13.0, True) is act.NONE
    assert monitor.check(4, 10, 22.9, True) is act.NONE
    assert monitor.check(4, 10, 23.0, True) is act.RESUME
    assert monitor.check(0, 0, 24.0, False) is act.NONE


def test_presence_pause_and_auto_resume_end_to_end(env: Env, client: TestClient) -> None:
    open_room(env, client)
    tokens = player_tokens(client, 8)
    admin = Ws(client, env.admin_token)
    admin.reply("admin.start")
    sockets = [Ws(client, token) for token, _ in tokens]
    engine = env.service.engine
    assert engine is not None
    for ws in sockets[:4]:
        ws.close()

    def advance(seconds: float) -> None:
        end = env.clock.now() + seconds
        while env.clock.now() < end:
            env.clock.advance(1)
            for ws in sockets[4:]:
                ws.send("ping")
            admin.send("ping")
            env.service.tick()

    advance(config.PRESENCE_HOLD_SECONDS + config.PRESENCE_CHECK_SECONDS + 2)
    assert engine.state.pause is not None
    assert engine.state.pause.reason is PauseReason.PRESENCE
    back = [Ws(client, token) for token, _ in tokens[:2]]
    advance(1)
    for ws in back:
        ws.send("ping")
    advance(config.PRESENCE_HOLD_SECONDS + config.PRESENCE_CHECK_SECONDS + 2)
    pause = env.service.engine.state.pause  # type: ignore[union-attr]
    assert pause is None or pause.resume_at is not None
    for ws in [*sockets[4:], *back, admin]:
        ws.close()


def test_host_offline_pauses_after_grace(env: Env, client: TestClient) -> None:
    open_room(env, client, "god")
    tokens = player_tokens(client, 8)
    admin = Ws(client, env.admin_token)
    admin.reply("admin.start")
    sockets = [Ws(client, token) for token, _ in tokens]
    engine = env.service.engine
    assert engine is not None
    admin.close()
    for _ in range(config.HOST_OFFLINE_GRACE_SECONDS + 6):
        env.clock.advance(1)
        for ws in sockets:
            ws.send("ping")
        time.sleep(0.002)
        env.service.tick()
    assert engine.state.pause is not None
    assert engine.state.pause.reason is PauseReason.HOST_OFFLINE
    env.admin_token = ""
    host = Ws(client, admin_headers(env, client)["Authorization"][7:])  # 另一支手機接手
    assert "host" in host.state
    assert host.reply("admin.resume")["t"] == "ack"
    for _ in range(3):
        env.clock.advance(1)
        host.send("ping")
        env.service.tick()
    assert env.service.host_gone_since is None or engine.state.pause is not None
    host.close()
    for ws in sockets:
        ws.close()


def test_N8_full_send_queue_drops_connection() -> None:
    async def scenario() -> bool:
        from server.hub import Connection, Session
        from server.views import OBSERVER_VIEWER

        class Slow:
            async def send_text(self, data: str) -> None:
                await asyncio.sleep(100)

            async def close(self, code: int = 1000) -> None:
                return None

        conn = Connection(Slow(), Session("t", None, False, "d"), OBSERVER_VIEWER, 0.0)
        for i in range(config.SEND_QUEUE_LIMIT + 2):
            conn.send({"t": "x", "i": i}, 0.0)
        return conn.closed

    assert asyncio.run(scenario())


def test_N8_send_timeout_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SEND_TIMEOUT_SECONDS", 0.01)

    async def scenario() -> bool:
        from server.hub import Connection, Session
        from server.views import OBSERVER_VIEWER

        class Stuck:
            async def send_text(self, data: str) -> None:
                await asyncio.sleep(100)

            async def close(self, code: int = 1000) -> None:
                raise OSError

        conn = Connection(Stuck(), Session("t", None, False, "d"), OBSERVER_VIEWER, 0.0)
        conn.start()
        conn.send({"t": "x"}, 0.0)
        assert conn.sender is not None
        await asyncio.wait_for(conn.sender, 1)
        conn.close()
        conn.send({"t": "x"}, 0.0)
        return conn.closed

    assert asyncio.run(scenario())


def test_state_fits_message_limit() -> None:
    big = {"t": "state", "chat": [{"x": "字" * 2000} for _ in range(100)]}
    fitted = RoomService._fit(big)
    assert len(json.dumps(fitted, ensure_ascii=False)) <= config.WS_MAX_MESSAGE_BYTES


def test_generated_protocol_is_current() -> None:
    from scripts.gen_protocol import TARGET, render

    assert TARGET.read_text(encoding="utf-8") == render()  # R5


def test_clean_text() -> None:
    assert protocol.clean_text(" ​小\x07美﻿ ") == "小美"
    assert protocol.clean_text("a\nb") == "a\nb"


# ---- 完整一局：20 個真實 WebSocket 客戶端（DEV_PLAN P3 通關） ----


class LiveServer:
    def __init__(self, service: RoomService) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        config_ = uvicorn.Config(
            create_app(service), host="127.0.0.1", port=self.port, log_level="warning"
        )
        self.server = uvicorn.Server(config_)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> LiveServer:
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(10)


class Bot:
    """只用協定跟伺服器互動的玩家。"""

    def __init__(self, url: str, token: str, is_host: bool = False) -> None:
        self.url = url
        self.token = token
        self.is_host = is_host
        self.view: dict[str, Any] = {}
        self.ws: Any = None
        self.ended = False
        self.leaks: list[str] = []
        self.last_seq = 0
        self.gaps = 0
        self.errors: list[str] = []

    async def send(self, kind: str, **fields: Any) -> None:
        seq = self.view.get("step_seq")
        await self.ws.send(
            json.dumps({"t": kind, "msg_id": uuid.uuid4().hex, "step_seq": seq, **fields})
        )

    async def run(self) -> None:
        async with websockets.connect(self.url, max_size=2**20) as ws:
            self.ws = ws
            await ws.send(
                json.dumps(
                    {"t": "auth", "token": self.token, "client_version": config.PROTOCOL_VERSION}
                )
            )
            poller = asyncio.create_task(self._poll())
            try:
                async for text in ws:
                    await self._on(json.loads(text))
                    if self.ended:
                        return
            finally:
                poller.cancel()

    async def _poll(self) -> None:
        while True:
            # 只當保險：真正的觸發是 _on 收到變動訊息時
            await asyncio.sleep(0.25)
            await self.send("state.request")

    async def _on(self, message: dict[str, Any]) -> None:
        seq = message.get("seq", 0)
        if seq != self.last_seq + 1:
            self.gaps += 1  # N5：每條連線的 seq 必須連續
        self.last_seq = seq
        if message["t"] == "error" and message["code"] == "internal_error":
            self.errors.append(json.dumps(message))
        if message["t"] in ("step", "timers", "wolf.picks", "paused"):
            await self.send("state.request")
        if message["t"] != "state":
            return
        self.view = message
        if message.get("step") == Step.END.value:
            self.ended = True
            return
        if message.get("phase") == "game" and not self.is_host:
            self._check_secret(message)
            await self._act(message)

    def _check_secret(self, view: dict[str, Any]) -> None:
        me = view.get("me") or {}
        text = json.dumps({k: v for k, v in view.items() if k != "me"})
        if '"faceless"' in text or '"real_author"' in text:
            self.leaks.append(text[:200])
        if me.get("role") != Role.FACELESS.value and "disguise_info" in me:
            self.leaks.append("disguise")

    async def _act(self, view: dict[str, Any]) -> None:
        me = view.get("me")
        if not me or not me["is_actor"] or view.get("paused"):
            return
        step = view["step"]
        targets = me.get("eligible_targets") or []
        first = targets[0] if targets else None
        if me["done"] and step != Step.SEER.value:
            return
        if step == Step.DEAL.value:
            await self.send("deal.ack")
        elif step == Step.WOLF.value:
            if me["id"] not in me["wolf_pack"].get("picks", {}):
                await self.send("wolf.pick", target=first)
        elif step == Step.SEER.value:
            if me["seer_info"]["checks"] and (
                me["seer_info"]["checks"][-1]["round_no"] == view["round_no"]
            ):
                await self.send("seer.ok")
            elif first:
                await self.send("seer.check", target=first)
        elif step == Step.WITCH.value:
            await self.send("witch.act")
        elif step == Step.HUNTER.value:
            await self.send("hunter.shoot", target=first)
        elif step in (Step.DAY_SPEAK.value, Step.LAST_WORDS.value):
            await self.send("speak.end")
        elif step == Step.VOTE.value:
            await self.send("vote.cast", target=first)


async def _host_loop(host: Bot, service: RoomService) -> None:
    while not host.ended:
        await asyncio.sleep(0.02)
        engine = service.engine
        if engine is None or host.ws is None or engine.state.step is Step.END:
            continue
        if engine.state.pause is None and engine.is_step_complete(engine.now):
            next_step = engine.next_step()
            if not engine.policy.should_advance(next_step):
                with contextlib.suppress(websockets.ConnectionClosed):
                    await host.ws.send(
                        json.dumps(
                            {
                                "t": "host.next",
                                "msg_id": uuid.uuid4().hex,
                                "step_seq": engine.state.step_seq,
                            }
                        )
                    )


@pytest.mark.parametrize("mode", [Mode.AUTO, Mode.GOD])
def test_P3_twenty_clients_play_a_full_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: Mode
) -> None:
    # 時間加速 20 倍；這裡只驗流程，斷線判斷另有測試
    monkeypatch.setattr(config, "OFFLINE_AFTER_SECONDS", 10**9)
    env = Env(tmp_path, clock=SystemClock(20.0), tick=0.02)
    env.service.strict = True
    with LiveServer(env.service) as live:
        base = f"http://127.0.0.1:{live.port}"
        url = f"ws://127.0.0.1:{live.port}/ws"
        with httpx.Client(base_url=base, timeout=30) as http:
            res = http.post("/api/admin/login", json={"username": "boss", "password": "password1"})
            admin_token = res.json()["token"]
            headers = {"Authorization": f"Bearer {admin_token}"}
            body = {"mode": mode.value, "name": "e2e", "password": "1234"}
            assert http.post("/api/admin/room", json=body, headers=headers).status_code == 200
            tokens = []
            for name in NAMES[:20]:
                payload = {"password": "1234", "name": name, "pin": "1111", "device_id": name}
                tokens.append(http.post("/api/join", json=payload).json()["token"])

            async def main() -> list[Bot]:
                bots = [Bot(url, token) for token in tokens]
                admin = Bot(url, admin_token, is_host=True)
                tasks = [asyncio.create_task(b.run()) for b in [*bots, admin]]
                await asyncio.sleep(0.3)
                await admin.ws.send(json.dumps({"t": "admin.start", "msg_id": "start"}))
                if mode is Mode.GOD:
                    tasks.append(asyncio.create_task(_host_loop(admin, env.service)))
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=300)
                return [*bots, admin]

            bots = asyncio.run(main())
    engine = env.service.engine
    assert engine is not None and engine.state.step is Step.END
    assert all(b.ended for b in bots)
    assert [b.leaks for b in bots if b.leaks] == []
    assert [b.errors for b in bots if b.errors] == []
    assert sum(b.gaps for b in bots) == 0


_ = Engine
