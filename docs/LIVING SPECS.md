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
- `load_to_neo4j.py` run against the cleaned `extractions.jsonl`: AuraDB now holds 225 Chunk nodes, 265 Entity nodes, 3 Filing nodes (2023/2024/2025), 972 MENTIONS edges, and 584 RELATED_TO edges, with 0 orphaned entities.
- Embedding/indexing ran successfully for current corpus: `build_pgvector_index.py` (using local `sentence-transformers`, `all-MiniLM-L6-v2`, 384-dim) has embedded and indexed the same 225 substantive 2023-2025 chunks into Supabase pgvector (`sec_chunk_embeddings` table). Originally indexed all 390 substantive chunks (all 5 years) since local embedding isn't quota-bound; rescoped to match Neo4j's 2023-2025 window and re-run with `RESET_TABLE=true` once the corpus mismatch was identified as a structural risk for Phase 3/4 (a vector hit from a year with no graph coverage would break the hybrid-answer premise).
- Shared library `src/kgrag/` added (`pip install -e .`): `db.py` (one home for Postgres/Neo4j connections), `entity_keys.py` (the `slugify` + post-merge canonical-key remap, single source of truth), `retrieval.py` (`vector_search()` — the primitive Phase 3/4 will import). Scripts no longer each re-implement DSN handling.
- **Entity linkage (Phase 2):** `sec_chunk_embeddings` now has an `entity_keys TEXT[]` column + GIN index. `scripts/backfill_entity_keys.py` (idempotent) added and populated it for all 225 rows from `extractions.jsonl`, remapping pre-merge entity names to their post-merge canonical `entity_key` so the vector side matches the live graph. Verified: 265 distinct keys on vector rows, every one exists as a Neo4j `Entity` (exact match to the graph's 265 nodes). `build_pgvector_index.py` updated so fresh rebuilds populate the column too.
- **Vector index switched `ivfflat` → `hnsw`** (`m=16, ef_construction=64`) during the backfill — the `ivfflat lists=100` over 225 rows was pathological (~2 rows/list). Query-time `hnsw.ef_search` is pinned (default 64) in `retrieval.py` so recall is reproducible.
- **Retrieval quality measured (Phase 2 gate):** 24 hand-labeled queries in `data/eval/retrieval_queries.jsonl` (12 single-hop, 3 aggregation, 6 multi-hop, 3 out-of-scope). `scripts/eval_retrieval.py` computes recall@k / hit@k / MRR by category and writes a timestamped baseline to `data/eval/results/`. First run (HNSW, ef_search=64): overall **hit@5 0.90, recall@5 0.54, MRR 0.78** across 21 scored queries; single-hop hit@5 0.83, multi-hop hit@5 1.0. Two single-hop misses (year-specific DMA deadline, FY2024 dividend) and out-of-scope queries scoring up to 0.69 (overlapping in-scope range) are noted as Phase 3 routing concerns — a naive score threshold won't cleanly gate out-of-scope.
- Ontology constrained: `entity_type`/`relation_type` are now a closed set (8 entity types, 20 relation types + `RELATED_TO` catch-all), enforced via `Literal[...]` in `extract_sec_entities.py`'s Pydantic schema. Existing `extractions.jsonl` was remapped to the closed set (`scripts/remap_ontology.py`) and reloaded into Neo4j — no re-extraction needed, since only type labels changed, not entity names.
- Entity resolution done for high-confidence cases: name-embedding similarity search over all 279 entities found 101 candidate duplicate pairs (`scripts/find_entity_merge_candidates.py`); each was reviewed with a merge/don't-merge recommendation and reasoning (`scripts/apply_merge_recommendations.py`, full detail in `data/processed/sec_filings/entity_merge_candidates.csv`) before anything was applied. Most candidates were false positives from shared vocabulary (e.g. different iPhone models, different fiscal years, different ASU document numbers). 13 genuine duplicate groups (14 entities) were merged into their canonical entity after user approval (`scripts/apply_entity_merges.py`) — edges redirected, aliases merged, duplicates deleted. Verified: entity count dropped from 279 to 265 (exactly matching the 14 merges), relationship counts unchanged, no orphaned nodes. A full Neo4j backup was taken before any merge (`data/backups/`). Resolution is still exact-match by default for new entities going forward — this pass cleaned up existing duplicates, it didn't change `load_to_neo4j.py`'s ingestion-time matching logic.

**Phase 1 is now complete.** Both previously-open items (ontology, entity resolution) are done and verified in the live graph.

**Phase 2 is now complete.** Both previously-open items are done:

- Entity linkage: `sec_chunk_embeddings.entity_keys` column, backfilled and verified against the graph.
- Retrieval quality measured: labeled query set + recall@k baseline committed under `data/eval/`.

The recall@k numbers set the vector-only baseline that Phase 5 will compare the hybrid system against. Phase 3 (question routing) can now begin; the eval also surfaced a concrete routing concern (out-of-scope queries are not cleanly separable by similarity score alone).
