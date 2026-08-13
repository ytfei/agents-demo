"""本地 demo 入口：售前 Agent 单用户交互（无需 Postgres）。

用于快速验证 Agent 行为：产品推销 + 主动询问 + 用户画像持久化。
长期记忆用 file_store.FilePerUserStore（每个用户一个 JSON 文件），
与生产服务的 service 包（Postgres + 远程沙箱 + FastAPI）共用同一套
agent 构建逻辑（service.agent.build_agent / SYSTEM_PROMPT）。

运行：uv run presales_agent.py
生产服务：uv run -m service.server
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from service.agent import build_agent
from file_store import FilePerUserStore

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def chat_once(agent, user_input: str, *, user_id: str, thread_id: str) -> str:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_input}]},
        config={"configurable": {"user_id": user_id, "thread_id": thread_id}},
    )
    return result["messages"][-1].content


def main():
    # 本地 demo 用 JSON 文件 store，无需 Postgres（生产服务见 service/ 包）
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
