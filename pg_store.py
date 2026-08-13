"""进程安全的异步 Postgres 长期记忆 Store —— 替代 file_store.FilePerUserStore。

为什么不用 langgraph 自带的 store postgres 后端：当前 pypi 源未提供该包，
这里基于 psycopg3 连接池自行实现 langgraph.store.base.BaseStore 契约，
接口与官方 PostgresStore 对齐（deepagents 在 async 路径下调用 abatch）。

并发模型（对应 10W 级设计）：
- 所有读写都经由 psycopg 的 AsyncConnectionPool，连接可被多协程复用。
- 每个 (namespace, key) 是一行，按 namespace 隔离记忆 —— 等价于 demo 里
  「每个用户一个独立文件」，但是进程安全、跨 worker、可水平扩展。
- 写操作用 INSERT ... ON CONFLICT DO UPDATE（upsert），并发不丢数据。
- 行的锁粒度是 (namespace, key)，不同用户的写入互不阻塞。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchOp,
)

_DDL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    namespace TEXT NOT NULL,
    key       TEXT NOT NULL,
    value     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS agent_memory_ns_idx ON agent_memory (namespace);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AsyncPostgresStore(BaseStore):
    """基于 psycopg3 异步连接池的 langgraph BaseStore 实现。

    用法：
        store = await AsyncPostgresStore.create(conninfo, pool_min=4, pool_max=64)
        ...
        await store.aclose()
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    @classmethod
    async def create(
        cls,
        conninfo: str,
        *,
        pool_min: int = 4,
        pool_max: int = 64,
        **kwargs: Any,
    ) -> "AsyncPostgresStore":
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo,
            min_size=pool_min,
            max_size=pool_max,
            open=False,  # 延迟打开，交给调用方 setup()
            **kwargs,
        )
        await pool.open()
        store = cls(pool)
        await store._ensure_schema()
        return store

    async def _ensure_schema(self) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_DDL)
            await conn.commit()

    async def aclose(self) -> None:
        await self._pool.close()

    # ---- 核心：batch / abatch ----
    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                for op in ops:
                    if isinstance(op, GetOp):
                        res = await self._get(cur, op)
                    elif isinstance(op, PutOp):
                        res = await self._put(cur, op)
                    elif isinstance(op, SearchOp):
                        res = await self._search(cur, op)
                    elif isinstance(op, ListNamespacesOp):
                        res = await self._list_ns(cur, op)
                    else:
                        res = None
                    results.append(res)
                await conn.commit()
        return results

    def batch(self, ops: Iterable[Op]) -> list[Result]:  # 同步路径兜底（demo/单线程用）
        # deepagents 异步运行时走 abatch；这里保留同步版以便本地 demo 不崩。
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            # 已在事件循环中：用 run_coroutine_threadsafe 不安全，直接报错提示
            raise RuntimeError("sync batch() called inside event loop; use abatch()")
        return asyncio.run(self.abatch(ops))

    # ---- 单个 Op 实现 ----
    async def _get(self, cur, op: GetOp):
        await cur.execute(
            "SELECT value, created_at, updated_at FROM agent_memory "
            "WHERE namespace = %s AND key = %s",
            (op.namespace[0] if op.namespace else "", op.key),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        value, created_at, updated_at = row
        return Item(
            namespace=op.namespace,
            key=op.key,
            value=value,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def _put(self, cur, op: PutOp):
        if op.value is None:
            # value=None 表示删除
            await cur.execute(
                "DELETE FROM agent_memory WHERE namespace = %s AND key = %s",
                (op.namespace[0] if op.namespace else "", op.key),
            )
            return None
        now = _now()
        await cur.execute(
            "INSERT INTO agent_memory (namespace, key, value, created_at, updated_at) "
            "VALUES (%s, %s, %s::jsonb, %s, %s) "
            "ON CONFLICT (namespace, key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            (op.namespace[0] if op.namespace else "", op.key, json.dumps(op.value), now, now),
        )
        return None

    async def _search(self, cur, op: SearchOp):
        ns = op.namespace_prefix[0] if op.namespace_prefix else ""
        params: list[Any] = [ns]
        sql = "SELECT value, created_at, updated_at, key FROM agent_memory WHERE namespace = %s"
        if op.key_prefix:
            sql += " AND key LIKE %s"
            params.append(op.key_prefix + "%")
        await cur.execute(sql, params)
        items = []
        for value, created_at, updated_at, key in await cur.fetchall():
            items.append(
                Item(
                    namespace=(ns,),
                    key=key,
                    value=value,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        return items

    async def _list_ns(self, cur, op: ListNamespacesOp):
        await cur.execute("SELECT DISTINCT namespace FROM agent_memory")
        return [tuple([row[0]]) for row in await cur.fetchall()]
