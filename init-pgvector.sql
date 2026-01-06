-- Initialize pgvector extension
-- This script runs automatically when the PostgreSQL container starts for the first time

-- Enable the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Log success
DO $$
BEGIN
  RAISE NOTICE 'pgvector extension enabled successfully';
END $$;
