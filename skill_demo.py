"""演示 DeepAgent 的 skills 功能：如何从磁盘加载 skill，并执行其中的 python 脚本。

核心机制（参考 deepagents 源码）：
- `create_deep_agent(..., skills=["/skills/"])` 通过 SkillsMiddleware 扫描
  backend 根目录下 skill 目录中的 SKILL.md，将 frontmatter 的 name/description
  注入系统提示，供模型决定是否调用该 skill。
- Skill 本质是「注入上下文的文件」，SKILL.md 内的指令会告诉模型如何读取并
  用 `execute` 工具运行同目录下的 python 脚本（如 compute.py）。
- 默认 `execute` 工具需要后端实现 SandboxBackendProtocol；这里用 LocalShellBackend
  （本机直接执行，无沙箱隔离）以便 demo 真正跑起来。仅用于受信任的本地环境。

运行：uv run skill_demo.py
"""

from langgraph.graph.state import CompiledStateGraph


from langchain.agents.middleware.types import AgentState, InputAgentState, OutputAgentState


from typing import Any


import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    # LocalShellBackend 既提供文件系统（加载 skills），又实现 execute 工具所需的
    # SandboxBackendProtocol，使 agent 能用 shell 真正运行 skill 里的 python 脚本。
    backend = LocalShellBackend(root_dir=PROJECT_ROOT)

    model = ChatDeepSeek(
        model="deepseek-v4-pro", api_key=os.environ["DEEPSEEK_API_KEY"]
    )

    agent: CompiledStateGraph[AgentState[Any], Any, InputAgentState, OutputAgentState[Any]] = create_deep_agent(
        model=model,
        backend=backend,
        # skills 为相对 backend 根目录的 POSIX 路径；会扫描其下每个含 SKILL.md
        # 的子目录并注入到上下文。
        skills=["/skills/"],
        system_prompt="You are a helpful assistant that uses available skills when relevant.",
    )

    print("Skill demo agent ready. Loaded skills from ./skills/")

    question = input(
        "Enter a request (e.g. '用 stock-metrics 计算 100 102 99 105 103 的指标'): "
    ).strip()
    if not question:
        question = "Use the stock-metrics skill to compute metrics for prices 100 102 99 105 103."

    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    print("\n=== Agent reply ===\n")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
