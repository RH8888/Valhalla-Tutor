FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for building python packages if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create dedicated non-root user and ensure permissions on runtime directories
RUN groupadd -r -g 10001 appuser && useradd -r -u 10001 -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /app/uploads/practice_booklets /app/uploads/report_cards \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

# Ensure entrypoint script is executable and normalized to Unix line endings
RUN sed -i 's/\r$//' /app/scripts/entrypoint.sh \
    && chmod +x /app/scripts/entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -f http://localhost:8000/health/db || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

