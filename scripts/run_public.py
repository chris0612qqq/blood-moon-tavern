"""正式開店（DEV_PLAN P7，SPEC B1 v4.21）。

用 Tailscale Funnel 給一個固定的 HTTPS 網址，朋友用 4G 也連得進來。

python scripts/run_public.py     （或雙擊 start.bat）

做的事：檢查不是開發模式、管理員帳密已設定 → 阻止電腦睡眠 → 啟動伺服器，當掉自動重啟
→ 開 Funnel → 從外面打一次健康檢查 → 印出網址。關掉這個視窗時會順便關掉 Funnel。
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
# 和開發用的 8765 分開，兩個可以同時開，資料也分開
PORT = 8770
TAILSCALE = r"C:\Program Files\Tailscale\tailscale.exe"
HEALTH_EVERY_SECONDS = 30
RESTART_DELAY_SECONDS = 2
FUNNEL_TIMEOUT_SECONDS = 60
# Windows：告訴系統這個程式在跑，不要睡眠（關掉視窗就恢復）
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def public_origin(status: dict[str, Any]) -> str:
    """從 `tailscale status --json` 取出這台電腦的固定網址。"""
    name = str(status["Self"]["DNSName"]).rstrip(".")
    if not name:
        raise SystemExit("Tailscale 還沒登入，請先打開 Tailscale。")
    return f"https://{name}"


def refuse_dev_mode(environ: dict[str, str]) -> None:
    """開發模式有固定帳密和機器人，絕不能對外開（CODING_RULES S8）。"""
    if environ.get("DEV_MODE") == "1":
        raise SystemExit("現在是開發模式（DEV_MODE=1），不能對外開店。請關掉這個視窗重新開。")


def tailscale(*args: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [TAILSCALE, *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout
    )


def keep_awake() -> None:
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def start_server(origin: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, "BMT_PUBLIC_ORIGIN": origin}
    command = [
        sys.executable, "-m", "uvicorn", "server.main:app",
        "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning",
    ]  # fmt: skip
    return subprocess.Popen(command, cwd=ROOT, env=env)


def open_funnel() -> None:
    try:
        result = tailscale("funnel", "--bg", str(PORT), timeout=FUNNEL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as err:
        # 第一次用：Tailscale 會印一個網址要你到後台按同意，然後一直等
        raise SystemExit(
            "Funnel 還沒開通。請照 Tailscale 印出的網址到後台開啟 HTTPS 和 Funnel，再重新執行。\n"
            f"{(err.stdout or '')!s}{(err.stderr or '')!s}"
        ) from err
    if result.returncode != 0:
        raise SystemExit(f"開 Funnel 失敗：\n{result.stdout}{result.stderr}")


def close_funnel() -> None:
    try:
        tailscale("funnel", "--bg", str(PORT), "off")
    except (OSError, subprocess.TimeoutExpired):
        print("關 Funnel 失敗，請手動執行：tailscale funnel reset")


def healthy(origin: str) -> bool:
    try:
        return httpx.get(f"{origin}/api/health", timeout=10).status_code == 200
    except httpx.HTTPError:
        return False


def main() -> None:
    refuse_dev_mode(dict(os.environ))
    sys.path.insert(0, str(ROOT))
    from server import auth, config

    try:
        auth.AdminStore(config.ADMIN_FILE).load()
    except RuntimeError as err:
        raise SystemExit(f"{err}\n請先執行：.venv\\Scripts\\python -m server.setup_admin") from err
    status = json.loads(tailscale("status", "--json").stdout)
    origin = public_origin(status)
    keep_awake()
    server = start_server(origin)
    try:
        open_funnel()
        while not healthy(origin):
            if server.poll() is not None:
                raise SystemExit("伺服器啟動失敗，請看上面的錯誤訊息。")
            time.sleep(2)
        print(f"\n✔ 酒館開門了：{origin}\n朋友用手機開這個網址就能加入（Wi-Fi、4G 都可以）。")
        print("遊戲中請不要關掉這個視窗，也不要讓電腦關機。\n")
        while True:
            time.sleep(HEALTH_EVERY_SECONDS)
            if server.poll() is not None:
                print("伺服器停了，自動重開…")
                time.sleep(RESTART_DELAY_SECONDS)
                server = start_server(origin)
            elif not healthy(origin):
                print("外面連不進來，重新開 Funnel…")
                open_funnel()
    except KeyboardInterrupt:
        print("關店中…")
    finally:
        close_funnel()
        server.terminate()


if __name__ == "__main__":
    main()
