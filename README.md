# Knowledge Graph RAG Engine

## What I am building

This project is a hybrid knowledge graph RAG system over SEC filings.

The project goal is to answer multi-hop questions by combining graph retrieval and vector retrieval with citations.

### Stack

- Python
- Neo4j (AuraDB free tier)
- LangChain
- Gemini API (entity extraction)
- sentence-transformers (local embeddings)
- pgvector + PostgreSQL (Supabase free tier)
- FastAPI
