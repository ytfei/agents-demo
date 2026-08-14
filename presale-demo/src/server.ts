import { existsSync } from "node:fs";
import { cpus } from "node:os";
import { resolve } from "node:path";
import cluster from "node:cluster";
import fastify, { type FastifyRequest } from "fastify";
import { Redis } from "ioredis";
import { config } from "./config.js";
import { getAgent, initAgent, shutdownAgent } from "./agent.js";
import { APP_VERSION } from "./version.js";
import {
  finalizeSession,
  startTimeoutScanner,
  touchSession,
} from "./session.js";

/**
 * 售前 Agent 生产服务（10W 级并发就绪）。
 *
 * 架构要点（对标 Python 版 service/server.py）：
 * - initAgent() 在启动时编译一次全局 agent 单例，10W 请求共用。
 * - 每次请求用 agent.ainvoke（异步、非阻塞），单进程事件循环可 hold 数千挂起
 *   请求（全程 await LLM，吃不到 CPU）。
 * - 隔离靠 configurable：thread_id=会话（checkpointer）、user_id=记忆 namespace（store）。
 * - Redis 做：① 同一 thread_id 分布式锁（防并发写同一会话）② 令牌桶限流。
 * - cluster 多 worker 吃满多核；瓶颈在 LLM 网关与 DB 池，不在 Node 进程数。
 */

const RELEASE_SCRIPT = `
  if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
  else
    return 0
  end
`;

async function buildApp(redis: Redis) {
  const app = fastify({ logger: false });

  app.get("/healthz", async () => ({
    status: "ok",
    version: APP_VERSION.label,
    semver: APP_VERSION.semver,
    channel: APP_VERSION.channel,
    timestamp: APP_VERSION.timestamp,
    startedAt: APP_VERSION.startedAt,
  }));

  app.post<{
    Body: { user_id: string; conversation_id: string; message: string };
  }>("/chat", async (req: FastifyRequest<{ Body: { user_id: string; conversation_id: string; message: string } }>, reply) => {
    const { user_id, conversation_id, message } = req.body ?? ({} as any);

    if (!user_id || !conversation_id || !message) {
      return reply.code(400).send({ error: "user_id / conversation_id / message 必填" });
    }

    // 限流：每用户每秒 N 次
    const rlKey = `rl:${user_id}`;
    const now = Date.now() / 1000;
    const pipe = redis.pipeline();
    pipe.zremrangebyscore(rlKey, 0, now - 1);
    pipe.zcard(rlKey);
    pipe.zadd(rlKey, now, String(now));
    pipe.expire(rlKey, 2);
    const card = (await pipe.exec())?.[1]?.[1] as number | undefined;
    if (card !== undefined && card > config.rateLimitPerUser) {
      return reply.code(429).send({ error: "too many requests" });
    }

    // 会话锁：同一会话必须串行（防并发写同一 thread 的 checkpoint）
    const lockKey = `lock:conv:${conversation_id}`;
    const token = cryptoRandom();
    const locked = await redis.set(lockKey, token, "EX", config.sessionLockTtl, "NX");
    if (!locked) {
      return reply.code(409).send({ error: "conversation is being processed by another request" });
    }

    try {
      // 惰性触发：若该会话之前活跃但已超时未固化，先固化上一段画像再继续本次
      const { staleConv } = await touchSession(redis, user_id, conversation_id);
      if (staleConv) {
        await finalizeSession(redis, staleConv, { reason: "next-request" });
      }

      const agent = getAgent();
      const result = await agent.invoke(
        { messages: [{ role: "user", content: message }] },
        {
          configurable: { user_id, thread_id: conversation_id },
          metadata: { user_id, conv: conversation_id },
          recursionLimit: 9999,
        },
      );
      const replyMsg =
        result.messages[result.messages.length - 1]?.content ?? "";

      // 每轮兜底：本对话已获得新画像，立即固化（任何结束场景都不丢）
      // 注意：这会让「收尾指令」也跑一次 LLM，属于代价可控的兜底。
      await finalizeSession(redis, conversation_id, { reason: "per-turn" });

      return { reply: typeof replyMsg === "string" ? replyMsg : String(replyMsg), conversation_id };
    } catch (err) {
      req.log.error(err);
      return reply.code(500).send({ error: `agent error: ${(err as Error).message}` });
    } finally {
      await redis.eval(RELEASE_SCRIPT, 1, lockKey, token);
    }
  });

  // 主动结束：前端在用户离开/关闭/点结束按钮时调用，做最后一次画像固化（幂等）
  app.post<{ Params: { id: string }; Body: { user_id?: string } }>(
    "/conversation/:id/end",
    async (req, reply) => {
      const convId = req.params.id;
      const userId = req.body?.user_id ?? "anonymous";
      const done = await finalizeSession(redis, convId, { reason: "endpoint" });
      return { conversation_id: convId, finalized: done, user_id: userId };
    },
  );

  return app;
}

function cryptoRandom(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

async function startWorker() {
  await initAgent();
  const redis = new Redis(config.redisUrl, { maxRetriesPerRequest: 3 });
  const app = await buildApp(redis);
  await app.listen({ port: config.port, host: "0.0.0.0" });
  console.log(
    `[worker ${process.pid}] listening on :${config.port} version=${APP_VERSION.label}`,
  );

  // 后台超时扫描：定期固化「超时且未结束」的会话画像
  startTimeoutScanner(redis, config.sessionScanMs);

  const shutdown = async () => {
    await app.close();
    redis.disconnect();
    await shutdownAgent();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

function main() {
  const workers = config.webConcurrency || cpus().length;
  if (cluster.isPrimary && workers > 1) {
    console.log(`[primary] forking ${workers} workers`);
    for (let i = 0; i < workers; i++) cluster.fork();
    cluster.on("exit", (worker) => {
      console.log(`[primary] worker ${worker.process.pid} exited, restarting`);
      cluster.fork();
    });
  } else {
    startWorker().catch((e) => {
      console.error("worker failed to start:", e);
      process.exit(1);
    });
  }
}

// tsx 直接运行时，import.meta.url 指向源码；编译后用 dist/server.js
const entry = resolve(process.argv[1] ?? "");
if (entry.endsWith("server.ts") || entry.endsWith("server.js") || existsSync(resolve("src/server.ts"))) {
  main();
}

export { buildApp };
