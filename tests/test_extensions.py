from __future__ import annotations

from pathlib import Path

import pytest

from pith.extensions import ExtensionError, ExtensionRegistry


@pytest.mark.asyncio
async def test_extension_tool_reserved_prefix_rejected(tmp_path: Path) -> None:
    tools_dir = tmp_path / "extensions" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "MCP__bad.py").write_text(
        "async def run() -> str:\n    return 'bad'\n",
        encoding="utf-8",
    )

    registry = ExtensionRegistry(tmp_path)

    with pytest.raises(ExtensionError):
        await registry.refresh()
