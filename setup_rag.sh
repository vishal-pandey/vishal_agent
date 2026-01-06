#!/bin/bash

# Quick setup script for RAG with pgvector
# This script helps you set up the complete RAG environment

set -e  # Exit on error

echo "🚀 Setting up RAG for Vishal's Portfolio AI Assistant"
echo "=================================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    echo "   ✅ .env file created"
    echo "   ⚠️  Please review and update the values in .env"
else
    echo "✅ .env file already exists"
fi

echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Start PostgreSQL with pgvector
echo "🗄️  Starting PostgreSQL with pgvector..."
docker-compose up -d postgres

echo "⏳ Waiting for PostgreSQL to be ready..."
sleep 5

# Check PostgreSQL health
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker exec postgres-sessions pg_isready -U vishal_agent -d vishal_agent_sessions > /dev/null 2>&1; then
        echo "   ✅ PostgreSQL is ready"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "   Waiting for PostgreSQL... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "   ❌ PostgreSQL failed to start"
    exit 1
fi

echo ""

# Verify pgvector extension
echo "🔧 Verifying pgvector extension..."
docker exec postgres-sessions psql -U vishal_agent -d vishal_agent_sessions -c "CREATE EXTENSION IF NOT EXISTS vector;" > /dev/null 2>&1
echo "   ✅ pgvector extension enabled"
echo ""

# Install Python dependencies if needed
if [ ! -d ".venv" ]; then
    echo "🐍 Creating Python virtual environment..."
    python3 -m venv .venv
    echo "   ✅ Virtual environment created"
fi

echo "📦 Installing Python dependencies..."
source .venv/bin/activate 2>/dev/null || . .venv/Scripts/activate 2>/dev/null
pip install -q -r requirements.txt
echo "   ✅ Dependencies installed"
echo ""

# Download embedding model
echo "🤖 Downloading embedding model (this may take a minute)..."
python3 -c "
from sentence_transformers import SentenceTransformer
import sys
try:
    print('   Loading all-MiniLM-L6-v2...')
    SentenceTransformer('all-MiniLM-L6-v2')
    print('   ✅ Embedding model ready')
except Exception as e:
    print(f'   ⚠️  Error loading model: {e}')
    sys.exit(1)
"

echo ""

# Run test
echo "🧪 Running RAG test..."
python3 test_rag.py

echo ""
echo "=================================================="
echo "✅ RAG setup complete!"
echo ""
echo "Next steps:"
echo "  1. Ingest documents:"
echo "     python -m scripts.ingest_documents --source knowledge_base/ --pattern '*.txt'"
echo ""
echo "  2. Start the agent:"
echo "     uvicorn vishal_agent.server:app --reload"
echo ""
echo "  3. Test RAG:"
echo "     curl -X POST http://localhost:8000/run \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"user_id\":\"test\",\"new_message\":{\"role\":\"user\",\"parts\":[{\"text\":\"What are Vishal's recent interests?\"}]}}'"
echo ""
echo "  4. Read the full guide:"
echo "     docs/RAG_SETUP.md"
echo ""
