"""正式開店腳本的檢查（DEV_PLAN P7、CODING_RULES S8）。"""

from __future__ import annotations

import pytest

from scripts import run_public


def test_public_origin_from_tailscale_status() -> None:
    status = {"Self": {"DNSName": "desktop-abc.tail123.ts.net."}}
    assert run_public.public_origin(status) == "https://desktop-abc.tail123.ts.net"


def test_not_logged_in_stops() -> None:
    with pytest.raises(SystemExit):
        run_public.public_origin({"Self": {"DNSName": ""}})


def test_dev_mode_never_goes_public() -> None:
    with pytest.raises(SystemExit):
        run_public.refuse_dev_mode({"DEV_MODE": "1"})
    run_public.refuse_dev_mode({})
