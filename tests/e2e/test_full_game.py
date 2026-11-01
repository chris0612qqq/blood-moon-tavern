"""真實瀏覽器跑完整局（DEV_PLAN P4、UI_RULES UT1）。手機尺寸，每位玩家一個獨立分頁環境。

所有操作都透過畫面上的按鈕；每一輪比對畫面與 store，並確認沒有前端錯誤。
"""

from __future__ import annotations

import contextlib
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
from playwright.sync_api import Error as PlaywrightError
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


@contextlib.contextmanager
def running_server(time_scale: int) -> Iterator[str]:
    port = _free_port()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        admin_file = Path(tmp) / "admin.json"
        AdminStore(admin_file).save("boss", "password1")
        env = {
            **os.environ,
            "BMT_DATA_DIR": tmp,
            "BMT_ADMIN_FILE": str(admin_file),
            "DEV_MODE": "1",
            "TIME_SCALE": str(time_scale),
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


@pytest.fixture
def server_url() -> Iterator[str]:
    with running_server(6) as url:
        yield url


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
        try:
            cells.first.click(timeout=800)
        except PlaywrightError:
            return  # 按的瞬間換步驟，格子被移除；下一輪再看畫面
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

        if host:  # 整局都開著簡報牆，真實資料有問題時下面的 errors 會抓到
            press(host, "host-tab-status")
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


# 無頭瀏覽器沒有語音引擎：換成記錄呼叫的假物件，驗證「該念的時候有叫它念」
FAKE_SPEECH_JS = """
window.__spoken = [];
Object.defineProperty(window, 'speechSynthesis', { value: {
  speaking: false, pending: false,
  getVoices: () => [],
  resume() {},
  cancel() {},
  addEventListener() {},
  speak(u) {
    window.__spoken.push({ text: u.text, rate: u.rate, volume: u.volume });
    if (u.onstart) u.onstart();
  },
} });
"""


def test_narrator_speaks_on_host_phone_after_first_tap(server_url: str) -> None:
    """試玩回饋：iPhone 上點語音沒聲音。第一次點擊要解鎖，之後伺服器叫念才念得出來。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        context.add_init_script(FAKE_SPEECH_JS)
        host = context.new_page()
        host.goto(server_url)
        spoken = lambda: host.evaluate("window.__spoken")  # noqa: E731
        admin_open_room(host, "god")
        # 第一次點擊就解鎖：無聲（音量 0），不必等使用者找到測試鈕
        first = spoken()[0]
        assert first["volume"] == 0
        # 測試聲音在進房前，進房後就不再出現
        press(host, "btn-sound-test")
        host.wait_for_function("window.__spoken.some((s) => s.volume === 1)")
        press(host, "btn-to-control")
        wait(host, "screen-s20")
        assert not has(host, "btn-sound-test")
        press(host, "btn-add-bots")
        host.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(host, "btn-start")
        press(host, "dialog-confirm")
        wait(host, "btn-host-next")
        host.wait_for_function("window.__bmt.server.host.next_line === 'night_start'")
        press(host, "btn-host-next")
        host.wait_for_timeout(250)
        if has(host, "dialog-confirm"):
            press(host, "dialog-confirm")
        host.wait_for_function("window.__spoken.some((s) => s.text === '天黑請閉眼')")
        said = next(s for s in spoken() if s["text"] == "天黑請閉眼")
        assert said["rate"] == pytest.approx(0.45) and said["volume"] == 1
        browser.close()


def _spoken(url: str, line: str) -> int:
    events = httpx.get(f"{url}/dev/state").json()["events"]
    return sum(e["type"] == "narrate" and e["data"]["line_id"] == line for e in events)


def test_host_voice_menu_repeats_and_never_jumps(server_url: str) -> None:
    """試玩回饋：主持人可重複催促；按完閉眼要等主持人按才換下一個角色。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        host = browser.new_context(viewport=MOBILE).new_page()
        host.goto(server_url)
        admin_open_room(host, "god")
        press(host, "btn-to-control")
        wait(host, "screen-s20")
        press(host, "btn-add-bots")
        host.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(host, "btn-start")
        press(host, "dialog-confirm")
        wait(host, "btn-host-next")
        step = lambda: store(host, "s.server.step")  # noqa: E731

        def next_line(expected: str) -> None:
            host.wait_for_function("(n) => window.__bmt.server.host.next_line === n", arg=expected)
            press(host, "btn-host-next")
            host.wait_for_timeout(250)  # 確認框要等下一次重繪才出現
            if has(host, "dialog-confirm"):
                press(host, "dialog-confirm")

        next_line("night_start")
        host.wait_for_function("window.__bmt.server.step === 'NIGHT_START'")
        next_line("wolf_open")
        host.wait_for_function("window.__bmt.server.step === 'WOLF'")
        host.wait_for_timeout(1500)
        before = _spoken(server_url, "wolf_open")
        press(host, "line-current")  # 催狼人
        host.wait_for_timeout(1400)
        press(host, "line-current")
        host.wait_for_timeout(300)
        assert _spoken(server_url, "wolf_open") == before + 2 and step() == "WOLF"

        host.wait_for_function(
            "(() => { const h = window.__bmt.server.host;"
            " return h.timed_out || h.nights.at(-1).wolf_decided; })()"
        )
        next_line("wolf_close")
        host.wait_for_function("window.__bmt.server.step === 'WOLF_END'")
        host.wait_for_timeout(4000)  # 不會自己跳走
        assert step() == "WOLF_END"
        assert page_text_lacks(host, "已逾時")  # 閉眼步驟沒有倒數
        before = _spoken(server_url, "wolf_close")
        press(host, "line-current")
        host.wait_for_timeout(300)
        assert _spoken(server_url, "wolf_close") == before + 1 and step() == "WOLF_END"
        folder = os.environ.get("BMT_SHOTS")
        if folder:
            host.screenshot(path=f"{folder}/host_voice_tab.png")
        # 三個側邊標籤一點就切；常用按鈕切到哪都在（試玩回饋）
        press(host, "host-tab-status")
        wait(host, "host-view-status")
        assert has(host, "btn-host-next") and has(host, "line-current")
        assert not has(host, "line-wolf_open")
        if folder:
            host.screenshot(path=f"{folder}/host_status_tab.png")
        press(host, "host-tab-reveal")
        wait(host, "host-view-reveal")
        assert has(host, "btn-host-next") and has(host, "host-deaths")
        if folder:
            host.screenshot(path=f"{folder}/host_reveal_tab.png")
        press(host, "host-tab-voice")
        wait(host, "line-wolf_open")
        label = host.locator('[data-testid="btn-host-next"]').inner_text()
        assert "預言家請睜眼" in label or "女巫請睜眼" in label
        browser.close()


def test_join_form_rules(server_url: str) -> None:
    """UT3 灰盒版：名字、PIN 的基本防呆；PIN 只打一次（試玩回饋）。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "input-join_name")
        assert not has(page, "input-join_pin2")
        fill(page, "input-join_password", "1234")
        fill(page, "input-join_name", "太長名字")
        assert page.locator('[data-testid="input-join_name"]').input_value() == "太長"  # 多的不收
        fill(page, "input-join_pin", "11")
        page.wait_for_timeout(200)
        assert page.locator('[data-testid="btn-join"]').is_disabled()  # PIN 不足 4 碼
        fill(page, "input-join_pin", "1111")
        press(page, "btn-join")
        wait(page, "my-seat")
        browser.close()


def test_room_name_optional_and_copy_without_clipboard_api(server_url: str) -> None:
    """試玩回饋：房名不用填；iPhone 連 http 沒有剪貼簿 API，複製邀請文字仍要能用。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        # 模擬非 HTTPS：localhost 在瀏覽器眼中算安全環境，所以手動拿掉 API
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'clipboard', { value: undefined });
            window.__copied = [];
            const original = document.execCommand.bind(document);
            document.execCommand = (name) => {
              window.__copied.push(document.activeElement.value);
              return name === 'copy' ? true : original(name);
            };
            """
        )
        page = context.new_page()
        page.goto(server_url)
        wait(page, "btn-admin-key")
        press(page, "btn-admin-key")
        fill(page, "input-admin_user", "boss")
        fill(page, "input-admin_pass", "password1")
        press(page, "btn-admin-login")
        wait(page, "btn-open-room")
        press(page, "mode-god")
        press(page, "btn-open-room")  # 什麼都沒填也能開房
        wait(page, "screen-s3")
        press(page, "btn-copy-invite")
        wait(page, "toast")
        assert page.locator('[data-testid="toast"]').inner_text() == "已複製"
        copied = page.evaluate("window.__copied")
        password = page.locator('[data-testid="room-password"]').inner_text()
        assert f"#pw={password}" in copied[0]
        health = httpx.get(f"{server_url}/api/health").json()
        assert health["room"]["name"] == "血月酒館"

        # 兩種方法都失敗時要說清楚，不能沒反應
        page.evaluate("document.execCommand = () => false")
        page.wait_for_timeout(3200)  # 等上一則 toast 消失
        press(page, "btn-copy-invite")
        page.wait_for_function(
            "document.querySelector('[data-testid=\"toast\"]')?.innerText.includes('手動複製')"
        )
        browser.close()
