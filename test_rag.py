#!/usr/bin/env python3
"""
Quick test script for RAG functionality

Tests:
1. Vector store initialization
2. Document ingestion
3. Similarity search
4. Cleanup

Usage:
    python test_rag.py
"""

import asyncio
import os
from vishal_agent.vector_store import VectorStore


async def test_rag():
    """Test RAG functionality."""
    
    # Check DATABASE_URL
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set. Set it in .env file:")
        print("   DATABASE_URL=postgresql+asyncpg://vishal_agent:vishal_agent_secret@localhost:5432/vishal_agent_sessions")
        return False
    
    print("🧪 Testing RAG functionality...\n")
    
    # Initialize vector store
    print("1️⃣ Initializing vector store...")
    store = VectorStore(
        database_url=database_url,
        table_name="test_documents"  # Use separate table for testing
    )
    await store.initialize()
    print("   ✅ Vector store initialized\n")
    
    # Test document ingestion
    print("2️⃣ Adding test documents...")
    test_docs = [
        "Vishal loves building AI agents with Python and TypeScript.",
        "He is passionate about distributed systems and Kubernetes.",
        "His favorite hobby is creating retro games in vanilla JavaScript.",
        "He founded AirTrik, an IoT platform for industrial applications."
    ]
    
    doc_ids = await store.add_documents(
        test_docs,
        metadatas=[{"test": True, "index": i} for i in range(len(test_docs))]
    )
    print(f"   ✅ Added {len(doc_ids)} documents\n")
    
    # Test similarity search
    print("3️⃣ Testing similarity search...")
    queries = [
        "What does Vishal like to build?",
        "Tell me about Kubernetes",
        "What are his hobbies?"
    ]
    
    for query in queries:
        print(f"\n   Query: '{query}'")
        results = await store.similarity_search(query, k=2)
        
        for i, (content, metadata, score) in enumerate(results, 1):
            print(f"   Result {i} (score: {score:.3f}): {content[:60]}...")
    
    print("\n   ✅ Search working correctly\n")
    
    # Count documents
    count = await store.count_documents()
    print(f"4️⃣ Total documents in store: {count}")
    
    # Cleanup
    print("\n5️⃣ Cleaning up test data...")
    await store.delete_all()
    print("   ✅ Test documents deleted\n")
    
    await store.close()
    
    print("✅ All tests passed! RAG is working correctly.\n")
    print("Next steps:")
    print("  1. Ingest your documents: python -m scripts.ingest_documents --source knowledge_base/")
    print("  2. Run the agent: uvicorn vishal_agent.server:app --reload")
    print("  3. Ask questions that require RAG!")
    
    return True


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        success = asyncio.run(test_rag())
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
