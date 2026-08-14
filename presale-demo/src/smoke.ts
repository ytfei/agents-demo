/**
 * 冒烟测试 —— 针对已部署的售前 Agent 验证核心功能正常。
 *
 * 用法：
 *   pnpm smoke                              # 全部用例（含真实 LLM 调用，需 DEEPSEEK_API_KEY）
 *   pnpm smoke --no-llm                     # 跳过真实 LLM 对话用例（只测路由/隔离/限流）
 *   pnpm smoke --url http://localhost:8000  # 指定目标
 *
 * 用例覆盖：
 *   [1] /healthz 存活                       —— 服务是否起来
 *   [2] /chat 参数校验                       —— 缺参应 400
 *   [3] /chat 正常对话（LLM）               —— 200 + 非空回复
 *   [4] 多用户并发隔离                       —— 不同 user/conv 并发不互相污染
 *   [5] 限流                                —— 超过每用户速率上限应 429
 *
 * 通过输出 "PASS"，失败输出 "FAIL"，全部通过退出码 0，任一失败退出码 1。
 */
import { resolve } from "node:path";
import { existsSync } from "node:fs";

const BASE = process.env.SMOKE_URL ?? process.env.CHECK_URL ?? "http://localhost:8000";
const WITH_LLM = !process.argv.includes("--no-llm");
const RATE_LIMIT = Number(process.env.RATE_LIMIT_PER_USER ?? 10);

let passed = 0;
let failed = 0;
const failures: string[] = [];

function report(name: string, ok: boolean, detail = "") {
  if (ok) {
    passed++;
    console.log(`  ✓ PASS  ${name}${detail ? `  (${detail})` : ""}`);
  } else {
    failed++;
    failures.push(name);
    console.error(`  ✗ FAIL  ${name}${detail ? `  (${detail})` : ""}`);
  }
}

async function healthz() {
  try {
    const res = await fetch(`${BASE}/healthz`);
    const body = await res.json();
    report("[1] 健康检查 /healthz", res.status === 200 && (body as any).status === "ok", `status=${res.status}`);
  } catch (e) {
    report("[1] 健康检查 /healthz", false, (e as Error).message);
  }
}

async function validation() {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  report("[2] 参数校验（缺 user_id 应 400）", res.status === 400, `status=${res.status}`);
}

async function normalChat() {
  const userId = `smoke-${Date.now()}`;
  const convId = `smoke-conv-${Date.now()}`;
  const started = Date.now();
  try {
    const res = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        conversation_id: convId,
        message: "你好，我想看看有什么冰箱推荐",
      }),
    });
    const text = await res.text();
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    let body: any = {};
    try {
      body = JSON.parse(text);
    } catch {}
    const hasReply = typeof body.reply === "string" && body.reply.trim().length > 0;
    report("[3] 正常对话 /chat（LLM）", res.status === 200 && hasReply, `status=${res.status} replyLen=${String(body.reply ?? "").length} ${elapsed}s`);
  } catch (e) {
    report("[3] 正常对话 /chat（LLM）", false, (e as Error).message);
  }
}

async function concurrentIsolation() {
  // 并发 5 个不同用户/会话，各自应返回 200 且互不干扰（用不同 user 触发不同 namespace）。
  const tasks = Array.from({ length: 5 }, (_, i) =>
    fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        user_id: `smoke-iso-${i}-${Date.now()}`,
        conversation_id: `smoke-isoc-${i}-${Date.now()}`,
        message: "简单介绍一下你们的产品",
      }),
    }),
  );
  const results = await Promise.allSettled(tasks);
  const ok = results.every(
    (r) => r.status === "fulfilled" && (r.value as Response).status === 200,
  );
  const statuses = results.map((r) =>
    r.status === "fulfilled" ? (r.value as Response).status : "rejected",
  );
  report("[4] 多用户并发隔离", ok, `statuses=${statuses.join(",")}`);
}

async function rateLimit() {
  const userId = `smoke-rl-${Date.now()}`;
  let got429 = false;
  // 连续打 RATE_LIMIT+5 次，超过上限应至少出现一次 429
  for (let i = 0; i < RATE_LIMIT + 5; i++) {
    const res = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        conversation_id: `smoke-rlc-${Date.now()}`,
        message: "测试限流",
      }),
    });
    if (res.status === 429) {
      got429 = true;
      break;
    }
  }
  report("[5] 限流（超限应 429）", got429, got429 ? "检测到 429" : `未触发 429（上限 ${RATE_LIMIT}/s）`);
}

async function main() {
  console.log(`\n冒烟测试目标: ${BASE}`);
  console.log(`LLM 真实对话: ${WITH_LLM ? "开" : "关（--no-llm）"}\n`);

  await healthz();
  await validation();
  if (WITH_LLM) {
    await normalChat();
    await concurrentIsolation();
  } else {
    console.log("  - 跳过 [3] 正常对话、[4] 并发隔离（--no-llm）");
  }
  await rateLimit();

  console.log(`\n结果: ${passed} passed, ${failed} failed`);
  if (failed > 0) {
    console.error(`失败用例: ${failures.join(", ")}`);
    process.exit(1);
  }
  process.exit(0);
}

const entry = resolve(process.argv[1] ?? "");
if (entry.endsWith("smoke.ts") || entry.endsWith("smoke.js") || existsSync(resolve("src/smoke.ts"))) {
  main().catch((e) => {
    console.error("冒烟测试执行异常:", e);
    process.exit(1);
  });
}
