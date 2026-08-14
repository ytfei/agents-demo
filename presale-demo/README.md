# Presale Agent Demo (TypeScript / DeepAgents JS)

面向 **10 万级并发** 的家电售前 Agent，使用 [DeepAgents JS](https://github.com/langchain-ai/deepagentsjs) + DeepSeek + LangGraph.js + Postgres + Redis + Fastify 实现。

本项目是 Python 版 `service/` 包的 TypeScript 等价实现，架构完全一致：

- **编译一次 graph 单例**：`createDeepAgent(...)` 开销大，启动时只编译一次，10W 请求共用同一份只读模板。
- **并发隔离靠 `configurable`**：
  - `thread_id` → checkpointer（PostgresSaver）隔离对话上下文。
  - `user_id` → store 的 namespace（`StoreBackend` 的 namespace 工厂从 `config.configurable.user_id` 取）隔离长期记忆。
- **异步 + 多 worker**：Fastify + Node `cluster`，单进程事件循环可 hold 数千挂起请求（全程 `await` LLM，吃不到 CPU）；cluster 多 worker 吃满多核。
- **长期记忆**：自定义 `PostgresStore`（实现 LangGraph `BaseStore`），按 `(namespace, key)` 行级隔离、upsert 并发安全。
- **限流 + 会话锁**：Redis 令牌桶限流 + 同一 `thread_id` 分布式锁（防并发写同一会话 checkpoint）。
- **生产不跑本机 shell**：售前场景的 skill 逻辑直接做成 LangChain Tool，避免多用户在同一宿主机 shell 互踩（对标 Python 版删掉 `LocalShellBackend`）。

## 与 Python 版对照

| Python (`service/`)        | TypeScript (`src/`)        |
|----------------------------|----------------------------|
| `agent.py`                 | `agent.ts`                 |
| `pg_store.py`              | `pgStore.ts`               |
| `server.py` (FastAPI)      | `server.ts` (Fastify)      |
| `backend_remote.py`        | （skill 改 tool，不再需沙箱）|
| `benchmark.py`             | `benchmark.ts`             |

## 目录

```
src/
  config.ts      # 环境变量集中管理
  tools.ts       # 产品目录工具（get_product_catalog / get_categories）
  pgStore.ts     # BaseStore 的 Postgres 实现（长期记忆）
  agent.ts       # buildAgent + 单例 + namespace 隔离工厂 + checkpointer
  server.ts      # Fastify + cluster + Redis 锁/限流
  benchmark.ts   # 轻量压测
  index.ts       # 导出
.env.example     # 环境变量模板
Dockerfile       # 镜像（pnpm + tsc + node cluster）
docker-compose.yml
```

## 快速开始

```bash
pnpm install
cp .env.example .env   # 填入 DEEPSEEK_API_KEY 与 DATABASE_URL
# 需要本地 Postgres（见 docker-compose.yml 的 postgres 服务）
pnpm serve             # tsx 直接跑 src/server.ts（cluster 多 worker）
```

或用 docker 一键起全套：

```bash
docker compose up --build
```

## 压测

```bash
pnpm serve &                       # 先起服务
pnpm bench --users 200 --requests 1000
```

## 接口

`POST /chat`

```json
{ "user_id": "alice", "conversation_id": "conv-1", "message": "我想看冰箱" }
```

```json
{ "reply": "...", "conversation_id": "conv-1" }
```

`GET /healthz` → `{ "status": "ok" }`

并发容量要点：Python 版分析中的结论同样适用——**瓶颈在 LLM 网关吞吐与 DB 连接池，不在 Node 进程数**。单进程 asyncio/事件循环即可 hold 数千挂起协程，cluster 多 worker 吃满多核，横向扩容加副本即可线性扩展。
