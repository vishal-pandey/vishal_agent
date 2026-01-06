# RAG Quick Reference Card

## 🚀 Quick Start (One Command)

```bash
./setup_rag.sh
```

## 📋 Common Commands

### Database Management
```bash
# Start PostgreSQL
docker-compose up -d postgres

# Stop PostgreSQL
docker-compose down

# View logs
docker-compose logs -f postgres
```

### Document Ingestion
```bash
# Ingest documents
python -m scripts.ingest_documents --source knowledge_base/ --pattern "*.txt"

# Count documents
python -m scripts.ingest_documents --count

# Search test
python -m scripts.ingest_documents --search "AI agents" --k 3

# Clear all
python -m scripts.ingest_documents --clear-all
```

### Agent Operations
```bash
# Run with RAG enabled (requires DATABASE_URL)
uvicorn vishal_agent.server:app --reload

# Production mode
gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker

# Check if RAG is enabled (look for this in logs)
# ✅ RAG enabled - agent can retrieve from knowledge base
```

### Testing
```bash
# Test RAG functionality
python test_rag.py

# Test via API
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What are Vishal's recent interests?"}]
    }
  }'
```

## 🔧 Configuration

### Environment Variables (.env)
```bash
# Required for RAG
DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@localhost:5432/vishal_agent_sessions

# Optional
EMBEDDING_MODEL=all-MiniLM-L6-v2
WORKERS=4
```

## 📊 File Structure

```
vishal_agent/
├── vishal_agent/
│   ├── vector_store.py     # pgvector operations
│   ├── rag_tools.py        # Agent retrieval tool
│   └── agent.py            # Agent with RAG
├── scripts/
│   └── ingest_documents.py # Document ingestion
├── knowledge_base/         # Your documents here
├── test_rag.py            # Quick test script
└── setup_rag.sh           # One-command setup
```

## 🎯 Key Concepts

| Concept | Description |
|---------|-------------|
| **Vector Store** | PostgreSQL + pgvector for storing embeddings |
| **Embedding** | Text → 384-dim vector (all-MiniLM-L6-v2) |
| **Chunking** | Documents → smaller pieces (500 chars default) |
| **Similarity Search** | Find most relevant chunks using cosine similarity |
| **RAG Tool** | Agent calls `retrieve_context` to search knowledge base |

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| RAG not enabled | Set `DATABASE_URL` in .env |
| pgvector error | Use `pgvector/pgvector:pg16` Docker image |
| No search results | Run ingestion: `python -m scripts.ingest_documents --source knowledge_base/` |
| Model download slow | Pre-download: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"` |

## 📚 Resources

- [Full RAG Setup Guide](RAG_SETUP.md)
- [API Documentation](API_USAGE.md)
- [Main README](../README.md)

## 🎓 Examples

### Ingest Markdown Docs
```bash
python -m scripts.ingest_documents --source docs/ --pattern "*.md" --chunk-size 800
```

### Custom Chunking
```bash
python -m scripts.ingest_documents --source blog/ --chunk-size 1000 --overlap 150
```

### Clear and Re-ingest
```bash
python -m scripts.ingest_documents --clear --source knowledge_base/
```

## ✅ Health Checks

```bash
# Check PostgreSQL
docker exec postgres-sessions pg_isready

# Check pgvector
docker exec postgres-sessions psql -U vishal_agent -d vishal_agent_sessions -c "SELECT * FROM pg_extension WHERE extname = 'vector';"

# Check document count
python -m scripts.ingest_documents --count

# Test RAG end-to-end
python test_rag.py
```

---

**Need help?** Read the [Full RAG Setup Guide](RAG_SETUP.md)
