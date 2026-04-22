# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy only dependency manifests first (layer cache)
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Build and install into a prefix directory for clean copy
RUN pip install --no-cache-dir --prefix=/install .


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Non-root user for security
RUN groupadd -r trader && useradd -r -g trader trader

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source and data
COPY src/ ./src/
COPY data/watchlist.json ./data/

# Ensure data directory exists for SQLite
RUN mkdir -p /app/data /app/logs && chown -R trader:trader /app

USER trader

# ── Environment defaults (override via docker run -e or .env) ───────────────
ENV TA_DB_PATH=/app/data/indicators.db
ENV TA_LOG_DIR=/app/logs

EXPOSE 8000

# Health check using the watchlist endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/watchlist')" || exit 1

CMD ["python", "-m", "trader_analysis", "serve", "--host", "0.0.0.0", "--port", "8000"]
