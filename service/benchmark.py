"""轻量压测脚本 —— 模拟 N 个并发用户打 /chat。

用法：
  uv run -m service.server &          # 先起服务
  uv run service/benchmark.py --users 200 --requests 1000

依赖：pip install httpx
不依赖重量级框架，便于在本地快速验证并发模型（单进程 asyncio 客户端）。
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx


async def _one_user(client: httpx.AsyncClient, base: str, user_id: str, conv_id: str, n: int):
    ok = 0
    for i in range(n):
        try:
            r = await client.post(
                f"{base}/chat",
                json={
                    "user_id": user_id,
                    "conversation_id": conv_id,
                    "message": f"我想买冰箱，家里 {i % 5 + 2} 口人，预算 5000。",
                },
                timeout=60,
            )
            if r.status_code == 200:
                ok += 1
        except Exception:
            pass
    return ok


async def main(users: int, requests: int):
    base = "http://localhost:8000"
    per = max(1, requests // users)
    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [
            _one_user(client, base, f"u{u}", f"c{u}", per)
            for u in range(users)
        ]
        results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    total = sum(results)
    print(f"users={users} total_requests={total} elapsed={elapsed:.1f}s "
          f"rps={total / elapsed:.1f} success_rate={total / (users * per):.1%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=200)
    ap.add_argument("--requests", type=int, default=1000)
    args = ap.parse_args()
    asyncio.run(main(args.users, args.requests))
