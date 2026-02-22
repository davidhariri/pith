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
    workspace_path: str
    memory_db_path: str
    log_dir: str
    bootstrap_version: int = 1


@dataclass
class ModelConfig:
    provider: str
    model: str
    api_key_env: str
    base_url: str | None = None
    temperature: float = 0.2


@dataclass
class TelegramConfig:
    transport: str = "polling"
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"


@dataclass
class MCPServerConfig:
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    tools: list[str] | None = None


@dataclass
class Config:
    version: int
    runtime: RuntimeConfig
    model: ModelConfig
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)


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


def _parse_runtime(raw: dict[str, Any], workspace_root: Path) -> RuntimeConfig:
    runtime = raw.get("runtime", {})
    workspace_path = Path(runtime.get("workspace_path", str(workspace_root)))
    memory_db_path = str(runtime.get("memory_db_path", str(workspace_path / "memory.db")))
    log_dir = str(runtime.get("log_dir", str(workspace_path / ".pith" / "logs")))
    return RuntimeConfig(
        workspace_path=workspace_path,
        memory_db_path=memory_db_path,
        log_dir=log_dir,
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


def _parse_telegram(raw: dict[str, Any]) -> TelegramConfig:
    telegram = raw.get("telegram", {})
    return TelegramConfig(
        transport=str(telegram.get("transport", "polling")),
        bot_token_env=str(telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN")),
    )


def _parse_mcp_servers(raw: dict[str, Any]) -> dict[str, MCPServerConfig]:
    out: dict[str, MCPServerConfig] = {}
    for name, cfg in (raw or {}).items():
        if not isinstance(cfg, dict):
            continue
        transport = cfg.get("transport", "stdio")
        tools = cfg.get("tools")
        out[str(name)] = MCPServerConfig(
            transport=str(transport),
            command=cfg.get("command"),
            args=cfg.get("args", []) or [],
            url=cfg.get("url"),
            headers=cfg.get("headers", {}) or {},
            tools=tools if isinstance(tools, list) else None,
        )
    return out


def load_config(
    config_path: Path | None = None, workspace_root: Path | None = None
) -> ConfigLoadResult:
    if workspace_root is None:
        workspace_root = Path.cwd()
    _load_workspace_env(workspace_root / ".env")

    path = config_path or Path(os.environ.get("PITH_CONFIG", str(default_config_path())))

    raw = _load_yaml(path)
    version = int(raw.get("version", 1))

    runtime = _parse_runtime(raw, workspace_root)
    model = _parse_model(raw)
    telegram = _parse_telegram(raw)
    mcp_servers = _parse_mcp_servers(raw.get("mcp", {}).get("servers", {}))

    return ConfigLoadResult(
        path=path,
        config=Config(
            version=version,
            runtime=runtime,
            model=model,
            telegram=telegram,
            mcp_servers=mcp_servers,
        ),
    )
