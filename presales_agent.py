"""售前 Agent Demo —— 家电推销 + 用户上下文持久化。

设计要点（对应需求）：
1. 产品推销：通过 product_api.py 模拟「产品描述接口」，并以 skill
   (skills/product-catalog) + get_product_catalog 工具暴露给 Agent。
2. 主动询问：system prompt 要求 Agent 先了解家庭需求（人口、风格、装修、
   预留尺寸），再据此推荐；每次都先读历史记忆再继续对话。
3. 上下文持久化：每个用户一个独立 agent 实例，记忆落在
   CompositeBackend 的 /memories/ 分区，该分区使用按 user_id 隔离 namespace
   的 StoreBackend —— 即「每个用户的上下文存储在不同地方」。
   - /memories/  -> StoreBackend(namespace=(user_id,))  跨对话持久、用户隔离
   - / 默认      -> StateBackend                        会话内临时文件

运行：uv run presales_agent.py
"""

import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, LocalShellBackend

import product_api
from file_store import FilePerUserStore

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 文件型 store：每个 namespace（即每个用户）持久化到 store_data/ 下的独立 JSON 文件，
# 进程重启后记忆仍在。所有用户共享同一 FilePerUserStore 实例，按 namespace 分文件隔离。
_SHARED_STORE = FilePerUserStore(data_dir=os.path.join(PROJECT_ROOT, "store_data"))

SYSTEM_PROMPT = """你是我们公司的家电售前顾问。你的目标是通过友好对话向用户推销我们的家电产品。

工作流程（务必遵守）：
1. 每次对话开始前，先读取 /memories/user_profile.md（若存在），回顾用户上次的喜好、家庭成员、装修风格、预留尺寸等信息，延续上次的沟通。
2. 如果用户的需求信息不完整，主动询问：家里几口人、偏好的电器风格（如现代简约/北欧/轻奢）、装修风格、各类电器的预留安装尺寸。
3. 需要产品信息时，使用 get_product_catalog 工具或 product-catalog skill 获取型号、参数、价格和最小安装宽度。
4. 结合用户的家庭情况与预留尺寸，给出 1-3 款最匹配的推荐，并说明推荐理由与价格。
5. 把了解到的用户画像（人口、风格、装修、尺寸、已推荐内容）更新写入 /memories/user_profile.md，以便下次对话继续。

语气亲切专业，不要一次性抛出所有型号，先理解需求再推荐。"""


def build_agent_for_user(user_id: str):
    """为每个用户构建独立 agent：记忆按 user_id 隔离到不同存储分区。"""
    # 用户专属的记忆后端：namespace 固定为该用户 -> 逻辑上「存到不同地方」。
    memory_backend = StoreBackend(
        store=_SHARED_STORE,
        namespace=lambda _rt: (f"user:{user_id}",),
    )
    composite = CompositeBackend(
        default=StateBackend(),              # 会话内临时文件
        routes={
            "/memories/": memory_backend,     # 用户持久记忆，隔离存储
            # 关键：skills 在磁盘 ./skills/ 下，必须显式路由到磁盘 backend，
            # 否则 /skills/ 会落到 default(StateBackend) 而找不到 SKILL.md。
            # 注意：composite 会剥掉前缀 /skills/，所以这里 root_dir 要指向
            # ./skills 目录本身（而非项目根），这样源路径 /skills/ 落到该 backend
            # 根后，正好扫描到 product-catalog/ 等 skill 子目录。
            "/skills/": LocalShellBackend(root_dir=os.path.join(PROJECT_ROOT, "skills")),
        },
    )

    model = ChatDeepSeek(
        model="deepseek-v4-pro", api_key=os.environ["DEEPSEEK_API_KEY"]
    )

    return create_deep_agent(
        model=model,
        backend=composite,
        tools=[product_api.get_product_catalog, product_api.get_categories],
        skills=["/skills/"],
        system_prompt=SYSTEM_PROMPT,
    )


def chat_once(agent, user_input: str) -> str:
    result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})
    return result["messages"][-1].content


def main():
    print("=== 家电售前 Agent Demo ===")
    user_id = input("请输入用户标识 (如 alice / bob): ").strip() or "demo_user"
    agent = build_agent_for_user(user_id)
    print(f"[已为用户 {user_id} 创建独立会话，记忆持久化在 /memories/ (namespace=user:{user_id})]\n")

    # 首轮：主动破冰 + 询问需求
    reply = chat_once(agent, "你好，我想看看你们家的家电。")
    print("Agent:", reply, "\n")

    try:
        while True:
            user_input = input("你: ").strip()
            if user_input.lower() in {"exit", "quit", "q", "退出"}:
                break
            if not user_input:
                continue
            reply = chat_once(agent, user_input)
            print("Agent:", reply, "\n")
    except (EOFError, KeyboardInterrupt):
        pass

    print("\n[提示] 重新以同一 user_id 运行本脚本，Agent 会从 /memories/ 读回历史画像继续对话。")


if __name__ == "__main__":
    main()
