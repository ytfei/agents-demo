"""本地文件型 BaseStore：每个 namespace 持久化到独立 JSON 文件。

用于替代 InMemoryStore，使售前 Agent 的用户记忆在进程退出后仍可保留，
且「每个用户一个独立文件」——namespace 直接映射为一个本地文件。

实现方式：继承 langgraph 的 InMemoryStore 复用其 get/search/list_namespaces
等逻辑，仅覆写 batch 增加两层：
  1. 启动时预加载 store_data/ 下所有已有文件到内存；
  2. 每次写/删操作后，把受影响 namespace 的数据落盘到独立 JSON 文件。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Iterable

from langgraph.store.base import Item, Op, Result
from langgraph.store.memory import InMemoryStore


def _ns_to_filename(namespace: tuple[str, ...]) -> str:
    """把一个 namespace 安全地映射成文件名，例如 ('user:alice',) -> 'user_alice.json'。"""
    raw = "__".join(namespace)
    safe = (
        raw.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "_")
    )
    return f"{safe}.json"


class FilePerUserStore(InMemoryStore):
    """每个 namespace 一个本地 JSON 文件的持久化 store。"""

    def __init__(self, *, data_dir: str = "store_data", index=None) -> None:
        super().__init__(index=index)
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._load_all()

    # ---- 落盘 / 加载 ----
    def _path_for(self, namespace: tuple[str, ...]) -> str:
        return os.path.join(self.data_dir, _ns_to_filename(namespace))

    def _load_all(self) -> None:
        for name in os.listdir(self.data_dir):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.data_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            ns = tuple(payload.get("namespace", []))
            items = {}
            for key, rec in payload.get("items", {}).items():
                items[key] = Item(
                    namespace=ns,
                    key=key,
                    value=rec.get("value"),
                    created_at=datetime.fromisoformat(rec["created_at"]),
                    updated_at=datetime.fromisoformat(rec["updated_at"]),
                )
            if ns in self._data or items:
                self._data[ns] = items

    def _dump_namespace(self, namespace: tuple[str, ...]) -> None:
        items = self._data.get(namespace)
        path = self._path_for(namespace)
        if not items:  # 空 namespace（含被删除）-> 删除对应文件
            if os.path.exists(path):
                os.remove(path)
            return
        payload = {
            "namespace": list(namespace),
            "items": {
                key: {
                    "value": item.value,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for key, item in items.items()
            },
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # 原子替换，避免写一半损坏

    # ---- 覆写 batch：先执行内存操作，再落盘受影响 namespace ----
    @staticmethod
    def _op_namespace(op: Op):
        """不同 Op 用不同字段表达作用域：PutOp/GetOp 用 namespace，
        SearchOp/ListNamespacesOp 用 namespace_prefix。"""
        ns = getattr(op, "namespace", None)
        if ns is not None:
            return ns
        prefix = getattr(op, "namespace_prefix", None)
        return prefix

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        touched: set[tuple[str, ...]] = set()
        for op in ops:
            ns = self._op_namespace(op)
            if ns is not None:
                touched.add(ns)

        results = super().batch(ops)

        for ns in touched:
            self._dump_namespace(ns)
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        touched: set[tuple[str, ...]] = set()
        for op in ops:
            ns = self._op_namespace(op)
            if ns is not None:
                touched.add(ns)

        results = await super().abatch(ops)

        for ns in touched:
            self._dump_namespace(ns)
        return results
