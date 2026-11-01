"""QR Code、拖曳排座位、測試聲音只在進房前、聊天載入舊訊息與自動捲動（SPEC v4.16）。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    admin_open_room,
    fill,
    has,
    join_form,
    press,
    server_url,  # noqa: F401
    store,
    wait,
)

pytestmark = pytest.mark.e2e


def admin_in_lobby(page: Page, url: str) -> None:
    page.goto(url)
    admin_open_room(page, "auto")
    wait(page, "invite-qr")
    press(page, "btn-to-join")
    join_form(page, "管理", None)


def test_qr_is_a_real_image_with_the_invite_inside(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        admin_open_room(page, "god")
        wait(page, "invite-qr")
        assert page.evaluate(
            "document.querySelector('[data-testid=\"invite-qr\"]').naturalWidth > 0"
        )
        # 尺寸對、三個定位圖案都在；真的掃得出來另外用解碼器驗過（見 PROGRESS）
        matrix = page.evaluate(
            "async () => (await import('/js/ui/qr.js')).qrMatrix(location.origin + '/#pw=1234')"
        )
        size = len(matrix)
        assert size % 4 == 1 and size >= 21
        for x, y in ((0, 0), (size - 7, 0), (0, size - 7)):
            assert all(matrix[y][x + i] for i in range(7))
            assert matrix[y + 3][x + 3]
            assert not matrix[y + 1][x + 1]
        too_long = page.evaluate(
            "async () => (await import('/js/ui/qr.js')).qrDataUrl('x'.repeat(500))"
        )
        assert too_long is None  # 太長就只顯示網址，不會壞
        browser.close()


def test_sound_test_only_before_entering_the_room(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        wait(admin, "btn-sound-test")  # 開房完成頁
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "btn-sound-test")  # 加入頁
        fill(page, "input-join_password", "1234")
        join_form(page, "玩甲", None)
        assert not has(page, "btn-sound-test")
        press(page, "btn-settings")
        wait(page, "screen-s21")
        assert not has(page, "btn-test-voice")
        browser.close()


def test_drag_reorders_seats_and_tells_the_player(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(page, server_url)
        press(page, "btn-add-bots")
        page.wait_for_function("window.__bmt.server.roster.length >= 6")
        order = store(page, "[...s.server.roster].sort((a, b) => a.seat - b.seat).map((r) => r.id)")
        first, third = order[0], order[2]
        handle = page.locator(f'[data-testid="seat-handle-{first}"]').bounding_box()
        target = page.locator(f'[data-testid="lobby-row-{third}"]').bounding_box()
        assert handle and target
        page.mouse.move(handle["x"] + 10, handle["y"] + 10)
        page.mouse.down()
        page.mouse.move(handle["x"] + 10, target["y"] + target["height"] / 2, steps=8)
        assert store(page, "s.ui.seatDrag.order")[2] == first  # 拖曳中名單就跟著動
        page.mouse.up()
        page.wait_for_function(
            "(id) => window.__bmt.server.roster.find((r) => r.id === id).seat === 3", arg=first
        )
        page.wait_for_function("window.__bmt.ui.seatDrag === null")
        wait(page, "toast")  # 「座位已調整，你是 3 號」
        assert "3 號" in page.locator('[data-testid="toast"]').inner_text()
        browser.close()


def test_chat_older_messages_and_scroll(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(page, server_url)
        press(page, "tab-chat")
        wait(page, "chat-input")
        fill(page, "chat-input", "最舊的一句")
        page.locator('[data-testid^="chat-send-public"]').click()
        page.wait_for_function("window.__bmt.server.chat?.length === 1")
        assert not has(page, "chat-older")  # 還沒滿一頁

        # 假裝畫面上已經有一整頁較新的訊息，只留伺服器上真的那句在更早
        page.evaluate(
            """() => {
              const s = window.__bmt;
              const real = s.server.chat[0];
              s.server.chat = Array.from({ length: 100 }, (_, i) => ({
                ...real, id: real.id + 1000 + i, content: `第 ${i} 句`,
              }));
              document.querySelector('[data-testid="tab-game"]').click();
              document.querySelector('[data-testid="tab-chat"]').click();
            }"""
        )
        wait(page, "chat-older")
        distance = (
            "(() => { const l = document.querySelector('.chat__list');"
            " return l.scrollHeight - l.scrollTop - l.clientHeight; })()"
        )
        page.wait_for_function(f"{distance} < 2")  # 打開時停在最新

        page.evaluate("document.querySelector('.chat__list').scrollTop = 0")
        page.wait_for_timeout(100)
        press(page, "chat-older")
        page.wait_for_function("window.__bmt.server.chat[0].content === '最舊的一句'")
        page.wait_for_timeout(100)
        # 插進舊訊息後還停在原本看的地方，不會跳走
        assert page.evaluate("document.querySelector('.chat__list').scrollTop") > 0

        assert not has(page, "chat-older")  # 已經翻到 1 號

        # 最舊的不是 1 號但伺服器說沒有了（例如前面都是看不到的狼人訊息）：按鈕收起來
        page.evaluate(
            """async () => {
              const s = window.__bmt;
              s.server.chat = s.server.chat.filter((m) => m.id > 1);
              const { applyMessage } = await import('/js/store.js');
              applyMessage({ t: 'state.none' });
            }"""
        )
        wait(page, "chat-older")
        press(page, "chat-older")  # before_id 比 1 號大，會拿回 1 號
        page.wait_for_function("window.__bmt.server.chat[0].id === 1")
        page.evaluate(
            """async () => {
              const s = window.__bmt;
              s.server.chat = s.server.chat.filter((m) => m.id > 1);
              const { applyMessage } = await import('/js/store.js');
              applyMessage({ t: 'chat.history', channel: 'public', messages: [] });
            }"""
        )
        page.wait_for_function("window.__bmt.ui.chatEnd.public === true")
        page.wait_for_timeout(100)
        assert not has(page, "chat-older")

        # 往上翻的時候，別人的新訊息不會把人拉走
        others = """async (content) => {
          const { applyMessage } = await import('/js/store.js');
          const s = window.__bmt;
          applyMessage({ ...s.server.chat.at(-1), t: 'chat.msg', mine: false, content,
            id: s.server.chat.at(-1).id + 1 });
        }"""
        page.evaluate("document.querySelector('.chat__list').scrollTop = 0")
        page.wait_for_timeout(100)
        page.evaluate(others, "別人的話")
        page.wait_for_timeout(100)
        assert page.evaluate("document.querySelector('.chat__list').scrollTop") < 50
        # 但自己發的一定看得到
        fill(page, "chat-input", "我的話")
        page.locator('[data-testid^="chat-send-public"]').click()
        page.wait_for_function("window.__bmt.server.chat.at(-1).content === '我的話'")
        page.wait_for_function(f"{distance} < 2")
        # 鍵盤跳出來、清單變矮後，看最新的人還是停在最新（先等上面的捲動事件送達）
        page.wait_for_timeout(100)
        page.set_viewport_size({"width": MOBILE["width"], "height": 400})
        page.wait_for_timeout(200)
        page.evaluate(others, "再一句")
        page.wait_for_function(f"{distance} < 2")
        browser.close()


def _lobby_with_bots(page: Page, url: str) -> list[str]:
    admin_in_lobby(page, url)
    press(page, "btn-add-bots")
    page.wait_for_function("window.__bmt.server.roster.length >= 6")
    return store(page, "[...s.server.roster].sort((a, b) => a.seat - b.seat).map((r) => r.id)")


def test_someone_joining_during_a_drag_does_not_lose_it(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        order = _lobby_with_bots(page, server_url)
        first = order[0]
        handle = page.locator(f'[data-testid="seat-handle-{first}"]').bounding_box()
        target = page.locator(f'[data-testid="lobby-row-{order[1]}"]').bounding_box()
        assert handle and target
        page.mouse.move(handle["x"] + 10, handle["y"] + 10)
        page.mouse.down()
        page.mouse.move(handle["x"] + 10, target["y"] + target["height"] / 2, steps=4)
        count = len(order)
        page.evaluate(
            """async () => {
              const { api } = await import('/js/net.js');
              const { loadTokens } = await import('/js/session.js');
              await api('/dev/bots?count=1', { method: 'POST', auth: loadTokens().admin });
            }"""
        )
        page.wait_for_function("(n) => window.__bmt.server.roster.length > n", arg=count)
        page.mouse.up()
        page.wait_for_function(
            "(id) => window.__bmt.server.roster.find((r) => r.id === id).seat === 2", arg=first
        )
        browser.close()


def test_drag_works_with_a_finger(server_url: str) -> None:  # noqa: F811
    """真正的觸控事件。滑鼠測不到列被移動時觸控會不會被取消；iPhone 仍要實機確認。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE, has_touch=True)
        page = context.new_page()
        order = _lobby_with_bots(page, server_url)
        first = order[0]
        handle = page.locator(f'[data-testid="seat-handle-{first}"]').bounding_box()
        target = page.locator(f'[data-testid="lobby-row-{order[2]}"]').bounding_box()
        assert handle and target
        x = handle["x"] + 10
        start = handle["y"] + 10
        end = target["y"] + target["height"] / 2
        cdp = context.new_cdp_session(page)
        touch = "Input.dispatchTouchEvent"
        cdp.send(touch, {"type": "touchStart", "touchPoints": [{"x": x, "y": start}]})
        steps = 10
        for i in range(1, steps + 1):
            y = start + (end - start) * i / steps
            cdp.send(touch, {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            page.wait_for_timeout(30)
        assert store(page, "s.ui.seatDrag && s.ui.seatDrag.order[2]") == first
        cdp.send(touch, {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function(
            "(id) => window.__bmt.server.roster.find((r) => r.id === id).seat === 3", arg=first
        )
        browser.close()
