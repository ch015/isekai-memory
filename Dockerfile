FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    ISEKAI_MEMORY_DATABASE_URL=sqlite:////data/memory.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy every package/build input before the single installation step.
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
RUN pip install --no-cache-dir .

RUN useradd -r -s /bin/false appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/ready', timeout=4)" || exit 1

ENTRYPOINT ["isekai-memory"]
CMD ["--mode", "http", "--host", "0.0.0.0", "--port", "8100"]
