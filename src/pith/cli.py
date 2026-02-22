"""Command-line interface surface."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import termios
import tty
from pathlib import Path

import yaml

from .chat import run_chat
from .config import ConfigLoadResult, default_config_path, load_config
from .extensions import ExtensionRegistry
from .mcp_client import MCPClient
from .runtime import Runtime
from .storage import Storage


def _load_runtime() -> Runtime:
    cfg_result: ConfigLoadResult = load_config()
    storage = Storage(cfg_result.config.runtime.memory_db_path)
    extensions = ExtensionRegistry(Path(cfg_result.config.runtime.workspace_path))
    mcp_client = MCPClient(
        Path(cfg_result.config.runtime.workspace_path), cfg_result.config.mcp_servers
    )
    return Runtime(cfg_result.config, storage, extensions, mcp_client)


# -- Interactive helpers --

_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "anthropic": {
        "label": "Anthropic",
        "model": "claude-sonnet-4-20250514",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "label": "OpenAI",
        "model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
}


def _select(prompt: str, options: list[tuple[str, str]], default: int = 0) -> str:
    """Inline arrow-key selector. options = [(value, label), ...]. Returns value."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    selected = default

    def render() -> None:
        # Move cursor up to overwrite previous render (except first time)
        for i, (_, label) in enumerate(options):
            if i == selected:
                sys.stdout.write(f"  \033[36m> {label}\033[0m\n")
            else:
                sys.stdout.write(f"    {label}\n")
        sys.stdout.flush()

    def clear() -> None:
        for _ in options:
            sys.stdout.write("\033[A\033[2K")
        sys.stdout.flush()

    sys.stdout.write(f"{prompt}\n")
    render()

    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\r" or ch == "\n":
                break
            if ch == "\x03":  # ctrl-c
                raise KeyboardInterrupt
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":  # up
                    selected = (selected - 1) % len(options)
                elif seq == "[B":  # down
                    selected = (selected + 1) % len(options)
                clear()
                render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Clear the selector and show the choice inline
    clear()
    _, label = options[selected]
    sys.stdout.write(f"\033[A\033[2K{prompt} \033[36m{label}\033[0m\n")
    sys.stdout.flush()

    return options[selected][0]


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" \033[90m[{default}]\033[0m" if default else ""
    value = input(f"{prompt}{suffix} ").strip()
    return value or default


def _is_interactive() -> bool:
    return sys.stdin.isatty()


# -- Configuration bootstrap --


def _ensure_configured() -> None:
    """Ensure config.yaml exists and API key is set. Prompt interactively if needed."""
    config_path = Path(os.environ.get("PITH_CONFIG", str(default_config_path())))
    env_path = Path.cwd() / ".env"

    if not config_path.exists():
        if not _is_interactive():
            raise SystemExit(
                f"config not found at {config_path}\n"
                "run `pith setup` interactively first"
            )
        _run_setup(config_path, env_path)
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
    _run_setup(config_path, env_path)


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


def _run_setup(config_path: Path, env_path: Path) -> None:
    """Interactive setup flow — creates config.yaml and .env."""
    workspace = Path.cwd()

    print("\n\033[1mpith setup\033[0m\n")

    # Provider selection
    provider_options = [(k, v["label"]) for k, v in _PROVIDER_PRESETS.items()]
    provider = _select("Model provider:", provider_options)
    preset = _PROVIDER_PRESETS[provider]

    # Model name
    model_name = _ask("Model name:", preset["model"])

    # API key
    api_key_env = preset["api_key_env"]
    api_key_value = _ask(f"API key ({api_key_env}):")
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

    print(f"\n\033[32m✓\033[0m wrote {config_path}")
    print(f"\033[32m✓\033[0m wrote {env_path}\n")


# -- Commands --


async def cmd_setup(_: argparse.Namespace) -> None:
    config_path = Path(os.environ.get("PITH_CONFIG", str(default_config_path()))).expanduser()
    env_path = Path.cwd() / ".env"
    _run_setup(config_path, env_path)


async def cmd_run(_: argparse.Namespace) -> None:
    from .channels.telegram import run_telegram

    _ensure_configured()
    runtime = _load_runtime()
    async with runtime.storage:
        await runtime.initialize()

        # Signal healthy startup (used by Docker HEALTHCHECK)
        health_file = Path(runtime.workspace / ".pith" / "healthy")
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.touch()

        token_env = runtime.cfg.telegram.bot_token_env
        if os.environ.get(token_env):
            print("\033[0;32m[startup ok]\033[0m pith service started successfully")
            print("transport: telegram enabled")
            print("status: service loop active")
            await run_telegram(runtime)
            return

        print("\033[0;32m[startup ok]\033[0m pith service started successfully")
        print("transport: telegram disabled (optional)")
        print(f"next step (optional): set {token_env} in .env to enable Telegram")
        print("local chat: run `pith chat` in another terminal")
        print("status: service loop active")
        await asyncio.Event().wait()


async def cmd_chat(_: argparse.Namespace) -> None:
    _ensure_configured()
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
