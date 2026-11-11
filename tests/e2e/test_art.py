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
        # 爪痕上寫同伴的代號，不是整個名字（SPEC v4.40）
        claw = page.locator('[data-testid="pick-cell-p3"] .cell__marks').inner_text()
        assert claw.strip() == "王"
        page.locator('[data-testid="pick-cell-p3"]').click()  # 跟同伴選一樣
        page.wait_for_selector('[data-testid="pick-cell-p3"].cell--confirming')
        wait(page, "wolf-victim", timeout=6000)  # 3 秒後自動確認
        cuts = page.locator('[data-testid="wolf-victim"] .slash__cut')
        assert cuts.count() == 3
        # 爪痕要真的劃完（描線從 1 收到 0），不是停在看不見的起點
        page.wait_for_function(
            "[...document.querySelectorAll('.slash__reveal')].every((p) => getComputedStyle(p).strokeDashoffset === '0px')",
            timeout=3000,
        )
        assert page.locator(".s8__moon circle").count() >= 2  # 血月是 SVG，有畫出來
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


def test_gallery_draws_every_illustration(server_url: str) -> None:  # noqa: F811
    """量產第二輪：角色徽章與各畫面主圖都畫得出來，沒有錯誤，最小的手機也不會左右滑。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport={"width": 320, "height": 568}).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{server_url}/gallery.html")
        page.wait_for_selector(".gallery__scene")
        for role in ("wolf", "faceless", "villager", "seer", "witch", "hunter"):
            assert page.locator(f".emblem--{role}").count() >= 2, role
        for kind in ("seer", "witch", "dawn", "hunter", "candle", "victory-wolf"):
            box = page.locator(f'[data-testid="hero-{kind}"]').first.bounding_box()
            assert box and box["width"] > 100 and box["height"] > 50, kind
        assert page.locator(".hero--wolf").count() == 1 and page.locator(".hero--good").count() == 1
        for state in ("pour-save", "pour-poison", "shot", "holster"):
            assert page.locator(f".hero--{state}").count() == 1, state
        # 紅綠色弱看不出藥瓶顏色：解藥圓瓶「＋」、毒藥方瓶「×」，形狀要不同（ART 3.5）
        shapes = page.evaluate(
            """() => [...document.querySelectorAll('.emblem--witch path[stroke-width="2"]')].slice(0, 2).map((p) => p.getAttribute('d'))"""
        )
        assert len(set(shapes)) == 2
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert errors == []
        browser.close()


SOUND = "async (line) => (await import('/js/sfx.js')).openingSound(line)"
# 結算音效：回傳要等幾毫秒，以及實際開始放的錄音長度（秒），用長度分辨放的是哪一個檔
WIN = """async (winner) => {
    const m = await import('/js/sfx.js');
    const started = [];
    const original = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (...args) {
        started.push(Math.round(this.buffer.duration * 10) / 10);
        return original.apply(this, args);
    };
    try {
        return { ms: m.openingSound('win', { winner }), started: started.sort() };
    } finally {
        AudioBufferSourceNode.prototype.start = original;
    }
}"""
HOWL_S, WIN_VILLAGE_S, WIN_WOLF_S, CLAW_S, BITE_S = 2.8, 8.6, 7.5, 0.2, 0.4
SHIELD_CLASH_S = 0.7


def open_sound(page: Page) -> None:
    """第一次點擊才開聲音；等錄音下載完，每個音效只放一次就能檢查。"""
    page.locator('[data-testid="screen-s8"]').click()
    page.evaluate("async () => { const m = await import('/js/sfx.js'); m.preloadRecordings(); await m.recordingsReady(); }")


def test_opening_sounds_wait_only_where_the_server_leaves_time(server_url: str) -> None:  # noqa: F811
    """量產第三輪音效：伺服器有預留時間的句子放完才念；沒預留的跟旁白一起出來，不等（免得被下一句打斷）。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        preview(page, server_url)
        open_sound(page)
        assert page.evaluate(SOUND, "seer_open") == 1200
        assert page.evaluate(SOUND, "night_start") == 2200
        assert page.evaluate(SOUND, "witch_open") == 1500
        # 雞鳴錄音 2.22 秒＋停 0.3 秒，伺服器預留 2.6 秒放得完（SPEC v4.36）
        assert page.evaluate(SOUND, "dawn") == 2520
        # 結算：好人放號角；狼人先狼嚎、再進低沉弦樂。前奏 2.5 秒後才念（SPEC v4.36）
        assert page.evaluate(WIN, "village") == {"ms": 2500, "started": [WIN_VILLAGE_S]}
        assert page.evaluate(WIN, "wolf") == {"ms": 2500, "started": [HOWL_S, WIN_WOLF_S]}
        for line in ("peaceful", "deaths", "hunter", "vote", "wolf_close", "seer_close"):
            assert page.evaluate(SOUND, line) == 0, line
        page.evaluate("async () => { const m = await import('/js/sfx.js'); m.diceRoll(); m.coinDrops(3); }")
        # 天亮有人被咬死：和旁白一起出來，不等（SPEC v4.37）
        # 第 1、3 位死者被咬：各一聲揮爪＋一口咬下，都用錄音（SPEC v4.37）
        bites = WIN.replace("openingSound('win', { winner })", "openingSound('deaths', { bites: [0, 2] })")
        assert page.evaluate(bites, None) == {"ms": 0, "started": [CLAW_S, CLAW_S, BITE_S, BITE_S]}
        # 守衛的「鏘」用錄音，伺服器預留 1.2 秒，放完才念（SPEC v4.44）
        guard = WIN.replace("openingSound('win', { winner })", "openingSound('guard_open', { take: winner })")
        assert page.evaluate(guard, "clash") == {"ms": 1200, "started": [SHIELD_CLASH_S]}
        assert page.evaluate(guard, "synth")["ms"] == 1200  # 合成版也預留 1.2 秒
        assert errors == []
        browser.close()


def test_recorded_sounds_with_synth_fallback(server_url: str) -> None:  # noqa: F811
    howl = "async () => (await import('/js/sfx.js')).wolfHowl()"
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        preview(page, server_url)
        open_sound(page)
        # 錄音 2.8 秒＋停 0.3 秒才念旁白
        assert page.evaluate(howl) == 3100
        # 錄音載不到就用合成的，旁白照樣會念；勝利音效也有合成的，不會沒聲音
        broken = browser.new_context(viewport=MOBILE).new_page()
        errors: list[str] = []
        broken.on("pageerror", lambda e: errors.append(str(e)))
        broken.route("**/audio/*.wav", lambda route: route.fulfill(status=404))
        preview(broken, server_url)
        open_sound(broken)
        assert broken.evaluate(howl) == 2300
        assert broken.evaluate(SOUND, "dawn") == 1500
        assert broken.evaluate(SOUND, "guard_open") == 1200  # 盾牌錄音沒載到：合成的「鏘」
        assert broken.evaluate(WIN, "village") == {"ms": 2500, "started": []}
        assert broken.evaluate(WIN, "wolf") == {"ms": 2500, "started": []}
        assert errors == []
        browser.close()


def test_dawn_bite_claws_the_bitten_row_only(server_url: str) -> None:  # noqa: F811
    """天亮公布：被狼咬死的那列有爪痕、血光、紅字；被毒死的照舊（SPEC v4.37）。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{server_url}/gallery.html")
        demo = page.locator('[data-testid="dawn-demo"]')
        demo.click()  # 重播一次，同時放咬的音效
        bitten = demo.locator('[data-testid="dead-bite-p1"]')
        assert bitten.locator(".slash__cut").count() == 3
        assert "被狼人咬死" in bitten.locator(".bite__cause").inner_text()
        assert demo.locator(".dead-bite").count() == 1  # 阿志是被毒死的，沒有爪痕
        # 爪痕要真的劃完，而且畫在頭像上，不是撐大整列
        page.wait_for_function(
            "[...document.querySelectorAll('.dead-bite .slash__reveal')]"
            ".every((p) => getComputedStyle(p).strokeDashoffset === '0px')",
            timeout=4000,
        )
        mark = bitten.locator(".bite__mark").bounding_box()
        assert mark and mark["height"] < 60
        assert errors == []
        browser.close()


def test_only_narrator_phones_download_recordings(server_url: str) -> None:  # noqa: F811
    """錄音只有旁白手機會放；沒說要下載的頁面點了畫面也不下載（省行動網路）。"""
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_context(viewport=MOBILE).new_page()
        fetched: list[str] = []
        page.on("request", lambda r: fetched.append(r.url) if r.url.endswith(".wav") else None)
        page.goto(f"{server_url}/gallery.html")
        page.wait_for_selector(".gallery__scene")
        page.evaluate("async () => { await import('/js/sfx.js'); }")
        page.mouse.click(2, 2)  # 第一次點擊才開聲音
        page.wait_for_timeout(500)
        assert len(fetched) == 7  # 總覽頁說要下載：七個都抓（守衛只留刀劍鏘，SPEC v4.45）
        plain = browser.new_context(viewport=MOBILE).new_page()
        plain_fetched: list[str] = []
        plain.on("request", lambda r: plain_fetched.append(r.url) if r.url.endswith(".wav") else None)
        plain.goto(f"{server_url}/")
        plain.evaluate("async () => { await import('/js/sfx.js'); }")
        plain.mouse.click(2, 2)  # 點角落，不要按到任何按鈕
        plain.wait_for_timeout(500)
        assert plain_fetched == []  # 沒進房、不是旁白手機：不抓
        browser.close()
