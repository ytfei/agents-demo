# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## 项目概述

这是一个 **DeepAgents** 入门 demo，用于学习如何结合 **DeepSeek** 模型高效构建 Agent。
核心依赖：`deepagents`（Agent Harness 层）、`langchain-deepseek`（DeepSeek 模型接入）、`tavily-python`（联网搜索工具）、`python-dotenv`（环境变量）。
示例使用 `uv` 管理环境与依赖（`pyproject.toml` + `uv.lock`）。

## 常用命令

- **安装依赖**：`uv sync`（基于 pyproject.toml 创建 .venv 并安装依赖）。
- **运行 demo**：`uv run main.py`（从 .env 读取 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY` 后执行）。
- **激活环境**：`uv run <命令>` 会自动使用项目 venv，无需手动 activate。
- **添加依赖**：`uv add <package>`（如 `uv add openai`）自动更新 pyproject.toml 与 uv.lock。
- **环境变量**：复制 `.env` 中的 `DEEPSEEK_API_KEY`、`TAVILY_API_KEY`、`LANGSMITH_*` 后运行；`.env` 已被 gitignore 忽略，切勿提交密钥。

## 架构与最佳实践

### 三层 Agent 技术栈（自底向上）
1. **Runtime（LangGraph）**：持久化执行、流式输出、人机协作、状态管理。需精细控制长期运行的 Agent 时使用。
2. **Framework（LangChain）**：构建于 LangGraph 之上，提供模型抽象、工具接口、Agent 循环，适合快速标准化开发。
3. **Harness（Deep Agents）**：预置开箱即用能力（虚拟文件系统、任务规划、子 Agent、长期记忆），适合复杂多步骤、高自主性任务。

本 demo 直接使用 Harness 层（`create_deep_agent`），把通用能力交给框架，而非从零手写文件读写/任务调度。需求越复杂，越应优先复用 Harness 预置工具。

### Deep Agents 预置共性能力（避免重复造轮子）
- **虚拟文件系统**：`read_file` / `write_file` / `edit_file` / `ls` / `glob` / `grep`。
- **任务规划**：`write_todos` 将大任务拆为可追踪的步骤。
- **子 Agent 委派**：`task` 工具把子任务派发给专门 Agent。
- **长期记忆**：基于 LangGraph Memory Store 跨对话持久化用户偏好。

### 上下文工程（Context Engineering）——核心反模式与正确做法
- **反模式**：把所有信息塞进 prompt → 上下文溢出、注意力稀释、不可扩展。
- **正确做法**：把 Harness 当作「为 LLM 高效获取/管理信息的基础设施」。用虚拟文件系统按需 `read_file`/`grep`/`glob`，大文件用 `offset`/`limit` 只读所需部分；上下文只保留当前步骤必要信息，其余落盘，需要时再取。
- **可插拔存储**：内存（调试）、本地磁盘、数据库（记忆）、远程沙箱（安全执行）可混合路由。

### 工具定义与 System Prompt
- `create_deep_agent(model=, tools=, system_prompt=)` 是核心 API 形态。
- **工具**由应用自行实现并注册（如本仓库的 `internet_search`），函数 docstring 即工具说明，务必清晰描述参数与用途。
- **System Prompt 应简明**（如 `"You are a helpful assistant."`），复杂行为交由 Harness 预置工具与上下文工程处理，不要把所有规则堆进 prompt。

### 模型选择与接入（关键：模型无关）
- Deep Agents 不锁定厂商，支持 100+ 模型。本 demo 通过 `langchain-deepseek.ChatDeepSeek` 接入 `deepseek-v4-pro`。
- 切换模型只需替换 `model=` 参数，工具与 Harness 逻辑无需改动，这是企业级部署的推荐方式。
- 不要针对特定模型硬编码行为；保持 Agent 逻辑与模型解耦，便于 A/B 与回退。

### 任务拆解与委派
- 复杂任务先用 `write_todos` 拆解；执行中发现新子问题时用 `task` 委派给子 Agent，避免主上下文被淹没。

### 可观测性与部署
- `.env` 已开启 **LangSmith**（`LANGSMITH_TRACING=true` + project `StockAnalyzer`），所有 Agent 调用可追溯，调试时优先查看 LangSmith trace。
- 生产部署推荐 LangGraph Platform + LangSmith 做可观测性；敏感操作可走远程沙箱（Sandbox-as-Tool）。

## 关键文件
- `main.py`：`create_deep_agent` 的端到端示例（DeepSeek 模型 + `internet_search` 工具 + 最小 system prompt）。修改模型、工具、prompt 均从此文件入手。
- `stock_analysis.py` / `stock_analysis_prompt.md`：股票分析 demo，system prompt 从 markdown 文件读取（便于业务方独立维护）。
- `skill_demo.py` + `skills/stock-metrics/`：演示 skill 加载与其中 python 脚本经 `execute` 执行（用 `LocalShellBackend`，本机无沙箱，仅本地 demo）。
- `presales_agent.py` + `product_api.py` + `skills/product-catalog/`：售前 Agent demo。每个用户一个独立 agent 实例，记忆经 `CompositeBackend` 路由到按 `user_id` 隔离 namespace 的 `StoreBackend`（`/memories/` 分区），实现跨对话、用户间隔离的持久化；产品数据由 `product_api.get_product_catalog` 模拟「产品描述接口」。
- `pyproject.toml`：依赖与 Python 版本（>=3.12）声明，决定运行环境。
- `.env`：密钥与 LangSmith 配置，本地运行必需，已被 gitignore。

## 用户隔离持久化范式（presales_agent.py 的核心模式）
- 用 `CompositeBackend(default=StateBackend(), routes={"/memories/": StoreBackend(store, namespace=lambda _rt: (f"user:{user_id}",))})`。
- **每个用户构建独立 agent 实例**，其 StoreBackend 的 namespace 绑定该 user_id——天然实现"每个用户的上下文存在不同地方"。
- Agent 把用户画像写进 `/memories/user_profile.md`（落 StoreBackend），重连时用新实例即可读回历史，延续对话。
- 跨进程真落盘可把 `InMemoryStore` 换成 `SqliteStore`（需装 `langgraph-store-sqlite`）。
