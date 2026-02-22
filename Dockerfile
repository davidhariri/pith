FROM python:3.12-slim

WORKDIR /workspace

RUN pip install --no-cache-dir uv
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md config.example.yaml ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "pith", "run"]
