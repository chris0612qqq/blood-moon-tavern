"""發布前加版本號（scripts/bust_cache.py）。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from scripts import bust_cache

ROOT = Path(__file__).resolve().parent.parent
# 相對路徑的 import 後面沒有接版本號，就是漏掉了
_MISSED = re.compile(r"['\"]\.{1,2}/[^'\"?]+\.js['\"]")


def test_every_local_file_gets_the_version(tmp_path: Path) -> None:
    web = tmp_path / "web"
    shutil.copytree(ROOT / "web", web)
    bust_cache.bust(web, "42")
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'src="js/app.js?v=42"' in html and 'href="css/base.css?v=42"' in html
    app = (web / "js" / "app.js").read_text(encoding="utf-8")
    assert "from './net.js?v=42';" in app
    for path in web.rglob("*.js"):
        assert not _MISSED.search(path.read_text(encoding="utf-8")), path.name
