"""
RAG Tools for ADK Agent

Provides retrieval-augmented generation tools for the agent to search
through the vector database and retrieve relevant context.
"""

import os
from typing import Optional

# Import vector store - will be initialized lazily
_vector_store = None


def get_vector_store_instance():
    """Get or initialize vector store singleton."""
    global _vector_store
    
    if _vector_store is None:
        from vishal_agent.vector_store import get_vector_store
        database_url = os.environ.get("DATABASE_URL")
        
        if not database_url:
            raise ValueError(
                "DATABASE_URL must be set to use RAG retrieval. "
                "The agent will work without RAG if this tool is not called."
            )
        
        _vector_store = get_vector_store(database_url)
    
    return _vector_store


async def retrieve_context(
    query: str,
    num_results: int = 3
) -> str:
    """
    Search the knowledge base for additional information about a specific topic.
    
    ONLY use this tool when:
    - User asks about specific technical details, projects, or documents not in your base knowledge
    - User explicitly asks to search for something
    - You need detailed information about a particular topic
    
    DO NOT use this tool for:
    - Simple greetings like "hi", "hello", "hey"
    - Questions you can already answer from your instruction/prompt
    - General conversation
    - Questions about Vishal's basic info (you already know that)
    
    Args:
        query: A specific search query describing what information you need. Must be at least 3 characters.
        num_results: Number of documents to retrieve (1-5). Default is 3.
    
    Returns:
        Relevant context from documents, or a message if nothing found.
    """
    # Validate query - don't search with empty or very short queries
    if not query or len(query.strip()) < 3:
        return "Query too short. Please provide a more specific search query."
    
    # Validate num_results
    try:
        num_results = int(num_results)
        num_results = max(1, min(5, num_results))  # Clamp between 1-5
    except (ValueError, TypeError):
        num_results = 3
    
    try:
        # Get vector store
        vector_store = get_vector_store_instance()
        
        # Initialize if needed
        if not vector_store.pool:
            await vector_store.initialize()
        
        # Search for similar documents
        results = await vector_store.similarity_search(query, k=num_results)
        
        if not results:
            return "No relevant information found in the knowledge base for this query."
        
        # Format results
        context_parts = []
        for i, (content, metadata, score) in enumerate(results, 1):
            source = metadata.get('source', 'unknown')
            context_parts.append(
                f"[Source {i}: {source} (relevance: {score:.2f})]\n{content}\n"
            )
        
        context = "\n---\n".join(context_parts)
        
        return f"""Retrieved {len(results)} relevant documents from knowledge base:

{context}

Use this information to answer the user's question. Cite the sources when appropriate."""
        
    except Exception as e:
        return f"Error retrieving context: {str(e)}"


# Tool metadata for ADK
retrieve_context.__name__ = "retrieve_context"
retrieve_context.__doc__ = """
Search the knowledge base for additional documents about a specific topic.

IMPORTANT: Only use this for specific information needs, NOT for:
- Greetings (hi, hello, hey)
- Questions you can answer from your base knowledge
- General conversation

Args:
    query: A specific search term (minimum 3 characters). Be descriptive.
    num_results: How many documents to retrieve (1-5, default 3)
"""
