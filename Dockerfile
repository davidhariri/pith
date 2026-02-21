FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock* README.md config.example.yaml ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "pith", "run"]
