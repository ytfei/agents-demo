# 多阶段构建（multi-stage build）：
#   deps   —— 只装依赖，锁文件不变时命中缓存，避免每次重新安装
#   build  —— 编译 TypeScript 产出 dist
#   runtime—— 最终运行镜像（最精简）
#
# 核心收益：源码改动只重新执行 COPY . . + pnpm build 两层，
# pnpm install 层（最耗时）在锁文件不变时始终命中缓存。

# ---------- 阶段 1：安装依赖 ----------
FROM node:22-slim AS deps
WORKDIR /app

# 启用 corepack 以使用 pnpm
RUN corepack enable

# 只拷锁文件 + workspace 配置：只要 package.json / pnpm-lock.yaml / pnpm-workspace.yaml
# 不变，本层就会命中缓存，跳过耗时的 pnpm install。
# 必须拷 pnpm-workspace.yaml：pnpm 11 从它读取 allowBuilds 等设置，
# 缺失会导致 esbuild 构建脚本被忽略而报 [ERR_PNPM_IGNORED_BUILDS]。
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# ---------- 阶段 2：编译 ----------
FROM node:22-slim AS build
WORKDIR /app

# 每个用到 pnpm 的阶段都需启用 corepack（corepack 管理 pnpm 版本，阶段间不继承）
RUN corepack enable

# 复用 deps 阶段安装好的 node_modules（含 devDependencies：typescript/tsx 编译必需）
COPY --from=deps /app/node_modules ./node_modules

# 拷源码并编译（仅此层随源码变化）
COPY . .
RUN pnpm build

# ---------- 阶段 3：运行时（最终镜像） ----------
FROM node:22-slim AS runtime
WORKDIR /app

# 复用编译产物与依赖，只拷贝运行所需，镜像更小
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./package.json

# 非 root 运行，安全加固
USER node

# cluster 多 worker；WEB_CONCURRENCY 由 compose 注入
EXPOSE 8000
CMD ["node", "dist/server.js"]
