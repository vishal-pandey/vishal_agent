# ADK Agent with Ollama - Dockerfile
# 
# This Dockerfile builds the ADK agent. Note that Ollama must be
# accessible from the container (either running on host or as a separate container).

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (including gunicorn for production)
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY vishal_agent/ ./vishal_agent/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash agent
USER agent

# Expose ports
# 8000 - ADK API Server
# 8001 - A2A Protocol
EXPOSE 8000 8001

# Default environment variables
# Override OLLAMA_API_BASE to point to your Ollama instance
ENV OLLAMA_API_BASE=http://host.docker.internal:11434 \
    # Number of worker processes (adjust based on CPU cores)
    WORKERS=4 \
    # Worker timeout for long-running requests (streaming)
    TIMEOUT=120

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Production command - uvicorn with multiple workers for concurrency
# Use gunicorn as process manager with uvicorn workers for best performance
CMD gunicorn vishal_agent.server:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WORKERS} \
    --bind 0.0.0.0:8000 \
    --timeout ${TIMEOUT} \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -
