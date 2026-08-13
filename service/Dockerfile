FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用层缓存）
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

# 再拷代码（含 service/ package 与根级共享文件）
COPY . .

# uvicorn 多 worker；WEB_CONCURRENCY 由 compose 注入
CMD ["sh", "-c", "uv run -m service.server"]
