"""版面健檢：12 支最小尺寸的手機玩完整局，每個畫面都量一次有沒有超出、裁切、按鈕太小或疊在一起。

人眼看截圖抓得到醜，但抓不完；這裡把量得出來的問題變成回歸測試。設 BMT_SHOTS 會同時截圖。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import pytest
from playwright.sync_api import Page, sync_playwright

from tests.e2e.test_full_game import (
    act,
    admin_open_room,
    has,
    join_form,
    press,
    running_server,
    store,
    tap,
    wait,
)

pytestmark = pytest.mark.e2e
SMALLEST = {"width": 320, "height": 568}  # iPhone SE 第一代：撐得住這個，其他手機都撐得住
PLAYERS = 12
GAME_LIMIT_SECONDS = 540
MIN_TAP = 44  # 手指點得到的最小高度（SPEC C7）

AUDIT_JS = """() => {
  const found = [];
  const width = window.innerWidth;
  const label = (el) => el.dataset.testid || `${el.tagName.toLowerCase()}.${el.className}`;
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    const css = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && css.visibility !== 'hidden' && css.display !== 'none';
  };
  // 刻意可左右滑的區塊（看真相的每夜標籤）裡面超出是正常的
  const inScroller = (el) => el.closest('.truth-tabs') !== null;
  if (document.documentElement.scrollWidth > width) found.push('整頁可左右滑');
  for (const el of document.querySelectorAll('#app *, .overlay *')) {
    if (!shown(el) || inScroller(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > width + 1 || r.left < -1) found.push(`超出螢幕：${label(el)}`);
    const css = getComputedStyle(el);
    if (el.children.length === 0 && el.textContent.trim()
        && css.overflowX !== 'visible' && el.scrollWidth > el.clientWidth + 1
        && el.tagName !== 'TEXTAREA' && el.tagName !== 'INPUT') {
      found.push(`文字被裁切：${label(el)}`);
    }
  }
  const tappable = [...document.querySelectorAll('#app button, .overlay button, #app input')]
    .filter(shown).filter((el) => !inScroller(el));
  for (const el of tappable) {
    const r = el.getBoundingClientRect();
    if (r.height < MIN_TAP - 0.5) found.push(`太小（高 ${Math.round(r.height)}）：${label(el)}`);
  }
  for (let i = 0; i < tappable.length; i += 1) {
    for (let j = i + 1; j < tappable.length; j += 1) {
      const a = tappable[i].getBoundingClientRect();
      const b = tappable[j].getBoundingClientRect();
      const overlap = Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
        && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
      // 不同區塊（內容區捲到分頁列後面）不算重疊，畫面上看不到也按不到
      const region = (el) => el.closest('.overlay, .main, .tabs, .status');
      if (overlap && region(tappable[i]) === region(tappable[j])) {
        found.push(`按鈕重疊：${label(tappable[i])} / ${label(tappable[j])}`);
      }
    }
  }
  return [...new Set(found)];
}""".replace("MIN_TAP", str(MIN_TAP))


class Audit:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.problems: dict[str, list[str]] = {}
        self.folder = os.environ.get("BMT_SHOTS")

    def look(self, page: Page, note: str = "") -> None:
        """同一種畫面只量一次；開著對話框、切到別的標籤都算不同畫面。"""
        info: dict[str, Any] = page.evaluate(
            """() => ({
              screen: document.documentElement.dataset.screen,
              step: window.__bmt?.server?.step ?? '',
              overlay: document.querySelector('.overlay') ? 'dialog' : '',
            })"""
        )
        key = "_".join(x for x in (info["screen"], info["step"], info["overlay"], note) if x)
        if key in self.seen:
            return
        self.seen.add(key)
        page.wait_for_timeout(150)  # 等這一影格畫完
        found: list[str] = page.evaluate(AUDIT_JS)
        if found:
            self.problems[key] = found
        if self.folder:
            page.screenshot(path=f"{self.folder}/{key}.png")


def walk_tabs(page: Page, audit: Audit, who: str) -> None:
    for tab, view in (
        ("tab-chat", "chat-list-public"),
        ("tab-wolf", "chat-list-wolf"),
        ("tab-players", "view-players"),
        ("tab-role", "role-card"),
    ):
        if not has(page, tab):
            continue
        press(page, tab)
        wait(page, view)
        audit.look(page, f"{who}_{tab}")
    box = page.locator('[data-testid="role-card"]').bounding_box()
    if box is not None:
        page.mouse.move(box["x"] + 30, box["y"] + 30)
        page.mouse.down()
        wait(page, "role-name")
        audit.look(page, f"{who}_role_open")
        page.mouse.up()
    press(page, "tab-game")


def walk_host(host: Page, audit: Audit, note: str) -> None:
    for tab in ("host-tab-reveal", "host-tab-status", "host-tab-voice"):
        if has(host, tab):
            press(host, tab)
            audit.look(host, f"{note}_{tab}")


def test_every_screen_fits_the_smallest_phone() -> None:
    audit = Audit()
    errors: list[str] = []
    with running_server(6) as url, sync_playwright() as driver:
        browser = driver.chromium.launch()

        def new_page() -> Page:
            page = browser.new_context(viewport=SMALLEST, has_touch=True).new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            return page

        host = new_page()
        audit.look(host, "start")
        press(host, "btn-admin-key")
        wait(host, "input-admin_user")
        audit.look(host, "login")
        host.reload()
        password = admin_open_room(host, "god")
        audit.look(host, "s3")
        press(host, "btn-to-control")
        wait(host, "screen-s20")
        audit.look(host, "lobby")

        pages = [new_page() for _ in range(PLAYERS)]
        audit.look(pages[0], "join")
        for i, page in enumerate(pages):
            join_form(page, f"玩{chr(65 + i)}", password)  # 名字恰 2 字
        audit.look(pages[0], "lobby")
        audit.look(host, "lobby_full")
        press(host, "btn-start")
        wait(host, "dialog-confirm")
        audit.look(host, "start_confirm")
        press(host, "dialog-confirm")
        for page in pages:
            page.wait_for_function("window.__bmt.server?.me?.role")
        audit.look(pages[0], "role")

        walked: set[str] = set()
        deadline = time.time() + GAME_LIMIT_SECONDS
        while store(host, "s.server && s.server.step") != "END":
            assert time.time() < deadline, sorted(audit.seen)
            step = store(host, "s.server.step")
            walk_host(host, audit, "host")
            tap(host, "dialog-confirm")
            done = store(
                host,
                "s.server.host && s.server.host.actors.every(a => s.server.host.done.includes(a))",
            )
            if done or store(host, "s.server.host && s.server.host.timed_out"):
                tap(host, "btn-host-next")
            for page in pages:
                role = store(page, "s.server.me && s.server.me.role")
                # 每種角色在遊戲畫面（不是看角色的時候）走一次所有分頁
                if role and role not in walked and step == "DAY_SPEAK":
                    walked.add(role)
                    walk_tabs(page, audit, role)
                audit.look(page, role or "")
                act(page)

        for page in pages[:2]:
            wait(page, "screen-s18", timeout=20000)
            audit.look(page, "end")
        walk_tabs(pages[0], audit, "end")
        walk_host(host, audit, "end")
        audit.look(host, "end")
        browser.close()
    if audit.folder:
        with open(f"{audit.folder}/problems.json", "w", encoding="utf-8") as out:
            json.dump(audit.problems, out, ensure_ascii=False, indent=1)
    assert errors == []
    assert audit.problems == {}
