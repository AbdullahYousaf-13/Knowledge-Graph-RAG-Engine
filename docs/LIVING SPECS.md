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
- Gemini API (entity extraction only)
- sentence-transformers (local embeddings, `all-MiniLM-L6-v2`)
- Neo4j (hosted on AuraDB free tier)
- Cypher
- PostgreSQL + pgvector (hosted on Supabase free tier)

## Hosting Decisions

- Neo4j and Postgres/pgvector are cloud-hosted (AuraDB free tier, Supabase free tier), not run locally.
- Reason: local machine has 8GB RAM, no GPU, and very limited free disk space, so local Neo4j/Postgres/Docker installs are not viable.
- Chunk embeddings use a local `sentence-transformers` model instead of the Gemini embedding API, since this is a free-internship project with no API billing budget. CPU-only inference is fine at this corpus size (a few hundred chunks).
- Gemini free tier is still used for entity extraction (needs LLM reasoning), resumed daily as the quota resets. Corpus may be trimmed to 2-3 filing years if extraction is taking too many days.

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

- 5 years of Apple 10-K filings (2021-2025) downloaded, chunked into 454 chunks (`data/processed/sec_filings/chunks.jsonl`).
- Corpus trimmed to 3 filing years (2023-2025) for **both** entity extraction and vector indexing, so Neo4j and pgvector reason over the same underlying facts. `extract_sec_entities.py` and `build_pgvector_index.py` both read `FILING_YEARS` (default `2023,2024,2025`) to scope which chunks they process; `chunks.jsonl` still has all 5 years on disk, but only the 2023-2025 subset is loaded into either database.
- AuraDB (Neo4j) and Supabase (Postgres+pgvector) free-tier instances are live; credentials in local `.env` (gitignored). Supabase requires the session pooler host (`aws-0-<region>.pooler.supabase.com`), not the direct `db.<ref>.supabase.co` host, since the direct host is IPv6-only and unreachable from this network.
- Entity extraction ran successfully for the trimmed scope: all 225 substantive 2023-2025 chunks extracted (`extractions.jsonl`), 0 failures. An earlier batch of 24 chunks from 2021 was extracted before the trim, then removed from `extractions.jsonl`/progress and purged from Neo4j once the scope narrowed, since none of those 89 entities overlapped with 2023-2025 data.
- `load_to_neo4j.py` run against the cleaned `extractions.jsonl`: AuraDB now holds 225 Chunk nodes, 279 Entity nodes, 3 Filing nodes (2023/2024/2025), 972 MENTIONS edges, and 584 RELATED_TO edges, with 0 orphaned entities.
- Embedding/indexing ran successfully for current corpus: `build_pgvector_index.py` (using local `sentence-transformers`, `all-MiniLM-L6-v2`, 384-dim) has embedded and indexed the same 225 substantive 2023-2025 chunks into Supabase pgvector (`sec_chunk_embeddings` table). Originally indexed all 390 substantive chunks (all 5 years) since local embedding isn't quota-bound; rescoped to match Neo4j's 2023-2025 window and re-run with `RESET_TABLE=true` once the corpus mismatch was identified as a structural risk for Phase 3/4 (a vector hit from a year with no graph coverage would break the hybrid-answer premise).

**Phase 1 and Phase 2 are NOT fully done.** The pipelines above ran successfully and produced working data, but against this project's own Phase 1/2 checklist (`PROJECT_GOAL_AND_PHASES.md`), 4 items remain open:

- No constrained ontology — `entity_type`/`relation_type` are free-text, not a closed set.
- Entity resolution is exact-match only — no embedding-similarity merging, likely produces duplicate nodes for the same real entity mentioned differently across chunks.
- No `entity_ids` column in pgvector — vector rows aren't linked back to the entities they mention.
- No retrieval quality measurement — no recall@k, no labeled query set, despite the spec explicitly saying to measure retrieval quality before building routing logic.

Full reasoning and better alternatives for each item: `docs/WHAT_WE_DID_AND_WHY.md`. Do not start Phase 3 (question routing) until at minimum the retrieval-quality measurement is done — building a router on top of unmeasured retrieval is exactly what the spec warns against.
