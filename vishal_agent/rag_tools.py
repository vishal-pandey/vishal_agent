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
    Retrieve relevant context from the knowledge base using vector similarity search.
    
    Use this tool when you need additional information that might be in the knowledge base.
    This searches through documents that have been ingested into the vector database.
    
    Args:
        query: The search query to find relevant documents
        num_results: Number of relevant documents to retrieve (default: 3)
    
    Returns:
        Relevant context from the knowledge base, or a message if nothing is found
    """
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
Retrieve relevant context from the knowledge base using vector similarity search.

Use this tool when:
- The user asks about topics that might be in additional documents
- You need more detailed information beyond your base knowledge
- You want to provide citations from specific sources

Do NOT use this tool for:
- Questions about Vishal's basic info (experience, skills, contact) - you already know that
- General conversation or greetings
- Questions you can already answer confidently
"""
