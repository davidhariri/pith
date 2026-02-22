FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml README.md config.example.yaml ./
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir .

ENTRYPOINT ["pith", "run"]
