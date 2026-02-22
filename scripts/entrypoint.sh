#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[0;31m"
RESET="\033[0m"

USAGE="Usage: $0 <run|risk>"
MODE="${1:-}"

if [[ -z "$MODE" ]]; then
  echo "$USAGE"
  exit 1
fi

CONFIG_EXAMPLE="$ROOT_DIR/config.example.yaml"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
DEFAULT_CONFIG="${PITH_CONFIG:-$ROOT_DIR/config.yaml}"
ENV_FILE="$ROOT_DIR/.env"
IMAGE_NAME="${PITH_DOCKER_IMAGE:-pith:dev}"

if [[ ! -f "$CONFIG_EXAMPLE" ]]; then
  echo "Missing config template: $CONFIG_EXAMPLE"
  exit 1
fi

if [[ ! -f "$ENV_EXAMPLE" ]]; then
  echo "Missing env template: $ENV_EXAMPLE"
  exit 1
fi

fatal() {
  printf "${RED}%s${RESET}\n" "$1"
  shift
  printf "%b\n" "$1"
  exit 1
}

mkdir -p "$(dirname "$DEFAULT_CONFIG")"
if [[ ! -f "$DEFAULT_CONFIG" ]]; then
  cp "$CONFIG_EXAMPLE" "$DEFAULT_CONFIG"
  echo "Created config template at $DEFAULT_CONFIG"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "Created environment template at $ENV_FILE"
fi

case "$MODE" in
  run)
    if ! command -v docker >/dev/null 2>&1; then
      fatal "Docker is required for 'make run'." "Install Docker, or use 'make risk' to run without containerization."
    fi

if ! docker info >/dev/null 2>&1; then
      fatal "Docker is installed, but the Docker daemon isn't running." \
        "Start Docker Desktop (or your local Docker service), then rerun: make run"
    fi

    if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
      echo "Building Docker image '$IMAGE_NAME'..."
      docker build -t "$IMAGE_NAME" "$ROOT_DIR"
    fi

    docker run --rm -it \
      -v "$ROOT_DIR:/workspace" \
      -w /workspace \
      "$IMAGE_NAME"
    ;;
  risk)
    if ! command -v uv >/dev/null 2>&1; then
      fatal "uv is required for make risk." \
        "Install uv from https://docs.astral.sh/uv/ then rerun: make risk"
    fi

    cd "$ROOT_DIR"
    uv sync
    uv run pith run
    ;;
  *)
    echo "$USAGE"
    exit 1
    ;;
esac
