"""把 web/img/icon.svg 轉成主畫面要用的 PNG（SPEC S23、CODING_RULES V11a）。

iPhone 的主畫面圖示只吃 PNG，所以改了 icon.svg 之後跑一次，產生的 PNG 一起 commit。

python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

IMG = Path(__file__).resolve().parent.parent / "web" / "img"
SIZES = {"icon-180.png": 180, "icon-192.png": 192, "icon-512.png": 512}


def main() -> None:
    svg = (IMG / "icon.svg").read_text(encoding="utf-8")
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        for name, size in SIZES.items():
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(
                f"<style>html,body{{margin:0}}svg{{width:{size}px;height:{size}px;display:block}}</style>{svg}"
            )
            page.screenshot(path=str(IMG / name))
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
