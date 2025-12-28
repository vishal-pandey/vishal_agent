"""
ADK Agent with Ollama Llama 3.2 via LiteLLM

A simple helpful assistant that runs locally using Ollama.
Supports both ADK web interface and A2A protocol.
"""

import os
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Ollama - use ollama_chat provider for better tool support
# The environment variable is required for LiteLLM to find Ollama
os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")

# Model constant - using ollama_chat provider as recommended by ADK docs
MODEL = "ollama_chat/llama3.2:latest"

# ============================================
# Create the ADK Agent
# ============================================

root_agent = Agent(
    name="llama_assistant",
    model=LiteLlm(model=MODEL),
    description="A helpful AI assistant powered by Llama 3.2 running locally via Ollama.",
    instruction="""You are a helpful AI assistant running on Llama 3.2 locally via Ollama.

You provide clear, accurate, and helpful responses to user questions.
Be concise but thorough in your answers.
If you don't know something, say so honestly.
""",
)

# ============================================
# A2A Protocol Support
# ============================================

# This creates an A2A-compatible ASGI app that can be served via uvicorn
# The agent card is auto-generated from the agent's name, description, etc.
def create_a2a_app(port: int = 8001):
    """Create an A2A application for this agent.
    
    Usage:
        uvicorn vishal_agent.agent:a2a_app --host localhost --port 8001
    """
    from google.adk.a2a.utils.agent_to_a2a import to_a2a
    from a2a.types import AgentCard, AgentCapabilities
    
    # Create agent card with streaming enabled
    agent_card = AgentCard(
        name=root_agent.name,
        description=root_agent.description,
        url=f"http://localhost:{port}",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=False,
        ),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[],
    )
    
    return to_a2a(root_agent, port=port, agent_card=agent_card)

# Create the A2A app instance for uvicorn
a2a_app = create_a2a_app()
