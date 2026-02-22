#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[0;31m"
RESET="\033[0m"

USAGE="Usage: $0 <run|risk|update>"
MODE="${1:-}"

if [[ -z "$MODE" ]]; then
  echo "$USAGE"
  exit 1
fi

IMAGE_NAME="${PITH_DOCKER_IMAGE:-pith:dev}"
CONTAINER_NAME="${PITH_CONTAINER_NAME:-pith-dev}"

fatal() {
  printf "${RED}%s${RESET}\n" "$1"
  shift
  printf "%b\n" "$1"
  exit 1
}

case "$MODE" in
  run)
    # Require config before building/running Docker
    config_path="${PITH_CONFIG:-$ROOT_DIR/config.yaml}"
    if [[ ! -f "$config_path" ]]; then
      fatal "No config found at $config_path." \
        "Run 'pith setup' or 'make risk' first to create config.yaml and .env."
    fi

    if ! command -v docker >/dev/null 2>&1; then
      fatal "Docker is required for 'make run'." "Install Docker, or use 'make risk' to run without containerization."
    fi

    if ! docker info >/dev/null 2>&1; then
      fatal "Docker is installed, but the Docker daemon isn't running." \
        "Start Docker Desktop (or your local Docker service), then rerun: make run"
    fi

    echo "Building Docker image '$IMAGE_NAME'..."
    if [[ "${PITH_VERBOSE_BUILD:-0}" == "1" ]]; then
      docker build -t "$IMAGE_NAME" "$ROOT_DIR"
    else
      if ! docker build -q -t "$IMAGE_NAME" "$ROOT_DIR" >/dev/null; then
        fatal "Docker image build failed." \
          "Run with verbose logs for details: PITH_VERBOSE_BUILD=1 make run"
      fi
    fi

    # Stop any existing container with the same name
    if docker ps -q -f "name=$CONTAINER_NAME" 2>/dev/null | grep -q .; then
      echo "Stopping existing container '$CONTAINER_NAME'..."
      docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

    echo "Starting container '$CONTAINER_NAME'..."
    docker run -d --name "$CONTAINER_NAME" \
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
          echo -e "\033[0;32m[ok]\033[0m pith is running (container: $CONTAINER_NAME)"
          echo "  logs:  docker logs -f $CONTAINER_NAME"
          echo "  stop:  make stop"
          exit 0
          ;;
        unhealthy)
          echo -e "\033[0;31m[error]\033[0m pith failed to start:"
          docker logs --tail 20 "$CONTAINER_NAME"
          docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
          exit 1
          ;;
      esac
      # Check if container exited
      running=$(docker inspect --format='{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo "false")
      if [ "$running" = "false" ]; then
        echo -e "\033[0;31m[error]\033[0m container exited:"
        docker logs --tail 20 "$CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
        exit 1
      fi
      sleep 1
    done

    echo -e "\033[0;31m[error]\033[0m startup timed out after 60s"
    docker logs --tail 20 "$CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    exit 1
    ;;
  update)
    if ! command -v docker >/dev/null 2>&1; then
      fatal "Docker is required for 'make update'." "Install Docker, then rerun: make update"
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
