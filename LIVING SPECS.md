# Living Specs

## Project Name

Knowledge Graph RAG Engine

## Current Goal

Build a hybrid knowledge graph RAG system over SEC filings using graph retrieval and vector retrieval.

The system should:

- extract entities and relationships from SEC filings into Neo4j
- build a vector index over the same chunks in pgvector
- route each question to the best retrieval path
- merge graph and vector results into one grounded answer
- return citations for every claim

## Canonical Corpus

Primary source corpus:

- SEC filings from the public EDGAR data API

## Tech Stack

- Python
- FastAPI
- LangChain
- Gemini API
- Neo4j
- Cypher
- PostgreSQL
- pgvector

## Phase 1 Scope

Phase 1 focuses only on ingestion and graph construction.

It includes:

- selecting a small set of SEC filings
- extracting entities and relationships
- validating structured output
- storing nodes and edges in Neo4j
- preserving source chunk references for traceability

It does not include:

- vector retrieval
- routing
- answer generation
- UI work

## Working Rules

- Start with a small corpus first.
- Keep the ontology limited and explicit.
- Use `MERGE` to keep ingestion idempotent.
- Store source document and chunk ids on every extracted relationship.
- Prefer measurable outputs over vague extraction quality claims.

## Current Status

Next step: download a small starter set of SEC filings and build the Phase 1 ingestion pipeline around them.
