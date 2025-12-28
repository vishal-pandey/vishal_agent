"""
Production ASGI Server for ADK Agent

This module creates a production-ready FastAPI application that exposes:
1. /run - Non-streaming agent execution
2. /run_sse - Streaming agent execution (SSE)
3. /a2a/* - A2A protocol endpoints

For production deployment with multiple workers:
    gunicorn vishal_agent.server:app -w 4 -k uvicorn.workers.UvicornWorker

For development:
    uvicorn vishal_agent.server:app --reload
"""

import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from .agent import root_agent

# ============================================
# Session Management
# ============================================

# Use in-memory sessions (for production, consider Redis or database-backed sessions)
session_service = InMemorySessionService()

# Create runner
runner = Runner(
    agent=root_agent,
    app_name=root_agent.name,
    session_service=session_service
)

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
async def run_agent(request: RunRequest):
    """Run agent and return complete response (non-streaming)"""
    
    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"
    
    # Ensure session exists
    try:
        await session_service.get_session(
            app_name=root_agent.name,
            user_id=request.user_id,
            session_id=session_id
        )
    except:
        await session_service.create_session(
            app_name=root_agent.name,
            user_id=request.user_id,
            session_id=session_id
        )
    
    # Prepare message
    content = types.Content(
        role=request.new_message.role,
        parts=[types.Part(text=part.text) for part in request.new_message.parts]
    )
    
    # Collect all events
    events = []
    final_response = None
    
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
    
    return {
        "session_id": session_id,
        "response": final_response,
        "events": events
    }

@app.post("/run_sse")
async def run_agent_sse(request: RunRequest):
    """Run agent with Server-Sent Events streaming"""
    
    session_id = request.session_id or f"session-{uuid.uuid4().hex[:8]}"
    
    # Ensure session exists
    try:
        await session_service.get_session(
            app_name=root_agent.name,
            user_id=request.user_id,
            session_id=session_id
        )
    except:
        await session_service.create_session(
            app_name=root_agent.name,
            user_id=request.user_id,
            session_id=session_id
        )
    
    # Prepare message
    content = types.Content(
        role=request.new_message.role,
        parts=[types.Part(text=part.text) for part in request.new_message.parts]
    )
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events"""
        import json
        
        # Enable SSE streaming mode for token-by-token streaming
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)
        
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=session_id,
            new_message=content,
            run_config=run_config
        ):
            event_data = {
                "author": getattr(event, 'author', None),
                "is_final": event.is_final_response(),
            }
            
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        event_data["text"] = part.text
            
            yield f"data: {json.dumps(event_data)}\n\n"
        
        yield "data: [DONE]\n\n"
    
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
