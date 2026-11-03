"""加到主畫面（S23）、準備檢查（S24）、離線也打得開（service worker）。SPEC v4.27。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, BrowserContext, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    fill,
    has,
    join_form,
    press,
    server_url,  # noqa: F401
    store,
    wait,
)
from tests.e2e.test_lobby_tools import admin_in_lobby

pytestmark = pytest.mark.e2e
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
NO_WAKE_LOCK_JS = "Object.defineProperty(navigator, 'wakeLock', { value: undefined });"
STANDALONE_JS = """
const realMatch = window.matchMedia.bind(window);
window.matchMedia = (q) => q.includes('standalone') ? { matches: true, media: q, addEventListener() {} } : realMatch(q);
"""


def iphone(browser: Browser) -> BrowserContext:
    return browser.new_context(viewport=MOBILE, user_agent=IPHONE_UA, has_touch=True, is_mobile=True)


def test_install_guide_comes_before_joining(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(admin, server_url)
        assert not has(admin, "screen-s23")  # 電腦開的不教
        page = iphone(browser).new_page()
        page.add_init_script(NO_WAKE_LOCK_JS)
        page.goto(f"{server_url}/#pw=1234")
        wait(page, "screen-s23")
        assert page.locator(".install__icon").count() == 1  # iPhone 版有分享按鈕的圖
        assert "1234" in page.locator('[data-testid="install-password"]').inner_text()
        press(page, "btn-install-skip")
        join_form(page, "玩甲", None)
        # 大廳：兩張準備卡都還沒好
        assert "☐" in page.locator('[data-testid="prep-pwa"]').inner_text()
        assert "☐" in page.locator('[data-testid="prep-wake"]').inner_text()
        wait(page, "wake-hint")
        # 回報給伺服器，管理員開始前看得到
        admin.wait_for_function(
            "() => (window.__bmt.server.roster || []).some((p) => p.name === '玩甲' && p.prep.wakelock === false)"
        )
        press(admin, "btn-add-bots")
        admin.wait_for_function("() => (window.__bmt.server.roster || []).length >= 6")
        press(admin, "btn-start")
        wait(admin, "dialog-text")
        assert "玩甲 的螢幕可能會自己關掉" in admin.locator('[data-testid="dialog-text"]').inner_text()
        press(admin, "dialog-cancel")
        # 玩家說已經把自動鎖定改成永不
        press(page, "btn-wake-done")
        wait(page, "prep-wake")
        assert "✔" in page.locator('[data-testid="prep-wake"]').inner_text()
        assert not has(page, "wake-hint")
        admin.wait_for_function(
            "() => window.__bmt.server.roster.some((p) => p.name === '玩甲' && p.prep.wakelock === true)"
        )
        # 大廳和設定都能再看一次教學，看完回原畫面
        press(page, "btn-pwa-how")
        wait(page, "btn-install-close")
        assert not has(page, "btn-install-skip")
        press(page, "btn-install-close")
        wait(page, "my-seat")
        press(page, "btn-settings")
        press(page, "btn-install-guide")
        wait(page, "screen-s23")
        browser.close()


def test_home_screen_app_skips_the_guide(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(admin, server_url)
        page = iphone(browser).new_page()
        page.add_init_script(STANDALONE_JS)
        page.goto(server_url)
        fill(page, "input-join_password", "1234")
        join_form(page, "玩乙", None)
        assert not has(page, "screen-s23")
        assert "✔" in page.locator('[data-testid="prep-pwa"]').inner_text()
        admin.wait_for_function(
            "() => (window.__bmt.server.roster || []).some((p) => p.name === '玩乙' && p.prep.pwa === true)"
        )
        press(page, "btn-settings")
        assert not has(page, "btn-install-guide")
        browser.close()


def test_opens_offline_but_never_caches_live_data(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        page = context.new_page()
        page.goto(server_url)
        wait(page, "btn-admin-key")
        page.evaluate("localStorage.setItem('bmt.sw_test', 'true')")
        page.reload()
        page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=15000)
        page.reload()  # 這次所有檔案都經過 service worker，存起來
        wait(page, "btn-admin-key")
        page.wait_for_function(
            """async () => {
                const keys = (await (await caches.open('bmt-static')).keys()).map((r) => new URL(r.url).pathname);
                return keys.includes('/') && keys.includes('/js/app.js') && keys.includes('/css/base.css');
            }"""
        )
        keys = page.evaluate(
            "async () => (await (await caches.open('bmt-static')).keys()).map((r) => r.url)"
        )
        assert not [k for k in keys if "server.json" in k or "/api/" in k or "?" in k]
        context.set_offline(True)
        page.reload()
        wait(page, "btn-admin-key")  # 畫面打得開，只是連不到酒館
        assert store(page, "s.health") is None
        browser.close()
