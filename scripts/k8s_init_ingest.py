"""
Kubernetes Init Container Script - Auto-ingest documents on deployment

This script runs as an init container before the main app starts.
It ingests all documents from knowledge_base into pgvector.

Environment variables required:
- DATABASE_URL: PostgreSQL connection string
- INGEST_MODE: 'replace' (clear and re-ingest) or 'append' (add new docs)
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vishal_agent.vector_store import initialize_vector_store
from scripts.ingest_documents import ingest_documents, chunk_text
from dotenv import load_dotenv

load_dotenv()


async def auto_ingest():
    """Auto-ingest documents on startup."""
    
    print("=" * 60)
    print("🚀 Kubernetes Init Container - Document Ingestion")
    print("=" * 60)
    
    # Check environment
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set - skipping RAG ingestion")
        print("   App will start without RAG capabilities")
        return True
    
    knowledge_base = Path(os.environ.get("KNOWLEDGE_BASE_PATH", "./knowledge_base"))
    ingest_mode = os.environ.get("INGEST_MODE", "replace")  # replace or append
    
    print(f"📂 Knowledge base: {knowledge_base}")
    print(f"🔄 Ingest mode: {ingest_mode}")
    print(f"🗄️  Database: {database_url.split('@')[1] if '@' in database_url else 'configured'}")
    print()
    
    # Check if knowledge_base exists
    if not knowledge_base.exists():
        print(f"⚠️  Knowledge base directory not found: {knowledge_base}")
        print("   Creating empty directory...")
        knowledge_base.mkdir(parents=True, exist_ok=True)
        print("   App will start with base knowledge only (no RAG documents)")
        return True
    
    # Count documents
    doc_files = list(knowledge_base.rglob("*.txt")) + list(knowledge_base.rglob("*.md"))
    if not doc_files:
        print("ℹ️  No documents found in knowledge_base")
        print("   App will start with base knowledge only")
        return True
    
    print(f"📚 Found {len(doc_files)} document(s) to ingest")
    print()
    
    try:
        # Initialize vector store
        print("🔧 Initializing vector store...")
        vector_store = await initialize_vector_store(database_url)
        
        # Check current document count
        current_count = await vector_store.count_documents()
        print(f"   Current documents in DB: {current_count}")
        
        # Clear if replace mode
        if ingest_mode == "replace" and current_count > 0:
            print(f"🗑️  Clearing {current_count} existing documents (replace mode)...")
            await vector_store.delete_all()
            print("   ✅ Cleared")
        
        # Ingest documents
        print(f"📥 Ingesting documents...")
        total_chunks = 0
        
        for doc_file in doc_files:
            print(f"   Processing: {doc_file.name}")
            
            # Read content
            try:
                content = doc_file.read_text(encoding='utf-8')
            except Exception as e:
                print(f"   ⚠️  Error reading {doc_file.name}: {e}")
                continue
            
            # Chunk content
            chunks = chunk_text(content, chunk_size=500, overlap=50)
            
            # Prepare metadata
            metadatas = [
                {
                    "source": str(doc_file.relative_to(knowledge_base)),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "file_name": doc_file.name,
                    "deployment": "k8s-auto-ingest"
                }
                for i in range(len(chunks))
            ]
            
            # Add to vector store
            await vector_store.add_documents(chunks, metadatas)
            total_chunks += len(chunks)
            print(f"      ✅ {len(chunks)} chunks")
        
        # Final count
        final_count = await vector_store.count_documents()
        print()
        print("=" * 60)
        print(f"✅ Ingestion complete!")
        print(f"   New chunks added: {total_chunks}")
        print(f"   Total documents in DB: {final_count}")
        print("=" * 60)
        
        await vector_store.close()
        return True
        
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ Ingestion failed: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        
        # Decide if we should fail the deployment
        fail_on_error = os.environ.get("FAIL_ON_INGEST_ERROR", "false").lower() == "true"
        if fail_on_error:
            print("⛔ FAIL_ON_INGEST_ERROR=true - deployment will fail")
            return False
        else:
            print("⚠️  FAIL_ON_INGEST_ERROR=false - deployment will continue")
            print("   App will start with existing documents in DB")
            return True


if __name__ == "__main__":
    success = asyncio.run(auto_ingest())
    sys.exit(0 if success else 1)
