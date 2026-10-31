"""聊天、狼人頻道、千面狼切換身分（SPEC A6、A7、A9）。

同一個瀏覽器開 6 個分頁當 6 位真人（CODING_RULES D9）；6 人局有 2 狼，所以千面狼和同伴都是分頁。
store 只用來找出誰拿到什麼角色，發言與檢查都走畫面，也檢查送到手機的資料裡沒有真實發言者。
"""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any

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
    server_url,  # noqa: F401
    store,
    tap,
    wait,
)

pytestmark = pytest.mark.e2e


# 好人繞過畫面，直接送匿名狼人訊息
FORGE_MASK_JS = """() => new Promise((resolve) => {
  const device = new URLSearchParams(location.search).get('dev_device');
  const token = JSON.parse(localStorage.getItem(`bmt.${device}.player_token`));
  const ws = new WebSocket(location.origin.replace('http', 'ws') + '/ws');
  ws.onopen = () => ws.send(JSON.stringify({t: 'auth', token, client_version: 2}));
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.t === 'state') {
      ws.send(JSON.stringify({
        t: 'chat.send', msg_id: 'forge', channel: 'public', kind: 'text', content: 'x', as: 'wolf',
      }));
    }
    if (m.msg_id === 'forge') {
      ws.close();
      resolve(m.code ?? m.t);
    }
  };
})"""


def shot(page: Page, name: str) -> None:
    """設了 BMT_SHOTS 才截圖，給人眼檢查版面用。"""
    folder = os.environ.get("BMT_SHOTS")
    if folder:
        page.wait_for_timeout(300)
        page.screenshot(path=f"{folder}/{name}.png")


def send_chat(page: Page, text: str) -> None:
    fill(page, "chat-input", text)
    page.locator('[data-testid^="chat-send-"]').first.click(timeout=8000)
    page.wait_for_function(
        "(t) => (window.__bmt.server.chat ?? []).some((m) => m.content === t)", arg=text
    )


def wait_message(page: Page, text: str) -> dict[str, Any]:
    """等訊息送達這支手機，回傳手機實際收到的資料。"""
    page.wait_for_function(
        "(t) => (window.__bmt.server.chat ?? []).some((m) => m.content === t)", arg=text
    )
    found: dict[str, Any] = page.evaluate(
        "(t) => window.__bmt.server.chat.find((m) => m.content === t)", text
    )
    return found


def bubble_who(page: Page, message: dict[str, Any]) -> str:
    return page.locator(f'[data-testid="chat-{message["id"]}"] .bubble__who').inner_text()


def bubble_is_mine(page: Page, message: dict[str, Any]) -> bool:
    classes = page.locator(f'[data-testid="chat-{message["id"]}"]').get_attribute("class")
    return "bubble--mine" in (classes or "")


def wait_step(page: Page, *steps: str) -> None:
    page.wait_for_function(
        "(steps) => steps.includes(window.__bmt.server?.step)", arg=list(steps), timeout=60000
    )


def wait_open(page: Page) -> None:
    page.wait_for_function(
        "!document.querySelector('[data-testid=\"countdown\"]')?.textContent.includes('準備')",
        timeout=30000,
    )


def play_night_without_deaths(pages: list[Page]) -> None:
    """狼人空刀、女巫不用藥，讓所有人活到白天。"""
    for _ in range(600):
        if store(pages[0], "s.server.step") in ("DAY_SPEAK", "LAST_WORDS", "VOTE"):
            return
        for page in pages:
            screen = page.evaluate("document.documentElement.dataset.screen")
            if screen == "S8":
                if not store(page, "s.server.me.id in (s.server.me.wolf_pack.picks ?? {})"):
                    tap(page, "pick-cell-none")
            elif screen == "S9":
                if not tap(page, "btn-seer-ok"):
                    cell = page.locator('[data-testid^="pick-cell-"]')
                    if cell.count():
                        # 點的瞬間可能剛好換步驟，格子消失，下一輪再判斷
                        with contextlib.suppress(PlaywrightError):
                            cell.first.click(timeout=800)
                        tap(page, "btn-seer-check")
            elif screen == "S10":
                for testid in (
                    "btn-witch-next",
                    "btn-witch-nosave",
                    "btn-witch-nopoison",
                    "btn-witch-done",
                ):
                    if tap(page, testid):
                        break
            page.wait_for_timeout(20)
    raise AssertionError("never reached day")


def test_chat_wolf_channel_and_faceless_switching(server_url: str) -> None:  # noqa: F811
    errors: list[str] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)

        def new_page(device: str) -> Page:
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{server_url}/?dev_device={device}")
            return page

        # ---- 六個分頁都能各自加入（同一個瀏覽器，CODING_RULES D9） ----
        admin = new_page("p0")
        password = admin_open_room(admin, "auto")
        press(admin, "btn-to-join")
        join_form(admin, "管理", None)
        pages = [admin]
        for i in range(1, 6):
            page = new_page(f"p{i}")
            join_form(page, f"玩{i}", password)
            pages.append(page)

        # ---- 大廳公共聊天 ----
        press(admin, "tab-chat")
        send_chat(admin, "大廳你好")
        lobby = wait_message(pages[1], "大廳你好")
        assert "mine" not in lobby and "real_author" not in lobby
        press(pages[1], "tab-chat")
        assert "大廳你好" in pages[1].locator('[data-testid="chat-list-public"]').inner_text()
        assert bubble_is_mine(admin, wait_message(admin, "大廳你好"))
        assert not bubble_is_mine(pages[1], lobby)
        press(admin, "tab-game")
        press(pages[1], "tab-game")

        press(admin, "btn-start")
        press(admin, "dialog-confirm")
        for page in pages:
            page.wait_for_function("window.__bmt.server?.me?.role")
            press(page, "btn-seen")

        # ---- 找出角色；之後的檢查都走畫面 ----
        role_of = {page: store(page, "s.server.me.role") for page in pages}
        id_of = {page: store(page, "s.server.me.id") for page in pages}
        faceless = next(p for p, r in role_of.items() if r == "faceless")
        ally = next(p for p, r in role_of.items() if r == "wolf")
        target_id = store(faceless, "s.server.me.disguise_info.target")
        goods = [p for p, r in role_of.items() if r not in ("faceless", "wolf")]
        target = next((p for p in pages if id_of[p] == target_id), None)
        bystander = next(p for p in goods if p is not target)
        name_of = {
            id_of[p]: store(p, "s.server.roster.find(r => r.id === s.server.me.id).name")
            for p in pages
        }
        faceless_name = name_of[id_of[faceless]]
        target_name = name_of[target_id]

        # ---- 夜晚：狼人頻道可用本名；公共頻道所有人只讀，草稿保留 ----
        wait_step(faceless, "WOLF")
        wait_open(faceless)
        press(faceless, "tab-wolf")
        send_chat(faceless, "今晚刀誰")
        assert not has(faceless, "chat-as-fake")  # 狼人頻道一律本名（SPEC A6）
        night_msg = wait_message(ally, "今晚刀誰")
        press(ally, "tab-wolf")
        assert bubble_who(ally, night_msg).startswith(faceless_name)
        press(ally, "tab-game")
        press(faceless, "tab-game")

        assert not has(bystander, "tab-wolf")  # 好人沒有狼人頻道
        assert (
            store(bystander, "(s.server.chat ?? []).some(m => m.content === '今晚刀誰')") is False
        )
        press(bystander, "tab-chat")
        wait(bystander, "chat-blocked")
        blocked = bystander.locator('[data-testid="chat-blocked"]').inner_text()
        assert "夜晚" in blocked and not has(bystander, "chat-input")
        press(bystander, "tab-game")

        play_night_without_deaths(pages)
        wait_step(faceless, "DAY_SPEAK", "LAST_WORDS", "VOTE")

        # ---- 白天：千面狼先用本人發言 ----
        press(faceless, "tab-chat")
        wait(faceless, "chat-as-fake")
        assert target_name in faceless.locator('[data-testid="chat-as-fake"]').inner_text()
        press(bystander, "tab-chat")
        send_chat(faceless, "這句是本人")
        seen = wait_message(bystander, "這句是本人")
        assert seen["display_player_id"] == id_of[faceless]

        # ---- 切到假扮：送出鈕寫出假扮對象，避免誤發（SPEC C9 #7） ----
        press(faceless, "chat-as-fake")
        fill(faceless, "chat-input", "這句是假扮")
        send_button = faceless.locator('[data-testid^="chat-send-"]').first
        faceless.wait_for_function(
            "(n) => document.querySelector('[data-testid^=\"chat-send-\"]')?.innerText.includes(n)",
            arg=target_name,
        )
        send_button.click(timeout=8000)

        shot(faceless, "1_faceless_after_fake")
        fake = wait_message(bystander, "這句是假扮")
        assert fake["display_player_id"] == target_id
        assert "real_author" not in fake and "mine" not in fake and "disguised_by_me" not in fake
        assert id_of[faceless] not in json.dumps(fake)  # 資料裡就沒有真實發言者（SPEC A7）
        assert bubble_who(bystander, fake).strip() == target_name

        # 狼同伴也看不出來（SPEC A6）
        ally_view = wait_message(ally, "這句是假扮")
        assert id_of[faceless] not in json.dumps(ally_view) and "real_author" not in ally_view

        # 被假扮者看到的是掛著自己名字、但不是自己泡泡的訊息（SPEC A6）
        if target is not None:
            press(target, "tab-chat")
            target_view = wait_message(target, "這句是假扮")
            assert "mine" not in target_view
            assert bubble_who(target, target_view).strip() == target_name
            assert not bubble_is_mine(target, target_view)
            press(target, "tab-game")

        # 千面狼自己看得到標記
        own = wait_message(faceless, "這句是假扮")
        assert own["disguised_by_me"] is True
        assert "你以" in bubble_who(faceless, own)

        # ---- 切回本人（這次測試的重點）：送出鈕不再寫假扮對象，訊息掛回本名 ----
        press(faceless, "chat-as-self")
        fill(faceless, "chat-input", "切回本人了")
        faceless.wait_for_function(
            "(n) => !document.querySelector('[data-testid^=\"chat-send-\"]')"
            "?.innerText.includes(n)",
            arg=target_name,
        )
        faceless.locator('[data-testid^="chat-send-"]').first.click(timeout=8000)
        back = wait_message(bystander, "切回本人了")
        shot(faceless, "2_faceless_back_to_self")
        shot(bystander, "3_bystander_view")
        assert back["display_player_id"] == id_of[faceless]
        assert bubble_who(bystander, back).strip() == faceless_name

        # 再切一次假扮又切回，確認沒有卡在某個身分
        press(faceless, "chat-as-fake")
        send_chat(faceless, "第二次假扮")
        assert wait_message(bystander, "第二次假扮")["display_player_id"] == target_id
        press(faceless, "chat-as-self")
        send_chat(faceless, "第二次切回")
        assert wait_message(bystander, "第二次切回")["display_player_id"] == id_of[faceless]

        # ---- 一般狼人：可以切「狼人」匿名嚇人，再切回本人裝好人（SPEC v4.9） ----
        press(ally, "tab-chat")
        wait(ally, "chat-as-wolf")
        assert not has(ally, "chat-as-fake")  # 假扮是千面狼獨有
        send_chat(ally, "同伴發言")
        assert wait_message(bystander, "同伴發言")["display_player_id"] == id_of[ally]

        press(ally, "chat-as-wolf")
        ally.wait_for_function(
            "document.querySelector('[data-testid^=\"chat-send-\"]')?.innerText.includes('狼人')"
        )
        send_chat(ally, "嗷嗚今晚吃誰")
        scary = wait_message(bystander, "嗷嗚今晚吃誰")
        assert scary["is_wolf_mask"] is True and scary["display_player_id"] is None
        assert id_of[ally] not in json.dumps(scary) and "real_author" not in scary
        assert bubble_who(bystander, scary).strip() == "狼人"
        assert not bubble_is_mine(bystander, scary)
        shot(bystander, "5_bystander_sees_masked_wolf")

        # 千面狼是同伴也看不出是誰
        peer = wait_message(faceless, "嗷嗚今晚吃誰")
        assert id_of[ally] not in json.dumps(peer) and bubble_who(faceless, peer).strip() == "狼人"

        own_scary = wait_message(ally, "嗷嗚今晚吃誰")
        assert own_scary["masked_by_me"] is True
        assert "你以狼人" in bubble_who(ally, own_scary)
        shot(ally, "6_wolf_after_mask")

        press(ally, "chat-as-self")
        ally.wait_for_function(
            "!document.querySelector('[data-testid^=\"chat-send-\"]')?.innerText.includes('狼人')"
        )
        send_chat(ally, "我是好人喔")
        innocent = wait_message(bystander, "我是好人喔")
        assert innocent["display_player_id"] == id_of[ally] and innocent["is_wolf_mask"] is False

        # 千面狼也能用狼人身分
        press(faceless, "chat-as-wolf")
        send_chat(faceless, "千面也嗷")
        assert wait_message(bystander, "千面也嗷")["is_wolf_mask"] is True
        press(faceless, "chat-as-self")

        # 好人沒有切換器，也不能硬送
        assert not has(bystander, "chat-as-wolf") and not has(bystander, "chat-as-self")
        forged = bystander.evaluate(FORGE_MASK_JS)
        assert forged == "forbidden"

        # 夜晚匿名身分關閉：切換器消失，也不會誤用舊身分（另有單元測試涵蓋夜晚拒絕）

        # ---- 白天狼人頻道仍是本名，好人仍收不到 ----
        press(faceless, "tab-wolf")
        wait(faceless, "chat-list-wolf")  # 等分頁切完才檢查
        assert not has(faceless, "chat-as-fake")
        send_chat(faceless, "白天狼話")
        shot(faceless, "4_faceless_wolf_channel")
        assert wait_message(ally, "白天狼話")["display_player_id"] == id_of[faceless]
        assert (
            store(bystander, "(s.server.chat ?? []).some(m => m.content === '白天狼話')") is False
        )
        press(faceless, "tab-game")

        # ---- 結算：全部揭曉 ----
        press(admin, "tab-players")
        press(admin, "btn-admin-end")
        press(admin, "dialog-confirm")
        wait_step(bystander, "END")
        press(bystander, "tab-game")
        wait(bystander, "screen-s18")  # 結算標題，確定已切回遊戲分頁
        text = bystander.locator("#app").inner_text()
        assert f"{faceless_name} 假扮 {target_name}" in text  # 看真相：假扮訊息的真身
        ally_name = name_of[id_of[ally]]
        assert f"{ally_name} 假扮 狼人" in text  # 看真相：匿名狼人的真身
        press(bystander, "tab-chat")
        ended = wait_message(bystander, "這句是假扮")
        assert ended["real_author"] == id_of[faceless]
        assert faceless_name in bubble_who(bystander, ended)
        press(bystander, "tab-wolf")  # 結算後所有人都能看狼人頻道（SPEC A7）
        wolf_text = bystander.locator('[data-testid="chat-list-wolf"]').inner_text()
        assert "今晚刀誰" in wolf_text and "白天狼話" in wolf_text
        browser.close()
    assert errors == []
