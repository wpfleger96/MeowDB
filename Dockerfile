FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN useradd --create-home --shell /bin/bash meowdb

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY src/ src/
RUN uv pip install --system --no-cache --no-deps .

USER meowdb

ENV MEOWDB_DATA_DIR=/data \
    MEOWDB_HOST=0.0.0.0 \
    MEOWDB_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["meowdb", "serve"]
