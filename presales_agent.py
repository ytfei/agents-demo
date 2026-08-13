"""售前 Agent —— 家电推销 + 用户上下文持久化（10W 级并发就绪）。

设计要点（对应需求与高并发架构）：
1. 产品推销：通过 product_api.py 模拟「产品描述接口」，并以 skill
   (skills/product-catalog) + get_product_catalog 工具暴露给 Agent。
2. 主动询问：system prompt 要求 Agent 先了解家庭需求，再据此推荐；
   每次都先读历史记忆再继续对话。
3. 上下文持久化（并发隔离核心）：
   - 对话上下文（checkpoint）按 configurable["thread_id"] 隔离。
   - 长期记忆（/memories/）按 configurable["user_id"] 隔离，经
     StoreBackend 的 namespace 路由到共享的 Postgres store。
   - 关键：不再「每用户 new 一个 agent 实例」（那样会重复编译 graph），
     而是编译一次全局单例 AGENT，user_id/thread_id 在每次 invoke 时
     通过 configurable 注入。graph 是只读模板，10W 请求共用同一份。

运行：
  - 本地 demo：uv run presales_agent.py
  - 生产服务：uv run agent_service.py  （FastAPI + uvicorn 多 worker）
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

import product_api
from pg_store import AsyncPostgresStore

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 环境变量（生产由 .env / 配置中心注入）
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

def _user_namespace(_rt=None) -> tuple[str, ...]:
    """从当前 run 的 configurable 取 user_id，作为 StoreBackend 的 namespace。

    并发隔离核心：同一份全局 AGENT，不同 user_id 路由到不同 namespace，
    记忆天然按用户隔离。deepagents 的 Runtime 无 .config，需走
    langgraph.config.get_config()。
    """
    from langgraph.config import get_config

    cfg = get_config()
    user_id = cfg["configurable"].get("user_id", "anonymous")
    return (f"user:{user_id}",)


SYSTEM_PROMPT = """你是我们公司的家电售前顾问。你的目标是通过友好对话向用户推销我们的家电产品。

工作流程（务必遵守）：
1. 每次对话开始前，先读取 /memories/user_profile.md（若存在），回顾用户上次的喜好、家庭成员、装修风格、预留尺寸等信息，延续上次的沟通。
2. 如果用户的需求信息不完整，主动询问：家里几口人、偏好的电器风格（如现代简约/北欧/轻奢）、装修风格、各类电器的预留安装尺寸。
3. 需要产品信息时，使用 get_product_catalog 工具或 product-catalog skill 获取型号、参数、价格和最小安装宽度。
4. 结合用户的家庭情况与预留尺寸，给出 1-3 款最匹配的推荐，并说明推荐理由与价格。
5. 把了解到的用户画像（人口、风格、装修、尺寸、已推荐内容）更新写入 /memories/user_profile.md，以便下次对话继续。

语气亲切专业，不要一次性抛出所有型号，先理解需求再推荐。"""


def _make_backend():
    """构造 backend。

    本地 demo 用 LocalShellBackend（仅本机、受信任环境）。
    生产环境应替换为远程沙箱（见 agent_service.py 的 RemoteSandboxBackend），
    避免多用户在本机 shell 互相踩踏。
    """
    from deepagents.backends import LocalShellBackend

    memory_backend = StoreBackend(
        # namespace 从当前 run 的 configurable["user_id"] 取 —— 这才是
        # 并发隔离的关键：同一份 AGENT，不同 user_id 路由到不同 namespace。
        # 注意：deepagents 的 Runtime 没有 .config 属性，必须走
        # langgraph.config.get_config() 取当前 run 的 RunnableConfig。
        store=None,  # 由调用方注入（build_agent 时传入）
        namespace=_user_namespace,
    )
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/memories/": memory_backend,
            "/skills/": LocalShellBackend(root_dir=os.path.join(PROJECT_ROOT, "skills")),
        },
    )


def build_agent(*, store, checkpointer=None, backend=None):
    """构建（编译）一个 deep agent。

    注意：这是一次性的「编译」动作，开销大。生产环境应只调用一次并缓存为单例
    （见 get_agent / agent_service.py），绝不要在每用户请求时调用。
    """
    if backend is None:
        # 临时 backend，store 在闭包里注入
        memory_backend = StoreBackend(
            store=store,
            namespace=_user_namespace,
        )
        from deepagents.backends import LocalShellBackend

        backend = CompositeBackend(
            default=StateBackend(),
            routes={
                "/memories/": memory_backend,
                "/skills/": LocalShellBackend(root_dir=os.path.join(PROJECT_ROOT, "skills")),
            },
        )

    model = ChatDeepSeek(model="deepseek-v4-pro", api_key=DEEPSEEK_API_KEY)

    kwargs = {
        "model": model,
        "backend": backend,
        "tools": [product_api.get_product_catalog, product_api.get_categories],
        "skills": ["/skills/"],
        "system_prompt": SYSTEM_PROMPT,
        "store": store,
    }
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer

    return create_deep_agent(**kwargs)


# ---------------------------------------------------------------------------
# 单例：进程内只编译一次 graph。多 uvicorn worker 时每个 worker 各持一份。
# ---------------------------------------------------------------------------
_AGENT = None
_STORE = None


def get_store() -> AsyncPostgresStore:
    """懒加载共享 store（每个 worker 一个连接池）。"""
    global _STORE
    if _STORE is None:
        raise RuntimeError("store 未初始化，请先调用 init_agent()")
    return _STORE


async def init_agent() -> None:
    """应用启动时调用一次：建立 Postgres 连接池 + 编译 agent 单例。"""
    global _AGENT, _STORE
    if _AGENT is not None:
        return
    if not DATABASE_URL:
        raise RuntimeError("缺少 DATABASE_URL，无法初始化 Postgres store（生产必需）。")
    _STORE = await AsyncPostgresStore.create(
        DATABASE_URL, pool_min=4, pool_max=64
    )
    _AGENT = build_agent(store=_STORE)


def get_agent():
    """返回编译好的全局 agent 单例（必须已 init_agent）。"""
    if _AGENT is None:
        raise RuntimeError("agent 未初始化，请先调用 init_agent()")
    return _AGENT


# ---------------------------------------------------------------------------
# 本地 demo（同步、单用户交互），便于直接运行验证行为。
# ---------------------------------------------------------------------------
def chat_once(agent, user_input: str, *, user_id: str, thread_id: str) -> str:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_input}]},
        config={"configurable": {"user_id": user_id, "thread_id": thread_id}},
    )
    return result["messages"][-1].content


def main():
    # 本地 demo 用 JSON 文件 store（file_store.FilePerUserStore）即可，无需 Postgres。
    from file_store import FilePerUserStore

    store = FilePerUserStore(data_dir=os.path.join(PROJECT_ROOT, "store_data"))
    agent = build_agent(store=store)

    print("=== 家电售前 Agent Demo ===")
    user_id = input("请输入用户标识 (如 alice / bob): ").strip() or "demo_user"
    thread_id = input("会话 id (回车自动生成): ").strip() or f"thread-{user_id}-1"
    print(f"[记忆持久化在 store_data/，namespace=user:{user_id}]\n")

    reply = chat_once(agent, "你好，我想看看你们家的家电。", user_id=user_id, thread_id=thread_id)
    print("Agent:", reply, "\n")

    try:
        while True:
            user_input = input("你: ").strip()
            if user_input.lower() in {"exit", "quit", "q", "退出"}:
                break
            if not user_input:
                continue
            reply = chat_once(agent, user_input, user_id=user_id, thread_id=thread_id)
            print("Agent:", reply, "\n")
    except (EOFError, KeyboardInterrupt):
        pass

    print("\n[提示] 重新以同一 user_id 运行本脚本，Agent 会从历史读回画像继续对话。")


if __name__ == "__main__":
    main()
