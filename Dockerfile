# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir --prefix=/install . && \
    pip install --no-cache-dir --prefix=/install futu-api


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r trader && useradd -r -g trader trader

# Install cron for scheduled tasks
RUN apt-get update && apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source and data
COPY src/ ./src/
COPY data/watchlist.json ./data/
COPY docker/crontab /etc/cron.d/trader-cron
COPY docker/entrypoint.sh /entrypoint.sh

# Setup cron job permissions
RUN chmod 0644 /etc/cron.d/trader-cron && \
    crontab /etc/cron.d/trader-cron

# Ensure data directory exists for SQLite
RUN mkdir -p /app/data /app/logs && chown -R trader:trader /app && \
    chmod +x /entrypoint.sh

# ── Environment defaults (override via docker run -e or .env) ───────────────
ENV TA_DB_PATH=/app/data/indicators.db
ENV TA_LOG_DIR=/app/logs
ENV FUTU_OPEND_HOST=host.docker.internal
ENV FUTU_OPEND_PORT=11111

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
