FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home app \
    && mkdir -p /data/media && chown app:app /data/media
ENV PATH="/app/backend/.venv/bin:$PATH"
USER app
EXPOSE 8000
CMD ["uvicorn", "app.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000"]
