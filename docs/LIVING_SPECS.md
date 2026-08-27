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
- **Ontology constrained, then trimmed twice to match spec range:** `entity_type`/`relation_type`
  are a closed set enforced via `Literal[...]` in `extract_sec_entities.py`. First pass: 8 entity
  types, 20 relation types + `RELATED_TO`. Second pass (against the original BASWE spec's 8-15
  target): consolidated the thinnest/most-overlapping relation types (`OFFERS`→`PROVIDES`,
  `ISSUED`→`ANNOUNCED`, `DEVELOPS`→`PRODUCES`, `EXPOSED_TO`→`SUBJECT_TO`, `MANAGES`→`RELATED_TO`,
  `SUPPLIES` removed - zero instances ever extracted) down to **8 entity types, 14 relation types +
  `RELATED_TO` = 15 total**. Both passes: `scripts/remap_ontology.py` remaps existing
  `extractions.jsonl` (label-only, no re-extraction), reload into Neo4j updates properties via
  `MERGE` — no structural change.
- **Entity resolution: one-time cleanup, then baked into ingestion.** First pass: name-embedding
  similarity search over 279 entities found 101 candidate pairs
  (`scripts/find_entity_merge_candidates.py`); each reviewed (`scripts/apply_merge_recommendations.py`,
  detail in `data/processed/sec_filings/entity_merge_candidates.csv`). 13 genuine duplicate groups
  (14 entities) merged after user approval (`scripts/apply_entity_merges.py`). Second pass: this
  only fixed *existing* data — `load_to_neo4j.py` still matched *new* entities by exact slug, so
  the same duplicates could reappear on a future extraction run. Fixed with a two-tier resolver
  (`src/kgrag/entity_resolution.py`, wired into `load_to_neo4j.py`): exact match first; otherwise
  embed and compare against every existing entity - auto-merge only above a conservative
  **0.95** similarity (an earlier false positive scored 0.969, so even this bar isn't provably
  safe, just conservative - disclosed, not hidden), anything **0.80-0.95** gets flagged to
  `entity_resolution_review.csv` for a human to check rather than guessed either way.
- **A real mistake, caught and fixed during this work:** re-running `load_to_neo4j.py` for the
  ontology trim used the *not-yet-updated* loader (before the resolver was wired in). Since
  `extractions.jsonl` never got rewritten with post-merge entity names, this recreated all 14
  previously-merged duplicates (265 → 279 entities). Caught by checking Neo4j directly rather than
  trusting the script's own success output, root-caused, fixed by re-running
  `apply_entity_merges.py` (safe to repeat - fixed keys, not one-time state). Verified back to 265,
  0 duplicates, before continuing.
- **Live graph:** 225 Chunk, 277 Entity, 3 Filing nodes (2023/2024/2025), 972 MENTIONS, 584 RELATED_TO
  edges, 0 orphans. (277, not 265: the resolver correctly left 12 borderline-similarity entities as
  separate nodes rather than guessing, flagging them for review instead - see above.)

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

## Phase 3 — complete (question routing)

- **`src/kgrag/router.py`**: `route_question()` calls Gemini with a Pydantic-forced
  `RouteDecision` (`vector` / `graph` / `both` / `out_of_scope` + extracted entity names +
  one-line reasoning) — same structured-output pattern as `extract_sec_entities.py`.
  `execute_route()` dispatches to `retrieval.vector_search()` and/or
  `graph_retrieval.graph_search()`; no model-written Cypher anywhere.
- **`src/kgrag/graph_retrieval.py`**: fixed, parameterized Cypher templates only —
  `resolve_entity()` (exact name match first, substring fallback, and a Company-type
  tiebreak when a generic name like "Apple" ambiguously matches several products),
  `entity_neighbors()` / `entity_paths_between()` (1-2 hop `RELATED_TO` traversal),
  `graph_search()` (the combining entry point, prefers precise cross-entity paths over
  one entity's raw neighborhood — see bugs below).
- **Two real bugs found and fixed during testing, not just assumed working:**
  1. Querying a hub entity like "Apple Inc." alone returned a flood of irrelevant
     facts (30-50 unrelated relationships). Fixed by preferring direct paths *between*
     multiple named entities in a question over each entity's full neighborhood.
  2. A bare name like "Apple" fuzzy-matched 5 entities (Apple Inc. + 4 products), and
     picking the wrong one caused irrelevant paths. Fixed with exact-match-first
     resolution, falling back to a Company-type tiebreak only when still ambiguous.
- **Routing accuracy measured (Phase 3 gate)**, reusing the 24-query eval set with a new
  `expected_path` field — assigned by actually running graph_search per query and
  checking the real output, not guessed from question wording (`scripts/eval_routing.py`).
  **Accuracy: 87.5% (21/24)**, `data/eval/results/routing_20260827T113400Z.json`. Of the 3
  misses, 2 are the router correctly choosing `graph` alone where I'd conservatively
  labeled `both` (graph alone already answered fully); 1 is a real but harmless
  inefficiency (extra graph query on non-existent entities, vector still answers correctly).
- **Honest scope note:** on this corpus, only 2 of 24 test questions genuinely need the
  graph (Epic Games lawsuit, App Store legal matters) — most filing content was never
  captured as a graph relationship in Phase 1 (`SUPPLIES` had zero instances and was
  removed from the ontology entirely - see above), so the router mostly (correctly)
  chooses vector. Hop count (2) and result limits in `graph_retrieval.py` are reasonable
  defaults, not tuned against measured results — same caveat as chunk size (2600 chars)
  and the original `ivfflat` parameters earlier in this project.
- **Confidence fallback + routing log added** (against the original BASWE spec, which asks
  for both): `RouteDecision.confidence` (0-1, Gemini-estimated). `execute_route()` runs
  **both** retrieval paths when confidence is below `ROUTER_CONFIDENCE_THRESHOLD` (default
  0.6), regardless of the router's single-path pick — the original pick is still recorded,
  not overwritten. Every call to `execute_route()` appends one line to
  `data/logs/routing_log.jsonl` (timestamp, question, decided vs. effective path, confidence,
  whether the fallback fired, entities, reasoning). Verified with two real calls: a
  high-confidence question (0.9) stayed on its single path; a deliberately vague one
  ("What's the deal with Apple and its partners?", confidence 0.3) correctly triggered the
  fallback and both paths ran.

## Next: Phase 4 — merge graph and vector results into one grounded answer

- Convert graph paths into readable statements, combine with retrieved passages into
  one context block, deduplicate overlapping evidence, require a citation for every
  claim. Plain Python + Gemini SDK, FastAPI endpoint — no LangChain.
