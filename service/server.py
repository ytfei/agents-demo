"""售前 Agent 生产服务（10W 级并发就绪）。

架构要点（对应高并发设计）：
- 模块加载时 init_agent() 编译一次全局 agent 单例，10W 请求共用。
- 每次请求用 ainvoke（异步、非阻塞），单进程 asyncio 可 hold 数千挂起协程
  （全程 await LLM，吃不到 CPU）。
- 隔离靠 configurable：thread_id=会话、user_id=记忆 namespace。
- Postgres 做 checkpoint + 长期记忆，进程安全、跨 worker。
- Redis 做：① 同一 thread_id 的分布式锁（防并发写同一会话）
                 ② 简单令牌桶限流。
- uvicorn --workers N 起多进程，吃满多核；瓶颈在 LLM 网关与 DB 池，不在 Python。

运行：
  uv run -m service.server
  # 或生产：uvicorn service.server:app --workers 16 --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import time

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import redis.asyncio as aioredis

from .agent import get_agent, init_agent

load_dotenv()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# 全局限流：每用户每秒最大请求数（令牌桶）
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_USER", "10"))
# 同一会话最大并发（应恒为 1，靠锁保证串行）
SESSION_LOCK_TTL = 30  # 秒

_redis: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：编译 agent 单例 + 建立 Postgres 连接池（每个 worker 各一份），
    # 并建立 Redis 连接池（进程级复用）
    global _redis
    await init_agent()
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True, max_connections=64)
    try:
        yield
    finally:
        # 关闭：释放 Redis 连接池
        if _redis is not None:
            await _redis.aclose()


app = FastAPI(title="Presales Agent Service", version="1.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    user_id: str
    conversation_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


# ---------------------------------------------------------------------------
# 中间件：限流 + 会话锁
# ---------------------------------------------------------------------------
async def _rate_limit(user_id: str) -> None:
    """简单令牌桶：RATE_LIMIT 个/秒，超出则拒绝。"""
    if _redis is None:
        return
    key = f"rl:{user_id}"
    now = time.time()
    # 用滑动窗口：记录最近请求时间戳列表（简化实现，生产可换漏桶）
    pipe = _redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - 1.0)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, 2)
    _, count, *_ = await pipe.execute()
    if count and count > RATE_LIMIT:
        raise HTTPException(status_code=429, detail="too many requests")


async def _acquire_session_lock(conversation_id: str) -> str:
    """同一会话必须串行：抢不到锁直接 409，避免并发写同一 thread 的 checkpoint。"""
    if _redis is None:
        return ""
    lock_key = f"lock:conv:{conversation_id}"
    token = os.urandom(8).hex()
    # SET NX EX：拿锁，TTL 自动释放防死锁
    ok = await _redis.set(lock_key, token, nx=True, ex=SESSION_LOCK_TTL)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="conversation is being processed by another request",
        )
    return token


async def _release_session_lock(conversation_id: str, token: str) -> None:
    if _redis is None or not token:
        return
    lock_key = f"lock:conv:{conversation_id}"
    # 仅释放自己持有的锁（Lua 保证原子）
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    await _redis.eval(script, 1, lock_key, token)


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    await _rate_limit(req.user_id)
    token = await _acquire_session_lock(req.conversation_id)
    try:
        agent = get_agent()
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": req.message}]},
            config={
                "configurable": {
                    "user_id": req.user_id,
                    "thread_id": req.conversation_id,
                },
                "metadata": {"user_id": req.user_id, "conv": req.conversation_id},
                "recursion_limit": 9999,
            },
        )
        reply = result["messages"][-1].content
        return ChatResponse(reply=reply, conversation_id=req.conversation_id)
    except HTTPException:
        raise
    except Exception as e:  # 兜底：不影响 worker 存活
        raise HTTPException(status_code=500, detail=f"agent error: {e}")
    finally:
        await _release_session_lock(req.conversation_id, token)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
    uvicorn.run(
        "service.server:app",
        host="0.0.0.0",
        port=8000,
        workers=workers,
        loop="asyncio",
    )
