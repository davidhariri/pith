from __future__ import annotations

import os
from pathlib import Path

from pith.config import load_config


def test_load_config_with_env_substitution(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path
    config_path = workspace / "config.yaml"
    env_path = workspace / ".env"

    env_path.write_text(
        "OPENAI_API_KEY=abc123\nOPENAI_BASE_URL=https://example.test/v1\n", encoding="utf-8"
    )
    config_path.write_text(
        """
version: 1
runtime:
  workspace_path: .
  memory_db_path: ./memory.db
  log_dir: ./.pith/logs
model:
  provider: openai
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  base_url: ${OPENAI_BASE_URL}
telegram:
  transport: polling
  bot_token_env: TELEGRAM_BOT_TOKEN
mcp:
  servers: {}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = load_config(config_path=config_path, workspace_root=workspace)

    assert result.path == config_path
    assert result.config.model.base_url == "https://example.test/v1"
    assert os.environ["OPENAI_API_KEY"] == "abc123"
    assert result.config.mcp_servers == {}


def test_load_config_missing_model_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
version: 1
runtime:
  workspace_path: .
  memory_db_path: ./memory.db
  log_dir: ./.pith/logs
model: {}
""".strip(),
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(ValueError, match="model.provider is required"):
        load_config(config_path=config_path, workspace_root=tmp_path)
