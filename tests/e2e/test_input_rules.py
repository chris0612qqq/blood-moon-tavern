"""防呆（UI_RULES UT2、UT3、K6、K8、K14）與控制台的女巫等待（SPEC C8.6）。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    admin_open_room,
    fill,
    has,
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
            ("ABC", "AB"),
            ("😀😀😀", "😀😀"),
            ("👍🏽阿", "👍🏽阿"),  # 膚色符號和手勢算一個字
        ):
            fill(page, name, raw)
            assert value(page, name) == want
        fill(page, name, "阿")
        page.wait_for_timeout(100)
        assert page.locator(join).is_disabled()  # 恰 2 個字
        assert "還能打 1 個字" in page.locator("#app").inner_text()
        fill(page, name, "😀😀")
        page.wait_for_timeout(100)
        assert page.locator(join).is_disabled()
        assert "只能用中文、英文或數字" in page.locator("#app").inner_text()
        fill(page, name, "小美")
        page.wait_for_timeout(100)
        assert not page.locator(join).is_disabled()
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


def test_k6_kick_hidden_until_manage(server_url: str) -> None:  # noqa: F811
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
        wait(page, "btn-players-manage")
        assert page.locator('[data-testid^="kick-"]').count() == 0
        assert not has(page, "btn-admin-end")
        press(page, "btn-players-manage")
        wait(page, "btn-admin-end")
        assert page.locator('[data-testid^="kick-"]').count() >= 6
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
