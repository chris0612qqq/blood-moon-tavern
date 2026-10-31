"""每個角色的能力都從畫面實際操作一次（SPEC A5、C8.3），結果再和伺服器核對。

腳本化的一局，8 位真人分頁：
第 1 夜 狼刀村民、預言家查到狼、女巫救人 → 第 1 天投出獵人、獵人開槍帶走狼同伴、遺言
→ 第 2 夜 狼刀預言家、女巫不再被告知被殺者並下毒 → 死亡的好人押注 → 結算核對死因與押注。
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    admin_open_room,
    fill,
    has,
    join_form,
    press,
    running_server,
    store,
    wait,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def slow_server() -> Iterator[str]:
    # 腳本要按的步驟多，時間只加速 2 倍，倒數才夠用
    with running_server(2) as url:
        yield url


def shot(page: Page, name: str) -> None:
    folder = os.environ.get("BMT_SHOTS")
    if folder:
        page.wait_for_timeout(250)
        page.screenshot(path=f"{folder}/{name}.png")


def text_of(page: Page, testid: str) -> str:
    return page.locator(f'[data-testid="{testid}"]').first.inner_text()


def wait_step(page: Page, step: str, timeout: int = 90000) -> None:
    page.wait_for_function("(s) => window.__bmt.server?.step === s", arg=step, timeout=timeout)


def wait_open(page: Page) -> None:
    page.wait_for_function(
        "(() => { const c = document.querySelector('[data-testid=\"countdown\"]');"
        " return c && !c.textContent.includes('準備') && c.textContent !== ''; })()",
        timeout=30000,
    )


def finish_speeches(pages: list[Page], until: str) -> None:
    """白天輪流結束發言／遺言，直到進入指定步驟。"""
    for _ in range(600):
        if store(pages[0], "s.server.step") == until:
            return
        for page in pages:
            for testid in ("btn-speak-end", "btn-last-words-end"):
                locator = page.locator(f'[data-testid="{testid}"]')
                if locator.count() and locator.first.is_enabled():
                    with contextlib.suppress(PlaywrightError):
                        locator.first.click(timeout=500)
        pages[0].wait_for_timeout(100)
    raise AssertionError(f"never reached {until}")


def test_every_role_ability_through_the_ui(slow_server: str) -> None:
    errors: list[str] = []
    url = slow_server
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)

        def new_page(device: str) -> Page:
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(f"{device}: {e}"))
            page.goto(f"{url}/?dev_device={device}")
            return page

        admin = new_page("r0")
        password = admin_open_room(admin, "auto")
        press(admin, "btn-to-join")
        join_form(admin, "管理", None)
        pages = [admin]
        for i in range(1, 8):
            page = new_page(f"r{i}")
            join_form(page, f"玩{i}", password)
            pages.append(page)
        press(admin, "btn-start")
        press(admin, "dialog-confirm")
        for page in pages:
            page.wait_for_function("window.__bmt.server?.me?.role")

        by_role: dict[str, list[Page]] = {}
        for page in pages:
            by_role.setdefault(store(page, "s.server.me.role"), []).append(page)
        faceless = by_role["faceless"][0]
        wolf = by_role["wolf"][0]
        seer = by_role["seer"][0]
        witch = by_role["witch"][0]
        hunter = by_role["hunter"][0]
        villagers = by_role["villager"]
        id_of = {p: store(p, "s.server.me.id") for p in pages}
        name_of = {
            p: store(p, "s.server.roster.find(r => r.id === s.server.me.id).name") for p in pages
        }

        # 發牌：全部按「我看過了」
        for page in pages:
            press(page, "btn-seen")

        # ---- 狼人：同伴的選擇即時可見，一致 3 秒後自動確認 ----
        wait_step(wolf, "WOLF")
        wait_open(wolf)
        victim = villagers[0]
        press(wolf, f"pick-cell-{id_of[victim]}")
        faceless.wait_for_function(
            "(n) => document.querySelector('[data-testid=\"wolf-status\"]')?.innerText.includes(n)",
            arg=name_of[victim],
        )
        assert name_of[wolf] in text_of(faceless, "wolf-status")  # 看得到同伴選了誰
        assert not has(faceless, "disguise-panel")  # 狼人步驟不露出千面狼面板
        shot(faceless, "wolf_step_ally_pick")
        press(faceless, f"pick-cell-{id_of[victim]}")
        wolf.wait_for_function(
            "document.querySelector('[data-testid=\"wolf-status\"]')?.innerText.includes('即將確認')"
        )
        wolf.wait_for_function(
            "document.querySelector('[data-testid=\"wolf-status\"]')?.innerText.includes('已確認')"
        )

        assert name_of[victim] in text_of(wolf, "wolf-status")  # 確認訊息留得住（曾只閃一下）
        shot(wolf, "wolf_confirmed")

        # ---- 預言家：查到狼（千面狼也顯示狼人），結果可回看 ----
        wait_step(seer, "SEER")
        wait_open(seer)
        press(seer, f"pick-cell-{id_of[faceless]}")
        press(seer, "btn-seer-check")
        wait(seer, "seer-result")
        assert text_of(seer, "seer-result") == f"{name_of[faceless]} 是狼人"
        shot(seer, "seer_result")
        press(seer, "btn-seer-ok")

        # ---- 女巫：被告知被殺者，救人 ----
        wait_step(witch, "WITCH")
        wait_open(witch)
        wait(witch, "witch-attacked")
        assert name_of[victim] in text_of(witch, "witch-attacked")
        shot(witch, "witch_save")
        press(witch, "btn-witch-save")
        wait(witch, "witch-acted")

        # ---- 天亮：平安夜 ----
        wait_step(hunter, "DAWN")
        admin.wait_for_function("window.__bmt.server.step !== 'WITCH_END'", timeout=60000)
        wait_step(hunter, "DAY_SPEAK")
        state: dict[str, Any] = httpx.get(f"{url}/dev/state").json()["state"]
        assert all(p["alive"] for p in state["players"])

        # ---- 千面狼面板白天出現 ----
        wait(faceless, "disguise-panel")
        shot(faceless, "faceless_panel")

        # ---- 投票：全投獵人（獵人棄票），揭曉 ----
        finish_speeches(pages, "VOTE")
        for page in pages:
            wait_open(page)
            if page is hunter:
                press(page, "pick-cell-abstain")
            else:
                press(page, f"pick-cell-{id_of[hunter]}")
            press(page, "btn-vote")
            wait(page, "vote-done")
        shot(pages[0], "vote_done")

        # ---- 獵人：被放逐，確認框後帶走狼同伴 ----
        wait_step(hunter, "HUNTER")
        wait(hunter, "screen-s12-mine")
        wait_open(hunter)
        press(hunter, f"pick-cell-{id_of[wolf]}")
        press(hunter, "btn-hunter-shoot")
        wait(hunter, "dialog-confirm")
        assert name_of[wolf] in text_of(hunter, "dialog-text")
        shot(hunter, "hunter_confirm")
        press(hunter, "dialog-confirm")

        # ---- 遺言：只能送一則，之後不能再發 ----
        wait_step(hunter, "LAST_WORDS")
        speaker = next(p for p in (hunter, wolf) if store(p, "s.server.speaker") == id_of[p])
        wait(speaker, "screen-s22-mine")
        wait_open(speaker)
        fill(speaker, "input-last-words", "我的遺言")
        press(speaker, "btn-last-words-send")
        villagers[1].wait_for_function(
            "(window.__bmt.server.chat ?? []).some((m) => m.content === '我的遺言')"
        )
        assert not has(speaker, "input-last-words") or speaker.wait_for_function(
            "!document.querySelector('[data-testid=\"input-last-words\"]')"
        )
        finish_speeches(pages, "NIGHT_START")

        # ---- 第 2 夜：剩千面狼一隻，刀預言家 ----
        wait_step(faceless, "WOLF")
        wait_open(faceless)
        press(faceless, f"pick-cell-{id_of[seer]}")
        faceless.wait_for_function(
            "document.querySelector('[data-testid=\"wolf-status\"]')?.innerText.includes('已確認')"
        )

        # 被刀的預言家今晚照常查驗（SPEC A5.3），查到好人
        wait_step(seer, "SEER")
        wait_open(seer)
        press(seer, f"pick-cell-{id_of[villagers[1]]}")
        press(seer, "btn-seer-check")
        wait(seer, "seer-result")
        assert text_of(seer, "seer-result") == f"{name_of[villagers[1]]} 是好人"
        press(seer, "btn-seer-ok")

        # ---- 女巫：解藥用過就不再被告知被殺者，改用毒藥 ----
        wait_step(witch, "WITCH")
        wait_open(witch)
        assert not has(witch, "witch-attacked") and not has(witch, "witch-safe")
        assert name_of[seer] not in witch.locator(".main").inner_text().split("要毒一個人嗎")[0]
        press(witch, f"pick-cell-{id_of[villagers[2]]}")
        press(witch, "btn-witch-poison")
        wait(witch, "witch-acted")
        shot(witch, "witch_poison_done")

        # ---- 紀錄：第 2 回合死者兩位，死因不公開 ----
        wait_step(hunter, "DAY_SPEAK")
        state = httpx.get(f"{url}/dev/state").json()["state"]
        causes = {p["id"]: p["death_cause"] for p in state["players"]}
        assert causes[id_of[seer]] == "wolf" and causes[id_of[villagers[2]]] == "poison"
        assert causes[id_of[hunter]] == "vote" and causes[id_of[wolf]] == "hunter"
        press(villagers[1], "tab-players")
        wait(villagers[1], "view-players")
        log = villagers[1].locator("#app").inner_text()
        assert name_of[seer] in log and name_of[villagers[2]] in log
        # 死因要寫清楚（使用者試玩回饋）
        assert f"{name_of[seer]}（被狼人咬死）" in log
        assert f"{name_of[villagers[2]]}（被女巫毒死）" in log
        assert f"{name_of[hunter]}（被放逐）" in log and f"{name_of[wolf]}（被獵人射死）" in log
        assert f"被救：{name_of[victim]}" in log
        shot(villagers[1], "players_log")
        press(villagers[1], "tab-game")

        # ---- 押注：死亡好人可押，死亡狼人沒有入口 ----
        assert not has(wolf, "btn-bet")
        wait(hunter, "btn-bet")
        press(hunter, "btn-bet")
        wait(hunter, "screen-s27")
        press(hunter, f"bet-wolf-{id_of[faceless]}")
        press(hunter, f"bet-faceless-{id_of[faceless]}")
        shot(hunter, "bet")
        press(hunter, "btn-bet-submit")
        hunter.wait_for_function("window.__bmt.server.me.my_bet?.faceless_guess")
        press(hunter, "btn-bet-close")

        # ---- 結算：死因與押注都公開 ----
        press(admin, "tab-players")
        press(admin, "btn-admin-end")
        press(admin, "dialog-confirm")
        target = villagers[1]
        wait_step(target, "END")
        wait(target, "screen-s18")
        # 結算用幽默版
        assert "咬死" in text_of(target, f"end-cause-{id_of[seer]}")
        assert "毒死" in text_of(target, f"end-cause-{id_of[villagers[2]]}")
        assert "放逐" in text_of(target, f"end-cause-{id_of[hunter]}")
        assert "帥" in text_of(target, f"end-cause-{id_of[wolf]}")
        assert text_of(target, f"end-role-{id_of[faceless]}") == "千面狼"
        bet = text_of(target, f"end-bet-{id_of[hunter]}")
        assert "3 分" in bet and name_of[faceless] in bet  # 猜中狼 +1、猜中千面狼 +2
        shot(target, "end_truth")
        browser.close()
    assert errors == []
