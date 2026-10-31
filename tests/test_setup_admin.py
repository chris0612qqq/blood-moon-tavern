"""管理員設定指令（DEV_PLAN P3、CODING_RULES E7）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from server import auth, setup_admin


def _answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, username: str, passwords: list[str]
) -> Path:
    target = tmp_path / "admin.json"
    monkeypatch.setattr("builtins.input", lambda _: username)
    remaining = iter(passwords)
    monkeypatch.setattr("getpass.getpass", lambda _: next(remaining))
    monkeypatch.setattr(setup_admin, "AdminStore", lambda: auth.AdminStore(target))
    return target


def test_saves_hashed_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = _answers(monkeypatch, tmp_path, "boss", ["password1", "password1"])
    setup_admin.main()
    assert auth.AdminStore(target).verify("boss", "password1")
    assert "password1" not in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("username", "passwords"),
    [("", ["password1", "password1"]), ("boss", ["short", "short"]), ("boss", ["password1", "x"])],
)
def test_rejects_bad_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, username: str, passwords: list[str]
) -> None:
    target = _answers(monkeypatch, tmp_path, username, passwords)
    with pytest.raises(SystemExit):
        setup_admin.main()
    assert not target.exists()
