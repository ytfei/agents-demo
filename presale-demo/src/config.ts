import "dotenv/config";

/**
 * 集中管理环境变量。生产由 .env / 配置中心注入。
 */
export const config = {
  deepseekApiKey: process.env.DEEPSEEK_API_KEY ?? "",
  deepseekModel: process.env.DEEPSEEK_MODEL ?? "deepseek-chat",

  // Postgres：checkpoint + 长期记忆（进程安全、跨 worker）
  databaseUrl: process.env.DATABASE_URL ?? "",

  // Redis：会话锁 + 限流
  redisUrl: process.env.REDIS_URL ?? "redis://localhost:6379/0",

  // 服务
  port: Number(process.env.PORT ?? 8000),
  webConcurrency: Number(process.env.WEB_CONCURRENCY ?? 4),
  rateLimitPerUser: Number(process.env.RATE_LIMIT_PER_USER ?? 10),
  sessionLockTtl: Number(process.env.SESSION_LOCK_TTL ?? 30),

  // LangSmith 可观测性（10W 下建议采样）
  langsmithTracing: (process.env.LANGSMITH_TRACING ?? "false") === "true",
  langsmithApiKey: process.env.LANGSMITH_API_KEY ?? "",
  langsmithProject: process.env.LANGSMITH_PROJECT ?? "PresalesAgent",
};
