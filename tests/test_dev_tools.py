"""開發工具（CODING_RULES D1、D4、S8）與主持人提示。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.enums import Step
from server.main import create_app
from tests.test_api import _OPEN, Env, Ws, admin_headers, open_room


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def dev_client(env: Env) -> Iterator[TestClient]:
    with TestClient(create_app(env.service, dev=True)) as client:
        yield client
        for ws in list(_OPEN):
            ws.close()


def test_S8_dev_routes_absent_in_production(env: Env) -> None:
    with TestClient(create_app(env.service, dev=False)) as client:
        assert client.get("/dev/state").status_code in (404, 405)
        assert client.get("/api/health").json()["dev"] is False


def test_bots_require_admin(dev_client: TestClient, env: Env) -> None:
    assert dev_client.post("/api/admin/bots?count=1").status_code == 401
    assert dev_client.get("/api/health").json()["dev"] is True


def test_production_admin_can_add_bots_in_lobby_only(env: Env) -> None:
    """正式店也能加機器人，但只有管理員、只在大廳（SPEC v4.23）。"""
    with TestClient(create_app(env.service, dev=False)) as client:
        open_room(env, client)
        headers = admin_headers(env, client)
        assert client.post("/api/admin/bots?count=0", headers=headers).status_code == 400
        assert len(client.post("/api/admin/bots?count=2", headers=headers).json()["added"]) == 2
        for ws in list(_OPEN):
            ws.close()


def test_admin_removes_bots_in_lobby_only(env: Env) -> None:
    """加多了可以移除：一個或全部；座位往前補；真人不能移除；開局後不行（SPEC v4.38）。"""
    with TestClient(create_app(env.service, dev=False)) as client:
        open_room(env, client)
        headers = admin_headers(env, client)
        assert client.delete("/api/admin/bots").status_code == 401
        bots = client.post("/api/admin/bots?count=6", headers=headers).json()["added"]
        humans = [r["id"] for r in env.service.roster_rows() if not r["is_bot"]]
        assert all(r["is_bot"] for r in env.service.roster_rows() if r["id"] in bots)
        # 移除第一個機器人：後面的人座位往前補，不留空位
        res = client.delete(f"/api/admin/bots?player={bots[0]}", headers=headers)
        assert res.json()["removed"] == [bots[0]]
        seats = sorted(r["seat"] for r in env.service.roster_rows() if not r["is_spectator"])
        assert seats == list(range(1, len(seats) + 1))
        # 真人、不存在的人都不能用這個移除
        for target in [*humans, "nobody"]:
            res = client.delete(f"/api/admin/bots?player={target}", headers=headers)
            assert res.status_code == 409, target
        # 全部移除：只剩真人；資料庫裡也刪掉，重開伺服器不會回來
        removed = client.delete("/api/admin/bots", headers=headers).json()["removed"]
        assert sorted(removed) == sorted(bots[1:])
        assert [r["id"] for r in env.service.roster_rows()] == humans
        left = env.service.db.rows("SELECT id FROM player WHERE device_id LIKE 'bot-%'")
        assert left == []
        # 開局後不能移除
        client.post("/api/admin/bots?count=6", headers=headers)
        admin = Ws(client, env.admin_token)
        admin.reply("admin.start")
        assert client.delete("/api/admin/bots", headers=headers).status_code == 403
        admin.close()
        for ws in list(_OPEN):
            ws.close()


def test_D1_bots_finish_a_game_alone(dev_client: TestClient, env: Env) -> None:
    open_room(env, dev_client)
    res = dev_client.post("/api/admin/bots?count=8", headers=admin_headers(env, dev_client))
    assert len(res.json()["added"]) == 8
    assert all(not row["offline"] for row in env.service.roster_rows())
    admin = Ws(dev_client, env.admin_token)
    assert admin.reply("admin.start")["t"] == "ack"
    for _ in range(40000):
        env.clock.advance(0.25)
        env.service.tick()
        if env.service.engine is not None and env.service.engine.state.step is Step.END:
            break
    assert env.service.engine is not None and env.service.engine.state.step is Step.END
    admin.close()


def test_D1_bots_respect_capacity_and_lobby(dev_client: TestClient, env: Env) -> None:
    open_room(env, dev_client)
    headers = admin_headers(env, dev_client)
    assert dev_client.post("/api/admin/bots?count=25", headers=headers).status_code == 400
    assert len(dev_client.post("/api/admin/bots?count=19", headers=headers).json()["added"]) == 19
    assert len(dev_client.post("/api/admin/bots?count=5", headers=headers).json()["added"]) == 1
    admin = Ws(dev_client, env.admin_token)
    admin.reply("admin.start")
    assert dev_client.post("/api/admin/bots?count=1", headers=headers).status_code == 403
    admin.close()


def test_D4_state_inspector(dev_client: TestClient, env: Env) -> None:
    assert dev_client.get("/dev/state").json()["state"] is None
    open_room(env, dev_client)
    headers = admin_headers(env, dev_client)
    dev_client.post("/api/admin/bots?count=6", headers=headers)
    admin = Ws(dev_client, env.admin_token)
    admin.reply("admin.start")
    body = dev_client.get("/dev/state").json()
    assert body["state"]["step"] == "DEAL" and body["events"]
    admin.close()


def test_host_gets_next_line_hint(dev_client: TestClient, env: Env) -> None:
    open_room(env, dev_client, "god")
    dev_client.post("/api/admin/bots?count=8", headers=admin_headers(env, dev_client))
    host = Ws(dev_client, env.admin_token)
    host.reply("admin.start")
    host.send("state.request")
    assert host.until("state")["host"]["next_line"] == "night_start"
    engine = env.service.engine
    assert engine is not None
    host.send("host.next", step_seq=engine.state.step_seq)
    assert host.until("host.progress")["next_line"] in ("wolf_open", "night_start")
    host.reply("admin.end")
    assert env.service._next_host_line() is None
    host.close()


def test_next_line_none_without_game(env: Env) -> None:
    assert env.service._next_host_line() is None
