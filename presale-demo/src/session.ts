import { Redis } from "ioredis";
import { config } from "./config.js";
import { getAgent } from "./agent.js";

/**
 * 对话会话管理 —— 负责「对话结束检测」与「用户画像固化」。
 *
 * 对话结束的判定场景：
 *   A. 主动结束：前端调 POST /conversation/:id/end，或 WS 断开时调 finalizeSession()
 *   B. 会话超时：Redis 记录每个会话的 last_active，后台定时任务扫描超时 → finalize
 *   C. 惰性触发：用户下次发消息时，若发现同 user 的上一会话已超时，先固化上一段再处理本次
 *   D. 每轮兜底：每次 /chat 返回后立即固化（对话中持续更新，任何结束场景都不丢画像）
 *
 * 画像固化 = 调用 agent，追加一条「收尾指令」，让模型把本段对话新增的用户画像
 * 写入 /memories/user_profile.md（经 StoreBackend 落到 agent_memory 表）。
 */

/** Redis key 前缀 */
const ACTIVE_KEY = "sess:active"; // hash: conversation_id -> {user_id, last_active, finalized}
const FINALIZED_FLAG = "1";

interface SessionInfo {
  user_id: string;
  last_active: string; // epoch seconds
  finalized: string; // "0" | "1"
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

/**
 * 会话开始/活跃标记：在每次 /chat 请求处理前调用。
 * 若发现该 user 的其它会话已超时且未固化，先返回需要固化它的旧会话信息。
 */
export async function touchSession(
  redis: Redis,
  user_id: string,
  conversation_id: string,
): Promise<{ staleConv?: string; isNew: boolean }> {
  const key = `${ACTIVE_KEY}:${conversation_id}`;
  const prev = await redis.hgetall(key);
  const isNew = Object.keys(prev).length === 0;

  // 惰性：若此会话之前存在且未 finalized，且已超时 → 标记需要固化
  if (!isNew && prev.finalized === "0") {
    const last = Number(prev.last_active ?? 0);
    if (nowSec() - last >= config.sessionTimeoutSec) {
      return { staleConv: conversation_id, isNew: false };
    }
  }

  // 记录/刷新活跃时间
  await redis.hset(
    key,
    "user_id",
    user_id,
    "last_active",
    String(nowSec()),
    "finalized",
    "0",
  );
  await redis.expire(key, config.sessionTimeoutSec * 3);
  return { isNew };
}

/**
 * 结束一个会话并固化画像（主动结束 / WS 断开 / 超时扫描共用）。
 * 幂等：已 finalized 的会话不会重复固化。
 */
export async function finalizeSession(
  redis: Redis,
  conversation_id: string,
  opts: { reason: "endpoint" | "timeout" | "next-request" | "per-turn" },
): Promise<boolean> {
  const key = `${ACTIVE_KEY}:${conversation_id}`;
  const prev = await redis.hgetall(key);
  if (Object.keys(prev).length === 0) {
    // 会话从没被 touch 过，但仍尽力固化（直接对 thread 做收尾）
    await runFinalize(conversation_id, prev.user_id ?? "anonymous");
    await redis.hset(key, "finalized", FINALIZED_FLAG, "last_active", String(nowSec()));
    return true;
  }
  if (prev.finalized === FINALIZED_FLAG) {
    return false; // 已固化过，幂等跳过
  }

  const user_id = prev.user_id ?? "anonymous";
  await runFinalize(conversation_id, user_id);
  // 原子标记已固化，避免并发重复（用 Lua 保证）
  await redis.eval(
    `if redis.call('hget', KEYS[1], 'finalized') ~= '${FINALIZED_FLAG}' then
       redis.call('hset', KEYS[1], 'finalized', '${FINALIZED_FLAG}', 'last_active', ARGV[1])
     end`,
    1,
    key,
    String(nowSec()),
  );
  return true;
}

/** 实际调用 agent 做一次画像固化（收尾指令）。 */
async function runFinalize(conversation_id: string, user_id: string): Promise<void> {
  try {
    const agent = getAgent();
    await agent.invoke(
      {
        messages: [
          {
            role: "user",
            content:
              "[系统收尾] 本次对话已结束。请依据本段对话，把用户新增的画像信息（家庭人口、风格偏好、装修、预留尺寸、预算、已看中的产品等）写入 /memories/user_profile.md，覆盖旧内容。若无新信息则跳过，不需要回复用户。",
          },
        ],
      },
      {
        configurable: { user_id, thread_id: conversation_id },
        metadata: { user_id, conv: conversation_id, purpose: "profile-finalize" },
        recursionLimit: 9999,
      },
    );
  } catch (e) {
    console.error(`[session] 画像固化失败 conv=${conversation_id}: ${(e as Error).message}`);
  }
}

/**
 * 后台定时任务：扫描所有活跃会话，发现超时且未固化的，触发结束固化。
 * 返回本次固化的会话数。
 */
export async function scanInactiveSessions(redis: Redis): Promise<number> {
  const keys = await redis.keys(`${ACTIVE_KEY}:*`);
  if (keys.length === 0) return 0;
  const now = nowSec();
  let finalized = 0;
  for (const key of keys) {
    const convId = key.slice(ACTIVE_KEY.length + 1);
    const prev = await redis.hgetall(key);
    if (prev.finalized === FINALIZED_FLAG) continue;
    const last = Number(prev.last_active ?? 0);
    if (now - last >= config.sessionTimeoutSec) {
      const ok = await finalizeSession(redis, convId, { reason: "timeout" });
      if (ok) finalized++;
    }
  }
  return finalized;
}

/** 启动后台超时扫描（返回可停止的 interval，测试用）。 */
export function startTimeoutScanner(redis: Redis, intervalMs = 30_000): NodeJS.Timeout {
  const timer = setInterval(async () => {
    try {
      const n = await scanInactiveSessions(redis);
      if (n > 0) console.log(`[session] 超时扫描：固化 ${n} 个会话画像`);
    } catch (e) {
      console.error("[session] 超时扫描异常:", (e as Error).message);
    }
  }, intervalMs);
  timer.unref?.(); // 不阻止进程退出
  return timer;
}
