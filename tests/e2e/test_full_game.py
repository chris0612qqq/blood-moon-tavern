"""真實瀏覽器跑完整局（DEV_PLAN P4、UI_RULES UT1）。手機尺寸，每位玩家一個獨立分頁環境。

所有操作都透過畫面上的按鈕；每一輪比對畫面與 store，並確認沒有前端錯誤。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest
from playwright.sync_api import Page, sync_playwright

from server.auth import AdminStore

ROOT = Path(__file__).resolve().parent.parent.parent
MOBILE = {"width": 390, "height": 780}
PLAYERS = 12
GAME_TIMEOUT_SECONDS = 600

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def server_url() -> Iterator[str]:
    port = _free_port()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        admin_file = Path(tmp) / "admin.json"
        AdminStore(admin_file).save("boss", "password1")
        env = {
            **os.environ,
            "BMT_DATA_DIR": tmp,
            "BMT_ADMIN_FILE": str(admin_file),
            "DEV_MODE": "1",
            "TIME_SCALE": "6",
        }
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server.main:app",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
        )
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{url}/api/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        try:
            yield url
        finally:
            for child in psutil.Process(proc.pid).children(recursive=True):
                child.terminate()
            proc.terminate()
            proc.wait(10)


def has(page: Page, testid: str) -> bool:
    return page.locator(f'[data-testid="{testid}"]').count() > 0


def tap(page: Page, testid: str) -> bool:
    """點一下；不存在或被停用就回 False。畫面隨時會變，所以不等待。"""
    locator = page.locator(f'[data-testid="{testid}"]').first
    try:
        if locator.count() == 0 or locator.is_disabled():
            return False
        locator.click(timeout=800)
    except Exception:
        return False
    return True


def press(page: Page, testid: str) -> None:
    """等到按鈕可按再點：表單填完要等下一次重繪才會解除停用。"""
    page.locator(f'[data-testid="{testid}"]').first.click(timeout=8000)


def fill(page: Page, testid: str, value: str) -> None:
    page.locator(f'[data-testid="{testid}"]').fill(value)


def wait(page: Page, testid: str, timeout: int = 15000) -> None:
    page.locator(f'[data-testid="{testid}"]').first.wait_for(timeout=timeout)


def store(page: Page, expression: str) -> Any:
    return page.evaluate(f"(() => {{ const s = window.__bmt; return {expression}; }})()")


def page_text_lacks(page: Page, text: str) -> bool:
    return text not in page.locator("#app").inner_text()


def admin_open_room(page: Page, mode: str) -> str:
    wait(page, "btn-admin-key")
    press(page, "btn-admin-key")
    wait(page, "input-admin_user")
    fill(page, "input-admin_user", "boss")
    fill(page, "input-admin_pass", "password1")
    press(page, "btn-admin-login")
    wait(page, f"mode-{mode}")
    press(page, f"mode-{mode}")
    fill(page, "input-room_name", "試玩")
    fill(page, "input-room_password", "1234")
    press(page, "btn-open-room")
    wait(page, "screen-s3")
    return "1234"


def join_form(page: Page, name: str, password: str | None) -> None:
    wait(page, "input-join_name")
    if password is not None:
        fill(page, "input-join_password", password)
    fill(page, "input-join_name", name)
    fill(page, "input-join_pin", "1111")
    fill(page, "input-join_pin2", "1111")
    press(page, "btn-join")
    wait(page, "my-seat")


def act(page: Page) -> None:
    """依這支手機目前畫面做一件合理的事。只看畫面元素，不看 store 裡的秘密。"""
    for testid in (
        "dialog-confirm",
        "btn-seen",
        "btn-seer-ok",
        "btn-witch-next",
        "btn-witch-nosave",
        "btn-witch-nopoison",
        "btn-witch-done",
        "btn-speak-end",
        "btn-last-words-end",
    ):
        if tap(page, testid):
            return
    screen = page.evaluate("document.documentElement.dataset.screen")
    me = store(page, "s.server && s.server.me && s.server.me.id")
    if screen in ("S8", "S9", "S12", "S14"):
        cells = page.locator('[data-testid^="pick-cell-"]')
        if cells.count() == 0:
            return
        if screen == "S8" and store(page, f"'{me}' in (s.server.me.wolf_pack.picks || {{}})"):
            return
        cells.first.click(timeout=800)
        for testid in ("btn-seer-check", "btn-hunter-shoot", "btn-vote"):
            if tap(page, testid):
                return


def check_screen_matches_store(page: Page) -> None:
    """UT1：畫面數值與 store 一致。"""
    # 等重繪後在同一影格內讀 store 與畫面；分兩次讀，中間來的新訊息會造成假警報（UI_RULES U3）
    result = page.evaluate(
        """() => new Promise((resolve) => setTimeout(() => {
          const s = window.__bmt;
          const read = (id) => document.querySelector(`[data-testid="${id}"]`)?.innerText ?? null;
          const version = s.version;
          requestAnimationFrame(() => requestAnimationFrame(() => resolve({
            stable: version === s.version,
            progress: s.server?.progress ?? null,
            voteText: read('vote-progress'),
            conn: s.conn,
            connText: read('conn-light'),
          })));
        }, 0))"""
    )
    if not result["stable"]:
        return
    progress = result["progress"] or {}
    if result["voteText"] and progress.get("total"):
        assert f"{progress['done']}/{progress['total']}" in result["voteText"]
    if result["connText"] and result["conn"] == "online":
        assert result["connText"] == "連線正常"


def play_until_end(pages: list[Page], host: Page | None) -> None:
    deadline = time.time() + GAME_TIMEOUT_SECONDS
    while time.time() < deadline:
        if all(store(p, "s.server && s.server.step") == "END" for p in pages[:1]):
            return
        for page in pages:
            page.wait_for_timeout(10)
            act(page)
            check_screen_matches_store(page)
        if host is not None:
            for testid in ("dialog-confirm",):
                tap(host, testid)
            if store(host, "s.server && s.server.host && s.server.host.next_line"):
                done = store(
                    host, "s.server.host.actors.every(a => s.server.host.done.includes(a))"
                )
                timed = store(host, "s.server.host.timed_out")
                if done or timed:
                    tap(host, "btn-host-next")
    state = store(pages[0], "s.server && [s.server.step, s.server.paused, s.server.round_no]")
    raise AssertionError(f"game did not end in time: {state}")


def run_game(server_url: str, mode: str) -> None:
    errors: list[str] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()

        def new_page() -> Page:
            context = browser.new_context(viewport=MOBILE, has_touch=True)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(server_url)
            return page

        admin = new_page()
        password = admin_open_room(admin, mode)
        pages: list[Page] = []
        host: Page | None = None
        if mode == "god":
            press(admin, "btn-to-control")
            wait(admin, "screen-s20")
            host = admin
        else:
            press(admin, "btn-to-join")
            join_form(admin, "管理", None)
            pages.append(admin)
        humans = 5 if mode == "god" else 4
        for i in range(humans):
            page = new_page()
            join_form(page, f"玩{i}", password)
            pages.append(page)
        # 其他位置用機器人補滿到 12 人
        # 實際操作時抓到的畫面問題，留作回歸測試
        assert page_text_lacks(admin, "你已出局")
        tap(admin, "btn-add-bots")
        admin.wait_for_timeout(500)
        while store(admin, "s.server.roster.filter(r => !r.is_spectator).length") < PLAYERS:
            tap(admin, "btn-add-bots")
            admin.wait_for_timeout(300)
        press(admin, "btn-start")
        wait(admin, "dialog-confirm")
        assert "12 人" in admin.locator('[data-testid="dialog-text"]').inner_text()
        press(admin, "dialog-confirm")
        for page in pages:
            page.wait_for_function(
                "document.documentElement.dataset.screen === 'S6'", timeout=10000
            )
        # 角色卡：放開時秘密不在 DOM（CODING_RULES V19）
        first = pages[0]
        assert not has(first, "role-name")
        assert not has(first, "disguise-panel")  # 千面狼的對象也不能露在卡片外
        box = first.locator('[data-testid="role-card"]').bounding_box()
        assert box is not None
        first.mouse.move(box["x"] + 20, box["y"] + 20)
        first.mouse.down()
        wait(first, "role-name")
        first.mouse.up()
        first.wait_for_function("!document.querySelector('[data-testid=\"role-name\"]')")

        play_until_end(pages, host)
        for page in pages:
            wait(page, "screen-s18", timeout=20000)
            assert page.locator('[data-testid^="end-role-"]').count() == PLAYERS
            # 手動試玩時發現的缺漏：死因結算才公開，且結算不再顯示「你已出局」
            assert page.locator('[data-testid^="end-cause-"]').count() > 0
            assert page_text_lacks(page, "你已出局")
        browser.close()
    assert errors == []


def test_auto_mode_full_game(server_url: str) -> None:
    run_game(server_url, "auto")


def test_god_mode_full_game(server_url: str) -> None:
    run_game(server_url, "god")


def test_join_form_rules(server_url: str) -> None:
    """UT3 灰盒版：名字、PIN 的基本防呆。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "input-join_name")
        fill(page, "input-join_password", "1234")
        fill(page, "input-join_name", "太長名字")
        fill(page, "input-join_pin", "1111")
        fill(page, "input-join_pin2", "2222")
        page.wait_for_timeout(200)
        assert page.locator('[data-testid="btn-join"]').is_disabled()
        fill(page, "input-join_pin2", "1111")
        page.wait_for_timeout(200)
        press(page, "btn-join")
        wait(page, "error-join")
        assert "2 個字" in page.locator('[data-testid="error-join"]').inner_text()
        browser.close()
