#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
uv run --frozen ruff check app tests evals
uv run --frozen pytest -q
uv run --frozen python -m evals.run
cd "$ROOT/frontend"
pnpm build
