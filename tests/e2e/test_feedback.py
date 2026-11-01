"""異常回饋（UI_RULES UT4、3.2 表）：出事時畫面一定說得出發生什麼，按鈕也一定會解鎖。

F7 暫停在 test_roles、F9 上傳失敗要等 P6 有上傳才測。
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Browser, Page, Route, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    admin_open_room,
    join_form,
    press,
    server_url,  # noqa: F401
    wait,
)

pytestmark = pytest.mark.e2e
BUTTON_LIMIT_S = 8.5  # UI_RULES K2：8 秒必解鎖，多留一點給畫面重繪

# 記下連線、可以弄斷；_answer 設了就不送伺服器，直接回假的錯誤
WS_TOOLS = """
const RealSocket = window.WebSocket;
window.__sockets = [];
window.WebSocket = function (url) {
  const ws = new RealSocket(window.__blockSockets ? 'ws://127.0.0.1:9/' : url);
  window.__sockets.push(ws);
  return ws;
};
Object.assign(window.WebSocket, RealSocket);
window.WebSocket.prototype = RealSocket.prototype;
const realSend = RealSocket.prototype.send;
RealSocket.prototype.send = function (raw) {
  const msg = JSON.parse(raw);
  if (window.__swallow === msg.t) return;
  if (window.__answer && window.__answer.t === msg.t) {
    const reply = { t: 'error', msg_id: msg.msg_id, code: window.__answer.code };
    setTimeout(() => this.onmessage({ data: JSON.stringify(reply) }));
    return;
  }
  realSend.call(this, raw);
};
"""


def lobby_page(browser: Browser, url: str) -> Page:
    """管理員加入大廳、人數湊滿，「開始」就是一顆可以按的送出鈕。"""
    page = browser.new_context(viewport=MOBILE).new_page()
    page.add_init_script(WS_TOOLS)
    page.goto(url)
    admin_open_room(page, "auto")
    press(page, "btn-to-join")
    join_form(page, "管理", None)
    press(page, "btn-add-bots")
    page.wait_for_function("window.__bmt.server.roster.length >= 6")
    return page


def press_start(page: Page) -> None:
    press(page, "btn-start")
    press(page, "dialog-confirm")


def button_text(page: Page) -> str:
    return page.locator('[data-testid="btn-start"]').inner_text()


@pytest.fixture
def browser() -> object:
    with sync_playwright() as driver:
        launched = driver.chromium.launch()
        yield launched
        launched.close()


def test_f4_no_reply_unlocks_within_eight_seconds(browser: Browser, server_url: str) -> None:  # noqa: F811
    page = lobby_page(browser, server_url)
    page.evaluate("window.__swallow = 'admin.start'")
    started = time.monotonic()
    press_start(page)
    page.wait_for_function(
        "document.querySelector('[data-testid=\"btn-start\"]').textContent.includes('沒有回應')",
        timeout=int(BUTTON_LIMIT_S * 1000),
    )
    assert time.monotonic() - started < BUTTON_LIMIT_S + 1
    page.wait_for_function(
        "!document.querySelector('[data-testid=\"btn-start\"]').disabled"
        " && document.querySelector('[data-testid=\"btn-start\"]').textContent.includes('開始')"
    )


@pytest.mark.parametrize(
    ("code", "text"),
    [
        ("internal_error", "發生問題"),
        ("invalid_target", "不能選這個人"),
        ("rate_limited", "慢一點"),
    ],
)
def test_f5_f6_server_error_shows_reason_then_unlocks(
    browser: Browser,
    server_url: str,  # noqa: F811
    code: str,
    text: str,
) -> None:
    page = lobby_page(browser, server_url)
    page.evaluate("(code) => { window.__answer = { t: 'admin.start', code }; }", code)
    press_start(page)
    page.wait_for_function(
        "(text) => document.querySelector('[data-testid=\"btn-start\"]')"
        ".textContent.includes(text)",
        arg=text,
    )
    page.wait_for_function("!document.querySelector('[data-testid=\"btn-start\"]').disabled")


def test_f1_f2_reconnect_banner_then_offline_then_recovers(
    browser: Browser,
    server_url: str,  # noqa: F811
) -> None:
    page = lobby_page(browser, server_url)
    page.evaluate("window.__blockSockets = true; window.__sockets.at(-1).close()")
    wait(page, "conn-banner")
    assert "重新連線中" in page.locator('[data-testid="conn-banner"]').inner_text()
    # 斷線時按鈕要停用並寫原因，畫面內容留著
    page.wait_for_function("document.querySelector('[data-testid=\"btn-start\"]').disabled")
    assert "連線中" in page.locator("#app").inner_text()
    assert page.locator('[data-testid="my-seat"]').count() == 1
    # 重試多次後轉成紅色的「連不上」，說明可能原因
    page.wait_for_function(
        "document.querySelector('[data-testid=\"conn-banner\"]').textContent.includes('連不上')",
        timeout=70000,
    )
    # 網路恢復：不用重新整理就回到正常
    page.evaluate("window.__blockSockets = false; window.dispatchEvent(new Event('online'))")
    page.wait_for_function("window.__bmt.conn === 'online'")
    assert page.locator('[data-testid="conn-banner"]').count() == 0


def test_f1_stuck_connection_gives_up_and_retries(browser: Browser, server_url: str) -> None:  # noqa: F811
    """封包被丟掉時瀏覽器遲遲不報失敗（WebKit 測出來的）：8 秒後自己放棄換下一次。"""
    page = lobby_page(browser, server_url)
    page.evaluate(
        """() => {
          const Working = window.WebSocket;
          window.__working = Working;
          window.__stuck = [];
          window.WebSocket = function () {
            const ws = { readyState: 0, close() { ws.closed = true; } };
            window.__stuck.push(ws);
            return ws;
          };
          Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1 });
          window.__sockets.at(-1).close();
        }"""
    )
    page.wait_for_function("window.__stuck.length >= 2", timeout=20000)
    assert page.evaluate("window.__stuck[0].closed") is True
    page.evaluate("window.WebSocket = window.__working; window.dispatchEvent(new Event('online'))")
    page.wait_for_function("window.__bmt.conn === 'online'")


def test_f3_server_down_says_closed_and_retries(browser: Browser, server_url: str) -> None:  # noqa: F811
    page = browser.new_context(viewport=MOBILE).new_page()

    def refuse(route: Route) -> None:
        route.abort()

    page.route("**/api/health", refuse)
    page.goto(server_url)
    wait(page, "screen-s0")
    page.wait_for_function("document.body.innerText.includes('每 5 秒自動重試')")
    page.unroute("**/api/health")
    # 伺服器回來後自己回到正常畫面（還沒開房就是等待頁，但不再說自動重試）
    page.wait_for_function("!document.body.innerText.includes('每 5 秒自動重試')", timeout=8000)


def test_f8_old_version_asks_to_reload(browser: Browser, server_url: str) -> None:  # noqa: F811
    page = lobby_page(browser, server_url)

    def old_protocol(route: Route) -> None:
        body = route.fetch().text()
        route.fulfill(
            body=body.replace("PROTOCOL_VERSION = ", "PROTOCOL_VERSION = -1 + "),
            content_type="text/javascript",
        )

    page.route("**/js/protocol.js", old_protocol)
    page.reload()
    page.wait_for_function("window.__bmt?.ui.dialog?.kind === 'version'")
    assert "版本不一致" in page.locator('[data-testid="dialog"]').inner_text()


def test_f10_no_speech_says_so_instead_of_breaking(browser: Browser, server_url: str) -> None:  # noqa: F811
    no_speech = "Object.defineProperty(window, 'speechSynthesis', { value: undefined })"
    admin = browser.new_context(viewport=MOBILE).new_page()
    admin.add_init_script(no_speech)
    admin.goto(server_url)
    admin_open_room(admin, "god")
    wait(admin, "sound-unsupported")  # 開房完成頁
    press(admin, "btn-to-control")
    wait(admin, "screen-s20")
    wait(admin, "sound-unsupported")  # 測試鈕只在進房前，但主持人進房後仍要看到警告
    page = browser.new_context(viewport=MOBILE).new_page()
    page.add_init_script(no_speech)
    page.goto(server_url)
    wait(page, "sound-unsupported")
    assert page.locator('[data-testid="btn-sound-test"]').count() == 0
    wait(page, "input-join_name")  # 其他功能不受影響


def test_f11_script_error_shows_toast_and_is_logged(browser: Browser, server_url: str) -> None:  # noqa: F811
    page = browser.new_context(viewport=MOBILE).new_page()
    page.goto(server_url)
    wait(page, "btn-admin-key")
    page.evaluate("setTimeout(() => { throw new Error('測試用錯誤'); })")
    wait(page, "toast")
    assert "重新整理" in page.locator('[data-testid="toast"]').inner_text()
    assert page.evaluate("window.__bmt.errorLog.at(-1).message").endswith("測試用錯誤")
