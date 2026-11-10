"""守衛從畫面實際操作（SPEC v4.42）：10 人局，管理員把守衛指定給一位真人，其他用機器人補。

天黑後先叫守衛；守衛看不到自己的格子；選了就定案；角色卡記下守了誰；
第二晚不能再守同一人，畫面會說明。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    FAKE_SPEECH_JS,
    MOBILE,
    admin_open_room,
    join_form,
    press,
    running_server,
    store,
    tap,
    wait,
)

pytestmark = pytest.mark.e2e
BOTS = 8  # 管理員＋守衛＋8 個機器人＝10 人，剛好開始有守衛


@pytest.fixture
def slow_server() -> Iterator[str]:
    with running_server(2) as url:
        yield url


def wait_guard_turn(guard: Page, others: list[Page], round_no: int) -> bool:
    """等到第 round_no 夜輪到守衛；遊戲先結束或守衛出局就回 False。

    等的時候真人的發言、遺言都直接結束，不然白天要等每個人講滿時間。
    """
    ready = """(n) => {
      const s = window.__bmt.server;
      return Boolean(s && (s.step === 'END' || !s.me.alive
        || (s.step === 'GUARD' && s.round_no === n && s.me.is_actor)));
    }"""
    for _ in range(1200):
        if guard.evaluate(ready, round_no):
            return bool(store(guard, "s.server.step === 'GUARD'"))
        for page in [guard, *others]:
            for testid in ("btn-speak-end", "btn-last-words-end", "btn-seen"):
                tap(page, testid)
        guard.wait_for_timeout(250)
    raise AssertionError(f"guard never got night {round_no}")


def test_guard_through_the_ui(slow_server: str) -> None:
    errors: list[str] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)
        context.add_init_script(FAKE_SPEECH_JS)

        def new_page(device: str) -> Page:
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(f"{device}: {e}"))
            page.goto(f"{slow_server}/?dev_device={device}")
            return page

        admin = new_page("g0")
        password = admin_open_room(admin, "auto")
        press(admin, "btn-to-join")
        join_form(admin, "管理", None)
        guard = new_page("g1")
        join_form(guard, "☆阿守☆", password)
        admin.evaluate(
            """async (n) => {
              const { api } = await import('/js/net.js');
              const { loadTokens } = await import('/js/session.js');
              await api(`/api/admin/bots?count=${n}`, { method: 'POST', auth: loadTokens().admin });
            }""",
            BOTS,
        )
        admin.wait_for_function("window.__bmt.server.roster.length === 10")
        # 開始前確認視窗列出守衛（SPEC v4.42）
        guard_id = store(guard, "s.server.me.id")
        press(admin, f"lobby-menu-{guard_id}")
        press(admin, f"role-guard-{guard_id}")
        wait(admin, f"planned-{guard_id}")
        press(admin, "lobby-menu-close")
        press(admin, "btn-start")
        wait(admin, "dialog-text")
        assert "守衛" in admin.locator('[data-testid="dialog-text"]').inner_text()
        press(admin, "dialog-confirm")

        guard.wait_for_function("window.__bmt.server?.me?.role === 'guard'")
        for page in (admin, guard):
            press(page, "btn-seen")

        # 第 1 夜：天黑後第一個睜眼的是守衛；格子裡沒有自己
        assert wait_guard_turn(guard, [admin], 1)
        wait(guard, "screen-s28")
        assert guard.locator(f'[data-testid="pick-cell-{guard_id}"]').count() == 0
        target = store(guard, "s.server.me.eligible_targets[0]")
        guard.locator(f'[data-testid="pick-cell-{target}"]').click()
        press(guard, "btn-guard")
        wait(guard, "guard-done")
        target_name = store(guard, f"s.server.roster.find((r) => r.id === '{target}').name")
        assert target_name in guard.locator('[data-testid="guard-done"]').inner_text()
        # 旁白先放盾牌音效才念；守衛不用等念完就能選，所以這裡等它念出來
        admin.wait_for_function("window.__spoken.some((s) => s.text.startsWith('守衛請睜眼'))")

        # 第 2 夜：不能再守同一人，畫面會說明原因
        if wait_guard_turn(guard, [admin], 2):
            wait(guard, "guard-blocked")
            assert target_name in guard.locator('[data-testid="guard-blocked"]').inner_text()
            assert guard.locator(f'[data-testid="pick-cell-{target}"]').count() == 0
            press(guard, "pick-cell-none")
            press(guard, "btn-guard")
            wait(guard, "guard-done")
        assert errors == []
        browser.close()
