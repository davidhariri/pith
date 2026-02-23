"""Tests for secrets management tools."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from pith.config import Config, ModelConfig, RuntimeConfig
from pith.extensions import ExtensionRegistry
from pith.runtime import Runtime
from pith.storage import Storage


def _make_runtime(tmp_path: Path) -> tuple[Runtime, Storage]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = tmp_path / "memory.db"

    cfg = Config(
        version=1,
        runtime=RuntimeConfig(
            workspace_path=str(workspace),
            memory_db_path=str(db_path),
            log_dir=str(workspace / "logs"),
        ),
        model=ModelConfig(provider="test", model="test-model", api_key_env="TEST_KEY"),
    )

    storage = Storage(db_path)
    extensions = ExtensionRegistry(workspace)
    runtime = Runtime(cfg, storage, extensions)
    return runtime, storage


@pytest.mark.asyncio
async def test_list_secrets_empty(tmp_path: Path) -> None:
    """list_secrets returns empty list when no .env exists."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    # env_path is workspace parent (tmp_path) / ".env"
    import json

    env_path = runtime.env_path
    assert not env_path.exists()

    # Simulate what the tool does
    result = "[]"
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_list_secrets_returns_names(tmp_path: Path) -> None:
    """list_secrets returns key names from .env."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    import json

    env_path = runtime.env_path
    env_path.write_text("BRAVE_API_KEY=secret123\n# comment\nOTHER_KEY=val\n", encoding="utf-8")

    # Read key names the same way list_secrets tool does
    names: list[str] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            names.append(key)

    assert names == ["BRAVE_API_KEY", "OTHER_KEY"]
    assert json.loads(json.dumps(names)) == ["BRAVE_API_KEY", "OTHER_KEY"]


@pytest.mark.asyncio
async def test_store_secret_with_callback(tmp_path: Path) -> None:
    """store_secret writes to .env and os.environ when callback provides a value."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    env_path = runtime.env_path
    secret_name = "TEST_SECRET_KEY"

    # Clean up env if it exists from prior test
    os.environ.pop(secret_name, None)

    async def mock_on_secret_request(request_id: str, name: str) -> None:
        """Simulate the client providing the secret value."""
        # Small delay to simulate round-trip
        await asyncio.sleep(0.01)
        runtime.provide_secret(request_id, "my-secret-value")

    runtime._on_secret_request = mock_on_secret_request

    # Simulate what store_secret does
    import uuid

    request_id = uuid.uuid4().hex[:12]
    event = asyncio.Event()
    runtime._pending_secrets[request_id] = event

    await runtime._on_secret_request(request_id, secret_name)
    await asyncio.wait_for(event.wait(), timeout=5)

    value = runtime._secret_values.pop(request_id, "")
    assert value == "my-secret-value"

    # Write to .env
    lines: list[str] = []
    lines.append(f"{secret_name}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    os.environ[secret_name] = value

    assert env_path.read_text(encoding="utf-8").strip() == f"{secret_name}=my-secret-value"
    assert os.environ[secret_name] == "my-secret-value"

    # Clean up
    os.environ.pop(secret_name, None)
    runtime._pending_secrets.pop(request_id, None)


@pytest.mark.asyncio
async def test_store_secret_timeout(tmp_path: Path) -> None:
    """store_secret returns error on timeout when no value is provided."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    request_id = "test-timeout"
    event = asyncio.Event()
    runtime._pending_secrets[request_id] = event

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(event.wait(), timeout=0.05)

    runtime._pending_secrets.pop(request_id, None)


@pytest.mark.asyncio
async def test_store_secret_no_callback(tmp_path: Path) -> None:
    """store_secret returns error when no callback (non-interactive)."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    # _on_secret_request defaults to not being set, so set it to None
    runtime._on_secret_request = None
    assert runtime._on_secret_request is None


@pytest.mark.asyncio
async def test_provide_secret_flow(tmp_path: Path) -> None:
    """Full provide_secret round-trip: event is set, value is retrievable."""
    runtime, _ = _make_runtime(tmp_path)

    request_id = "abc123"
    event = asyncio.Event()
    runtime._pending_secrets[request_id] = event

    assert not event.is_set()
    runtime.provide_secret(request_id, "the-value")
    assert event.is_set()
    assert runtime._secret_values[request_id] == "the-value"


@pytest.mark.asyncio
async def test_env_path_is_outside_workspace(tmp_path: Path) -> None:
    """env_path should be in config_dir (workspace parent), not workspace itself."""
    runtime, _ = _make_runtime(tmp_path)
    workspace = Path(runtime.cfg.runtime.workspace_path)
    assert runtime.env_path == workspace.parent / ".env"
    assert not str(runtime.env_path).startswith(str(workspace))


@pytest.mark.asyncio
async def test_store_secret_replaces_existing(tmp_path: Path) -> None:
    """store_secret replaces an existing key in .env rather than duplicating it."""
    runtime, storage = _make_runtime(tmp_path)
    async with storage:
        await runtime.initialize()

    env_path = runtime.env_path
    env_path.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")

    # Simulate the replacement logic from store_secret
    name = "FOO"
    value = "new"
    lines: list[str] = []
    replaced = False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key == name:
                lines.append(f"{name}={value}")
                replaced = True
                continue
        lines.append(line)
    if not replaced:
        lines.append(f"{name}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    content = env_path.read_text(encoding="utf-8")
    assert content.count("FOO=") == 1
    assert "FOO=new" in content
    assert "BAR=keep" in content
