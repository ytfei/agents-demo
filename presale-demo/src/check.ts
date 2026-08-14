/**
 * 验证 docker compose up 后应用是否真正就绪。
 *
 * 用法：
 *   pnpm check                  # 轮询默认 http://localhost:8000/healthz
 *   pnpm check --url http://localhost:9000   # 指定地址
 *   pnpm check --timeout 120    # 超时秒数（默认 60）
 *
 * 判定逻辑：
 *   1. /healthz 返回 200 且 body.status === "ok"  → 应用健康，通过。
 *   2. 在超时时间内未就绪 → 退出码 1，并给出排查提示。
 * 同时做一次 /chat 的 400 校验（无参数时应被拒绝），证明 HTTP 路由可交互。
 */
import { cpus } from "node:os";
import { resolve } from "node:path";
import { existsSync } from "node:fs";

function parseArgs(argv: string[]) {
  const args: { url: string; timeout: number } = {
    url: "http://localhost:8000/healthz",
    timeout: 60,
  };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--url") args.url = argv[++i] ?? args.url;
    else if (argv[i] === "--timeout") args.timeout = Number(argv[++i] ?? args.timeout);
  }
  return args;
}

function baseUrl(healthzUrl: string): string {
  const u = new URL(healthzUrl);
  return `${u.protocol}//${u.host}`;
}

async function waitForHealthy(url: string, timeoutSec: number): Promise<void> {
  const deadline = Date.now() + timeoutSec * 1000;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      const body = (await res.json()) as { status?: string };
      if (res.status === 200 && body.status === "ok") {
        console.log(`[check] /healthz OK (${url})`);
        return;
      }
      lastError = `unexpected status=${res.status}, body=${JSON.stringify(body)}`;
    } catch (err) {
      lastError = (err as Error).message;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error(
    `应用在 ${timeoutSec}s 内未就绪。最后错误: ${lastError}\n` +
      `排查：\n` +
      `  - 确认已执行 docker compose up --build -d\n` +
      `  - docker compose ps 看 app 是否 running\n` +
      `  - docker compose logs app 看是否有异常（缺 DEEPSEEK_API_KEY / 连不上 Postgres 等）`,
  );
}

async function checkChatRoute(base: string): Promise<void> {
  // 不传必填参数，应被 400 拒绝 —— 证明路由层已可交互（而非仅静态探活）。
  const res = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (res.status === 400) {
    console.log(`[check] /chat 参数校验 OK (status=400, 符合预期)`);
  } else {
    console.warn(
      `[warn] /chat 期望 400，实际 ${res.status}（${await res.text()}）—— 不影响健康，仅供参考`,
    );
  }
}

async function main() {
  const { url, timeout } = parseArgs(process.argv.slice(2));
  const base = baseUrl(url);
  console.log(`[check] 验证目标: ${url}（超时 ${timeout}s）`);
  try {
    await waitForHealthy(url, timeout);
    await checkChatRoute(base);
    console.log("[check] ✅ 应用已成功启动并通过健康检查");
    process.exit(0);
  } catch (err) {
    console.error(`[check] ❌ ${(err as Error).message}`);
    process.exit(1);
  }
}

const entry = resolve(process.argv[1] ?? "");
if (entry.endsWith("check.ts") || entry.endsWith("check.js") || existsSync(resolve("src/check.ts"))) {
  main();
}

export { waitForHealthy, checkChatRoute };
