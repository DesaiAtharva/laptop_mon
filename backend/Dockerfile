# Multi-stage slim production build for Laptop Monitoring Backend
# Stage 1: Build wheels
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# Stage 2: Final runtime image
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Install only minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client \
    libmariadb3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group
RUN groupadd -g 10001 -r appgroup && \
    useradd -u 10001 -r -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

# Copy and install pre-built wheels
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application source (excluding tests, docs, scratch)
COPY . /app/

# Ensure directory permissions for staticfiles/logs
RUN mkdir -p /app/static /app/logs && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "4", "--timeout", "60"]
