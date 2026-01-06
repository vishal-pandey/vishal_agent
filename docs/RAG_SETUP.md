# RAG Setup Guide

This guide explains how to set up and use Retrieval-Augmented Generation (RAG) with pgvector in Vishal's Portfolio AI Assistant.

## Overview

RAG enhances the agent with the ability to:
- 📚 Search through custom documents and knowledge bases
- 🔍 Retrieve relevant context before answering questions
- 📊 Provide citations and sources for information
- 🎯 Handle queries beyond the hardcoded knowledge in the agent

## Architecture

```
User Query → Agent → retrieve_context tool → pgvector DB → Relevant Docs → Agent → Response
```

The system uses:
- **pgvector**: PostgreSQL extension for vector similarity search
- **sentence-transformers**: Generate embeddings (all-MiniLM-L6-v2 model)
- **Vector Store**: Custom async implementation with PostgreSQL
- **ADK Tools**: Agent can call `retrieve_context` tool when needed

## Prerequisites

1. **PostgreSQL with pgvector**
   ```bash
   # Using docker-compose (recommended)
   docker-compose up -d postgres
   
   # Or install pgvector locally
   # See: https://github.com/pgvector/pgvector#installation
   ```

2. **Database URL**
   ```bash
   # Add to .env file
   DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@localhost:5432/vishal_agent_sessions
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Quick Start

### 1. Start PostgreSQL with pgvector

```bash
# Using docker-compose
docker-compose up -d postgres

# Verify pgvector is enabled
docker exec -it postgres-sessions psql -U vishal_agent -d vishal_agent_sessions -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Prepare Documents

Create a directory with your documents (text files, markdown, etc.):

```bash
mkdir -p knowledge_base
echo "Vishal loves building AI agents and contributing to open source." > knowledge_base/about.txt
echo "His favorite programming languages are Python and TypeScript." > knowledge_base/tech.txt
```

### 3. Ingest Documents

```bash
# Ingest all .txt files from a directory
python -m scripts.ingest_documents --source knowledge_base --pattern "*.txt"

# Ingest markdown files
python -m scripts.ingest_documents --source docs/ --pattern "*.md"

# Ingest a single file
python -m scripts.ingest_documents --file path/to/document.txt

# Clear existing and re-ingest
python -m scripts.ingest_documents --source knowledge_base --pattern "*.txt" --clear
```

### 4. Verify Ingestion

```bash
# Count documents in vector store
python -m scripts.ingest_documents --count

# Test search
python -m scripts.ingest_documents --search "AI agents" --k 3
```

### 5. Run the Agent

```bash
# The agent automatically enables RAG if DATABASE_URL is set
uvicorn vishal_agent.server:app --reload

# Or with production settings
gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker
```

## Document Ingestion

### Basic Usage

```bash
# Ingest with default settings (500 char chunks, 50 char overlap)
python -m scripts.ingest_documents --source docs/

# Custom chunk size and overlap
python -m scripts.ingest_documents --source docs/ --chunk-size 1000 --overlap 100

# Multiple file patterns
python -m scripts.ingest_documents --source docs/ --pattern "*.{txt,md}"
```

### Script Options

| Option | Description | Default |
|--------|-------------|---------|
| `--source` | Source directory or file | Required |
| `--pattern` | File glob pattern | `*.txt` |
| `--chunk-size` | Characters per chunk | 500 |
| `--overlap` | Overlap between chunks | 50 |
| `--clear` | Clear existing docs first | False |
| `--count` | Count total documents | - |
| `--search` | Search for query | - |
| `--k` | Number of search results | 4 |
| `--clear-all` | Delete all documents | - |

### Chunking Strategy

Documents are split into overlapping chunks:
- **Why chunking?** LLMs have token limits; smaller chunks = more precise retrieval
- **Overlap:** Ensures context isn't lost at chunk boundaries
- **Smart splitting:** Breaks at sentence boundaries when possible

Example:
```
Document: "This is sentence one. This is sentence two. This is sentence three."
Chunk size: 30, Overlap: 10

Chunk 1: "This is sentence one. This"
Chunk 2: "This is sentence two."
Chunk 3: "sentence two. This is sentence three."
```

## Using RAG in the Agent

### How It Works

The agent has a `retrieve_context` tool that:
1. Takes a user query
2. Generates an embedding for the query
3. Searches the vector database for similar documents
4. Returns the top-k most relevant chunks
5. Agent uses this context to answer

### When the Tool is Called

The agent **automatically decides** when to use RAG:
- ✅ User asks about topics that might be in additional documents
- ✅ Need for detailed information beyond base knowledge
- ✅ When citations from sources are helpful
- ❌ Questions about Vishal's basic info (already in instruction)
- ❌ General greetings or small talk

### Example Queries

```python
# Query that triggers RAG
"What are Vishal's thoughts on distributed systems?"
# Agent calls retrieve_context → searches vector DB → finds relevant docs → answers

# Query that doesn't need RAG
"What's Vishal's email?"
# Agent knows this already → answers directly
```

## Testing RAG

### 1. Test Search Directly

```bash
# Search the vector store
python -m scripts.ingest_documents --search "machine learning projects" --k 5
```

### 2. Test via API

```bash
# Create session
curl -X POST "http://localhost:8000/sessions" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user"}'

# Ask a question that requires RAG
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "session_id": "test-session",
    "new_message": {
      "role": "user",
      "parts": [{"text": "Tell me about the advanced topics in the documentation"}]
    }
  }'
```

### 3. Check Logs

The agent logs when RAG is enabled:
```
✅ RAG enabled - agent can retrieve from knowledge base
```

## Configuration

### Environment Variables

```bash
# Required for RAG
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/dbname

# Optional - change embedding model
EMBEDDING_MODEL=all-MiniLM-L6-v2  # Default, 384 dimensions
# Or use: sentence-transformers/all-mpnet-base-v2  # 768 dimensions, more accurate
```

### Embedding Models

| Model | Dimensions | Speed | Quality | Use Case |
|-------|------------|-------|---------|----------|
| all-MiniLM-L6-v2 | 384 | Fast ⚡ | Good ✓ | Default, balanced |
| all-mpnet-base-v2 | 768 | Medium | Better ✓✓ | Higher accuracy |
| multi-qa-MiniLM-L6-cos-v1 | 384 | Fast ⚡ | Good ✓ | Q&A optimized |

To change the model, edit [vector_store.py](../vishal_agent/vector_store.py):
```python
VectorStore(
    database_url=database_url,
    embedding_model="sentence-transformers/all-mpnet-base-v2"
)
```

### Vector Store Configuration

Edit [vector_store.py](../vishal_agent/vector_store.py):

```python
VectorStore(
    database_url="...",
    embedding_model="all-MiniLM-L6-v2",
    table_name="documents",  # Change table name
    dimension=384  # Match your embedding model
)
```

## Advanced Usage

### 1. Multiple Knowledge Bases

Use metadata to separate different knowledge bases:

```python
# Ingest with custom metadata
await vector_store.add_document(
    content="Document content",
    metadata={"category": "technical", "author": "vishal"}
)

# Search with filters (TODO: implement in vector_store.py)
results = await vector_store.similarity_search(
    query="python tips",
    k=5,
    filter_metadata={"category": "technical"}
)
```

### 2. Batch Ingestion

```python
# In Python script
from vishal_agent.vector_store import initialize_vector_store

async def ingest_bulk():
    store = await initialize_vector_store()
    
    documents = ["doc1", "doc2", "doc3", ...]
    metadatas = [{"source": "web"}, {"source": "pdf"}, ...]
    
    await store.add_documents(documents, metadatas)
```

### 3. Update Documents

```bash
# Clear old documents
python -m scripts.ingest_documents --clear-all

# Re-ingest fresh data
python -m scripts.ingest_documents --source knowledge_base/
```

### 4. Production Deployment

```yaml
# docker-compose.yml already configured with pgvector
services:
  postgres:
    image: pgvector/pgvector:pg16
    # ... pgvector ready!
  
  adk-agent:
    environment:
      - DATABASE_URL=postgresql+asyncpg://...
```

## Troubleshooting

### RAG Not Enabled

**Problem:** Agent doesn't use RAG
```
ℹ️ RAG disabled - DATABASE_URL not set
```

**Solution:**
```bash
# Set DATABASE_URL in .env
echo 'DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@localhost:5432/vishal_agent_sessions' >> .env
```

### pgvector Extension Missing

**Problem:**
```
ERROR: extension "vector" is not available
```

**Solution:**
```bash
# Using docker-compose (uses pgvector/pgvector image)
docker-compose up -d postgres

# Or install pgvector manually
# https://github.com/pgvector/pgvector#installation
```

### No Results from Search

**Problem:** Search returns empty results

**Solution:**
```bash
# Check if documents are ingested
python -m scripts.ingest_documents --count

# If 0, ingest documents
python -m scripts.ingest_documents --source knowledge_base/
```

### Embedding Model Download Issues

**Problem:** Model download fails or is slow

**Solution:**
```bash
# Pre-download the model
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Or set cache directory
export SENTENCE_TRANSFORMERS_HOME=/path/to/models
```

### Memory Issues

**Problem:** High memory usage

**Solution:**
- Use a smaller embedding model (all-MiniLM-L6-v2 is already small)
- Reduce chunk size: `--chunk-size 300`
- Batch ingest in smaller groups
- Increase PostgreSQL `shared_buffers` and `work_mem`

## Performance Tips

### 1. Indexing

Vector indexes are created automatically using HNSW (fast) or ivfflat (fallback):
```sql
-- HNSW index (better performance)
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

-- Check index usage
EXPLAIN ANALYZE SELECT * FROM documents ORDER BY embedding <=> '[0.1, 0.2, ...]' LIMIT 5;
```

### 2. Batch Operations

```python
# Good - batch insert
await store.add_documents(many_documents)

# Bad - many individual inserts
for doc in many_documents:
    await store.add_document(doc)  # Slow!
```

### 3. Connection Pooling

Already configured in [vector_store.py](../vishal_agent/vector_store.py):
```python
pool = await asyncpg.create_pool(
    database_url,
    min_size=2,
    max_size=10  # Adjust based on workload
)
```

## Examples

### Example 1: Technical Documentation

```bash
# Ingest your project docs
python -m scripts.ingest_documents --source docs/ --pattern "*.md" --chunk-size 800

# Ask the agent
curl -X POST "http://localhost:8000/run" -d '{
  "user_id": "dev",
  "new_message": {"role": "user", "parts": [{"text": "How do I configure the vector store?"}]}
}'
```

### Example 2: Blog Posts

```bash
# Ingest blog content
python -m scripts.ingest_documents --source blog_posts/ --pattern "*.txt" --chunk-size 600

# Query about specific topics
curl -X POST "http://localhost:8000/run" -d '{
  "new_message": {"role": "user", "parts": [{"text": "What did Vishal write about microservices?"}]}
}'
```

### Example 3: Research Papers

```bash
# Larger chunks for academic content
python -m scripts.ingest_documents --source papers/ --pattern "*.txt" --chunk-size 1200 --overlap 200
```

## API Reference

### VectorStore Methods

```python
from vishal_agent.vector_store import VectorStore

store = VectorStore(database_url="...")

# Initialize
await store.initialize()

# Add documents
doc_id = await store.add_document("content", metadata={"source": "web"})
doc_ids = await store.add_documents(["doc1", "doc2"], metadatas=[{}, {}])

# Search
results = await store.similarity_search("query", k=5)
# Returns: List[(content, metadata, similarity_score)]

# Manage
count = await store.count_documents()
await store.delete_all()
await store.close()
```

### Ingestion Script

```bash
# Full command reference
python -m scripts.ingest_documents \
  --source knowledge_base/ \
  --pattern "*.txt" \
  --chunk-size 500 \
  --overlap 50 \
  --clear
```

## Next Steps

1. **Ingest Your Data**: Add documents to the knowledge base
2. **Test Queries**: Verify the agent retrieves correct information
3. **Tune Chunking**: Adjust chunk size/overlap for your content
4. **Monitor Performance**: Check search latency and relevance
5. **Scale**: Use PostgreSQL replication for high-traffic deployments

## Resources

- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [sentence-transformers](https://www.sbert.net/)
- [Google ADK Tools Guide](https://github.com/google/adk-toolkit)
- [Vector Database Best Practices](https://www.pinecone.io/learn/vector-database/)

## Support

Issues or questions? Check:
1. This guide's troubleshooting section
2. Project [README.md](../README.md)
3. [API_USAGE.md](API_USAGE.md) for API examples
4. Open an issue on GitHub

---

**Pro Tip:** Start with a small set of documents (10-20 files) to test your setup before ingesting large knowledge bases. This makes debugging much easier! 🚀
