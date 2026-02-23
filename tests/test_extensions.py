from __future__ import annotations

from pathlib import Path

import pytest

from pith.extensions import ExtensionError, ExtensionRegistry


@pytest.mark.asyncio
async def test_extension_tool_loaded(tmp_path: Path) -> None:
    tools_dir = tmp_path / "extensions" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "greet.py").write_text(
        "async def run(name: str = 'world') -> str:\n"
        '    """Say hello."""\n'
        "    return f'hello {name}'\n",
        encoding="utf-8",
    )

    registry = ExtensionRegistry(tmp_path)
    await registry.refresh()

    assert "greet" in registry.tools
    assert registry.tools["greet"].description == "Say hello."
    result = await registry.call_tool("greet", {"name": "pith"})
    assert result == "hello pith"


@pytest.mark.asyncio
async def test_extension_channel_missing_attr(tmp_path: Path) -> None:
    channels_dir = tmp_path / "extensions" / "channels"
    channels_dir.mkdir(parents=True, exist_ok=True)
    # Missing send()
    (channels_dir / "broken.py").write_text(
        "async def connect(): pass\nasync def recv(): pass\n",
        encoding="utf-8",
    )

    registry = ExtensionRegistry(tmp_path)
    with pytest.raises(ExtensionError, match="missing send"):
        await registry.refresh()
