"""正式開店（DEV_PLAN P7，SPEC B1 v4.22）。

朋友永遠開 https://chris0612qqq.github.io/blood-moon-tavern/ 。這個程式在家裡電腦開一條
Cloudflare 臨時通道（每次網址都不同），再把網址寫進 GitHub Pages 上的 server.json，手機就找得到。

python scripts/run_public.py     （或雙擊 start.bat）

做的事：檢查不是開發模式、管理員帳密已設定 → 阻止電腦睡眠 → 啟動伺服器，當掉自動重啟
→ 開通道 → 發布網址 → 從外面做健康檢查 → 一直盯著，通道掛了就換一條重新發布。
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
# 和開發用的 8765 分開，兩個可以同時開，資料也分開
PORT = 8770
REPO = "chris0612qqq/blood-moon-tavern"
PAGES_URL = "https://chris0612qqq.github.io/blood-moon-tavern/"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TUNNEL_START_SECONDS = 60
PUBLISH_TIMEOUT_SECONDS = 300
POLL_SECONDS = 5
HEALTH_EVERY_SECONDS = 30
# 連續幾次從外面打不通才換通道：一次失敗可能只是網路抖一下
TUNNEL_FAILS_BEFORE_RESTART = 3
RESTART_DELAY_SECONDS = 2
# Windows：告訴系統這個程式在跑，不要睡眠（關掉視窗就恢復）
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def find_tunnel_url(line: str) -> str | None:
    """cloudflared 啟動時會在某一行印出這次的網址。"""
    match = TUNNEL_URL.search(line)
    return match.group(0) if match else None


def refuse_dev_mode(environ: dict[str, str]) -> None:
    """開發模式有固定帳密和機器人，絕不能對外開（CODING_RULES S8）。"""
    if environ.get("DEV_MODE") == "1":
        raise SystemExit("現在是開發模式（DEV_MODE=1），不能對外開店。請關掉這個視窗重新開。")


def cloudflared_path() -> str:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "cloudflared" / "cloudflared.exe"
    found = shutil.which("cloudflared") or (str(local) if local.exists() else None)
    if found is None:
        raise SystemExit("找不到 cloudflared，請先安裝（見 PROGRESS.md 的 P7 說明）。")
    return found


def keep_awake() -> None:
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)


def start_server() -> subprocess.Popen[bytes]:
    command = [
        sys.executable, "-m", "uvicorn", "server.main:app",
        "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning",
    ]  # fmt: skip
    return subprocess.Popen(command, cwd=ROOT)


class Tunnel:
    """一條 Cloudflare 臨時通道。網址只有這個程式活著時有效。"""

    def __init__(self) -> None:
        command = [
            cloudflared_path(),
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{PORT}",
        ]
        self.process = subprocess.Popen(
            command, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, encoding="utf-8"
        )
        self.url: str | None = None
        found = threading.Event()

        def read() -> None:
            # 一直讀到結束，免得輸出塞滿管線把 cloudflared 卡住
            assert self.process.stderr is not None
            for line in self.process.stderr:
                if self.url is None and (url := find_tunnel_url(line)):
                    self.url = url
                    found.set()

        threading.Thread(target=read, daemon=True).start()
        if not found.wait(TUNNEL_START_SECONDS):
            self.close()
            raise RuntimeError("Cloudflare 通道開不起來")

    def alive(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        self.process.terminate()


def publish(url: str) -> None:
    """觸發 GitHub Actions 把網址寫進 Pages，等到外面讀得到新的 server.json。"""
    run = subprocess.run(
        ["gh", "workflow", "run", "pages.yml", "-R", REPO, "--ref", "main", "-f", f"api={url}"],
        capture_output=True, text=True, encoding="utf-8",
    )  # fmt: skip
    if run.returncode != 0:
        raise RuntimeError(f"發布網址失敗：{run.stderr.strip()}")
    deadline = time.monotonic() + PUBLISH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            data = httpx.get(
                f"{PAGES_URL}server.json", params={"t": time.time()}, timeout=10
            ).json()
        except (httpx.HTTPError, ValueError):
            continue
        if data.get("api") == url:
            return
    raise RuntimeError("GitHub Pages 一直沒有更新，請看 GitHub 的 Actions 頁面")


def healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=10).status_code == 200
    except httpx.HTTPError:
        return False


def open_tunnel() -> Tunnel:
    """開通道並發布；失敗就等一下再試，直到成功。"""
    while True:
        try:
            tunnel = Tunnel()
            assert tunnel.url is not None
            print(f"通道開好了：{tunnel.url}，正在更新網址（約 1–2 分鐘）…")
            publish(tunnel.url)
            return tunnel
        except RuntimeError as err:
            print(f"{err}，10 秒後再試…")
            time.sleep(10)


def main() -> None:
    refuse_dev_mode(dict(os.environ))
    sys.path.insert(0, str(ROOT))
    from server import auth, config

    try:
        auth.AdminStore(config.ADMIN_FILE).load()
    except RuntimeError as err:
        raise SystemExit(f"{err}\n請先執行：.venv\\Scripts\\python -m server.setup_admin") from err
    keep_awake()
    server = start_server()
    tunnel: Tunnel | None = None
    try:
        tunnel = open_tunnel()
        print(f"\n✔ 酒館開門了：{PAGES_URL}\n朋友用手機開這個網址就能加入（Wi-Fi、4G 都可以）。")
        print(f"（直連網址，備用：{tunnel.url}）")
        print("遊戲中請不要關掉這個視窗，也不要讓電腦關機。\n")
        fails = 0
        while True:
            time.sleep(HEALTH_EVERY_SECONDS)
            if server.poll() is not None:
                print("伺服器停了，自動重開…")
                time.sleep(RESTART_DELAY_SECONDS)
                server = start_server()
                continue
            assert tunnel.url is not None
            fails = 0 if tunnel.alive() and healthy(tunnel.url) else fails + 1
            if fails >= TUNNEL_FAILS_BEFORE_RESTART:
                # 手機斷線時伺服器會自動暫停（SPEC A11），換好網址會自己連回來
                print("外面連不進來，換一條通道…")
                tunnel.close()
                tunnel = open_tunnel()
                print(f"✔ 換好了：{tunnel.url}")
                fails = 0
    except KeyboardInterrupt:
        print("關店中…")
    finally:
        if tunnel is not None:
            tunnel.close()
        server.terminate()


if __name__ == "__main__":
    main()
