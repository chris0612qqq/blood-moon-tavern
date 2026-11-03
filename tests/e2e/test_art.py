"""美術垂直切片：夜晚·狼人選刀（DEV_PLAN P8、ART 7.2、11.2、11.3）。用預覽頁的假資料測，不用開一局。"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import MOBILE, has, server_url, wait  # noqa: F401

pytestmark = pytest.mark.e2e
SLOW_PHONE = 4  # CPU 降速 4 倍，模擬 iPhone SE 級舊手機（UT5 同樣做法）
MIN_FPS = 50


def preview(page: Page, url: str) -> None:
    page.goto(f"{url}/preview.html")
    wait(page, "screen-s8")


def choose(page: Page, label: str) -> None:
    page.get_by_role("button", name=label, exact=True).click()


def test_ring_turns_ember_then_beats(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        preview(page, server_url)
        ring = page.locator('[data-testid="countdown-ring"]')
        assert ring.get_attribute("data-zone") == "calm"
        choose(page, "剩 10 秒")
        page.wait_for_function("document.querySelector('[data-testid=\"countdown-ring\"]').dataset.zone === 'warn'")
        # 環會跟著時間變短
        first = float(ring.evaluate("(el) => el.style.getPropertyValue('--frac')"))
        page.wait_for_timeout(1500)
        assert float(ring.evaluate("(el) => el.style.getPropertyValue('--frac')")) < first
        page.wait_for_function(
            "document.querySelector('[data-testid=\"countdown-ring\"]').dataset.zone === 'urgent'", timeout=12000
        )
        choose(page, "暫停")
        page.wait_for_function("document.querySelector('[data-testid=\"countdown-ring\"]').dataset.zone === 'paused'")
        assert page.locator('[data-testid="countdown"]').inner_text() == "‖"
        browser.close()


def test_agree_glows_then_claws_the_target(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        preview(page, server_url)
        choose(page, "同伴已選")
        assert "老王" in page.locator('[data-testid="pick-cell-p3"] .cell__marks').inner_text()
        page.locator('[data-testid="pick-cell-p3"]').click()  # 跟同伴選一樣
        page.wait_for_selector('[data-testid="pick-cell-p3"].cell--confirming')
        wait(page, "wolf-victim", timeout=6000)  # 3 秒後自動確認
        assert page.locator('[data-testid="wolf-victim"] .slash i').count() == 3
        assert "大華" in page.locator('[data-testid="wolf-status"]').inner_text()
        browser.close()


def test_decorations_stay_inside_and_do_not_block_taps(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport={"width": 320, "height": 568}).new_page()
        preview(page, server_url)
        # 最小的手機也不能左右滑
        assert page.evaluate("document.querySelector('.main').scrollWidth <= document.querySelector('.main').clientWidth")
        # 爪痕、霧、血月光都點不到：格子正中央點下去拿到的是格子本身
        for testid in ("pick-cell-p1", "pick-cell-none"):
            cell = page.locator(f'[data-testid="{testid}"]')
            cell.scroll_into_view_if_needed()
            hit = cell.evaluate(
                """(el) => {
                    const r = el.getBoundingClientRect();
                    return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2).closest('button') === el;
                }"""
            )
            assert hit, testid
        browser.close()


def test_smooth_on_a_slow_phone(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        page = context.new_page()
        preview(page, server_url)
        cdp = context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": SLOW_PHONE})
        choose(page, "剩 10 秒")  # 火星、霧、血月光同時在動
        page.locator('[data-testid="pick-cell-p3"]').click()
        fps = page.evaluate(
            """() => new Promise((done) => {
                let frames = 0;
                const start = performance.now();
                const step = (now) => {
                    frames += 1;
                    if (now - start < 2000) requestAnimationFrame(step);
                    else done(frames * 1000 / (now - start));
                };
                requestAnimationFrame(step);
            })"""
        )
        assert fps >= MIN_FPS, fps
        assert not page.evaluate("document.documentElement.hasAttribute('data-lowfx')")
        browser.close()


def test_slow_frames_turn_off_decorations(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        preview(page, server_url)
        # 故意每影格卡 40 ms（約 25 fps），2 秒後應該自動關掉裝飾
        page.evaluate(
            """() => {
                const busy = () => { const end = performance.now() + 40; while (performance.now() < end); requestAnimationFrame(busy); };
                requestAnimationFrame(busy);
            }"""
        )
        page.wait_for_function("document.documentElement.hasAttribute('data-lowfx')", timeout=8000)
        assert page.locator(".ring__sparks").evaluate("(el) => getComputedStyle(el).display") == "none"
        assert not has(page, "dialog")
        browser.close()


def test_recorded_howl_with_synth_fallback(server_url: str) -> None:  # noqa: F811
    howl = "async () => (await import('/js/sfx.js')).wolfHowl()"
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        preview(page, server_url)
        page.locator('[data-testid="screen-s8"]').click()  # 第一次點擊才開聲音、下載錄音
        # 錄音 2.8 秒＋停 0.3 秒才念旁白
        page.wait_for_function(f"({howl})().then((ms) => ms === 3100)", timeout=8000)
        # 錄音載不到就用合成的，旁白照樣會念
        broken = browser.new_context(viewport=MOBILE).new_page()
        broken.route("**/audio/wolf_howl.wav", lambda route: route.fulfill(status=404))
        preview(broken, server_url)
        broken.locator('[data-testid="screen-s8"]').click()
        broken.wait_for_timeout(1000)
        assert broken.evaluate(howl) == 2300
        browser.close()
