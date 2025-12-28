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

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY vishal_agent/ ./vishal_agent/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash agent
USER agent

# Expose ports
# 8000 - ADK Web UI
# 8001 - A2A Protocol
EXPOSE 8000 8001

# Default environment variables
# Override OLLAMA_API_BASE to point to your Ollama instance
ENV OLLAMA_API_BASE=http://host.docker.internal:11434

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Default command - starts ADK web server
CMD ["adk", "web", "--host", "0.0.0.0", "."]
