"""管理員選哪些手機也念旁白（SPEC v4.29）。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import MOBILE, fill, has, join_form, press, server_url, store, wait  # noqa: F401
from tests.e2e.test_lobby_tools import admin_in_lobby

pytestmark = pytest.mark.e2e
SPEAKS = "async () => (await import('/js/narrator.js')).speaksHere(window.__bmt.server)"


def speaks(page: Page) -> bool:
    return bool(page.evaluate(SPEAKS))


def wait_speaks(page: Page, value: bool) -> None:
    page.wait_for_function(f"async () => (await import('/js/narrator.js')).speaksHere(window.__bmt.server) === {str(value).lower()}")


def test_admin_picks_which_phones_read_narration(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(admin, server_url)  # 管理員是旁白主機
        page = browser.new_context(viewport=MOBILE).new_page()
        page.goto(server_url)
        fill(page, "input-join_password", "1234")
        join_form(page, "玩甲", None)
        assert speaks(admin) and not speaks(page)
        press(page, "btn-settings")
        assert not has(page, "voices-all")  # 只有管理員能改
        press(admin, "btn-settings")
        press(admin, "voices-all")
        wait_speaks(page, True)
        # 指定的人：先沒人被選，玩家不念；點了才念
        press(admin, "voices-some")
        wait_speaks(page, False)
        pid = store(page, "s.server.me.id")
        press(admin, f"voice-{pid}")
        wait_speaks(page, True)
        assert "cell--on" in (admin.locator(f'[data-testid="voice-{pid}"]').get_attribute("class") or "")
        press(admin, "voices-narrator")
        wait_speaks(page, False)
        assert speaks(admin)
        browser.close()
