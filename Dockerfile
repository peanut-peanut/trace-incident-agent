FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
RUN npm install -g pnpm@10.33.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim
RUN pip install --no-cache-dir uv==0.11.7
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY --from=frontend /ui/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/backend/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
