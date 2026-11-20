"""
Production ASGI Server for ADK Agent

This module creates a production-ready FastAPI application that exposes:
1. /run - Non-streaming agent execution
2. /run_sse - Streaming agent execution (SSE)
3. /a2a/* - A2A protocol endpoints

Session storage:
- Uses PostgreSQL via DatabaseSessionService for production (scalable, multi-worker)
- Falls back to InMemorySessionService if DATABASE_URL is not set (development)

For production deployment with multiple workers:
    gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker

For development:
    uvicorn vishal_agent.server:app --reload
"""

import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from .agent import root_agent
from . import notify

# ============================================
# Session Management
# ============================================

# Check for DATABASE_URL environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Use PostgreSQL for production (supports multiple workers)
    from google.adk.sessions import DatabaseSessionService
    print(f"🗄️ Using DatabaseSessionService with PostgreSQL")
    session_service = DatabaseSessionService(db_url=DATABASE_URL)
else:
    # Fallback to in-memory for development
    from google.adk.sessions import InMemorySessionService
    print("⚠️ Using InMemorySessionService (sessions not shared between workers)")
    session_service = InMemorySessionService()

# Create runner
runner = Runner(
    agent=root_agent,
    app_name=root_agent.name,
    session_service=session_service
)


async def ensure_session(user_id: str, session_id: str):
    """Ensure session exists, create if not."""
    try:
        return await session_service.get_session(
            app_name=root_agent.name,
            user_id=user_id,
            session_id=session_id
        )
    except Exception:
        return await session_service.create_session(
            app_name=root_agent.name,
            user_id=user_id,
            session_id=session_id
        )


def turn_number(session) -> int:
    """1 for the visitor's first question in this session, 2 for the next, and so on."""
    events = getattr(session, "events", None) or []
    return 1 + sum(1 for e in events if getattr(e, "author", None) == "user")


def question_text(message) -> str:
    return " ".join(p.text for p in message.parts if p.text).strip()


def visitor_country(http_request: Request) -> str:
    # Cloudflare sits in front of the API and stamps the visitor's country
    return (http_request.headers.get("cf-ipcountry") or "").upper()


# ============================================
# Request/Response Models
# ============================================

class MessagePart(BaseModel):
    text: str

class Message(BaseModel):
    role: str = "user"
    parts: list[MessagePart]

class RunRequest(BaseModel):
    user_id: str = "default_user"
    session_id: str | None = None
    new_message: Message
    streaming: bool = False

class SessionCreateRequest(BaseModel):
    user_id: str = "default_user"
    session_id: str | None = None

# ============================================
# Lifespan Management
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"🚀 Starting ADK Agent Server: {root_agent.name}")
    print(f"📡 Ollama API Base: {os.environ.get('OLLAMA_API_BASE', 'not set')}")
    yield
    # Shutdown
    print("👋 Shutting down ADK Agent Server")

# ============================================
# FastAPI Application
# ============================================

app = FastAPI(
    title="Vishal's Portfolio Assistant API",
    description="Personal AI assistant for Vishal Pandey's portfolio - answers questions about his experience, skills, and projects",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# Endpoints
# ============================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "agent": root_agent.name}

@app.post("/sessions")
async def create_session(request: SessionCreateRequest):
    """Create a new session"""
    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"
    
    session = await session_service.create_session(
        app_name=root_agent.name,
        user_id=request.user_id,
        session_id=session_id
    )
    
    return {
        "session_id": session_id,
        "user_id": request.user_id,
        "app_name": root_agent.name
    }

@app.post("/run")
async def run_agent(request: RunRequest, http_request: Request):
    """Run agent and return complete response (non-streaming)"""

    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"

    # Ensure session exists (handles multi-worker scenarios)
    session = await ensure_session(request.user_id, session_id)
    turn = turn_number(session)
    
    # Prepare message
    content = types.Content(
        role=request.new_message.role,
        parts=[types.Part(text=part.text) for part in request.new_message.parts]
    )
    
    # Collect all events
    events = []
    final_response = None
    
    try:
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=session_id,
            new_message=content
        ):
            events.append({
                "author": getattr(event, 'author', None),
                "content": event.content.model_dump() if event.content else None,
                "is_final": event.is_final_response()
            })
            
            if event.is_final_response() and event.content and event.content.parts:
                final_response = event.content.parts[0].text
    except ValueError as e:
        if "Session not found" in str(e):
            # Session was lost, recreate and retry
            await ensure_session(request.user_id, session_id)
            async for event in runner.run_async(
                user_id=request.user_id,
                session_id=session_id,
                new_message=content
            ):
                events.append({
                    "author": getattr(event, 'author', None),
                    "content": event.content.model_dump() if event.content else None,
                    "is_final": event.is_final_response()
                })
                
                if event.is_final_response() and event.content and event.content.parts:
                    final_response = event.content.parts[0].text
        else:
            raise

    notify.chat_turn(question_text(request.new_message), final_response or "", session_id, turn,
                     visitor_country(http_request))

    return {
        "session_id": session_id,
        "response": final_response,
        "events": events
    }

class AnswerTracker:
    """Rebuilds the agent's answer from a streamed run, for the WhatsApp alert.

    In SSE mode ADK yields partial events (text deltas) and then a non-partial event
    carrying the whole text; the last non-partial text is the answer the visitor saw.
    """

    def __init__(self):
        self.full = ""
        self.partial = ""
        self.finished = False

    def see(self, event) -> None:
        text = "".join(p.text for p in (event.content.parts if event.content else []) or []
                       if getattr(p, "text", None))
        if text and getattr(event, "author", None) != "user":
            if getattr(event, "partial", False):
                self.partial += text
            else:
                self.full, self.partial = text, ""
        if event.is_final_response():
            self.finished = True

    @property
    def answer(self) -> str:
        return self.full or self.partial


@app.post("/run_sse")
async def run_agent_sse(request: RunRequest, http_request: Request):
    """Run agent with Server-Sent Events streaming"""

    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"
    country = visitor_country(http_request)

    # Prepare message
    content = types.Content(
        role=request.new_message.role,
        parts=[types.Part(text=part.text) for part in request.new_message.parts]
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events"""
        import json

        # Always ensure session exists inside the generator
        # This handles multi-worker scenarios where session might not exist in this worker
        session = await ensure_session(request.user_id, session_id)
        turn = turn_number(session)
        tracker = AnswerTracker()

        # Enable SSE streaming mode for token-by-token streaming
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        def sse(event) -> str:
            tracker.see(event)
            event_data = {
                "author": getattr(event, 'author', None),
                "is_final": event.is_final_response(),
            }

            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        event_data["text"] = part.text

            return f"data: {json.dumps(event_data)}\n\n"

        try:
            try:
                async for event in runner.run_async(
                    user_id=request.user_id,
                    session_id=session_id,
                    new_message=content,
                    run_config=run_config
                ):
                    yield sse(event)
            except ValueError as e:
                if "Session not found" in str(e):
                    # Session was lost between ensure and run, recreate and retry
                    await ensure_session(request.user_id, session_id)
                    async for event in runner.run_async(
                        user_id=request.user_id,
                        session_id=session_id,
                        new_message=content,
                        run_config=run_config
                    ):
                        yield sse(event)
                else:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

            yield "data: [DONE]\n\n"
        finally:
            # Runs on completion and when the visitor closes the tab mid-stream
            notify.chat_turn(question_text(request.new_message), tracker.answer, session_id, turn,
                             country, finished=tracker.finished)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )

# ============================================
# Mount A2A Application (optional)
# ============================================

try:
    from .agent import a2a_app
    from starlette.routing import Mount
    
    # Mount A2A at /a2a path
    app.mount("/a2a", a2a_app)
    print("✅ A2A endpoints mounted at /a2a")
except Exception as e:
    print(f"⚠️ A2A endpoints not available: {e}")

# ============================================
# Run directly for development
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
