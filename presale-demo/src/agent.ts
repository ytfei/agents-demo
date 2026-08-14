import { ChatDeepSeek } from "@langchain/deepseek";
import { PostgresSaver } from "@langchain/langgraph-checkpoint-postgres";
import { Pool } from "pg";
import {
  CompositeBackend,
  createDeepAgent,
  StateBackend,
  StoreBackend,
} from "deepagents";
type DeepAgentGraph = ReturnType<typeof createDeepAgent>;
import { config } from "./config.js";
import { PostgresStore } from "./pgStore.js";
import { getCategories, getProductCatalog } from "./tools.js";

const SYSTEM_PROMPT = `你是我们公司的家电售前顾问。你的目标是通过友好对话向用户推销我们的家电产品。

工作流程（务必遵守）：
1. 每次对话开始前，先读取 /memories/user_profile.md（若存在），回顾用户上次的喜好、家庭成员、装修风格、预留尺寸等信息，延续上次的沟通。
2. 如果用户的需求信息不完整，主动询问：家里几口人、偏好的电器风格（如现代简约/北欧/轻奢）、装修风格、各类电器的预留安装尺寸。
3. 需要产品信息时，使用 get_product_catalog 工具或 get_categories 获取型号、参数、价格和最小安装宽度。
4. 结合用户的家庭情况与预留尺寸，给出 1-3 款最匹配的推荐，并说明推荐理由与价格。
5. 把了解到的用户画像（人口、风格、装修、尺寸、已推荐内容）更新写入 /memories/user_profile.md，以便下次对话继续。

语气亲切专业，不要一次性抛出所有型号，先理解需求再推荐。`;

/**
 * 并发隔离核心（对标 Python 版 _user_namespace）：
 * 同一份全局 agent，不同 user_id 路由到不同 StoreBackend namespace，
 * 记忆天然按用户隔离。deepagents 的 namespace 工厂从当前 run 的
 * config.configurable 取 user_id。
 */
function userNamespace(context: {
  config?: { configurable?: Record<string, unknown> };
}): string[] {
  const userId =
    (context.config?.configurable?.user_id as string | undefined) ?? "anonymous";
  return [`user:${userId}`];
}

// ---- 进程内单例（多 worker 时每个 worker 各持一份）----
let _agent: DeepAgentGraph | null = null;
let _store: PostgresStore | null = null;
let _pgPool: Pool | null = null;

export async function initAgent(): Promise<void> {
  if (_agent) return;
  if (!config.databaseUrl) {
    throw new Error("缺少 DATABASE_URL，无法初始化 Postgres store（生产必需）。");
  }

  // 1) Postgres 连接池（checkpoint 与 store 共用同一池）
  _pgPool = new Pool({ connectionString: config.databaseUrl });
  _store = await PostgresStore.create(config.databaseUrl);

  // 2) checkpointer：对话上下文按 configurable.thread_id 隔离（进程安全）
  const checkpointer = new PostgresSaver(_pgPool);
  // 关键：必须 setup() 创建 checkpoints / checkpoint_writes 等表，
  // 否则首次调用会报 relation "public.checkpoints" does not exist。
  await checkpointer.setup();

  // 3) backend：/memories/ 路由到按 user_id 隔离的 store；其余用 StateBackend
  const memoryBackend = new StoreBackend({
    store: _store,
    namespace: userNamespace,
  });
  const backend = new CompositeBackend(new StateBackend(), {
    "/memories/": memoryBackend,
  });

  // 4) 编译一次 agent（开销大，必须单例）
  const model = new ChatDeepSeek({
    model: config.deepseekModel,
    apiKey: config.deepseekApiKey,
  });

  _agent = createDeepAgent({
    model,
    tools: [getProductCatalog, getCategories],
    systemPrompt: SYSTEM_PROMPT,
    checkpointer,
    store: _store,
    backend,
  });
}

export function getAgent(): DeepAgentGraph {
  if (!_agent) throw new Error("agent 未初始化，请先调用 initAgent()");
  return _agent;
}

export function getStore(): PostgresStore {
  if (!_store) throw new Error("store 未初始化，请先调用 initAgent()");
  return _store;
}

export async function shutdownAgent(): Promise<void> {
  await _store?.close();
  await _pgPool?.end();
}
