#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[0;31m"
GREEN="\033[0;32m"
RESET="\033[0m"

USAGE="Usage: $0 <run|risk|update>"
MODE="${1:-}"

if [[ -z "$MODE" ]]; then
  echo "$USAGE"
  exit 1
fi

IMAGE_NAME="${PITH_DOCKER_IMAGE:-pith:dev}"
CONTAINER_NAME="${PITH_CONTAINER_NAME:-pith-dev}"
CONFIG_PATH="${PITH_CONFIG:-$ROOT_DIR/config.yaml}"
ENV_FILE="$ROOT_DIR/.env"

fatal() {
  printf "${RED}%s${RESET}\n" "$1"
  shift
  printf "%b\n" "$1"
  exit 1
}

# Run pith setup locally if config or API key is missing
ensure_configured() {
  # Quick check: config exists and .env has a non-empty key value
  if [[ -f "$CONFIG_PATH" && -f "$ENV_FILE" ]]; then
    local key_env
    key_env=$(grep 'api_key_env:' "$CONFIG_PATH" 2>/dev/null | head -1 | awk '{print $2}')
    if [[ -n "$key_env" ]]; then
      local key_val
      key_val=$(grep "^${key_env}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
      if [[ -n "$key_val" ]]; then
        return 0
      fi
    fi
  fi

  # Need setup — run it locally via uv
  if ! command -v uv >/dev/null 2>&1; then
    fatal "uv is required for first-time setup." \
      "Install uv from https://docs.astral.sh/uv/ then rerun: make run"
  fi

  cd "$ROOT_DIR"
  uv sync --quiet 2>/dev/null || uv sync
  uv run pith setup
}

case "$MODE" in
  run)
    if ! command -v docker >/dev/null 2>&1; then
      fatal "Docker is required for 'make run'." \
        "Install Docker, or use 'make risk' to run without containerization."
    fi

    if ! docker info >/dev/null 2>&1; then
      fatal "Docker is installed, but the Docker daemon isn't running." \
        "Start Docker Desktop (or your local Docker service), then rerun: make run"
    fi

    ensure_configured

    echo "Building Docker image '$IMAGE_NAME'..."
    if [[ "${PITH_VERBOSE_BUILD:-0}" == "1" ]]; then
      docker build -t "$IMAGE_NAME" "$ROOT_DIR"
    else
      if ! docker build -q -t "$IMAGE_NAME" "$ROOT_DIR" >/dev/null; then
        fatal "Docker image build failed." \
          "Run with verbose logs for details: PITH_VERBOSE_BUILD=1 make run"
      fi
    fi

    # Stop any existing container
    if docker ps -q -f "name=$CONTAINER_NAME" 2>/dev/null | grep -q .; then
      echo "Stopping existing container '$CONTAINER_NAME'..."
      docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

    echo "Starting container '$CONTAINER_NAME'..."
    docker run -d --name "$CONTAINER_NAME" \
      --env-file "$ENV_FILE" \
      -v "$ROOT_DIR:/workspace" \
      -w /workspace \
      "$IMAGE_NAME" >/dev/null

    # Wait for healthy (Docker HEALTHCHECK)
    echo "Waiting for startup..."
    deadline=$((SECONDS + 60))
    while [ $SECONDS -lt $deadline ]; do
      status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")
      case "$status" in
        healthy)
          echo -e "${GREEN}[ok]${RESET} pith is running (container: $CONTAINER_NAME)"
          echo "  logs:  docker logs -f $CONTAINER_NAME"
          echo "  stop:  make stop"
          exit 0
          ;;
        unhealthy)
          echo -e "${RED}[error]${RESET} pith failed to start:"
          docker logs --tail 20 "$CONTAINER_NAME"
          docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
          exit 1
          ;;
      esac
      running=$(docker inspect --format='{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo "false")
      if [ "$running" = "false" ]; then
        echo -e "${RED}[error]${RESET} container exited:"
        docker logs --tail 20 "$CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        exit 1
      fi
      sleep 1
    done

    echo -e "${RED}[error]${RESET} startup timed out after 60s"
    docker logs --tail 20 "$CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    exit 1
    ;;
  update)
    if ! command -v docker >/dev/null 2>&1; then
      fatal "Docker is required for 'make update'." \
        "Install Docker, then rerun: make update"
    fi

    if ! docker info >/dev/null 2>&1; then
      fatal "Docker is installed, but the Docker daemon isn't running." \
        "Start Docker Desktop (or your local Docker service), then rerun: make update"
    fi

    echo "Rebuilding Docker image '$IMAGE_NAME' from scratch..."
    if [[ "${PITH_VERBOSE_BUILD:-0}" == "1" ]]; then
      docker build --pull --no-cache -t "$IMAGE_NAME" "$ROOT_DIR"
    else
      if ! docker build --pull --no-cache -q -t "$IMAGE_NAME" "$ROOT_DIR" >/dev/null; then
        fatal "Docker image rebuild failed." \
          "Run with verbose logs for details: PITH_VERBOSE_BUILD=1 make update"
      fi
    fi
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
