# Portfolio Assistant API Usage Guide

This guide covers how to interact with Vishal's Portfolio AI Assistant via the REST API endpoints.

## Live Demo

🌐 **Production URL:** https://vishal-agent.codeshare.co.in

You can use all the examples below with either:
- `http://localhost:8000` (local development)
- `https://vishal-agent.codeshare.co.in` (production)

## What Can You Ask?

The assistant can answer questions about:
- 💼 **Experience**: Current role at Lumiq, previous work at LimeChat and AirTrik
- 🚀 **Skills**: Full-stack development, cloud infrastructure, leadership
- 📊 **Projects**: emPower pryzm, LimeChat, AirTrik IoT, and personal projects
- 🎓 **Education**: B.Tech + M.Tech in AI & Robotics
- 📧 **Contact**: Email, phone, LinkedIn, GitHub

**Example Questions:**
- "What does Vishal do?"
- "Tell me about his experience at LimeChat"
- "What are his technical skills?"
- "Show me his projects"
- "How can I contact him?"
- "What's his email?"

---

## Server Modes

| Mode | Command | Use Case |
|------|---------|----------|
| Development | `adk web .` | Local development with UI |
| Production | `gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker` | Production deployment |
| A2A Only | `uvicorn vishal_agent.agent:a2a_app --host 0.0.0.0 --port 8001` | A2A protocol only |

## Production Deployment

### Using Docker (Recommended)

```bash
# Pull and run
docker pull ghcr.io/vishal-pandey/vishal_agent:latest
docker run -p 8000:8000 -e OLLAMA_API_BASE=http://host.docker.internal:11434 -e WORKERS=4 ghcr.io/vishal-pandey/vishal_agent:latest

# Or with docker-compose
docker-compose up -d
```

### Manual Production Server

```bash
# Install dependencies
pip install -r requirements.txt

# Run with gunicorn (4 workers)
gunicorn vishal_agent.server:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

### Scaling Guidelines

| CPU Cores | Recommended Workers |
|-----------|---------------------|
| 1 | 2 |
| 2 | 4 |
| 4 | 8-12 |
| 8+ | 16-24 |

Formula: `workers = 2-4 × CPU cores`

---

## Prerequisites

1. Start the server (choose one):
   ```bash
   # Development
   adk web .
   
   # Production  
   gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
   ```

2. The server runs on `http://localhost:8000` by default.

3. View interactive API docs at: http://localhost:8000/docs

---

## API Endpoints Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/apps/{app}/users/{user}/sessions/{session}` | POST | Create a session |
| `/apps/{app}/users/{user}/sessions/{session}` | GET | Get session details |
| `/apps/{app}/users/{user}/sessions` | GET | List all sessions |
| `/run` | POST | Run agent (non-streaming) |
| `/run_sse` | POST | Run agent with SSE streaming |

---

## Step-by-Step Usage

> **Tip:** Replace `http://localhost:8000` with `https://vishal-agent.codeshare.co.in` to use the live demo.

### 1. Create a Session

Before sending messages, you must create a session:

```bash
# Local
curl -X POST "http://localhost:8000/apps/vishal_assistant/users/user-1/sessions/session-1" \
  -H "Content-Type: application/json" \
  -d '{}'

# Production
curl -X POST "https://vishal-agent.codeshare.co.in/apps/vishal_assistant/users/user-1/sessions/session-1" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response:**
```json
{
  "id": "session-1",
  "app_name": "vishal_assistant",
  "user_id": "user-1",
  "state": {},
  "events": [],
  "last_update_time": 1735380000.0
}
```

### 2. Ask About Vishal's Experience

```bash
curl -X POST http://localhost:8000/run_sse \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What does Vishal do at Lumiq?"}]
    },
    "streaming": true
  }'
```

### 3. Ask About Technical Skills

```bash
curl -X POST http://localhost:8000/run_sse \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What are his main technical skills?"}]
    },
    "streaming": true
  }'
```

### 4. Get Contact Information

```bash
curl -X POST http://localhost:8000/run_sse \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "How can I contact Vishal?"}]
    },
    "streaming": true
  }'
```

**Response (SSE stream):**
```
data: {"content":{"parts":[{"text":"Vishal"}],"role":"model"},...}
data: {"content":{"parts":[{"text":" is"}],"role":"model"},...}
data: {"content":{"parts":[{"text":" a"}],"role":"model"},...}
...
```

### 5. Send Message without Streaming

Use `/run` for a single response:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "vishal_assistant",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "Tell me about his projects"}]
    },
    "streaming": false
  }'
```

### 6. Get Session History

Retrieve conversation history:

```bash
curl -X GET "http://localhost:8000/apps/vishal_assistant/users/user-1/sessions/session-1"
```

### 7. List All Sessions

```bash
curl -X GET "http://localhost:8000/apps/vishal_assistant/users/user-1/sessions"
```

---

## Complete Example Script

```bash
#!/bin/bash
# complete_chat.sh - Create session and chat with portfolio assistant

APP_NAME="vishal_assistant"
USER_ID="user-1"
SESSION_ID="session-$(date +%s)"
BASE_URL="http://localhost:8000"

# 1. Create session
echo "Creating session: $SESSION_ID"
curl -s -X POST "$BASE_URL/apps/$APP_NAME/users/$USER_ID/sessions/$SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{}' > /dev/null

# 2. Ask about Vishal's experience
echo -e "\nAsking about Vishal's experience...\n"
curl -X POST "$BASE_URL/run_sse" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d "{
    \"app_name\": \"$APP_NAME\",
    \"user_id\": \"$USER_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"new_message\": {
      \"role\": \"user\",
      \"parts\": [{\"text\": \"Tell me about Vishal's work at LimeChat\"}]
    },
    \"streaming\": true
  }"

echo -e "\n\nDone!"
```

---

## Request Body Schema

### `/run` and `/run_sse`

```json
{
  "app_name": "string (required) - Agent folder name",
  "user_id": "string (required) - User identifier",
  "session_id": "string (required) - Session identifier",
  "new_message": {
    "role": "user",
    "parts": [
      {"text": "Your message here"}
    ]
  },
  "streaming": "boolean (optional) - Enable streaming, default: false",
  "state_delta": "object (optional) - State changes to apply"
}
```

---

## A2A Protocol (Alternative)

For A2A protocol access, start the A2A server instead:

```bash
uvicorn vishal_agent.agent:a2a_app --host 127.0.0.1 --port 8001
```

See [README.md](../README.md) for A2A usage examples.

---

## Troubleshooting

### "Session not found"
Create the session first using the POST endpoint.

### Connection refused
Make sure `adk web .` is running.

### No streaming tokens
LiteLLM/Ollama may batch responses. This is expected behavior with local models.
