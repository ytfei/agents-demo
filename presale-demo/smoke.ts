import { ChatDeepSeek } from "@langchain/deepseek";
import { MemoryStore, MemorySaver } from "@langchain/langgraph-checkpoint";
import {
  CompositeBackend,
  createDeepAgent,
  StateBackend,
  StoreBackend,
} from "deepagents";
import { config } from "./src/config.js";
import { getCategories, getProductCatalog } from "./src/tools.js";

// namespace 工厂验证：模拟 config.configurable.user_id
let captured: string[] = [];
const memoryBackend = new StoreBackend({
  store: new MemoryStore(),
  namespace: (ctx: any) => {
    captured = [`user:${ctx?.config?.configurable?.user_id ?? "anonymous"}`];
    return captured;
  },
});
const backend = new CompositeBackend(new StateBackend(), {
  "/memories/": memoryBackend,
});

const model = new ChatDeepSeek({
  model: config.deepseekModel,
  apiKey: config.deepseekApiKey || "dummy",
});

const agent = createDeepAgent({
  model,
  tools: [getProductCatalog, getCategories],
  systemPrompt: "test",
  checkpointer: new MemorySaver(),
  store: new MemoryStore(),
  backend,
});

console.log("graph compiled:", typeof (agent as any).invoke === "function");
console.log("namespace factory captured (before call):", captured);
// 触发一次调用会真正打 LLM，这里只验证构建与工厂签名存在
console.log("SMOKE OK");
