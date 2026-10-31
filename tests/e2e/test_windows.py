"""每個視窗的每個分頁都走一遍，並逐回合核對遊戲紀錄（SPEC C3「玩家 → 紀錄」）。

答案來自伺服器的 /dev/state；畫面只能顯示公開資訊，所以同時檢查不該出現的東西。
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx
import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    MOBILE,
    act,
    admin_open_room,
    has,
    join_form,
    press,
    server_url,  # noqa: F401
    store,
    wait,
)

pytestmark = pytest.mark.e2e
GAME_LIMIT_SECONDS = 520
SECRET_WORDS = ("千面狼",)
# SPEC A5.2：每個角色卡一定要講到的能力
ROLE_KEYWORDS = {
    "wolf": ("咬死", "不咬", "同伴", "狼人頻道", "匿名"),
    "faceless": ("咬", "匿名", "假扮", "2 回合"),
    "villager": ("投票",),
    "seer": ("查驗",),
    "witch": ("解藥", "毒藥", "首夜", "同一晚"),
    "hunter": ("帶走", "不開槍", "毒死"),
}


def shot(page: Page, name: str) -> None:
    folder = os.environ.get("BMT_SHOTS")
    if folder:
        page.wait_for_timeout(250)
        page.screenshot(path=f"{folder}/{name}.png")


def dev_state(url: str) -> dict[str, Any]:
    state: dict[str, Any] = httpx.get(f"{url}/dev/state").json()["state"]
    return state


def round_panels(page: Page) -> dict[int, str]:
    """讀「玩家 → 紀錄」每回合的文字。"""
    press(page, "tab-players")
    wait(page, "view-players")
    page.wait_for_timeout(120)
    panels = {}
    for text in page.locator(".panel").all_inner_texts():
        match = re.match(r"第 (\d+) 回合", text)
        if match:
            panels[int(match.group(1))] = text
    return panels


def verify_log(
    page: Page, url: str, label: str, problems: list[str], snap: str | None = None
) -> None:
    """已結束的回合：死者、每一票都要和伺服器一致，不能多也不能少。"""
    state = dev_state(url)
    panels = round_panels(page)
    state_after = dev_state(url)
    names = {p["id"]: p["name"] for p in state["players"]}
    current = state_after["round_no"]
    ended = state_after["step"] == "END"
    for votes in state["votes"]:
        number = votes["round_no"]
        finished = number < current or ended
        if number == current and state["step"] != state_after["step"]:
            continue  # 讀取途中換步驟，這回合下一次再核對
        text = panels.get(number)
        if text is None:
            if finished:
                problems.append(f"{label}: 第 {number} 回合沒有紀錄")
            continue
        expected_dead = sorted(
            names[p["id"]] for p in state["players"] if p["death_round"] == number
        )
        match = re.search(r"死亡：(.*)", text)
        shown = (match.group(1) if match else "").strip()
        # 每位死者後面括號寫死因：「小美（被狼人咬死）」
        shown_dead = [] if shown == "無" else sorted(x.split("（")[0] for x in shown.split("、"))
        plain = {
            "wolf": "被狼人咬死",
            "poison": "被女巫毒死",
            "vote": "被放逐",
            "hunter": "被獵人射死",
            "kick": "被踢出局",
        }
        for player in state["players"]:
            if player["death_round"] == number and player["death_cause"] in plain:
                wanted = f"{player['name']}（{plain[player['death_cause']]}）"
                if wanted not in shown:
                    problems.append(f"{label}: 第 {number} 回合少了「{wanted}」：{shown}")
        if shown_dead != expected_dead:
            problems.append(f"{label}: 第 {number} 回合死者 {shown_dead}，應為 {expected_dead}")
        lines = {line.strip() for line in text.splitlines() if "→" in line}
        if votes["revealed"]:
            want = {
                f"{names[voter]} → {names[target] if target else '棄票'}"
                for voter, target in votes["ballots"].items()
            }
            if lines != want:
                problems.append(f"{label}: 第 {number} 回合票 {sorted(lines)}，應為 {sorted(want)}")
        elif lines:
            problems.append(f"{label}: 第 {number} 回合揭曉前就看得到票 {sorted(lines)}")
    if not ended:
        for word in SECRET_WORDS:
            if word in page.locator("#app").inner_text():
                problems.append(f"{label}: 玩家分頁出現秘密字眼 {word}")
    if snap:
        shot(page, snap)
    press(page, "tab-game")


def check_tabs(
    page: Page, label: str, role: str, problems: list[str], snap: bool, ended: bool = False
) -> None:
    """走過這個視窗的每個分頁。結算後所有人都能看狼人頻道（SPEC A7）。"""
    is_wolf = ended or role in ("wolf", "faceless")
    if has(page, "tab-wolf") != is_wolf:
        problems.append(f"{label}: 狼人頻道分頁 應{'有' if is_wolf else '無'}")
    press(page, "tab-chat")
    wait(page, "chat-list-public")
    if snap:
        shot(page, f"{label}_chat")
    if is_wolf:
        press(page, "tab-wolf")
        wait(page, "chat-list-wolf")
        if snap:
            shot(page, f"{label}_wolf")
    press(page, "tab-role")
    wait(page, "role-card")
    if has(page, "role-name"):
        problems.append(f"{label}: 沒按住就看得到角色")
    box = page.locator('[data-testid="role-card"]').bounding_box()
    if box is not None:
        page.mouse.move(box["x"] + 30, box["y"] + 30)
        page.mouse.down()
        wait(page, "role-name")
        ability = page.locator('[data-testid="role-ability"]').inner_text()
        for word in ROLE_KEYWORDS.get(role, ()):
            if word not in ability:
                problems.append(f"{label}: 角色說明少了「{word}」：{ability}")
        if not page.locator('[data-testid="role-faction"]').inner_text():
            problems.append(f"{label}: 角色卡沒有陣營")
        if not page.locator('[data-testid="role-story"]').inner_text():
            problems.append(f"{label}: 角色卡沒有故事")
        if snap:
            shot(page, f"{label}_role")
        page.mouse.up()
        page.wait_for_function("!document.querySelector('[data-testid=\"role-name\"]')")
    press(page, "tab-game")
    if snap:
        shot(page, f"{label}_game")


def test_every_window_every_tab_and_game_log(server_url: str) -> None:  # noqa: F811
    errors: list[str] = []
    problems: list[str] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(viewport=MOBILE)

        def new_page(device: str) -> Page:
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(f"{device}: {e}"))
            page.goto(f"{server_url}/?dev_device={device}")
            return page

        admin = new_page("w0")
        password = admin_open_room(admin, "auto")
        press(admin, "btn-to-join")
        join_form(admin, "管理", None)
        pages = [admin]
        for i in range(1, 8):
            page = new_page(f"w{i}")
            join_form(page, f"玩{i}", password)
            pages.append(page)
        # 大廳：名單每個視窗一致
        for page in pages:
            page.wait_for_function("window.__bmt.server.roster.length === 8")
        shot(admin, "lobby")
        press(admin, "btn-start")
        press(admin, "dialog-confirm")
        for page in pages:
            page.wait_for_function("window.__bmt.server?.me?.role")
        roles = {page: store(page, "s.server.me.role") for page in pages}
        labels = {page: f"w{i}_{roles[page]}" for i, page in enumerate(pages)}

        # 第一次：每個視窗都走遍所有分頁並截圖
        for page in pages:
            check_tabs(page, labels[page], roles[page], problems, snap=True)

        checked_rounds: set[int] = set()
        verified_rounds: set[int] = set()
        deadline = time.time() + GAME_LIMIT_SECONDS
        reloaded = False
        while time.time() < deadline:
            state = dev_state(server_url)
            if state["step"] == "END":
                break
            # 每進入新一回合的夜晚，核對每個視窗的紀錄
            if state["round_no"] not in checked_rounds and state["round_no"] >= 1:
                checked_rounds.add(state["round_no"])
                if state["round_no"] >= 2:
                    verified_rounds.add(state["round_no"])
                    for page in pages:
                        snap = f"log_round{state['round_no']}" if page is pages[0] else None
                        verify_log(page, server_url, labels[page], problems, snap)
                    if not reloaded:
                        # 重新整理後紀錄不能掉（資料來自伺服器的完整狀態）
                        reloaded = True
                        pages[1].reload()
                        pages[1].wait_for_function("window.__bmt.server?.me?.role")
                        verify_log(pages[1], server_url, f"{labels[pages[1]]}(重整後)", problems)
            for page in pages:
                act(page)
                page.wait_for_timeout(5)
        else:
            final_state = dev_state(server_url)
            summary = {
                "step": final_state["step"],
                "round": final_state["round_no"],
                "pause": final_state["pause"],
                "alive": sum(p["alive"] for p in final_state["players"]),
                "actors": final_state["actors"],
                "done": final_state["done"],
            }
            raise AssertionError(f"game did not end in time: {summary}")

        # 結算：每個視窗都核對最終紀錄與全部角色
        final = dev_state(server_url)
        names = {p["id"]: p["name"] for p in final["players"]}
        for page in pages:
            wait(page, "screen-s18", timeout=20000)
            text = page.locator("#app").inner_text()
            for player in final["players"]:
                if player["name"] not in text:
                    problems.append(f"{labels[page]}: 結算少了 {player['name']}")
            if page.locator('[data-testid^="end-role-"]').count() != len(final["players"]):
                problems.append(f"{labels[page]}: 結算角色數不對")
            for player in final["players"]:
                if player["death_cause"]:
                    cause = page.locator(f'[data-testid="end-cause-{player["id"]}"]')
                    if cause.count() != 1:
                        problems.append(f"{labels[page]}: {player['name']} 沒顯示死因")
            verify_log(page, server_url, f"{labels[page]}(結算)", problems)
            check_tabs(
                page,
                f"{labels[page]}_end",
                roles[page],
                problems,
                snap=page is pages[0],
                ended=True,
            )
        shot(pages[0], "end_summary")
        # 看真相：每夜一個標籤，內容與伺服器一致（試玩回饋）
        names_by_id = {p["id"]: p["name"] for p in final["players"]}
        viewer = pages[0]
        expected_tabs = min(final["round_no"], 7)
        assert viewer.locator('[data-testid^="truth-tab-"]').count() == expected_tabs + 1
        for night in final["nights"][:7]:
            number = night["round_no"]
            press(viewer, f"truth-tab-{number}")
            wait(viewer, f"truth-night-{number}")
            shown = viewer.locator(f'[data-testid="truth-night-{number}"]').inner_text()
            if night["wolf_target"]:
                assert f"咬 {names_by_id[night['wolf_target']]}" in shown, shown
            else:
                assert "不咬" in shown, shown
            if night["seer_target"]:
                assert f"查驗 {names_by_id[night['seer_target']]}" in shown, shown
            if night["witch_poison"]:
                assert f"毒 {names_by_id[night['witch_poison']]}" in shown, shown
            for label in ("狼人", "預言家", "女巫", "天亮結果", "白天投票"):
                assert label in shown, shown
            shot(viewer, f"truth_night_{number}")
        press(viewer, "truth-tab-summary")
        assert names
        assert final["round_no"] < 3 or verified_rounds  # 中途核對真的有跑到
        browser.close()
    assert errors == []
    assert problems == []
