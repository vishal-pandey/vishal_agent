"""
Vector Store using pgvector for RAG

This module provides vector storage and retrieval capabilities using PostgreSQL
with the pgvector extension. It supports:
- Document embedding using sentence-transformers
- Similarity search for RAG
- Async operations for production use
"""

import os
from typing import List, Optional, Tuple
import asyncio
import json
from contextlib import asynccontextmanager

import asyncpg
from sentence_transformers import SentenceTransformer


class VectorStore:
    """Vector store using pgvector for document embeddings."""
    
    def __init__(
        self,
        database_url: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        table_name: str = "documents",
        dimension: int = 384
    ):
        """
        Initialize vector store.
        
        Args:
            database_url: PostgreSQL connection URL
            embedding_model: HuggingFace model name for embeddings
            table_name: Name of the table to store vectors
            dimension: Dimension of embedding vectors (384 for all-MiniLM-L6-v2)
        """
        self.database_url = database_url
        self.table_name = table_name
        self.dimension = dimension
        self.pool: Optional[asyncpg.Pool] = None
        
        # Initialize embedding model
        print(f"Loading embedding model: {embedding_model}")
        self.embedding_model = SentenceTransformer(embedding_model)
        print(f"✅ Embedding model loaded (dimension: {self.dimension})")
    
    async def initialize(self):
        """Initialize database connection pool and create tables."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10
            )
            await self.create_tables()
            print(f"✅ Vector store initialized with table: {self.table_name}")
    
    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
    
    async def create_tables(self):
        """Create tables and enable pgvector extension."""
        async with self.pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Create documents table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    embedding vector({self.dimension}),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for vector similarity search
            # Using HNSW (Hierarchical Navigable Small World) for fast approximate search
            try:
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_idx 
                    ON {self.table_name} 
                    USING hnsw (embedding vector_cosine_ops)
                """)
            except Exception as e:
                # Fallback to ivfflat if hnsw not available
                print(f"⚠️ HNSW index failed, using ivfflat: {e}")
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_idx 
                    ON {self.table_name} 
                    USING ivfflat (embedding vector_cosine_ops)
                """)
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for text.
        
        Args:
            text: Input text to embed
            
        Returns:
            List of floats representing the embedding
        """
        embedding = self.embedding_model.encode(text, convert_to_tensor=False)
        return embedding.tolist()
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of input texts
            
        Returns:
            List of embeddings
        """
        embeddings = self.embedding_model.encode(texts, convert_to_tensor=False)
        return embeddings.tolist()
    
    async def add_document(
        self,
        content: str,
        metadata: Optional[dict] = None
    ) -> int:
        """
        Add a single document to the vector store.
        
        Args:
            content: Document content
            metadata: Optional metadata dictionary
            
        Returns:
            Document ID
        """
        if not self.pool:
            await self.initialize()
        
        # Generate embedding
        embedding = self.embed_text(content)
        
        async with self.pool.acquire() as conn:
            doc_id = await conn.fetchval(
                f"""
                INSERT INTO {self.table_name} (content, metadata, embedding)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                content,
                metadata,
                embedding
            )
        
        return doc_id
    
    async def add_documents(
        self,
        contents: List[str],
        metadatas: Optional[List[dict]] = None
    ) -> List[int]:
        """
        Add multiple documents to the vector store.
        
        Args:
            contents: List of document contents
            metadatas: Optional list of metadata dictionaries
            
        Returns:
            List of document IDs
        """
        if not self.pool:
            await self.initialize()
        
        if metadatas is None:
            metadatas = [None] * len(contents)
        
        # Generate embeddings in batch
        embeddings = self.embed_texts(contents)
        
        async with self.pool.acquire() as conn:
            doc_ids = []
            async with conn.transaction():
                for content, metadata, embedding in zip(contents, metadatas, embeddings):
                    # Convert metadata dict to JSON string for JSONB column
                    metadata_json = json.dumps(metadata) if metadata else None
                    
                    doc_id = await conn.fetchval(
                        f"""
                        INSERT INTO {self.table_name} (content, metadata, embedding)
                        VALUES ($1, $2, $3)
                        RETURNING id
                        """,
                        content,
                        metadata_json,
                        embedding
                    )
                    doc_ids.append(doc_id)
        
        return doc_ids
    
    async def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter_metadata: Optional[dict] = None
    ) -> List[Tuple[str, dict, float]]:
        """
        Search for similar documents using cosine similarity.
        
        Args:
            query: Search query
            k: Number of results to return
            filter_metadata: Optional metadata filter (not implemented yet)
            
        Returns:
            List of tuples (content, metadata, similarity_score)
        """
        if not self.pool:
            await self.initialize()
        
        # Generate query embedding
        query_embedding = self.embed_text(query)
        
        async with self.pool.acquire() as conn:
            # Use cosine similarity (1 - cosine_distance)
            rows = await conn.fetch(
                f"""
                SELECT 
                    content,
                    metadata,
                    1 - (embedding <=> $1) as similarity
                FROM {self.table_name}
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                query_embedding,
                k
            )
        
        results = [
            (row['content'], row['metadata'] or {}, float(row['similarity']))
            for row in rows
        ]
        
        return results
    
    async def delete_all(self):
        """Delete all documents from the vector store."""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            await conn.execute(f"DELETE FROM {self.table_name}")
        
        print(f"✅ Deleted all documents from {self.table_name}")
    
    async def count_documents(self) -> int:
        """Count total documents in the vector store."""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")
        
        return count


# Singleton instance
_vector_store: Optional[VectorStore] = None


def get_vector_store(database_url: Optional[str] = None) -> VectorStore:
    """
    Get or create vector store singleton.
    
    Args:
        database_url: PostgreSQL connection URL (uses DATABASE_URL env var if not provided)
        
    Returns:
        VectorStore instance
    """
    global _vector_store
    
    if _vector_store is None:
        if database_url is None:
            database_url = os.environ.get("DATABASE_URL")
            if not database_url:
                raise ValueError(
                    "DATABASE_URL environment variable must be set for vector store"
                )
        
        _vector_store = VectorStore(database_url)
    
    return _vector_store


async def initialize_vector_store(database_url: Optional[str] = None):
    """Initialize the vector store (call at startup)."""
    store = get_vector_store(database_url)
    await store.initialize()
    return store
