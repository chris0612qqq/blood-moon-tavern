"""效能基準（CODING_RULES T6）：20 人房間、每秒 20 則聊天，量伺服器 CPU、記憶體、廣播延遲。

用法：python scripts/bench_t6.py --minutes 30
伺服器跑在獨立程序，資料放暫存資料夾，不碰正式的 data/。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import psutil
import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.auth import AdminStore  # noqa: E402
from server.config import PROTOCOL_VERSION  # noqa: E402

PLAYERS = 20
CHATS_PER_SECOND = 20
CPU_LIMIT = 20.0
LATENCY_LIMIT_MS = 100.0
# 前 1/3 與後 1/3 平均 RSS 的差異上限；超過視為持續成長
GROWTH_LIMIT_MB = 20.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def wait_ready(base: str) -> None:
    async with httpx.AsyncClient(base_url=base) as http:
        for _ in range(100):
            try:
                if (await http.get("/api/health")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError("server did not start")


async def setup(base: str) -> tuple[str, list[str]]:
    """上帝模式、發牌後主持人不推進：遊戲留在 DEAL，公共頻道可發言，事件走完整的引擎路徑。"""
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        res = await http.post(
            "/api/admin/login", json={"username": "boss", "password": "password1"}
        )
        admin = res.json()["token"]
        headers = {"Authorization": f"Bearer {admin}"}
        body = {"mode": "god", "name": "bench", "password": "1234"}
        await http.post("/api/admin/room", json=body, headers=headers)
        tokens = []
        for i in range(PLAYERS):
            payload = {
                "password": "1234",
                "name": f"{chr(65 + i)}1",
                "pin": "1111",
                "device_id": f"d{i}",
            }
            tokens.append((await http.post("/api/join", json=payload)).json()["token"])
    return admin, tokens


async def open_socket(url: str, token: str) -> Any:
    ws = await websockets.connect(url, max_size=2**20)
    await ws.send(json.dumps({"t": "auth", "token": token, "client_version": PROTOCOL_VERSION}))
    return ws


async def run(minutes: float, port: int, proc: psutil.Process) -> dict[str, Any]:
    base = f"http://127.0.0.1:{port}"
    url = f"ws://127.0.0.1:{port}/ws"
    await wait_ready(base)
    # Windows 虛擬環境的 python.exe 是轉接程序，真正的伺服器是它的子程序
    children = proc.children(recursive=True)
    proc = children[-1] if children else proc
    admin, tokens = await setup(base)
    host = await open_socket(url, admin)
    sockets = [await open_socket(url, token) for token in tokens]
    await host.send(json.dumps({"t": "admin.start", "msg_id": "start"}))

    latencies: list[float] = []
    sent_at: dict[str, float] = {}
    received = [0]

    async def reader(ws: Any) -> None:
        async for text in ws:
            message = json.loads(text)
            received[0] += 1
            if message["t"] == "chat.msg" and message.get("mine"):
                started = sent_at.pop(message["content"], None)
                if started is not None:
                    latencies.append((time.perf_counter() - started) * 1000)

    async def pinger() -> None:
        while True:
            await asyncio.sleep(5)
            for ws in [host, *sockets]:
                await ws.send(json.dumps({"t": "ping", "msg_id": uuid.uuid4().hex}))

    readers = [asyncio.create_task(reader(ws)) for ws in [host, *sockets]]
    ping_task = asyncio.create_task(pinger())
    proc.cpu_percent(None)
    cpu_samples: list[float] = []
    rss_samples: list[float] = []
    end = time.perf_counter() + minutes * 60
    next_sample = time.perf_counter() + 10
    count = 0
    interval = 1 / CHATS_PER_SECOND
    start = time.perf_counter()
    while time.perf_counter() < end:
        content = uuid.uuid4().hex
        sent_at[content] = time.perf_counter()
        ws = sockets[count % PLAYERS]
        await ws.send(
            json.dumps(
                {"t": "chat.send", "msg_id": content, "channel": "public", "content": content}
            )
        )
        count += 1
        now = time.perf_counter()
        if now >= next_sample:
            cpu_samples.append(proc.cpu_percent(None))
            rss_samples.append(proc.memory_info().rss / 1024 / 1024)
            next_sample = now + 10
        await asyncio.sleep(max(0.0, start + count * interval - time.perf_counter()))
    ping_task.cancel()
    for task in readers:
        task.cancel()
    third = max(1, len(rss_samples) // 3)
    early = statistics.mean(rss_samples[:third])
    late = statistics.mean(rss_samples[-third:])
    ordered = sorted(latencies)
    return {
        "minutes": minutes,
        "chats_sent": count,
        "chats_acked": len(latencies),
        "messages_received": received[0],
        "cpu_mean_percent_of_one_core": round(statistics.mean(cpu_samples), 1),
        "cpu_max_percent_of_one_core": round(max(cpu_samples), 1),
        "cpu_cores": psutil.cpu_count(),
        "rss_early_mb": round(early, 1),
        "rss_late_mb": round(late, 1),
        "latency_median_ms": round(ordered[len(ordered) // 2], 1),
        "latency_p99_ms": round(ordered[int(len(ordered) * 0.99)], 1),
        "latency_max_ms": round(ordered[-1], 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=30.0)
    args = parser.parse_args()
    port = free_port()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        admin_file = Path(tmp) / "admin.json"
        AdminStore(admin_file).save("boss", "password1")
        env = {**os.environ, "BMT_DATA_DIR": tmp, "BMT_ADMIN_FILE": str(admin_file)}
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server.main:app",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
        )
        try:
            result = asyncio.run(run(args.minutes, port, psutil.Process(server.pid)))
        finally:
            for child in psutil.Process(server.pid).children(recursive=True):
                child.terminate()
            server.terminate()
            server.wait(10)
    print(json.dumps(result, indent=2))
    passed = (
        result["cpu_mean_percent_of_one_core"] < CPU_LIMIT
        and result["rss_late_mb"] - result["rss_early_mb"] < GROWTH_LIMIT_MB
        and result["latency_p99_ms"] < LATENCY_LIMIT_MS
    )
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
