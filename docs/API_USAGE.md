# ADK API Usage Guide

This guide covers how to interact with your ADK agent via the REST API endpoints.

## Prerequisites

1. Start the ADK web server:
   ```bash
   cd /Users/vishal/Developer/llama
   source .venv/bin/activate
   adk web .
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

### 1. Create a Session

Before sending messages, you must create a session:

```bash
curl -X POST "http://localhost:8000/apps/vishal_agent/users/user-1/sessions/session-1" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response:**
```json
{
  "id": "session-1",
  "app_name": "vishal_agent",
  "user_id": "user-1",
  "state": {},
  "events": [],
  "last_update_time": 1735380000.0
}
```

### 2. Send Message with Streaming (SSE)

Use `/run_sse` for Server-Sent Events streaming:

```bash
curl -X POST http://localhost:8000/run_sse \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{
    "app_name": "vishal_agent",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "Tell me a short joke"}]
    },
    "streaming": true
  }'
```

**Response (SSE stream):**
```
data: {"content":{"parts":[{"text":"Here"}],"role":"model"},...}
data: {"content":{"parts":[{"text":"'s"}],"role":"model"},...}
data: {"content":{"parts":[{"text":" a"}],"role":"model"},...}
...
```

### 3. Send Message without Streaming

Use `/run` for a single response:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "vishal_agent",
    "user_id": "user-1",
    "session_id": "session-1",
    "new_message": {
      "role": "user",
      "parts": [{"text": "What is 2 + 2?"}]
    },
    "streaming": false
  }'
```

### 4. Get Session History

Retrieve conversation history:

```bash
curl -X GET "http://localhost:8000/apps/vishal_agent/users/user-1/sessions/session-1"
```

### 5. List All Sessions

```bash
curl -X GET "http://localhost:8000/apps/vishal_agent/users/user-1/sessions"
```

---

## Complete Example Script

```bash
#!/bin/bash
# complete_chat.sh - Create session and chat with agent

APP_NAME="vishal_agent"
USER_ID="user-1"
SESSION_ID="session-$(date +%s)"
BASE_URL="http://localhost:8000"

# 1. Create session
echo "Creating session: $SESSION_ID"
curl -s -X POST "$BASE_URL/apps/$APP_NAME/users/$USER_ID/sessions/$SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{}' > /dev/null

# 2. Send message with streaming
echo -e "\nSending message with SSE streaming...\n"
curl -X POST "$BASE_URL/run_sse" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d "{
    \"app_name\": \"$APP_NAME\",
    \"user_id\": \"$USER_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"new_message\": {
      \"role\": \"user\",
      \"parts\": [{\"text\": \"Hello! What can you help me with?\"}]
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
