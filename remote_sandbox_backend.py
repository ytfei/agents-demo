"""远程沙箱 Backend —— 生产环境替代 LocalShellBackend（本机 shell）。

为什么需要：10W 并发下绝不能让所有用户的 skill 脚本在同一台宿主机 shell
上执行（互相踩踏 + 安全灾难）。用 Daytona 等远程微 VM 隔离执行。

实现：把 deepagents 的 BackendProtocol 方法直接委托给 langchain_daytona
的 DaytonaSandbox（方法签名天然对齐）。沙箱实例可复用（构造时创建一次），
生产环境建议按租户/会话池化，避免每次请求都新建 sandbox。

注意：本文件为「可选生产组件」，presales_agent.build_agent 默认仍用
LocalShellBackend（demo 友好）。切换到远程沙箱时，把 backend 参数传入
RemoteSandboxBackend 即可。
"""

from __future__ import annotations

import os

from deepagents.backends import BackendProtocol
from langchain_daytona import DaytonaSandbox


class RemoteSandboxBackend(BackendProtocol):
    """基于 Daytona 远程微 VM 的 backend 适配器。"""

    def __init__(self, *, api_key: str | None = None, root_dir: str = "/workspace"):
        from daytona import Daytona, DaytonaConfig

        cfg = DaytonaConfig(api_key=api_key or os.environ["DAYTONA_API_KEY"])
        daytona = Daytona(cfg)
        # 复用单个 sandbox 实例（生产可改为池化）
        self._sandbox = DaytonaSandbox(sandbox=daytona.create())
        self.root_dir = root_dir

    # ---- 文件系统 ----
    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        return self._sandbox.read(file_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str):
        return self._sandbox.write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False):
        return self._sandbox.edit(file_path, old_string, new_string, replace_all=replace_all)

    def ls(self, path: str):
        return self._sandbox.ls(path)

    def glob(self, pattern: str, path: str | None = None):
        return self._sandbox.glob(pattern, path=path)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None):
        return self._sandbox.grep(pattern, path=path, glob=glob, max_count=max_count)

    def execute(self, command: str, *, timeout: int | None = None):
        return self._sandbox.execute(command, timeout=timeout)
