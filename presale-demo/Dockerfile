# 使用支持 pnpm 的 Node 22 镜像
FROM node:22-slim

WORKDIR /app

# 启用 corepack 以使用 pnpm
RUN corepack enable

# 先装依赖（利用层缓存）
# 必须同时拷 pnpm-workspace.yaml：pnpm 11 从它读取 onlyBuiltDependencies 等设置，
# 缺失会导致 esbuild 构建脚本被忽略而报 [ERR_PNPM_IGNORED_BUILDS]
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# 再拷源码
COPY . .

# 编译 TypeScript
RUN pnpm build

# cluster 多 worker；WEB_CONCURRENCY 由 compose 注入
CMD ["node", "dist/server.js"]
