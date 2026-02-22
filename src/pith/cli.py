"""Command-line interface surface."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import yaml

from .chat import run_chat
from .config import DEFAULT_CONFIG_PATH, ConfigLoadResult, load_config
from .extensions import ExtensionRegistry
from .mcp_client import MCPClient
from .runtime import Runtime
from .storage import Storage


def _load_runtime() -> Runtime:
    cfg_result: ConfigLoadResult = load_config()
    storage = Storage(cfg_result.config.runtime.memory_db_path)
    extensions = ExtensionRegistry(Path(cfg_result.config.runtime.workspace_path))
    mcp_client = MCPClient(Path(cfg_result.config.runtime.workspace_path), cfg_result.config.mcp_servers)
    return Runtime(cfg_result.config, storage, extensions, mcp_client)


def _default_config_text() -> str:
    return yaml.safe_dump(
        {
            "version": 1,
            "runtime": {
                "workspace_path": str(Path.cwd()),
                "memory_db_path": str(Path.cwd() / "memory.db"),
                "log_dir": str(Path.cwd() / ".pith" / "logs"),
            },
            "model": {
                "provider": "openai",
                "model": "gpt-5",
                "api_key_env": "OPENAI_API_KEY",
                "temperature": 0.2,
            },
            "telegram": {
                "transport": "polling",
                "bot_token_env": "TELEGRAM_BOT_TOKEN",
            },
            "mcp": {
                "servers": {
                    "filesystem": {
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                    }
                }
            },
        },
        sort_keys=False,
    )


async def cmd_setup(_: argparse.Namespace) -> None:
    config_path = Path(os.environ.get("PITH_CONFIG", str(DEFAULT_CONFIG_PATH))).expanduser()
    workspace = Path.cwd()
    env_path = workspace / ".env"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_text = _default_config_text().replace(str(Path.cwd()), str(workspace))
        config_path.write_text(config_text, encoding="utf-8")

    if not env_path.exists():
        env_path.write_text("OPENAI_API_KEY=\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8")

    print(f"wrote config: {config_path}")
    print(f"wrote env template: {env_path}")
    print("edit these values before running pith")


async def cmd_run(_: argparse.Namespace) -> None:
    from .channels.telegram import run_telegram

    runtime = _load_runtime()
    async with runtime.storage:
        await runtime.initialize()
        token_env = runtime.cfg.telegram.bot_token_env
        if os.environ.get(token_env):
            print("pith service running (telegram enabled)")
            await run_telegram(runtime)
            return

        print("pith service running (telegram not configured; this is optional)")
        print(f"set {token_env} in .env only if you want Telegram transport")
        print("local interactive chat remains available via `pith chat`")
        await asyncio.Event().wait()


async def cmd_chat(_: argparse.Namespace) -> None:
    runtime = _load_runtime()
    async with runtime.storage:
        await runtime.initialize()
        await run_chat(runtime)


async def cmd_doctor(_: argparse.Namespace) -> None:
    cfg_result = load_config()
    cfg = cfg_result.config

    print(f"Config path: {cfg_result.path}")
    print(f"Workspace: {cfg.runtime.workspace_path}")
    print(f"DB: {cfg.runtime.memory_db_path}")
    print(f"Log dir: {cfg.runtime.log_dir}")
    print(f"Model: {cfg.model.provider}:{cfg.model.model}")

    api_key = os.environ.get(cfg.model.api_key_env)
    print(f"Model key ({cfg.model.api_key_env}): {'set' if api_key else 'missing'}")

    tg_key = os.environ.get(cfg.telegram.bot_token_env)
    print(f"Telegram key ({cfg.telegram.bot_token_env}): {'set' if tg_key else 'missing'}")

    print(f"MCP servers: {', '.join(cfg.mcp_servers.keys()) or 'none'}")


async def cmd_logs_tail(_: argparse.Namespace) -> None:
    cfg_result = load_config()
    log_dir = Path(cfg_result.config.runtime.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "events.jsonl"
    if not log_path.exists():
        print(f"no log file yet: {log_path}")
        return

    with log_path.open("r", encoding="utf-8") as fp:
        fp.seek(0, 2)
        while True:
            line = fp.readline()
            if line:
                print(line.rstrip())
            else:
                await asyncio.sleep(0.25)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pith")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create starter config and env files")
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
