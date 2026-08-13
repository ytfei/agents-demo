import os
from typing import Literal

from tavily import TavilyClient
from deepagents import create_deep_agent

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Run a web search"""
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


def main():
    from langchain_deepseek import ChatDeepSeek
    from deepagents import create_deep_agent

    # Initialize the desired DeepSeek model (e.g., DeepSeek V4 Pro)
    model = ChatDeepSeek(
        model="deepseek-v4-pro", api_key=os.environ["DEEPSEEK_API_KEY"]
    )

    # Spin up the Deep Agent
    agent = create_deep_agent(
        model=model,
        tools=[internet_search],
        system_prompt="You are a helpful assistant.",
    )

    print("Deep Agent successfully initialized with DeepSeek!")

    result = agent.invoke({"messages": [{"role": "user", "content": "What is langgraph?"}]})

    # Print the agent's response
    print(result["messages"][-1].content)    


if __name__ == "__main__":
    main()
