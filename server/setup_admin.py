"""設定管理員帳密：python -m server.setup_admin（DEV_PLAN P3；setup.bat 也呼叫這裡）。"""

from __future__ import annotations

import getpass

from server.auth import AdminStore


def main() -> None:
    username = input("管理員帳號：").strip()
    password = getpass.getpass("管理員密碼（至少 8 碼）：")
    again = getpass.getpass("再輸入一次：")
    if not username or len(password) < 8 or password != again:
        raise SystemExit("帳號不可空白，密碼至少 8 碼且兩次要相同，請重新執行。")
    AdminStore().save(username, password)
    print("已儲存到 server/admin.local.json（不會進 git）。")


if __name__ == "__main__":
    main()
