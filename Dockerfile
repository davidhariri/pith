FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir uv
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen

ENV PITH_CONFIG=/pith/config.yaml

EXPOSE 8420

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=3 \
  CMD test -f /pith/.pith/healthy || exit 1

ENTRYPOINT ["uv", "run", "pith", "run", "--foreground"]
