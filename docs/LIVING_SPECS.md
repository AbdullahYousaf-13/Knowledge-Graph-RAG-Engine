# Living Specs

_Current state of the build. For the goal and the 5-phase plan see
`PROJECT_GOAL_AND_PHASES.md`; for tool choices and reasoning see `TECH_STACK.md`; for the
supervisor-facing decision log see `WHAT_WE_DID_AND_WHY.md`._

## Snapshot

- **Goal:** hybrid knowledge-graph + vector RAG over SEC filings (see `PROJECT_GOAL_AND_PHASES.md`).
- **Corpus:** Apple 10-K filings. 5 years (2021-2025) downloaded and chunked into 454 chunks
  (`data/processed/sec_filings/chunks.jsonl`); **scoped to 2023-2025 (225 substantive chunks)**
  in both databases so Neo4j and pgvector reason over the same facts. Trim was forced by the
  Gemini free-tier extraction quota; `FILING_YEARS` env var controls the scope.
- **Infra:** AuraDB (Neo4j) and Supabase (Postgres+pgvector) free tiers, live; credentials in
  local `.env` (gitignored).
- **Phases 1 and 2 are complete.** Next: Phase 3 (question routing).

## Known gotchas

- Supabase needs the **session pooler host** (`aws-0-<region>.pooler.supabase.com`), not the
  direct `db.<ref>.supabase.co` host — the direct host is IPv6-only and unreachable from this network.
- Chunk size (2600 chars) was never tuned against retrieval quality — a reasonable default, not a measured choice.
- The retrieval eval set is 24 queries — directional, not statistically tight.

## Phase 1 — complete (extract entities & relationships into Neo4j)

- All 225 substantive 2023-2025 chunks extracted (`extractions.jsonl`), 0 failures. An earlier
  batch of 24 chunks from 2021 was extracted before the trim, then removed and purged from Neo4j.
- **Ontology constrained:** `entity_type`/`relation_type` are a closed set (8 entity types,
  20 relation types + `RELATED_TO` catch-all), enforced via `Literal[...]` in
  `extract_sec_entities.py`. Existing data remapped (`scripts/remap_ontology.py`) and reloaded —
  no re-extraction, since only type labels changed.
- **Entity resolution done for existing data:** name-embedding similarity search over 279 entities
  found 101 candidate pairs (`scripts/find_entity_merge_candidates.py`); each reviewed
  (`scripts/apply_merge_recommendations.py`, detail in
  `data/processed/sec_filings/entity_merge_candidates.csv`). 13 genuine duplicate groups
  (14 entities) merged after user approval (`scripts/apply_entity_merges.py`) — edges redirected,
  aliases merged. Full Neo4j backup taken first. Ingestion-time matching in `load_to_neo4j.py` is
  still exact-match by design; this was a cleanup pass on existing data.
- **Live graph:** 225 Chunk, 265 Entity, 3 Filing nodes (2023/2024/2025), 972 MENTIONS, 584 RELATED_TO edges, 0 orphans.

## Phase 2 — complete (vector index alongside the graph)

- **Index built:** `build_pgvector_index.py` embedded the same 225 chunks
  (`sentence-transformers`, `all-MiniLM-L6-v2`, 384-dim) into Supabase pgvector
  (`sec_chunk_embeddings`). Originally indexed all 5 years; rescoped to 2023-2025 with
  `RESET_TABLE=true` once the corpus mismatch with Neo4j was identified as a Phase 3/4 risk.
- **Shared library `src/kgrag/`** added (`pip install -e .`): `db.py`, `entity_keys.py`
  (`slugify` + post-merge canonical-key remap, single source of truth), `retrieval.py`
  (`vector_search()` — the primitive Phase 3/4 import).
- **Entity linkage:** `sec_chunk_embeddings.entity_keys TEXT[]` column + GIN index.
  `scripts/backfill_entity_keys.py` (idempotent) populated all 225 rows from `extractions.jsonl`,
  remapping pre-merge entity names to their post-merge canonical `entity_key`. Verified: 265
  distinct keys on vector rows, every one exists as a Neo4j `Entity` (exact match to the graph's 265).
- **Vector index switched `ivfflat` → `hnsw`** (`m=16, ef_construction=64`); the `ivfflat lists=100`
  over 225 rows was pathological. Query-time `hnsw.ef_search` pinned (default 64) in `retrieval.py`.
- **Retrieval quality measured (Phase 2 gate):** 24 hand-labeled queries in
  `data/eval/retrieval_queries.jsonl` (12 single-hop, 3 aggregation, 6 multi-hop, 3 out-of-scope).
  `scripts/eval_retrieval.py` computes recall@k / hit@k / MRR by category, writing a timestamped
  baseline to `data/eval/results/`. First run (HNSW, ef_search=64): overall **hit@5 0.90,
  recall@5 0.54, MRR 0.78**; single-hop hit@5 0.83, multi-hop hit@5 1.0. This is the vector-only
  baseline Phase 5 compares the hybrid system against.

## Next: Phase 3 — question routing

- Route each question to graph retrieval, vector retrieval, or both. Plain Python + Gemini
  structured output, parameterized Cypher (no model-written queries).
- **Carried over from the Phase 2 eval:** out-of-scope queries scored up to ~0.69 cosine
  similarity, overlapping the in-scope range — a naive similarity threshold won't cleanly gate
  out-of-scope questions. `kgrag.retrieval.vector_search(entity_keys=[...])` is ready for the router.
