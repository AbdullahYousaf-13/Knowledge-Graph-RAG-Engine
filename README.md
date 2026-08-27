# Knowledge Graph RAG Engine

A hybrid knowledge-graph + vector RAG system over SEC filings (Apple 10-Ks). It answers
multi-hop questions by combining graph retrieval (Neo4j) and vector retrieval (pgvector)
and returning citations for every claim.

## Stack

Python · Neo4j / Cypher (AuraDB) · PostgreSQL + pgvector (Supabase) · `sentence-transformers`
local embeddings · Gemini API for entity extraction · FastAPI · plain Python, no LangChain.

## Docs

- [`docs/PROJECT_GOAL_AND_PHASES.md`](docs/PROJECT_GOAL_AND_PHASES.md) — goal and the 5-phase plan
- [`docs/TECH_STACK.md`](docs/TECH_STACK.md) — every tool and why
- [`docs/LIVING_SPECS.md`](docs/LIVING_SPECS.md) — current build state
- [`docs/WHAT_WE_DID_AND_WHY.md`](docs/WHAT_WE_DID_AND_WHY.md) — decision log

## Setup

```
pip install -r requirements.txt
pip install -e .          # the src/kgrag/ shared library
cp .env.example .env      # fill in Neo4j + Supabase + Gemini credentials
```
