/**
 * 客户端脚本 —— 访问已部署的售前 Agent 服务（交互式命令行对话）。
 *
 * 用法：
 *   pnpm client                       # 交互式对话（默认 localhost:8000）
 *   pnpm client --url http://host:8000  # 指定服务地址
 *   pnpm client --user alice --conv c1  # 指定用户/会话（用于延续同一会话上下文）
 *   pnpm client --message "你好"        # 一次性发送（非交互）
 *   pnpm client --health                # 只做健康检查
 *   pnpm client --timeout 120           # 单次请求超时（秒，默认 90）
 *
 * 说明：
 *   - user_id    决定长期记忆隔离（不同用户互不共享记忆）
 *   - conversation_id 决定对话上下文（同一会话延续历史；不同会话隔离）
 *   - 交互模式下可用 :quit 退出、:health 查健康
 */
import { resolve } from "node:path";
import { existsSync } from "node:fs";
import * as readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

function parseArgs(argv: string[]) {
  const args: {
    url: string;
    user: string;
    conv: string;
    message?: string;
    health: boolean;
    timeout: number;
  } = {
    url: process.env.CLIENT_URL ?? "http://localhost:8000",
    user: `cli-${process.env.USER ?? "user"}`,
    conv: "",
    health: false,
    timeout: 90,
  };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--url") args.url = argv[++i] ?? args.url;
    else if (v === "--user") args.user = argv[++i] ?? args.user;
    else if (v === "--conv") args.conv = argv[++i] ?? args.conv;
    else if (v === "--message") args.message = argv[++i];
    else if (v === "--health") args.health = true;
    else if (v === "--timeout") args.timeout = Number(argv[++i] ?? args.timeout);
  }
  if (!args.conv) args.conv = `cli-${Date.now()}`; // 默认新会话
  return args;
}

async function health(url: string): Promise<boolean> {
  try {
    const res = await fetch(`${url}/healthz`);
    const body = (await res.json()) as { status?: string };
    const ok = res.status === 200 && body.status === "ok";
    console.log(`[health] ${url} -> ${ok ? "ok" : `unhealthy (status=${res.status})`}`);
    return ok;
  } catch (e) {
    console.error(`[health] 无法连接 ${url}: ${(e as Error).message}`);
    return false;
  }
}

async function chat(url: string, user: string, conv: string, message: string, timeout: number) {
  const started = Date.now();
  try {
    const res = await fetch(`${url}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_id: user, conversation_id: conv, message }),
      signal: AbortSignal.timeout(timeout * 1000),
    });
    const text = await res.text();
    let body: any = {};
    try {
      body = JSON.parse(text);
    } catch {}
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    if (res.status === 200) {
      return { ok: true, reply: (body.reply as string) ?? "", elapsed };
    }
    if (res.status === 429) {
      return { ok: false, error: `限流：${body.error ?? "too many requests"}`, elapsed };
    }
    if (res.status === 409) {
      return { ok: false, error: `会话忙：${body.error ?? "conversation locked"}`, elapsed };
    }
    return { ok: false, error: `HTTP ${res.status}: ${text.slice(0, 300)}`, elapsed };
  } catch (e) {
    return { ok: false, error: (e as Error).message, elapsed: ((Date.now() - started) / 1000).toFixed(1) };
  }
}

async function interactive(args: ReturnType<typeof parseArgs>) {
  const { url, user, conv } = args;
  console.log(`\n连接: ${url}`);
  console.log(`用户: ${user}   会话: ${conv}`);
  console.log("输入消息开始对话，:quit 退出，:health 查健康\n");

  const rl = readline.createInterface({ input, output });
  for (;;) {
    const line = (await rl.question("你> ")).trim();
    if (!line) continue;
    if (line === ":quit" || line === "q") break;
    if (line === ":health") {
      await health(url);
      continue;
    }
    const r = await chat(url, user, conv, line, args.timeout);
    if (r.ok) {
      console.log(`\nAgent> ${r.reply}\n[${r.elapsed}s]\n`);
    } else {
      console.error(`\n[错误] ${r.error}（${r.elapsed}s）\n`);
    }
  }
  rl.close();
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.health) {
    const ok = await health(args.url);
    process.exit(ok ? 0 : 1);
  }

  // 健康预检（信息性，不阻塞）
  await health(args.url).catch(() => {});

  if (args.message) {
    const r = await chat(args.url, args.user, args.conv, args.message, args.timeout);
    if (r.ok) {
      console.log(r.reply);
      process.exit(0);
    }
    console.error(`错误: ${r.error}（${r.elapsed}s）`);
    process.exit(1);
  }

  await interactive(args);
}

const entry = resolve(process.argv[1] ?? "");
if (entry.endsWith("client.ts") || entry.endsWith("client.js") || existsSync(resolve("src/client.ts"))) {
  main().catch((e) => {
    console.error("客户端异常:", e);
    process.exit(1);
  });
}
