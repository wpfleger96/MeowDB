FROM ghcr.io/astral-sh/uv:0.7 AS uv
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv

RUN useradd --create-home meowdb
RUN mkdir -p /data && chown meowdb:meowdb /data

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN python src/meowdb/build.py
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"

USER meowdb
ENV MEOWDB_DATA_DIR=/data MEOWDB_HOST=0.0.0.0 MEOWDB_PORT=8000
EXPOSE 8000
CMD ["meowdb", "serve"]
