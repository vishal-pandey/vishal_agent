# ADK Agent with Ollama - Dockerfile
# 
# Multi-stage build to reduce final image size
# Stage 1: Build dependencies and download models
# Stage 2: Runtime with only necessary files

# ============================================
# Stage 1: Builder - Install dependencies and download models
# ============================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies with retry logic
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    || (apt-get clean && apt-get update && apt-get install -y --no-install-recommends --fix-missing gcc g++) && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies to /install
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    gunicorn

# Pre-download the embedding model to /install/models
# Set PYTHONPATH so Python can find the installed packages
ENV PYTHONPATH=/install/lib/python3.12/site-packages

RUN python -c "\
from sentence_transformers import SentenceTransformer; \
import os; \
os.makedirs('/install/models', exist_ok=True); \
model = SentenceTransformer('all-MiniLM-L6-v2', cache_folder='/install/models'); \
print('Model downloaded successfully')"

# ============================================
# Stage 2: Runtime - Minimal production image
# ============================================
FROM python:3.12-slim-bookworm

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Tell sentence-transformers and HuggingFace to use our pre-downloaded model
    SENTENCE_TRANSFORMERS_HOME=/app/models \
    HF_HOME=/app/models \
    TRANSFORMERS_CACHE=/app/models \
    MODEL_CACHE_DIR=/app/models

# Install only runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy pre-downloaded models from builder
COPY --from=builder /install/models /app/models

# Copy application code
COPY vishal_agent/ ./vishal_agent/

# Copy scripts for document ingestion (including k8s init script)
COPY scripts/ ./scripts/

# Copy knowledge_base (can be overridden by ConfigMap in k8s)
COPY knowledge_base/ ./knowledge_base/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash agent

# Change ownership of app directory
USER root
RUN chown -R agent:agent /app
USER agent

# Expose ports
# 8000 - ADK API Server
# 8001 - A2A Protocol
EXPOSE 8000 8001

# Default environment variables
# Override OLLAMA_API_BASE to point to your Ollama instance
ENV OLLAMA_API_BASE=http://host.docker.internal:11434 \
    # PostgreSQL connection URL for session storage (optional)
    # If not set, falls back to InMemorySessionService
    # DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
    # Number of worker processes (scalable with PostgreSQL session storage)
    WORKERS=4 \
    # Worker timeout for long-running requests (streaming)
    TIMEOUT=120

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Production command - uvicorn with gunicorn process manager
CMD ["sh", "-c", "gunicorn vishal_agent.server:app --worker-class uvicorn.workers.UvicornWorker --workers ${WORKERS} --bind 0.0.0.0:8000 --timeout ${TIMEOUT} --keep-alive 5 --access-logfile - --error-logfile -"]
