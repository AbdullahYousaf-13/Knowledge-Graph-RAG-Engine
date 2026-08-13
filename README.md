# Knowledge Graph RAG Engine

## What I am building

This project is a hybrid knowledge graph RAG system for enterprise data.

The goal is to answer questions that need more than simple vector search, especially multi-hop questions that require following relationships between entities across documents.

### Core idea

- Extract entities and relationships from a real document corpus into Neo4j.
- Build a vector index over the same chunks in pgvector.
- Route each question to the best retrieval path, graph or vector search.
- Merge both sources into one grounded answer with citations.
- Benchmark the system against a vector-only baseline and report the improvement.

### Why this matters

This is not just a basic RAG demo. It is meant to show that I can build retrieval systems that handle enterprise data, relationship-heavy queries, and source-backed answers with measurable results.

### Expected stack

- Python
- Neo4j
- LangChain
- Claude API
- pgvector
- FastAPI
