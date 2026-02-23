"""Runtime config loading."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def default_config_path() -> Path:
    """Return the default config path, evaluated lazily."""
    return Path.cwd() / "config.yaml"


@dataclass
class RuntimeConfig:
    """Derived paths — not configurable, computed from config_dir."""

    workspace_path: str
    memory_db_path: str
    log_dir: str


@dataclass
class ModelConfig:
    provider: str
    model: str
    api_key_env: str
    base_url: str | None = None
    temperature: float = 0.2


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8420


@dataclass
class Config:
    version: int
    runtime: RuntimeConfig
    model: ModelConfig
    server: ServerConfig = field(default_factory=ServerConfig)


@dataclass
class ConfigLoadResult:
    path: Path
    config: Config


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return _ENV_VAR_RE.sub(repl, value)
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_vars(val) for key, val in value.items()}
    return value


def _load_workspace_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_yaml(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}

    return _resolve_env_vars(raw)


def _build_runtime(config_dir: Path) -> RuntimeConfig:
    workspace = (config_dir / "workspace").resolve()
    return RuntimeConfig(
        workspace_path=str(workspace),
        memory_db_path=str((config_dir / "memory.db").resolve()),
        log_dir=str((workspace / ".pith" / "logs").resolve()),
    )


def _parse_model(raw: dict[str, Any]) -> ModelConfig:
    model_raw = raw.get("model", {})
    for required in ("provider", "model", "api_key_env"):
        if required not in model_raw:
            raise ValueError(f"model.{required} is required in config.yaml")
    return ModelConfig(
        provider=str(model_raw["provider"]),
        model=str(model_raw["model"]),
        api_key_env=str(model_raw["api_key_env"]),
        base_url=model_raw.get("base_url"),
        temperature=float(model_raw.get("temperature", 0.2)),
    )


def _parse_server(raw: dict[str, Any]) -> ServerConfig:
    server = raw.get("server", {})
    return ServerConfig(
        host=str(server.get("host", "0.0.0.0")),
        port=int(server.get("port", 8420)),
    )


def load_config(
    config_path: Path | None = None, workspace_root: Path | None = None
) -> ConfigLoadResult:
    path = config_path or Path(os.environ.get("PITH_CONFIG", str(default_config_path())))
    config_dir = path.resolve().parent

    env_root = workspace_root or config_dir
    _load_workspace_env(env_root / ".env")

    raw = _load_yaml(path)
    version = int(raw.get("version", 1))

    runtime = _build_runtime(config_dir)
    model = _parse_model(raw)
    server = _parse_server(raw)

    return ConfigLoadResult(
        path=path,
        config=Config(
            version=version,
            runtime=runtime,
            model=model,
            server=server,
        ),
    )
