"""無管理員模式的開房流程（試玩回饋）：從上一間上帝房關房後改開無管理員房。

重點是同一支手機接著操作：不能跳到「這一局結束」，要能加入成玩家，
而且它就是旁白主機，要念得出聲音。
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    FAKE_SPEECH_JS,
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


def screen(page: Page) -> str:
    value: str = page.evaluate("document.documentElement.dataset.screen")
    return value


def text(page: Page) -> str:
    value: str = page.locator("#app").inner_text()
    return value


def close_current_room(page: Page) -> None:
    press(page, "btn-admin-key")
    wait(page, "btn-close-room")
    press(page, "btn-close-room")
    press(page, "dialog-confirm")
    wait(page, "btn-open-room")


def test_switch_from_god_room_to_auto_room_and_narrate(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        context.add_init_script(FAKE_SPEECH_JS)
        admin = context.new_page()
        admin.goto(server_url)

        # 先有一間上帝房，管理員連進控制台
        admin_open_room(admin, "god")
        press(admin, "btn-to-control")
        wait(admin, "screen-s20")

        # 關掉它，改開無管理員房
        close_current_room(admin)
        press(admin, "mode-auto")
        fill(admin, "input-room_password", "1234")
        press(admin, "btn-open-room")
        wait(admin, "screen-s3")

        # 下一頁不能跳成「這一局結束」
        press(admin, "btn-to-join")
        admin.wait_for_timeout(400)
        assert screen(admin) == "S4", (screen(admin), text(admin))
        fill(admin, "input-join_name", "管理")
        fill(admin, "input-join_pin", "1111")
        press(admin, "btn-join")
        wait(admin, "my-seat")
        assert "旁觀" not in text(admin)
        assert store(admin, "s.server.is_admin") is True
        narrator = store(admin, "s.server.room.narrator_id")
        assert narrator == store(admin, "s.server.me.id")  # 管理員手機就是旁白主機

        # 開始玩：管理員手機要念得出聲音
        press(admin, "btn-add-bots")
        admin.wait_for_function("window.__bmt.server.roster.length >= 6")
        press(admin, "btn-start")
        press(admin, "dialog-confirm")
        admin.wait_for_function("window.__bmt.server.phase === 'game'")
        assert store(admin, "s.server.me.role")
        press(admin, "btn-seen")
        admin.wait_for_function(
            "window.__spoken.some((s) => s.text === '天黑請閉眼' && s.volume === 1)",
            timeout=60000,
        )
        assert not has(admin, "screen-s25")
        browser.close()


def test_admin_cannot_start_auto_room_without_joining(server_url: str) -> None:  # noqa: F811
    """管理員走「進控制台」時只是旁觀；沒加入就開始，自己會變成旁觀者、也沒有旁白。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin.goto(server_url)
        admin_open_room(admin, "auto")
        # 開房後先離開這一頁，再從管理員選單回來
        press(admin, "btn-to-join")
        wait(admin, "input-join_name")
        press(admin, "btn-admin-key")
        wait(admin, "screen-s2")
        assert not has(admin, "btn-to-control")  # 不能用旁觀身分進去
        wait(admin, "btn-to-join")
        press(admin, "btn-to-join")
        wait(admin, "input-join_name")
        browser.close()
