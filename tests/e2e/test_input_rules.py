"""防呆（UI_RULES UT2、UT3、K6、K8、K14）與控制台的女巫等待（SPEC C8.6）。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    admin_open_room,
    fill,
    press,
    server_url,  # noqa: F401
    store,
    wait,
)

pytestmark = pytest.mark.e2e


def join_page(url: str, browser_context: object) -> Page:
    page: Page = browser_context.new_page()  # type: ignore[attr-defined]
    page.goto(url)
    wait(page, "input-join_name")
    return page


def value(page: Page, testid: str) -> str:
    return page.locator(f'[data-testid="{testid}"]').input_value()


def test_ut3_inputs(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "input-join_name")
        name, pin, join = "input-join_name", "input-join_pin", '[data-testid="btn-join"]'
        fill(page, "input-join_password", "12a3b4")
        assert value(page, "input-join_password") == "1234"  # 非數字直接不收
        fill(page, pin, "1x1y1z1")
        assert value(page, pin) == "1111"
        for raw, want in (
            ("小美", "小美"),
            (" 美 ", "美"),
            ("​美​", "美"),
            ("一二三四五六七八九", "一二三四五六七八"),  # 最多 8 個字（SPEC v4.40）
            ("👍🏽阿", "👍🏽阿"),  # 膚色符號和手勢算一個字
        ):
            fill(page, name, raw)
            assert value(page, name) == want
        fill(page, name, "😀😀")
        page.wait_for_timeout(100)
        assert page.locator(join).is_disabled()
        assert "不能用表情符號和空白" in page.locator("#app").inner_text()
        # 80 年代風的名字：語音名字只留漢字和數字、代號取第一個字，都自動帶入（SPEC v4.40）
        fill(page, name, "Oo風花雪月oO")
        page.wait_for_timeout(100)
        assert value(page, "input-join_spoken") == "風花雪月"
        assert value(page, "input-join_mark") == "風"
        preview = page.locator('[data-testid="name-preview"]').inner_text()
        assert "旁白念「風花雪月」" in preview and "爪痕上是「風」" in preview
        assert not page.locator(join).is_disabled()
        fill(page, name, "玩1")  # 數字留著，旁白才分得出玩1、玩2
        page.wait_for_timeout(100)
        assert value(page, "input-join_spoken") == "玩1"
        # 自己改過語音名字，名字再改也不會被蓋掉；代號跟著語音名字
        fill(page, "input-join_spoken", "Moon")
        fill(page, name, "★風花雪月★")
        page.wait_for_timeout(100)
        assert (value(page, "input-join_spoken"), value(page, "input-join_mark")) == ("Moon", "M")
        fill(page, "input-join_spoken", "月！")
        page.wait_for_timeout(100)
        assert page.locator(join).is_disabled()  # 語音名字不能有標點
        assert "只能用中文、英文或數字" in page.locator("#app").inner_text()
        fill(page, "input-join_spoken", "月亮")
        fill(page, "input-join_mark", "★")
        page.wait_for_timeout(100)
        assert page.locator(join).is_disabled()  # 代號不能是符號
        fill(page, "input-join_mark", "AB")
        assert value(page, "input-join_mark") == "A"  # 代號只收 1 個字
        page.wait_for_timeout(100)
        assert not page.locator(join).is_disabled()
        press(page, "btn-join")
        page.wait_for_function(
            "(window.__bmt.server?.roster ?? []).some((r) => r.name === '★風花雪月★')"
        )
        mine = store(page, "s.server.roster.find((r) => r.name === '★風花雪月★')")
        assert (mine["spoken"], mine["mark"]) == ("月亮", "A")
        browser.close()


def test_k8_composition_is_left_alone(server_url: str) -> None:  # noqa: F811
    """打注音組字中不能被判超過字數，也不能被改掉；選字完才算。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "input-join_name")
        box = page.locator('[data-testid="input-join_name"]')
        box.click()
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Input.imeSetComposition",
            {"text": "ㄒㄧㄠˇㄇㄟˇ", "selectionStart": 6, "selectionEnd": 6},
        )
        page.wait_for_timeout(100)
        assert box.input_value() == "ㄒㄧㄠˇㄇㄟˇ"
        assert store(page, "s.ui.form.join_name ?? ''") == ""
        cdp.send("Input.insertText", {"text": "小美"})
        page.wait_for_timeout(100)
        assert box.input_value() == "小美"
        assert store(page, "s.ui.form.join_name") == "小美"
        browser.close()


def test_ut2_button_mash_counts_once(server_url: str) -> None:  # noqa: F811
    """UT2：開始鈕 1 秒內連點 20 下，也只會跳一次確認、只送一次。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "auto")
        press(admin, "btn-to-join")
        wait(admin, "input-join_name")
        fill(admin, "input-join_name", "管理")
        fill(admin, "input-join_pin", "1111")
        press(admin, "btn-join")
        wait(admin, "my-seat")
        press(admin, "btn-add-bots")
        admin.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(admin, "btn-start")
        wait(admin, "dialog-confirm")
        admin.evaluate(
            """() => {
              window.__sent = 0;
              const original = WebSocket.prototype.send;
              WebSocket.prototype.send = function (data) {
                if (String(data).includes('admin.start')) window.__sent += 1;
                return original.call(this, data);
              };
              const button = document.querySelector('[data-testid="dialog-confirm"]');
              for (let i = 0; i < 20; i += 1) button.click();
            }"""
        )
        admin.wait_for_function("window.__bmt.server.phase === 'game'")
        assert admin.evaluate("window.__sent") == 1
        browser.close()


def test_k14_back_button_keeps_you_in_game(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        admin_open_room(page, "auto")
        press(page, "btn-to-join")
        wait(page, "input-join_name")
        fill(page, "input-join_name", "管理")
        fill(page, "input-join_pin", "1111")
        press(page, "btn-join")
        wait(page, "my-seat")
        press(page, "btn-add-bots")
        page.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(page, "btn-start")
        press(page, "dialog-confirm")
        page.wait_for_function("window.__bmt.server.phase === 'game'")
        page.go_back()
        wait(page, "dialog-text")
        assert "離開遊戲畫面" in page.locator('[data-testid="dialog-text"]').inner_text()
        press(page, "dialog-cancel")
        assert store(page, "s.server.phase") == "game"
        # 再按一次一樣會問，不會直接離開
        page.go_back()
        wait(page, "dialog-text")
        assert page.url.startswith(server_url)
        browser.close()


def test_k6_end_button_below_the_log(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        admin_open_room(page, "auto")
        press(page, "btn-to-join")
        wait(page, "input-join_name")
        fill(page, "input-join_name", "管理")
        fill(page, "input-join_pin", "1111")
        press(page, "btn-join")
        wait(page, "my-seat")
        press(page, "btn-add-bots")
        page.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(page, "btn-start")
        press(page, "dialog-confirm")
        page.wait_for_function("window.__bmt.server.phase === 'game'")
        press(page, "tab-players")
        wait(page, "btn-admin-end")
        assert page.locator('[data-testid^="kick-"]').count() == 0
        press(page, "btn-admin-end")
        wait(page, "dialog-text")  # 不可逆，一定先確認（UI_RULES K5）
        browser.close()


def test_witch_wait_rule(server_url: str) -> None:  # noqa: F811
    """女巫沒藥或已死時建議主持人等一下（SPEC C8.6）；有事可做就不用。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        wait(page, "btn-admin-key")
        result = page.evaluate(
            """async () => {
              const { witchWaitUntil } = await import('/js/screens/host.js');
              const server = (step, actors, used) => ({
                step,
                host: {
                  actors,
                  witch: { antidote_used: used, poison_used: used },
                  timers: { min_until: 100 },
                },
              });
              return [
                witchWaitUntil(server('WITCH', ['w'], true), 90),
                witchWaitUntil(server('WITCH', [], false), 90),
                witchWaitUntil(server('WITCH', ['w'], false), 90),
                witchWaitUntil(server('WITCH', [], false), 100),
                witchWaitUntil(server('SEER', [], true), 90),
              ];
            }"""
        )
        assert result == [100, 100, None, None, None]
        browser.close()


def test_symbol_buttons_insert_at_cursor(server_url: str) -> None:  # noqa: F811
    """名字欄下面的常用符號：點一下插進游標位置，語音名字不念，滿 8 字不加（SPEC v4.46）。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "god")
        page = join_page(server_url, browser.new_context(viewport=MOBILE))
        name = "input-join_name"
        symbols = page.locator('[data-testid="name-symbols"] button')
        assert symbols.count() == 15
        texts = symbols.all_inner_texts()
        fill(page, name, "小美")
        page.locator(f'[data-testid="name-symbol-{texts.index("彡")}"]').click()
        assert value(page, name) == "小美彡"
        # 游標移到最前面再點：插在前面
        page.locator(f'[data-testid="{name}"]').evaluate("(el) => el.setSelectionRange(0, 0)")
        page.locator(f'[data-testid="name-symbol-{texts.index("★")}"]').click()
        assert value(page, name) == "★小美彡"
        page.wait_for_timeout(100)
        assert value(page, "input-join_spoken") == "小美"  # 彡 不念
        fill(page, name, "一二三四五六七八")
        page.locator('[data-testid="name-symbol-0"]').click()
        assert value(page, name) == "一二三四五六七八"  # 滿了不加
        wait(page, "toast")
        assert "加不下了" in page.locator('[data-testid="toast"]').inner_text()
        # 最小的手機也不能左右滑
        root = "document.documentElement"
        assert page.evaluate(f"{root}.scrollWidth <= {root}.clientWidth")
        browser.close()
