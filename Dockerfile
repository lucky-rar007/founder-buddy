# Founder Buddy Dockerfile v2.0
FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
# Bind to all interfaces inside the container so port mapping works
ENV HOST=0.0.0.0

WORKDIR /app

# Install system utilities needed for building dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security best practices
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy and install dependencies first for Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=appuser:appuser . .

# Ensure data and logs directories exist and are owned by appuser
RUN mkdir -p /app/data /app/logs && chown -R appuser:appuser /app/data /app/logs

# Switch to non-root user
USER appuser

# Expose server port
EXPOSE 8080

# Health probe check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Start Founder Buddy server (HOST env var is already set to 0.0.0.0 above)
CMD ["python", "main.py"]
