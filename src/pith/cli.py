"""Command-line interface surface."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

import questionary
import yaml
from rich.console import Console

from .config import ConfigLoadResult, default_config_path, load_config
from .extensions import ExtensionRegistry
from .runtime import Runtime
from .storage import Storage

console = Console()

# -- Seed extensions (written on first run) --

_SEED_TELEGRAM = '''\
"""Telegram channel — extension version.

Polls the Telegram Bot API for messages and sends replies.
Requires TELEGRAM_BOT_TOKEN in the environment.

Extension channel contract:
  connect()            — initialize transport
  recv() -> dict       — block until next message
  send(incoming, text) — send reply using metadata from incoming
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

_client: httpx.AsyncClient | None = None
_offset: int = 0


async def connect() -> None:
    global _client
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    _client = httpx.AsyncClient(
        base_url=f"https://api.telegram.org/bot{token}", timeout=60
    )


async def recv() -> dict[str, Any]:
    global _offset
    assert _client is not None
    while True:
        params: dict[str, Any] = {
            "offset": _offset,
            "timeout": 30,
            "allowed_updates": ["message"],
        }
        resp = await _client.get("/getUpdates", params=params)
        data = resp.json()
        if not data.get("ok"):
            await asyncio.sleep(2)
            continue
        for update in data.get("result", []):
            _offset = max(_offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            text = message.get("text")
            if text:
                return {"text": text, "chat_id": message["chat"]["id"]}
        await asyncio.sleep(0.25)


async def send(incoming: dict[str, Any], text: str) -> None:
    assert _client is not None
    await _client.post(
        "/sendMessage", json={"chat_id": incoming["chat_id"], "text": text}
    )
'''

_SEED_WEB_FETCH = '''\
"""Fetch a URL and return its text content.

Usage via tool_call:
  tool_call(name="web_fetch", args={"url": "https://example.com"})
"""

from __future__ import annotations

import httpx


async def run(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and return the response body (truncated to max_chars)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        text = resp.text
        if len(text) > max_chars:
            text = text[:max_chars] + "\\n... (truncated)"
        return text
'''


def _seed_workspace_extensions(workspace: Path) -> None:
    """Write example extensions if the extensions directory doesn't exist yet."""
    ext_dir = workspace / "extensions"
    if ext_dir.exists():
        return

    channels_dir = ext_dir / "channels"
    tools_dir = ext_dir / "tools"
    channels_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)

    (channels_dir / "telegram.py").write_text(_SEED_TELEGRAM, encoding="utf-8")
    (tools_dir / "web_fetch.py").write_text(_SEED_WEB_FETCH, encoding="utf-8")


def _load_runtime() -> Runtime:
    cfg_result: ConfigLoadResult = load_config()
    storage = Storage(cfg_result.config.runtime.memory_db_path)
    extensions = ExtensionRegistry(Path(cfg_result.config.runtime.workspace_path))
    return Runtime(cfg_result.config, storage, extensions)


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
                f"config not found at {config_path}\nrun `pith setup` interactively first"
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
            f"API key not set: {api_key_env} is empty\nrun `pith setup` interactively first"
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
        questionary.Choice(title=label, value=model_id) for model_id, label in preset["models"]
    ]
    model_name = await questionary.select("Model:", choices=model_choices).ask_async()
    if model_name is None:
        raise SystemExit("setup cancelled")

    # API key — use getpass (no echo at all; password() floods terminal with asterisks)
    import getpass

    api_key_env = preset["api_key_env"]
    api_key_value = getpass.getpass(f"  API key ({api_key_env}): ").strip()
    if not api_key_value:
        raise SystemExit("API key is required to run pith")

    os.environ[api_key_env] = api_key_value

    # Build config (paths are derived from config file location)
    config_data: dict = {
        "version": 1,
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
    console.print(f"[green]✓[/green] wrote {env_path}")
    console.print("\n[bold]next steps:[/bold]")
    console.print("  pith chat    start a conversation")
    console.print("  pith run     start the service loop")
    console.print("  pith status  check if the service is running")
    console.print("  pith doctor  check configuration\n")


# -- Channel runner --


async def _run_channel(runtime: Runtime, channel) -> None:
    """Run an extension channel: connect, then loop recv/send."""
    try:
        await channel.connect()
    except Exception as exc:
        console.print(f"[yellow]channel {channel.name}:[/yellow] {exc}")
        return
    while True:
        try:
            incoming = await channel.recv()
            text = incoming.get("text", "")
            if not text:
                continue
            session_id = await runtime.storage.ensure_active_session()
            reply = await runtime.chat(text, session_id=session_id, channel=channel.name)
            await channel.send(incoming, reply)
        except Exception as exc:
            console.print(f"[yellow]channel {channel.name}:[/yellow] {exc}")
            await asyncio.sleep(2)


# -- Commands --


async def cmd_setup(_: argparse.Namespace) -> None:
    config_path = Path(os.environ.get("PITH_CONFIG", str(default_config_path()))).expanduser()
    env_path = Path.cwd() / ".env"
    await _run_setup(config_path, env_path)


async def _run_foreground() -> None:
    """Run the server in the foreground (used by the spawned subprocess and Docker)."""
    import uvicorn

    from .server import create_app

    await _ensure_configured()
    runtime = _load_runtime()
    runtime.workspace.mkdir(parents=True, exist_ok=True)

    # Seed example extensions on first run
    _seed_workspace_extensions(runtime.workspace)

    # Ensure mcp directory exists
    (runtime.workspace / "mcp").mkdir(parents=True, exist_ok=True)

    async with runtime.storage:
        await runtime.initialize()

        # Signal healthy startup (used by Docker HEALTHCHECK and `pith status`)
        pith_dir = runtime.workspace / ".pith"
        pith_dir.mkdir(parents=True, exist_ok=True)
        (pith_dir / "healthy").touch()
        (pith_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")

        tasks = []

        # HTTP API server
        app = create_app(runtime)
        server_cfg = runtime.cfg.server
        uvi_config = uvicorn.Config(
            app,
            host=server_cfg.host,
            port=server_cfg.port,
            log_level="warning",
        )
        server = uvicorn.Server(uvi_config)
        tasks.append(server.serve())

        # Extension channels (e.g. telegram)
        for ch in runtime.extensions.channels.values():
            tasks.append(_run_channel(runtime, ch))

        await asyncio.gather(*tasks)


def _spawn_daemon() -> int:
    """Spawn `pith run --foreground` as a detached background process. Returns the child PID."""
    import subprocess

    log_dir = Path(load_config().config.runtime.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"

    with log_file.open("a") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pith", "run", "--foreground"],
            stdout=lf,
            stderr=lf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return proc.pid


async def _wait_for_server(port: int, timeout: float = 5.0) -> bool:
    """Poll the health endpoint until it responds or timeout."""
    import httpx

    url = f"http://localhost:{port}/health"
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
    return False


async def cmd_run(args: argparse.Namespace) -> None:
    if getattr(args, "foreground", False):
        await _run_foreground()
        return

    await _ensure_configured()

    # Check if already running
    _, _, existing_pid = _read_pid()
    if existing_pid is not None:
        console.print(f"[yellow]already running[/yellow]  pid {existing_pid}")
        return

    cfg_result = load_config()
    port = cfg_result.config.server.port

    pid = _spawn_daemon()
    if await _wait_for_server(port):
        console.print(f"[green]running[/green]  pid {pid} on port {port}")
    else:
        console.print(f"[yellow]spawned[/yellow]  pid {pid} — but health check didn't respond")
        console.print(f"  check logs: {cfg_result.config.runtime.log_dir}/server.log")


async def cmd_chat(_: argparse.Namespace) -> None:
    from .channels.chat import run_chat
    from .client import PithClient
    from .constants import DEFAULT_API_PORT

    await _ensure_configured()

    # Determine server URL from config (best-effort) or default
    try:
        cfg_result = load_config()
        port = cfg_result.config.server.port
    except Exception:
        port = DEFAULT_API_PORT

    client = PithClient(
        f"http://localhost:{port}",
        channel=(
            "Terminal (CLI). Plain text only — no markdown rendering, "
            "no images, no file attachments. Keep formatting simple."
        ),
    )
    try:
        await client.health()
    except Exception:
        console.print("[red]error:[/red] pith server is not running")
        console.print("  start it with [bold]pith run[/bold]")
        return

    try:
        await run_chat(client)
    finally:
        await client.close()


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


async def cmd_status(_: argparse.Namespace) -> None:
    _pid_file, _health_file, pid = _read_pid()
    if pid is None:
        console.print("[red]stopped[/red]  no running service found")
        console.print("  run `pith run` to start the service")
        return
    console.print(f"[green]running[/green]  pid {pid}")


def _find_pid_on_port(port: int) -> int | None:
    """Find a PID listening on the given port via lsof (fallback when pid file is stale)."""
    import subprocess

    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # May return multiple PIDs (one per connection); take the first
            return int(result.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def _read_pid() -> tuple[Path, Path, int | None]:
    """Read PID and health file paths. Returns (pid_file, health_file, pid_or_None)."""
    cfg_result = load_config()
    workspace = Path(cfg_result.config.runtime.workspace_path)
    port = cfg_result.config.server.port
    pith_dir = workspace / ".pith"
    pid_file = pith_dir / "pid"
    health_file = pith_dir / "healthy"

    # Try pid file first
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            return pid_file, health_file, pid
        except OSError:
            pid_file.unlink(missing_ok=True)
            health_file.unlink(missing_ok=True)

    # Fallback: check what's actually listening on the port
    port_pid = _find_pid_on_port(port)
    if port_pid is not None:
        return pid_file, health_file, port_pid

    return pid_file, health_file, None


async def _kill_and_wait(pid: int) -> None:
    """Send SIGTERM and wait for the process to exit, escalating to SIGKILL."""
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        await asyncio.sleep(0.25)
        try:
            os.kill(pid, 0)
        except OSError:
            return
    console.print(f"[yellow]warning:[/yellow] pid {pid} didn't exit, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
        await asyncio.sleep(0.2)
    except OSError:
        pass


async def cmd_stop(_: argparse.Namespace) -> None:
    pid_file, health_file, pid = _read_pid()
    if pid is None:
        console.print("[yellow]not running[/yellow]")
        return

    await _kill_and_wait(pid)
    console.print(f"[green]stopped[/green]  pid {pid}")
    pid_file.unlink(missing_ok=True)
    health_file.unlink(missing_ok=True)


async def cmd_restart(args: argparse.Namespace) -> None:
    pid_file, health_file, pid = _read_pid()
    if pid is not None:
        await _kill_and_wait(pid)
        console.print(f"[green]stopped[/green]  pid {pid}")
        pid_file.unlink(missing_ok=True)
        health_file.unlink(missing_ok=True)
    else:
        console.print("[yellow]no running service — starting fresh[/yellow]")

    await cmd_run(args)


async def cmd_nuke(_: argparse.Namespace) -> None:
    import shutil

    # Stop the server if running and wait for it to die
    pid_file, health_file, pid = _read_pid()
    if pid is not None:
        await _kill_and_wait(pid)
        console.print(f"[green]stopped[/green]  pid {pid}")
        pid_file.unlink(missing_ok=True)
        health_file.unlink(missing_ok=True)

    cfg_result = load_config()
    cfg = cfg_result.config

    db_path = Path(cfg.runtime.memory_db_path)
    log_dir = Path(cfg.runtime.log_dir)
    pith_dir = Path(cfg.runtime.workspace_path) / ".pith"

    removed: list[str] = []

    # Remove database files (main + WAL/SHM)
    for suffix in ("", "-wal", "-shm"):
        p = db_path.parent / (db_path.name + suffix)
        if p.exists():
            p.unlink()
            removed.append(str(p))

    # Remove logs
    if log_dir.exists():
        shutil.rmtree(log_dir)
        removed.append(str(log_dir))

    # Remove SOUL.md
    soul = Path(cfg.runtime.workspace_path) / "SOUL.md"
    if soul.exists():
        soul.unlink()
        removed.append(str(soul))

    # Clean .pith state files (healthy, pid) but keep input_history
    if pith_dir.exists():
        for f in pith_dir.iterdir():
            if f.name == "input_history":
                continue
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()

    if removed:
        for r in removed:
            console.print(f"  removed {r}")
    console.print("[green]nuked[/green]  ready for fresh bootstrap")
    console.print("  run [bold]pith run[/bold] to start fresh")


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
    run_parser = sub.add_parser("run", help="Start the pith server (daemonizes by default)")
    run_parser.add_argument(
        "--foreground", action="store_true", help="Run in foreground (for Docker / debugging)"
    )
    start_parser = sub.add_parser("start", help="Alias for run")
    start_parser.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("chat", help="Interactive streaming terminal chat")
    sub.add_parser("status", help="Check if the service is running")
    sub.add_parser("stop", help="Stop the running service")
    sub.add_parser("restart", help="Stop and restart the service")
    sub.add_parser("nuke", help="Wipe database and identity — fresh bootstrap")
    sub.add_parser("doctor", help="Show configuration details")

    logs = sub.add_parser("logs", help="View local logs")
    logs_sub = logs.add_subparsers(dest="logs_cmd", required=True)
    logs_sub.add_parser("tail", help="Tail event log")

    return parser


async def run() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "setup":
        await cmd_setup(args)
    elif args.command in ("run", "start"):
        await cmd_run(args)
    elif args.command == "chat":
        await cmd_chat(args)
    elif args.command == "status":
        await cmd_status(args)
    elif args.command == "stop":
        await cmd_stop(args)
    elif args.command == "restart":
        await cmd_restart(args)
    elif args.command == "nuke":
        await cmd_nuke(args)
    elif args.command == "doctor":
        await cmd_doctor(args)
    elif args.command == "logs":
        if args.logs_cmd == "tail":
            await cmd_logs_tail(args)
        else:
            raise SystemExit("unknown logs command")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
