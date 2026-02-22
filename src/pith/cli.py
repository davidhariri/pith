"""Command-line interface surface."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import questionary
import yaml
from rich.console import Console

from .chat import run_chat
from .config import ConfigLoadResult, default_config_path, load_config
from .extensions import ExtensionRegistry
from .mcp_client import MCPClient
from .runtime import Runtime
from .storage import Storage

console = Console()


def _load_runtime() -> Runtime:
    cfg_result: ConfigLoadResult = load_config()
    storage = Storage(cfg_result.config.runtime.memory_db_path)
    extensions = ExtensionRegistry(Path(cfg_result.config.runtime.workspace_path))
    mcp_client = MCPClient(
        Path(cfg_result.config.runtime.workspace_path), cfg_result.config.mcp_servers
    )
    return Runtime(cfg_result.config, storage, extensions, mcp_client)


# -- Interactive helpers --

_PROVIDER_PRESETS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": [
            ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
            ("claude-opus-4-6", "Claude Opus 4.6"),
            ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
            ("claude-opus-4-5", "Claude Opus 4.5"),
            ("claude-haiku-4-5", "Claude Haiku 4.5"),
        ],
    },
    "openai": {
        "label": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "models": [
            ("gpt-5", "GPT-5"),
            ("gpt-5.2", "GPT-5.2"),
            ("gpt-5.1", "GPT-5.1"),
            ("gpt-5-mini", "GPT-5 mini"),
            ("gpt-5-nano", "GPT-5 nano"),
            ("o3", "o3"),
            ("o4-mini", "o4-mini"),
            ("o1", "o1"),
            ("gpt-4.1", "GPT-4.1"),
            ("gpt-4.1-mini", "GPT-4.1 mini"),
            ("gpt-4.1-nano", "GPT-4.1 nano"),
            ("gpt-4o", "GPT-4o"),
            ("gpt-4o-mini", "GPT-4o mini"),
        ],
    },
}


def _is_interactive() -> bool:
    return sys.stdin.isatty()


# -- Configuration bootstrap --


async def _ensure_configured() -> None:
    """Ensure config.yaml exists and API key is set. Prompt interactively if needed."""
    config_path = Path(os.environ.get("PITH_CONFIG", str(default_config_path())))
    env_path = Path.cwd() / ".env"

    if not config_path.exists():
        if not _is_interactive():
            raise SystemExit(
                f"config not found at {config_path}\n"
                "run `pith setup` interactively first"
            )
        await _run_setup(config_path, env_path)
        return

    # Config exists — check API key
    cfg_result = load_config(config_path=config_path)
    api_key_env = cfg_result.config.model.api_key_env
    api_key = os.environ.get(api_key_env, "").strip()

    if api_key:
        return

    if not _is_interactive():
        raise SystemExit(
            f"API key not set: {api_key_env} is empty\n"
            "run `pith setup` interactively first"
        )

    # Config exists but key is missing — run full setup
    await _run_setup(config_path, env_path)


def _set_env_value(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    lines.append("")
    env_path.write_text("\n".join(lines), encoding="utf-8")


async def _run_setup(config_path: Path, env_path: Path) -> None:
    """Interactive setup flow — creates config.yaml and .env."""
    workspace = Path.cwd()

    console.print("\n[bold]pith setup[/bold]\n")

    # Provider selection
    provider_choices = [
        questionary.Choice(title=v["label"], value=k) for k, v in _PROVIDER_PRESETS.items()
    ]
    provider = await questionary.select("Model provider:", choices=provider_choices).ask_async()
    if provider is None:
        raise SystemExit("setup cancelled")
    preset = _PROVIDER_PRESETS[provider]

    # Model selection
    model_choices = [
        questionary.Choice(title=label, value=model_id)
        for model_id, label in preset["models"]
    ]
    model_name = await questionary.select("Model:", choices=model_choices).ask_async()
    if model_name is None:
        raise SystemExit("setup cancelled")

    # API key
    api_key_env = preset["api_key_env"]
    api_key_value = await questionary.password(f"API key ({api_key_env}):").ask_async()
    if not api_key_value:
        raise SystemExit("API key is required to run pith")

    os.environ[api_key_env] = api_key_value

    # Build config
    config_data: dict = {
        "version": 1,
        "runtime": {
            "workspace_path": str(workspace),
            "memory_db_path": str(workspace / "memory.db"),
            "log_dir": str(workspace / ".pith" / "logs"),
        },
        "model": {
            "provider": provider,
            "model": model_name,
            "api_key_env": api_key_env,
            "temperature": 0.2,
        },
    }

    # Write config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")

    # Write .env
    env_path.write_text(f"{api_key_env}={api_key_value}\n", encoding="utf-8")

    console.print(f"\n[green]✓[/green] wrote {config_path}")
    console.print(f"[green]✓[/green] wrote {env_path}\n")


# -- Commands --


async def cmd_setup(_: argparse.Namespace) -> None:
    config_path = Path(os.environ.get("PITH_CONFIG", str(default_config_path()))).expanduser()
    env_path = Path.cwd() / ".env"
    await _run_setup(config_path, env_path)


async def cmd_run(_: argparse.Namespace) -> None:
    from .channels.telegram import run_telegram

    await _ensure_configured()
    runtime = _load_runtime()
    async with runtime.storage:
        await runtime.initialize()

        # Signal healthy startup (used by Docker HEALTHCHECK)
        health_file = Path(runtime.workspace / ".pith" / "healthy")
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.touch()

        token_env = runtime.cfg.telegram.bot_token_env
        if os.environ.get(token_env):
            console.print("[green]\\[startup ok][/green] pith service started successfully")
            console.print("transport: telegram enabled")
            console.print("status: service loop active")
            await run_telegram(runtime)
            return

        console.print("[green]\\[startup ok][/green] pith service started successfully")
        console.print("transport: telegram disabled (optional)")
        console.print(f"next step (optional): set {token_env} in .env to enable Telegram")
        console.print("local chat: run `pith chat` in another terminal")
        console.print("status: service loop active")
        await asyncio.Event().wait()


async def cmd_chat(_: argparse.Namespace) -> None:
    await _ensure_configured()
    runtime = _load_runtime()
    async with runtime.storage:
        await runtime.initialize()
        await run_chat(runtime)


async def cmd_doctor(_: argparse.Namespace) -> None:
    cfg_result = load_config()
    cfg = cfg_result.config

    console.print(f"Config path: {cfg_result.path}")
    console.print(f"Workspace: {cfg.runtime.workspace_path}")
    console.print(f"DB: {cfg.runtime.memory_db_path}")
    console.print(f"Log dir: {cfg.runtime.log_dir}")
    console.print(f"Model: {cfg.model.provider}:{cfg.model.model}")

    api_key = os.environ.get(cfg.model.api_key_env)
    console.print(f"Model key ({cfg.model.api_key_env}): {'set' if api_key else 'missing'}")

    tg_key = os.environ.get(cfg.telegram.bot_token_env)
    console.print(f"Telegram key ({cfg.telegram.bot_token_env}): {'set' if tg_key else 'missing'}")

    console.print(f"MCP servers: {', '.join(cfg.mcp_servers.keys()) or 'none'}")


async def cmd_logs_tail(_: argparse.Namespace) -> None:
    cfg_result = load_config()
    log_dir = Path(cfg_result.config.runtime.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "events.jsonl"
    if not log_path.exists():
        console.print(f"no log file yet: {log_path}")
        return

    with log_path.open("r", encoding="utf-8") as fp:
        fp.seek(0, 2)
        while True:
            line = fp.readline()
            if line:
                console.print(line.rstrip())
            else:
                await asyncio.sleep(0.25)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pith")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Interactive setup wizard")
    sub.add_parser("run", help="Run service loop (telegram optional)")
    sub.add_parser("chat", help="Interactive streaming terminal chat")
    sub.add_parser("doctor", help="Show runtime status")

    logs = sub.add_parser("logs", help="View local logs")
    logs_sub = logs.add_subparsers(dest="logs_cmd", required=True)
    logs_sub.add_parser("tail", help="Tail event log")

    return parser


async def run() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "setup":
        await cmd_setup(args)
    elif args.command == "run":
        await cmd_run(args)
    elif args.command == "chat":
        await cmd_chat(args)
    elif args.command == "doctor":
        await cmd_doctor(args)
    elif args.command == "logs":
        if args.logs_cmd == "tail":
            await cmd_logs_tail(args)
        else:
            raise SystemExit("unknown logs command")


def main() -> None:
    asyncio.run(run())
