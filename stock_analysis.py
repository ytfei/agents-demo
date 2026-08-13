import os
from typing import Literal

from dotenv import load_dotenv
from tavily import TavilyClient
from deepagents import create_deep_agent

load_dotenv()

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "finance",
    include_raw_content: bool = False,
):
    """Run a web search for up-to-date financial information, news, or market data."""
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


PROMPT_PATH = os.path.join(os.path.dirname(__file__), "stock_analysis_prompt.md")


def load_system_prompt(path: str = PROMPT_PATH) -> str:
    """Read the system prompt from a markdown file.

    Falls back to a minimal default if the file is missing so the agent
    can still run while the prompt is being authored.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Warning: {path} not found, using default system prompt.")
        return "You are a helpful assistant."


def main():
    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(
        model="deepseek-v4-pro", api_key=os.environ["DEEPSEEK_API_KEY"]
    )

    # System prompt 从 stock_analysis_prompt.md 读取（在此文件中补充分析框架）。
    system_prompt = load_system_prompt()

    agent = create_deep_agent(
        model=model,
        tools=[internet_search],
        system_prompt=system_prompt,
    )

    print("Stock Analysis Agent initialized with DeepSeek!")

    question = input("Enter a stock or analysis question (e.g. '分析一下英伟达 NVDA'): ").strip()
    if not question:
        question = "What is a good framework for analyzing a stock?"

    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
