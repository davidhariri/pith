#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed"
  exit 1
fi

uv sync
uv run pith setup

echo "Installation complete. Start chat with: uv run pith chat"
echo "Or start telegram loop with: uv run pith run"
