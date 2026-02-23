FROM python:3.12-slim

WORKDIR /workspace

RUN pip install --no-cache-dir uv
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen

EXPOSE 8420

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=3 \
  CMD test -f /workspace/workspace/.pith/healthy || exit 1

ENTRYPOINT ["uv", "run", "pith", "run", "--foreground"]
