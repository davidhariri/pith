#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "pyproject.toml" ]]; then
  ROOT_DIR="$(pwd)"
elif [[ -f "$SCRIPT_DIR/../pyproject.toml" ]]; then
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "Could not find repository root (pyproject.toml). Run from the project directory or from scripts/install.sh."
  exit 1
fi

cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed"
  exit 1
fi

uv sync
uv run pith setup

echo "Installation complete. Start chat with: uv run pith chat"
echo "Or start telegram loop with: uv run pith run"
