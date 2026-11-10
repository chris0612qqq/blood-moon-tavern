"""正式開店腳本的檢查（DEV_PLAN P7、CODING_RULES S8）。"""

from __future__ import annotations

import socket
import time

import pytest

from scripts import run_public


def test_finds_tunnel_url_in_cloudflared_output() -> None:
    line = "2026-11-02T08:25:10Z INF |  https://vista-sunglasses-gallery.trycloudflare.com  |"
    assert run_public.find_tunnel_url(line) == "https://vista-sunglasses-gallery.trycloudflare.com"
    assert run_public.find_tunnel_url("INF Registered tunnel connection") is None


def test_cloudflare_api_error_is_not_a_tunnel_url() -> None:
    """申請通道失敗的錯誤訊息裡有 api.trycloudflare.com，不能當成通道網址發布出去（v4.41）。"""
    line = (
        'ERR Error unmarshaling QuickTunnel response: error="Post '
        '\\"https://api.trycloudflare.com/tunnel\\": dial tcp: i/o timeout"'
    )
    assert run_public.find_tunnel_url(line) is None


def test_dev_mode_never_goes_public() -> None:
    with pytest.raises(SystemExit):
        run_public.refuse_dev_mode({"DEV_MODE": "1"})
    run_public.refuse_dev_mode({})


def test_second_store_refuses_to_open() -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]
        assert run_public.already_open(port)
    assert not run_public.already_open(port)


def test_failed_publish_closes_its_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    """發布沒成功就換通道，舊的要關掉，不能留著一堆 cloudflared（v4.39）。"""
    opened: list[FakeTunnel] = []

    class FakeTunnel:
        def __init__(self) -> None:
            self.url = f"https://try-{len(opened)}.trycloudflare.com"
            self.closed = False
            opened.append(self)

        def close(self) -> None:
            self.closed = True

    def publish(url: str) -> None:
        if len(opened) == 1:
            raise RuntimeError("GitHub Pages 一直沒有更新")

    monkeypatch.setattr(run_public, "Tunnel", FakeTunnel)
    monkeypatch.setattr(run_public, "publish", publish)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    returned: object = run_public.open_tunnel()
    assert returned is opened[1]
    assert [t.closed for t in opened] == [True, False]


def test_waits_long_enough_for_slow_pages() -> None:
    """實測 GitHub Pages 部署完到外面讀得到要 6 分鐘以上（v4.39）。"""
    assert run_public.PUBLISH_TIMEOUT_SECONDS >= 10 * 60


def test_dead_tunnel_is_replaced_at_once_flaky_one_after_three_fails() -> None:
    assert run_public.needs_new_tunnel(alive=False, fails=1)
    assert not run_public.needs_new_tunnel(alive=True, fails=2)
    assert run_public.needs_new_tunnel(alive=True, fails=3)
