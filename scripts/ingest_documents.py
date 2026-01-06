"""
Document Ingestion Script for RAG

This script chunks and embeds documents into the pgvector database.
Supports various document formats and provides utilities for managing the knowledge base.

Usage:
    # Ingest text files
    python -m scripts.ingest_documents --source docs/ --pattern "*.md"
    
    # Ingest from a single file
    python -m scripts.ingest_documents --file path/to/document.txt
    
    # Clear all documents and re-ingest
    python -m scripts.ingest_documents --clear --source docs/
    
    # Check document count
    python -m scripts.ingest_documents --count
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path
from typing import List, Tuple
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vishal_agent.vector_store import get_vector_store, initialize_vector_store
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks.
    
    Args:
        text: Input text to chunk
        chunk_size: Maximum characters per chunk
        overlap: Number of overlapping characters between chunks
        
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence ending in the last 100 characters
            last_period = text[max(start, end - 100):end].rfind('.')
            last_newline = text[max(start, end - 100):end].rfind('\n')
            
            break_point = max(last_period, last_newline)
            if break_point > 0:
                end = max(start, end - 100) + break_point + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
    
    return chunks


def read_file(file_path: Path) -> str:
    """Read content from file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ Error reading {file_path}: {e}")
        return ""


def find_files(source_path: Path, pattern: str = "*.txt") -> List[Path]:
    """
    Find all files matching pattern in source directory.
    
    Args:
        source_path: Directory to search
        pattern: Glob pattern for files
        
    Returns:
        List of file paths
    """
    if source_path.is_file():
        return [source_path]
    
    files = list(source_path.rglob(pattern))
    return sorted(files)


async def ingest_file(
    file_path: Path,
    vector_store,
    chunk_size: int = 500,
    overlap: int = 50
) -> int:
    """
    Ingest a single file into vector store.
    
    Args:
        file_path: Path to file
        vector_store: VectorStore instance
        chunk_size: Characters per chunk
        overlap: Overlap between chunks
        
    Returns:
        Number of chunks added
    """
    print(f"📄 Processing: {file_path}")
    
    # Read file content
    content = read_file(file_path)
    if not content:
        return 0
    
    # Chunk the content
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    print(f"  → Split into {len(chunks)} chunks")
    
    # Prepare metadata
    metadatas = [
        {
            "source": str(file_path),
            "chunk_index": i,
            "total_chunks": len(chunks),
            "file_name": file_path.name
        }
        for i in range(len(chunks))
    ]
    
    # Add to vector store
    doc_ids = await vector_store.add_documents(chunks, metadatas)
    print(f"  ✅ Added {len(doc_ids)} chunks to vector store")
    
    return len(doc_ids)


async def ingest_documents(
    source_path: Path,
    pattern: str = "*.txt",
    chunk_size: int = 500,
    overlap: int = 50,
    clear: bool = False
):
    """
    Ingest documents from source directory.
    
    Args:
        source_path: Directory or file path
        pattern: File pattern to match
        chunk_size: Characters per chunk
        overlap: Overlap between chunks
        clear: Clear existing documents before ingesting
    """
    # Initialize vector store
    print("🔧 Initializing vector store...")
    vector_store = await initialize_vector_store()
    
    # Clear if requested
    if clear:
        print("🗑️ Clearing existing documents...")
        await vector_store.delete_all()
    
    # Find files
    files = find_files(source_path, pattern)
    print(f"\n📚 Found {len(files)} files matching pattern: {pattern}")
    
    if not files:
        print("⚠️ No files found!")
        return
    
    # Ingest each file
    total_chunks = 0
    for file_path in files:
        chunks_added = await ingest_file(
            file_path,
            vector_store,
            chunk_size=chunk_size,
            overlap=overlap
        )
        total_chunks += chunks_added
    
    # Summary
    total_docs = await vector_store.count_documents()
    print(f"\n✅ Ingestion complete!")
    print(f"   Added: {total_chunks} new chunks")
    print(f"   Total: {total_docs} documents in vector store")
    
    await vector_store.close()


async def search_documents(query: str, k: int = 4):
    """
    Search for documents similar to query.
    
    Args:
        query: Search query
        k: Number of results
    """
    print(f"🔍 Searching for: {query}")
    print(f"   Top {k} results\n")
    
    # Initialize vector store
    vector_store = await initialize_vector_store()
    
    # Search
    results = await vector_store.similarity_search(query, k=k)
    
    # Display results
    for i, (content, metadata, score) in enumerate(results, 1):
        print(f"--- Result {i} (similarity: {score:.4f}) ---")
        print(f"Source: {metadata.get('source', 'unknown')}")
        print(f"Content preview: {content[:200]}...")
        print()
    
    await vector_store.close()


async def count_documents():
    """Count documents in vector store."""
    vector_store = await initialize_vector_store()
    count = await vector_store.count_documents()
    print(f"📊 Total documents in vector store: {count}")
    await vector_store.close()


async def clear_documents():
    """Clear all documents from vector store."""
    vector_store = await initialize_vector_store()
    await vector_store.delete_all()
    await vector_store.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest documents into vector store for RAG"
    )
    
    parser.add_argument(
        "--source",
        type=str,
        help="Source directory or file path"
    )
    
    parser.add_argument(
        "--file",
        type=str,
        help="Single file to ingest"
    )
    
    parser.add_argument(
        "--pattern",
        type=str,
        default="*.txt",
        help="File pattern to match (default: *.txt)"
    )
    
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Characters per chunk (default: 500)"
    )
    
    parser.add_argument(
        "--overlap",
        type=int,
        default=50,
        help="Overlap between chunks (default: 50)"
    )
    
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing documents before ingesting"
    )
    
    parser.add_argument(
        "--count",
        action="store_true",
        help="Count documents in vector store"
    )
    
    parser.add_argument(
        "--search",
        type=str,
        help="Search for similar documents"
    )
    
    parser.add_argument(
        "--k",
        type=int,
        default=4,
        help="Number of search results (default: 4)"
    )
    
    parser.add_argument(
        "--clear-all",
        action="store_true",
        help="Clear all documents from vector store"
    )
    
    args = parser.parse_args()
    
    # Check DATABASE_URL
    if not os.environ.get("DATABASE_URL"):
        print("❌ Error: DATABASE_URL environment variable not set")
        print("   Set it in .env file or export it:")
        print("   export DATABASE_URL='postgresql://user:pass@localhost/dbname'")
        sys.exit(1)
    
    # Execute action
    if args.count:
        asyncio.run(count_documents())
    elif args.clear_all:
        asyncio.run(clear_documents())
    elif args.search:
        asyncio.run(search_documents(args.search, args.k))
    elif args.source or args.file:
        source = Path(args.file if args.file else args.source)
        if not source.exists():
            print(f"❌ Error: {source} does not exist")
            sys.exit(1)
        
        asyncio.run(ingest_documents(
            source,
            pattern=args.pattern,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            clear=args.clear
        ))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
