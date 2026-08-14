import { argv } from "node:process";

/**
 * 轻量压测脚本 —— 模拟 N 个并发用户打 /chat。
 * 用法：pnpm bench --users 200 --requests 1000
 * 依赖 axios/fetch（Node 内置 fetch 即可，无需额外依赖）。
 */

function parseArgs(): { users: number; requests: number } {
  const users = Number(argv.find((a, i) => a === "--users" && argv[i + 1]) ?? 200);
  const requests = Number(argv.find((a, i) => a === "--requests" && argv[i + 1]) ?? 1000);
  return { users: users || 200, requests: requests || 1000 };
}

async function oneUser(base: string, userId: string, convId: string, n: number): Promise<number> {
  let ok = 0;
  for (let i = 0; i < n; i++) {
    try {
      const res = await fetch(`${base}/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          conversation_id: convId,
          message: `我想买冰箱，家里 ${i % 5 + 2} 口人，预算 5000。`,
        }),
      });
      if (res.status === 200) ok++;
    } catch {
      // 忽略网络错误，计入失败
    }
  }
  return ok;
}

async function main() {
  const { users, requests } = parseArgs();
  const base = `http://localhost:${process.env.PORT ?? 8000}`;
  const per = Math.max(1, Math.floor(requests / users));
  const start = Date.now();

  const tasks = Array.from({ length: users }, (_, u) =>
    oneUser(base, `u${u}`, `c${u}`, per),
  );
  const results = await Promise.all(tasks);

  const elapsed = (Date.now() - start) / 1000;
  const total = results.reduce((a, b) => a + b, 0);
  console.log(
    `users=${users} total_requests=${total} elapsed=${elapsed.toFixed(1)}s ` +
      `rps=${(total / elapsed).toFixed(1)} success_rate=${((total / (users * per)) * 100).toFixed(1)}%`,
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
