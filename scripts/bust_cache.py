"""發布到 GitHub Pages 前，在檔案網址加版本號（SPEC B1、CODING_RULES N19）。

GitHub Pages 會讓手機快取檔案 10 分鐘，畫面更新後手機還在用舊版。
每次發布帶不同的版本號，手機就會抓新的。只在 pages.yml 裡對發布用的副本執行，不改 repo。

python scripts/bust_cache.py web <版本號>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_IMPORT = re.compile(r"(['\"])(\.{1,2}/[^'\"]+\.js)\1")
_TAG = re.compile(r'(src|href)="((?:js|css)/[^"]+\.(?:js|css))"')


def bust(web: Path, version: str) -> None:
    for path in web.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        path.write_text(_IMPORT.sub(rf"\1\2?v={version}\1", text), encoding="utf-8")
    index = web / "index.html"
    html = index.read_text(encoding="utf-8")
    index.write_text(_TAG.sub(rf'\1="\2?v={version}"', html), encoding="utf-8")


if __name__ == "__main__":
    bust(Path(sys.argv[1]), sys.argv[2])
