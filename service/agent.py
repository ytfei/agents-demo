"""Agent 构建与进程内单例（10W 级并发隔离核心）。

设计要点：
- 编译一次：build_agent 内部走 create_deep_agent(...).compile(...)，开销大。
  init_agent 在应用启动时只调用一次，缓存为全局单例 _AGENT。
- 并发隔离靠 configurable：
    * 对话上下文（checkpoint）按 configurable["thread_id"] 隔离。
    * 长期记忆（/memories/）按 configurable["user_id"] 隔离，经
      StoreBackend 的 namespace 路由到共享 store（Postgres）。
- 关键：不再「每用户 new 一个 agent 实例」（那样会重复编译 graph），
  而是编译一次全局单例，user_id/thread_id 在每次 invoke 时通过 configurable 注入。
  graph 是只读模板，10W 请求共用同一份。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

import product_api
from .pg_store import AsyncPostgresStore

load_dotenv()

# 项目根（service/ 的上一级），用于定位 skills/ 目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def _user_namespace(_rt=None) -> tuple[str, ...]:
    """从当前 run 的 configurable 取 user_id，作为 StoreBackend 的 namespace。

    并发隔离核心：同一份全局 AGENT，不同 user_id 路由到不同 namespace，
    记忆天然按用户隔离。deepagents 的 Runtime 无 .config 属性，需走
    langgraph.config.get_config() 取当前 run 的 RunnableConfig。
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


def _local_backend(store) -> CompositeBackend:
    """本地 demo / 默认 backend：本机 shell 执行 skill。

    生产环境应改用 backend_remote.RemoteSandboxBackend 避免多用户互踩。
    """
    from deepagents.backends import LocalShellBackend

    memory_backend = StoreBackend(store=store, namespace=_user_namespace)
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/memories/": memory_backend,
            "/skills/": LocalShellBackend(root_dir=os.path.join(PROJECT_ROOT, "skills")),
        },
    )


def build_agent(*, store, checkpointer=None, backend=None):
    """构建（编译）一个 deep agent 单例。

    注意：这是一次性的「编译」动作，开销大。生产环境应只调用一次并缓存
    （见 init_agent），绝不要在每用户请求时调用。
    """
    if backend is None:
        backend = _local_backend(store)

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
# 进程内单例（多 uvicorn worker 时每个 worker 各持一份）。
# ---------------------------------------------------------------------------
_AGENT = None
_STORE = None


def get_store() -> AsyncPostgresStore:
    """返回共享 store（每个 worker 一个连接池）。"""
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
    _STORE = await AsyncPostgresStore.create(DATABASE_URL, pool_min=4, pool_max=64)
    _AGENT = build_agent(store=_STORE)


def get_agent():
    """返回编译好的全局 agent 单例（必须已 init_agent）。"""
    if _AGENT is None:
        raise RuntimeError("agent 未初始化，请先调用 init_agent()")
    return _AGENT
