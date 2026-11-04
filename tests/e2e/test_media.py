"""聊天照片與電子音訊息（SPEC A9、v4.24）。"""

from __future__ import annotations

import struct
import zlib

import pytest
from playwright.sync_api import sync_playwright

from tests.e2e.test_full_game import (  # noqa: F401
    MOBILE,
    fill,
    has,
    join_form,
    press,
    server_url,
    store,
    wait,
)
from tests.e2e.test_lobby_tools import admin_in_lobby

pytestmark = pytest.mark.e2e

RECORD_SPEECH_JS = """
window.__said = [];
speechSynthesis.speak = (u) => window.__said.push({ text: u.text, pitch: u.pitch, rate: u.rate });
"""


def tiny_png() -> bytes:
    """4×4 紅色 PNG；手機端會重新畫一次、轉成 JPEG 再上傳。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(bytes([0]) + bytes([255, 0, 0]) * 4 for _ in range(4))
    header = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return (
        signature
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_photo_and_voice_messages(server_url: str) -> None:  # noqa: F811
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        admin = browser.new_context(viewport=MOBILE).new_page()
        admin_in_lobby(admin, server_url)
        player = browser.new_context(viewport=MOBILE).new_page()
        player.add_init_script(RECORD_SPEECH_JS)
        player.goto(server_url)
        fill(player, "input-join_password", "1234")
        join_form(player, "玩甲", None)

        # 照片：上傳後兩邊都看得到，點了全螢幕，關得掉
        press(admin, "tab-chat")
        admin.locator('[data-testid="chat-photo-input"]').set_input_files(
            files=[{"name": "a.png", "mimeType": "image/png", "buffer": tiny_png()}]
        )
        press(player, "tab-chat")
        player.wait_for_function(
            "(() => { const img = document.querySelector('[data-testid^=\"chat-photo-\"]');"
            " return img && img.complete && img.naturalWidth > 0; })()",
            timeout=15000,
        )
        player.locator('[data-testid^="chat-photo-"]').first.click()
        wait(player, "lightbox")
        press(player, "lightbox-close")
        player.wait_for_function("!document.querySelector('[data-testid=\"lightbox\"]')")

        # 電子音：打字後按 🔊 送出，點一下才念，不會收到就念
        fill(admin, "chat-input", "大家好")
        admin.locator('[data-testid^="chat-tts-send-public-"]').click()
        player.wait_for_function("(window.__bmt.server.chat ?? []).some((m) => m.kind === 'tts')")
        # 收到時不自動念（點擊時會念無聲的「。」解鎖語音，不算）
        assert not player.evaluate("window.__said.some((s) => s.text === '大家好')")
        # 只能用聽的：泡泡只有喇叭，發的人自己也一樣（SPEC v4.36）
        assert player.locator("button.tts").last.inner_text().strip() == "🔊"
        admin.wait_for_selector("button.tts")
        assert admin.locator("button.tts").last.inner_text().strip() == "🔊"
        player.locator("button.tts").last.click()
        player.wait_for_function("window.__said.some((s) => s.text === '大家好')")
        said = player.evaluate("window.__said.find((s) => s.text === '大家好')")
        assert said["pitch"] > 1  # 一般玩家的音調；狼人身分很低（另見 test_wolf_schedule）
        assert not has(player, "sched-open")  # 不是狼人沒有定時電子音
        assert store(player, "s.server.chat.at(-1).kind") == "tts"
        browser.close()
