import { Pool } from "pg";
import {
  BaseStore,
  type GetOperation,
  type Item,
  type ListNamespacesOperation,
  type Operation,
  type OperationResults,
  type PutOperation,
  type SearchItem,
  type SearchOperation,
} from "@langchain/langgraph-checkpoint";

/**
 * 进程安全的 Postgres 长期记忆 Store —— 对标 Python 版 pg_store.AsyncPostgresStore。
 *
 * 并发模型（10W 级）：
 * - 所有读写经 pg.Pool 连接池，连接被事件循环上的并发请求复用（单进程即可 hold 数千挂起）。
 * - 每个 (namespace, key) 是一行，按 namespace 隔离记忆 —— 等价于 Python 版
 *   「每个用户一个独立文件」，但进程安全、跨 worker、可水平扩展。
 * - 写用 INSERT ... ON CONFLICT DO UPDATE（upsert），并发不丢数据。
 * - 行锁粒度 (namespace, key)，不同用户的写入互不阻塞。
 *
 * 实现 BaseStore 契约：只需实现 batch()，其余 get/search/put/listNamespaces 由父类委托。
 */

const DDL = `
CREATE TABLE IF NOT EXISTS agent_memory (
  namespace TEXT NOT NULL,
  key       TEXT NOT NULL,
  value     JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS agent_memory_ns_idx ON agent_memory (namespace);
`;

export class PostgresStore extends BaseStore {
  private pool: Pool;

  constructor(pool: Pool) {
    super();
    this.pool = pool;
  }

  static async create(connectionString: string): Promise<PostgresStore> {
    const pool = new Pool({ connectionString });
    // 建表（生产可用迁移工具代替）
    const client = await pool.connect();
    try {
      await client.query(DDL);
    } finally {
      client.release();
    }
    return new PostgresStore(pool);
  }

  async close(): Promise<void> {
    await this.pool.end();
  }

  async batch<Op extends Operation[]>(
    operations: Op,
  ): Promise<OperationResults<Op>> {
    const client = await this.pool.connect();
    try {
      const results: unknown[] = [];
      for (const op of operations) {
        if (isListNamespaces(op)) {
          results.push(await this.listNsOp(client, op));
        } else if (isSearch(op)) {
          results.push(await this.searchOp(client, op));
        } else if (isPut(op)) {
          await this.putOp(client, op);
          results.push(undefined);
        } else {
          // GetOperation
          results.push(await this.getOp(client, op));
        }
      }
      return results as OperationResults<Op>;
    } finally {
      client.release();
    }
  }

  private async getOp(
    client: import("pg").PoolClient,
    op: GetOperation,
  ): Promise<Item | null> {
    const ns = op.namespace.join("/");
    const { rows } = await client.query(
      "SELECT value, created_at, updated_at FROM agent_memory WHERE namespace = $1 AND key = $2",
      [ns, op.key],
    );
    if (rows.length === 0) return null;
    const { value, created_at, updated_at } = rows[0];
    return {
      namespace: op.namespace,
      key: op.key,
      value,
      createdAt: new Date(created_at),
      updatedAt: new Date(updated_at),
    };
  }

  private async putOp(
    client: import("pg").PoolClient,
    op: PutOperation,
  ): Promise<void> {
    const ns = op.namespace.join("/");
    if (op.value === null) {
      await client.query(
        "DELETE FROM agent_memory WHERE namespace = $1 AND key = $2",
        [ns, op.key],
      );
      return;
    }
    await client.query(
      `INSERT INTO agent_memory (namespace, key, value, created_at, updated_at)
       VALUES ($1, $2, $3::jsonb, now(), now())
       ON CONFLICT (namespace, key) DO UPDATE
       SET value = EXCLUDED.value, updated_at = now()`,
      [ns, op.key, JSON.stringify(op.value)],
    );
  }

  private async searchOp(
    client: import("pg").PoolClient,
    op: SearchOperation,
  ): Promise<SearchItem[]> {
    const ns = op.namespacePrefix.join("/");
    const { rows } = await client.query(
      "SELECT value, created_at, updated_at, key FROM agent_memory WHERE namespace = $1",
      [ns],
    );
    return rows.map((r) => ({
      namespace: op.namespacePrefix,
      key: r.key,
      value: r.value,
      createdAt: new Date(r.created_at),
      updatedAt: new Date(r.updated_at),
    }));
  }

  private async listNsOp(
    client: import("pg").PoolClient,
    _op: ListNamespacesOperation,
  ): Promise<string[][]> {
    const { rows } = await client.query(
      "SELECT DISTINCT namespace FROM agent_memory",
    );
    return rows.map((r) => String(r.namespace).split("/"));
  }
}

function isListNamespaces(op: Operation): op is ListNamespacesOperation {
  return "limit" in op && "offset" in op;
}
function isSearch(op: Operation): op is SearchOperation {
  return "namespacePrefix" in op;
}
function isPut(op: Operation): op is PutOperation {
  return "value" in op;
}
