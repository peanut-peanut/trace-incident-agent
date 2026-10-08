#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
pnpm install --frozen-lockfile
pnpm build
cd "$ROOT/backend"
uv sync --frozen
if [ ! -f .env ]; then cp .env.example .env; fi
printf '\nTrace is starting at http://127.0.0.1:8000\n'
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
