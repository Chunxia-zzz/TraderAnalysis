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

# Copy application source and example data
COPY src/ ./src/
COPY examples/ ./examples/

# Set ownership
RUN chown -R trader:trader /app

USER trader

# ── Environment defaults (override via docker run -e or .env) ───────────────
ENV TA_DATA_PATH=examples/mock_futu_kline_HK.00700.json
ENV TA_SYMBOL=HK.00700
ENV TA_TIMEFRAME=1D
ENV TA_STRATEGY=ma_cross
ENV TA_REFRESH_SECONDS=5

EXPOSE 8000

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "trader_analysis", "serve", "--host", "0.0.0.0", "--port", "8000"]
