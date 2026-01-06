# Vishal's Portfolio AI Assistant

[![Docker Image](https://github.com/vishal-pandey/vishal_agent/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/vishal-pandey/vishal_agent/actions/workflows/docker-publish.yml)
[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-vishal--pandey%2Fvishal__agent-blue)](https://ghcr.io/vishal-pandey/vishal_agent)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-vishal--agent.codeshare.co.in-green)](https://www.vishalpandey.co.in)

A personal AI assistant for Vishal Pandey's portfolio that answers questions about his experience, skills, projects, and professional background. Powered by Llama 3.2 running locally via Ollama and LiteLLM.

**Repository:** https://github.com/vishal-pandey/vishal_agent  
**Live Demo:** https://vishal-agent.codeshare.co.in

## Features

- ✅ Personal portfolio assistant - knows everything about Vishal Pandey
- ✅ Runs locally with Ollama - no API costs, complete privacy
- ✅ Works with Google ADK web interface (`adk web`)
- ✅ Exposes agent via A2A protocol for multi-agent systems
- ✅ Supports streaming responses
- ✅ **RAG Support** - Retrieve context from custom documents using pgvector
- 🌐 **Live Demo**: https://vishal-agent.codeshare.co.in

## What Can You Ask?

The assistant can answer questions about:
- 💼 **Experience**: Current role at Lumiq, previous work at LimeChat and AirTrik
- 🚀 **Skills**: Full-stack development, cloud infrastructure, leadership
- 📊 **Projects**: emPower pryzm, LimeChat, AirTrik IoT, and personal projects
- 🎓 **Education**: B.Tech + M.Tech in AI & Robotics
- 📧 **Contact**: Email, phone, LinkedIn, GitHub
- 🎯 **Philosophy**: Approach to building products and leading teams
- 📚 **Custom Knowledge** (with RAG): Any documents you ingest into the vector database

## Try it Live

No setup required! Try the agent directly:

```bash
# 1. Create a session
curl -X POST "https://vishal-agent.codeshare.co.in/apps/vishal_assistant/users/demo/sessions/demo-session" \
  -H "Content-Type: application/json" -d '{}'

# 2. Ask about Vishal's experience
curl -X POST "https://vishal-agent.codeshare.co.in/run_sse" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "demo",
    "session_id": "demo-session",
    "new_message": {"role": "user", "parts": [{"text": "What does Vishal do?"}]},
    "streaming": true
  }'

# 3. Ask about skills
curl -X POST "https://vishal-agent.codeshare.co.in/run_sse" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "demo",
    "session_id": "demo-session",
    "new_message": {"role": "user", "parts": [{"text": "What are his technical skills?"}]},
    "streaming": true
  }'

# 4. Get contact information
curl -X POST "https://vishal-agent.codeshare.co.in/run_sse" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "demo",
    "session_id": "demo-session",
    "new_message": {"role": "user", "parts": [{"text": "How can I contact Vishal?"}]},
    "streaming": true
  }'
```

---

## Local Setup

### Prerequisites

1. **Ollama** installed and running with Llama 3.2:
   ```bash
   # Install Ollama (https://ollama.ai)
   # Then pull the model:
   ollama pull llama3.2:latest
   
   # Verify it's running:
   ollama list
   ```

2. **Python 3.10+** with virtual environment

## Installation

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Option 1: ADK Web Interface

Run the agent with the ADK development UI:

```bash
# From the project root (parent of vishal_agent/)
adk web .
```

Then open http://localhost:8000 and select `vishal_assistant` from the dropdown.

### Option 2: A2A Protocol Server

Expose the agent via A2A protocol for other agents to consume:

```bash
# Start the A2A server
uvicorn vishal_agent.agent:a2a_app --host localhost --port 8001
```

**Endpoints:**
- Agent Card: http://localhost:8001/.well-known/agent-card.json
- A2A API: http://localhost:8001

### Testing the A2A Server

```bash
# Check agent card
curl http://localhost:8001/.well-known/agent-card.json | python -m json.tool

# Send a message (non-streaming)
curl -X POST http://localhost:8001 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "messageId": "msg-1",
        "parts": [{"text": "Hello! What can you help me with?"}]
      }
    }
  }'

# Send a message (streaming)
curl -X POST http://localhost:8001 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  --no-buffer \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/stream",
    "params": {
      "message": {
        "role": "user",
        "messageId": "msg-1",
        "parts": [{"text": "What is 2 + 2?"}]
      }
    }
  }'
```

## Project Structure

```
vishal_agent/
├── vishal_agent/
│   ├── __init__.py
│   ├── agent.py          # Main agent definition with RAG tools
│   ├── server.py         # FastAPI server with REST endpoints
│   ├── vector_store.py   # pgvector integration for RAG
│   └── rag_tools.py      # RAG retrieval tool for agent
├── scripts/
│   └── ingest_documents.py  # Document ingestion CLI
├── docs/
│   ├── API_USAGE.md      # REST API documentation
│   └── RAG_SETUP.md      # RAG setup and usage guide
├── knowledge_base/       # Example documents for RAG
│   └── example.txt
├── Dockerfile            # Docker image
├── docker-compose.yml    # PostgreSQL + pgvector + agent
├── init-pgvector.sql     # pgvector initialization
├── requirements.txt
└── README.md
```

## RAG (Retrieval-Augmented Generation) 🔍

Enhance the agent with custom knowledge by ingesting documents into pgvector:

```bash
# 1. Start PostgreSQL with pgvector
docker-compose up -d postgres

# 2. Set DATABASE_URL in .env
echo 'DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@localhost:5432/vishal_agent_sessions' >> .env

# 3. Ingest documents
python -m scripts.ingest_documents --source knowledge_base/ --pattern "*.txt"

# 4. Run the agent (RAG automatically enabled)
uvicorn vishal_agent.server:app --reload
```

**What RAG enables:**
- 📚 Search through custom documents and knowledge bases
- 🔍 Agent retrieves relevant context before answering
- 📊 Provides citations and sources
- 🎯 Handles queries beyond hardcoded knowledge

See [docs/RAG_SETUP.md](docs/RAG_SETUP.md) for complete guide.

## Docker Usage

### Build and Run with Docker

```bash
# Build the image locally
docker build -t adk-agent .

# Or pull from GitHub Container Registry
docker pull ghcr.io/vishal-pandey/vishal_agent:latest

# Run with ADK Web (connects to Ollama on host)
docker run -p 8000:8000 -e OLLAMA_API_BASE=http://host.docker.internal:11434 ghcr.io/vishal-pandey/vishal_agent:latest

# Run with A2A server instead
docker run -p 8001:8001 -e OLLAMA_API_BASE=http://host.docker.internal:11434 ghcr.io/vishal-pandey/vishal_agent:latest \
  uvicorn vishal_agent.agent:a2a_app --host 0.0.0.0 --port 8001
```

### Using Docker Compose

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## REST API Usage

See [docs/API_USAGE.md](docs/API_USAGE.md) for complete API documentation.

### Quick Example

```bash
# 1. Create session
curl -X POST "http://localhost:8000/apps/vishal_agent/users/user-1/sessions/session-1" \
  -H "Content-Type: application/json" -d '{}'

# 2. Chat with streaming
curl -X POST http://localhost:8000/run_sse \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_agent",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "Hello!"}]
    },
    "streaming": true
  }'
```

## Troubleshooting

1. **Ollama not running**: Make sure Ollama is running with `ollama serve` or check if it's already running.

2. **Model not found**: Pull the model with `ollama pull llama3.2:latest`

3. **Import errors**: Make sure you've installed dependencies with `pip install -r requirements.txt`

4. **A2A connection issues**: Ensure no other process is using port 8001
