# Tech Stack — Locked

What we are using throughout this project.

## Core

| Category | Technology |
|---|---|
| Language | Python |
| API Framework | FastAPI |

## Knowledge Graph

| Category | Technology |
|---|---|
| Graph Database | Neo4j (hosted on AuraDB, free tier) |
| Query Language | Cypher |

## Vector Search

| Category | Technology |
|---|---|
| Database | PostgreSQL (hosted on Supabase, free tier) |
| Vector Extension | pgvector |
| Vector Index | HNSW |
| Embedding Model | sentence-transformers (`all-MiniLM-L6-v2`), run locally |

## LLM

| Category | Technology |
|---|---|
| Provider | Google Gemini API (free tier) |
| Output Format | Structured JSON output, schema-validated |

## Orchestration

| Category | Technology |
|---|---|
| Framework | None — plain Python throughout |
| LLM calls | Google's official `google-genai` SDK, called directly |
| Graph database calls | Official `neo4j` Python driver, called directly |
| Vector database calls | `psycopg` (Postgres driver) + `pgvector` Python package, called directly |

---