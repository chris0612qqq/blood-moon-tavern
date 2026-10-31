"""區網試玩啟動（DEV_PLAN P4）：手機連同一個 Wi-Fi，用瀏覽器開印出來的網址。

python scripts/run_lan.py            正式資料，需先跑 python -m server.setup_admin
python scripts/run_lan.py --dev      開發模式：獨立資料夾、帳密 boss／password1、可加機器人
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765


def lan_ip() -> str:
    """找這台電腦的區網 IP。只是選路由，不會真的送出封包。"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 80))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--time-scale", type=float, default=1.0)
    args = parser.parse_args()
    if args.dev:
        data = ROOT / "data" / "dev"
        data.mkdir(parents=True, exist_ok=True)
        os.environ.update(
            DEV_MODE="1",
            TIME_SCALE=str(args.time_scale),
            BMT_DATA_DIR=str(data),
            BMT_ADMIN_FILE=str(data / "admin.json"),
        )
    sys.path.insert(0, str(ROOT))

    from server import auth, config

    if args.dev and not config.ADMIN_FILE.exists():
        auth.AdminStore(config.ADMIN_FILE).save("boss", "password1")
    try:
        auth.AdminStore(config.ADMIN_FILE).load()
    except RuntimeError as err:
        raise SystemExit(str(err)) from err

    import uvicorn

    print(f"手機打開：http://{lan_ip()}:{args.port}")
    print("手機要和這台電腦連同一個 Wi-Fi；Windows 跳出防火牆詢問時請按允許。")
    uvicorn.run("server.main:app", host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
