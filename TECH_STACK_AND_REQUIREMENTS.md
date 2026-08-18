# Tech Stack and Requirements

## Tech Stack

### Core backend

- Python
- FastAPI
- LangChain
- Gemini API (entity extraction only; free tier, no billing)
- sentence-transformers (local embeddings, `all-MiniLM-L6-v2`)

### Knowledge graph

- Neo4j, hosted on AuraDB free tier
- Cypher

### Vector search

- pgvector
- PostgreSQL, hosted on Supabase free tier

### Retrieval and orchestration

- Entity extraction and schema validation
- Question routing logic
- Citation validation
- Hybrid answer assembly

## Functional Requirements

- Extract entities and relationships from SEC filings.
- Store graph data in Neo4j with source chunk references.
- Store embeddings for the same chunks in pgvector.
- Resolve entity duplicates so one real-world entity maps to one node.
- Route questions to graph retrieval, vector retrieval, or both.
- Return answers with citations tied to retrieved evidence.
- Compare performance against a vector-only baseline.

## Non-Functional Requirements

- The ingestion pipeline should be idempotent.
- Graph queries should be parameterized, not generated as raw Cypher by the model.
- Every answer should be grounded in retrievable source data.

## Data Requirements

- A small corpus of SEC filings with meaningful relationships. Currently scoped to 3 filing years (2023-2025) for entity extraction, trimmed down from 5 years (2021-2025) due to Gemini free-tier quota limits; vector indexing still covers all 5 years since it isn't quota-bound.
- Documents that can be chunked into traceable segments.
- Enough labeled questions to test single-hop, multi-hop, and out-of-scope queries.
- Metadata for each chunk, including document id and source reference.

## Expected Outputs

- A Neo4j knowledge graph
- A pgvector-backed embedding index
- A FastAPI endpoint for question answering
- Citation-backed answers

## Optional Dependencies

- API client tooling for Gemini integration if needed
- Monitoring or logging tools for debugging and performance tracking

## Constraints

- Development machine has 8GB RAM, no GPU, and very limited free disk space, so Neo4j and Postgres run on cloud free tiers instead of locally, and embeddings run on a small local CPU model instead of a paid API.
- No budget for paid API usage (free internship project). All external services must stay on free tiers.
