#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED="\033[0;31m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
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

# -- Bootstrap: ensure config.yaml and .env are ready --

ensure_configured() {
  if [[ ! -t 0 ]]; then
    # Non-interactive: just check, don't prompt
    if [[ ! -f "$CONFIG_PATH" ]]; then
      fatal "No config found at $CONFIG_PATH." "Run 'make run' interactively first."
    fi
    return
  fi

  # Step 1: config.yaml
  if [[ ! -f "$CONFIG_PATH" ]]; then
    echo -e "${CYAN}First-time setup${RESET}\n"

    # Provider
    read -r -p "Model provider (anthropic/openai) [anthropic]: " provider
    provider="${provider:-anthropic}"

    # Model name
    case "$provider" in
      anthropic) default_model="claude-sonnet-4-20250514"; default_key_env="ANTHROPIC_API_KEY" ;;
      openai)    default_model="gpt-4o";                   default_key_env="OPENAI_API_KEY" ;;
      *)         default_model="";                         default_key_env="API_KEY" ;;
    esac

    read -r -p "Model name [$default_model]: " model_name
    model_name="${model_name:-$default_model}"

    read -r -p "API key env var name [$default_key_env]: " api_key_env
    api_key_env="${api_key_env:-$default_key_env}"

    # Write config.yaml
    cat > "$CONFIG_PATH" <<YAML
version: 1

runtime:
  workspace_path: /workspace
  memory_db_path: /workspace/memory.db
  log_dir: /workspace/.pith/logs

model:
  provider: $provider
  model: $model_name
  api_key_env: $api_key_env
  temperature: 0.2
YAML
    echo "wrote $CONFIG_PATH"
  fi

  # Step 2: .env with API key
  # Read api_key_env from config
  api_key_env=$(grep 'api_key_env:' "$CONFIG_PATH" | head -1 | awk '{print $2}')

  if [[ -z "$api_key_env" ]]; then
    fatal "config.yaml is missing model.api_key_env." "Fix config.yaml and retry."
  fi

  # Create .env if missing
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "$api_key_env=" > "$ENV_FILE"
  fi

  # Source .env to check current value
  set +u
  source_env
  eval "current_key=\${$api_key_env:-}"
  set -u

  if [[ -z "$current_key" ]]; then
    echo ""
    read -r -p "$api_key_env is not set. Enter your API key: " api_key_value
    if [[ -z "$api_key_value" ]]; then
      fatal "API key is required." "Set $api_key_env in .env and retry."
    fi
    set_env_value "$api_key_env" "$api_key_value"
    echo "saved to .env"
  fi

  echo ""
}

source_env() {
  if [[ -f "$ENV_FILE" ]]; then
    while IFS='=' read -r key value; do
      key=$(echo "$key" | xargs)
      [[ -z "$key" || "$key" == \#* ]] && continue
      value=$(echo "$value" | xargs | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
      if [[ -n "$key" && -z "${!key:-}" ]]; then
        export "$key=$value"
      fi
    done < "$ENV_FILE"
  fi
}

set_env_value() {
  local key="$1"
  local value="$2"
  if [[ -f "$ENV_FILE" ]] && grep -q "^${key}=" "$ENV_FILE"; then
    local tmp
    tmp="$(mktemp)"
    sed "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
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

    # Stop any existing container with the same name
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
      # Check if container exited
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
