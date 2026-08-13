# Tech Stack and Requirements

## Tech Stack

### Core backend

- Python
- FastAPI
- LangChain
- Gemini API

### Knowledge graph

- Neo4j
- Cypher

### Vector search

- pgvector
- PostgreSQL

### Retrieval and orchestration

- Entity extraction and schema validation
- Question routing logic
- Citation validation
- Hybrid answer assembly

### Evaluation and benchmarking

- Labeled question sets
- Accuracy measurement by hop count
- Latency tracking
- Cost tracking

## Functional Requirements

- Extract entities and relationships from a real document corpus.
- Store graph data in Neo4j with source chunk references.
- Store embeddings for the same chunks in pgvector.
- Resolve entity duplicates so one real-world entity maps to one node.
- Route questions to graph retrieval, vector retrieval, or both.
- Return answers with citations tied to retrieved evidence.
- Compare performance against a vector-only baseline.

## Non-Functional Requirements

- The ingestion pipeline should be idempotent.
- Retrieval should be measurable before routing is added.
- Graph queries should be parameterized, not generated as raw Cypher by the model.
- Every answer should be grounded in retrievable source data.
- The system should support benchmarking and repeatable evaluation.

## Data Requirements

- A real corpus with meaningful relationships.
- Documents that can be chunked into traceable segments.
- Enough labeled questions to test single-hop, multi-hop, and out-of-scope queries.
- Metadata for each chunk, including document id and source reference.

## Expected Outputs

- A Neo4j knowledge graph
- A pgvector-backed embedding index
- A FastAPI endpoint for question answering
- Citation-backed answers
- A benchmark table comparing hybrid RAG vs vector-only RAG

## Optional Dependencies

- Docker for local development
- API client tooling for Gemini integration if needed
- Monitoring or logging tools for debugging and performance tracking
