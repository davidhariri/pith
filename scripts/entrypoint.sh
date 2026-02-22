#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[0;31m"
YELLOW="\033[0;33m"
RESET="\033[0m"

USAGE="Usage: $0 <run|risk|update>"
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
CONTAINER_NAME="${PITH_CONTAINER_NAME:-pith-dev}"

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

warn() {
  printf "${YELLOW}%s${RESET}\n" "$1"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done=0 }
    index($0, k "=") == 1 { print k "=" v; done=1; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

created_config=0
created_env=0

mkdir -p "$(dirname "$DEFAULT_CONFIG")"
if [[ ! -f "$DEFAULT_CONFIG" ]]; then
  cp "$CONFIG_EXAMPLE" "$DEFAULT_CONFIG"
  created_config=1
  echo "Created config template at $DEFAULT_CONFIG"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  created_env=1
  echo "Created environment template at $ENV_FILE"
fi

if [[ "$created_config" -eq 1 || "$created_env" -eq 1 ]]; then
  echo
  echo "First-time setup"
  if [[ -t 0 ]]; then
    read -r -p "Model API key (required to chat): " api_key
    if [[ -n "$api_key" ]]; then
      set_env_value "OPENAI_API_KEY" "$api_key"
    fi

    read -r -p "Telegram bot token (optional, press enter to skip): " tg_token
    if [[ -n "$tg_token" ]]; then
      set_env_value "TELEGRAM_BOT_TOKEN" "$tg_token"
    fi

    echo "Setup complete. You can edit config.yaml and .env any time."
  else
    echo "Generated config.yaml and .env."
    echo "Set OPENAI_API_KEY in .env before starting the service."
    exit 0
  fi
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
