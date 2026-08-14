/**
 * 应用版本信息。
 *
 * 版本标签格式：v<主版本>.<次版本>-<channel>-<timestamp>
 *   例：v0.01-dev-20260814034503
 *
 * 优先级：
 *   1. 环境变量 APP_VERSION —— 生产由 docker-compose/.env 注入，覆盖自动生成的值
 *   2. 自动生成：v0.01-dev-<进程启动时间戳>
 *
 * 时间戳 = 进程启动时刻（YYYYMMDDHHmmss），每次启动唯一，便于区分部署实例。
 */
export interface AppVersion {
  /** 主.次版本号（默认 0.01） */
  semver: string;
  /** 发布通道（dev / staging / prod） */
  channel: string;
  /** 进程启动时间戳（YYYYMMDDHHmmss，本地时区） */
  timestamp: string;
  /** 进程启动时间（ISO 8601） */
  startedAt: string;
  /** 合成版本标签，如 v0.01-dev-20260814034503 */
  label: string;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function timestampOf(date: Date): string {
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  );
}

function buildVersion(): AppVersion {
  const semver = process.env.APP_SEMVER?.trim() || "0.01";
  const channel = process.env.APP_CHANNEL?.trim() || "dev";
  const now = new Date();
  const timestamp = timestampOf(now);

  // 显式注入优先（例如生产固定版本），否则自动生成 v<semver>-<channel>-<timestamp>
  const explicit = process.env.APP_VERSION?.trim() ?? "";
  const label =
    explicit ||
    `v${semver}-${channel}-${timestamp}`;

  return {
    semver,
    channel,
    timestamp,
    startedAt: now.toISOString(),
    label,
  };
}

export const APP_VERSION: AppVersion = buildVersion();
