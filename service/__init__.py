"""售前 Agent 生产服务 package（10W 级并发就绪）。

目录结构：
  service/
    agent.py          # agent 构建 + 进程内单例 + 并发隔离 namespace
    pg_store.py       # 进程安全的异步 Postgres 长期记忆 store
    backend_remote.py # 远程沙箱 backend（生产替代本机 shell）
    server.py         # FastAPI 服务（uvicorn 多 worker）
    benchmark.py      # 轻量压测脚本
    Dockerfile
    .env.example

本地 demo 仍可用根目录的 presales_agent.py（依赖 file_store 的 JSON 文件 store）。
"""

from .agent import (
    SYSTEM_PROMPT,
    build_agent,
    init_agent,
    get_agent,
    get_store,
)
from .server import app

__all__ = [
    "SYSTEM_PROMPT",
    "build_agent",
    "init_agent",
    "get_agent",
    "get_store",
    "app",
]
