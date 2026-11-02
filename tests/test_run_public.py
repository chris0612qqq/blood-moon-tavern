"""正式開店腳本的檢查（DEV_PLAN P7、CODING_RULES S8）。"""

from __future__ import annotations

import pytest

from scripts import run_public


def test_finds_tunnel_url_in_cloudflared_output() -> None:
    line = "2026-11-02T08:25:10Z INF |  https://vista-sunglasses-gallery.trycloudflare.com  |"
    assert run_public.find_tunnel_url(line) == "https://vista-sunglasses-gallery.trycloudflare.com"
    assert run_public.find_tunnel_url("INF Registered tunnel connection") is None


def test_dev_mode_never_goes_public() -> None:
    with pytest.raises(SystemExit):
        run_public.refuse_dev_mode({"DEV_MODE": "1"})
    run_public.refuse_dev_mode({})
