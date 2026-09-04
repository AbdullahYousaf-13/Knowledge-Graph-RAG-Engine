# Living Specs

_Current state of the build. For the goal and the 5-phase plan see
`PROJECT_GOAL_AND_PHASES.md`; for tool choices and reasoning see `TECH_STACK.md`; for the
supervisor-facing decision log see `WHAT_WE_DID_AND_WHY.md`._

## Snapshot

- **Goal:** hybrid knowledge-graph + vector RAG over SEC filings (see `PROJECT_GOAL_AND_PHASES.md`).
- **Corpus:** Apple 10-K filings, fiscal years 2023-2025. 3 filings chunked into 266 chunks
  (`data/processed/sec_filings/chunks.jsonl`), of which **225 are substantive** and loaded into
  both databases so Neo4j and pgvector reason over the same facts. The scope was set at 2023-2025
  by the Gemini free-tier extraction quota; `FILING_YEARS` env var controls it. (Earlier, FY2021
  and FY2022 were also downloaded and chunked, then removed entirely once the scope was fixed.)
- **Infra:** AuraDB (Neo4j) and Supabase (Postgres+pgvector) free tiers, live; credentials in
  local `.env` (gitignored).
- **All five phases are complete.** Hybrid answerer benchmarks at **0.85 vs. 0.68** for a
  vector-only baseline over 53 questions — the edge is on relationship questions, aggregation,
  and out-of-scope refusal, at ~2.8× the token cost (see Phase 5 below).
- **Security:** deliberate review done — injection surfaces sound (bound params everywhere,
  model never writes queries), layered prompt-injection defenses, request-input bounds,
  generic error responses. Perimeter controls (auth/rate-limit/TLS) are accepted risk for
  a local demo. What was weak / what we fixed / what's deferred: `SECURITY.md`.
  Tests: `tests/test_security.py` (unit) + `scripts/injection_probe.py` (live-LLM).

## Known gotchas

- Supabase needs the **session pooler host** (`aws-0-<region>.pooler.supabase.com`), not the
  direct `db.<ref>.supabase.co` host — the direct host is IPv6-only and unreachable from this network.
- Chunk size (2600 chars) was never tuned against retrieval quality — a reasonable default, not a measured choice.
- The retrieval eval set is 27 queries — directional, not statistically tight.
- `chunk.section_name` is best-effort metadata (display/citations only — no logic depends on it).
  25 non-substantive chunks (cover page / ToC fragments, none embedded) still carry a
  best-guess label; a chunk straddling a section boundary is labelled by its bulk.

## Phase 1 — complete (extract entities & relationships into Neo4j)

- All 225 substantive 2023-2025 chunks extracted (`extractions.jsonl`), 0 failures. An earlier
  batch of 24 chunks from 2021 was extracted before the scope was fixed, then removed and purged
  from Neo4j; the FY2021/FY2022 raw and chunked data has since been deleted from the repo too.
- **Extraction retry** covers every transient failure, not just quota: `should_retry()` in
  `scripts/extract_sec_entities.py` also retries schema `ValidationError`, empty/truncated
  responses (`EmptyResponseError`), and 5xx/network blips, bounded by `MAX_RETRIES`. Chunks that
  exhaust all retries are written to `data/processed/sec_filings/extractions_failed.jsonl`.
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
  (`sec_chunk_embeddings`). Originally indexed FY2021-2025; rescoped to 2023-2025 with
  `RESET_TABLE=true` once the corpus mismatch with Neo4j was identified as a Phase 3/4 risk.
- **Shared library `src/kgrag/`** added (`pip install -e .`): `db.py`, `entity_keys.py`
  (`slugify` + post-merge canonical-key remap, single source of truth), `retrieval.py`
  (`vector_search()` — the primitive Phase 3/4 import).
- **Entity linkage:** `sec_chunk_embeddings.entity_keys TEXT[]` column + GIN index.
  `scripts/backfill_entity_keys.py` (idempotent) populated all 225 rows from `extractions.jsonl`,
  remapping pre-merge entity names to their post-merge canonical `entity_key`. Verified: 265
  distinct keys on vector rows, every one exists as a Neo4j `Entity` (exact match to the graph's 265).
- **Vector index switched `ivfflat` → `hnsw`** (`m=16, ef_construction=64`); the `ivfflat lists=100`
  over 225 rows was pathological. Query-time `hnsw.ef_search` = 64 in `retrieval.py`.
- **`ef_search` tuned:** `eval_retrieval.py --ef-sweep` over {32,64,100,200,400} + an exact-scan
  ceiling shows recall/MRR **flat across all values** (225 vectors → no HNSW approximation loss),
  so 64 stays. `data/eval/results/ef_sweep_20260828T121309Z.json`.
- **Retrieval quality measured (Phase 2 gate):** 27 hand-labeled queries in
  `data/eval/retrieval_queries.jsonl` (12 single-hop, 4 aggregation, 8 multi-hop, 3 out-of-scope;
  the last 3 added in Phase 3 to exercise the comparison / aggregation / multi-hop graph templates).
  `scripts/eval_retrieval.py` computes recall@k / hit@k / MRR by category, writing a timestamped
  baseline to `data/eval/results/`. Phase 2 baseline on the original 24 queries (HNSW,
  ef_search=64): overall **hit@5 0.90, recall@5 0.54, MRR 0.78**. Re-run over the full 27
  (vector-only): **hit@5 0.83, recall@5 0.50, MRR 0.73** — the drop is concentrated in the two
  added graph queries (q025 comparison, q026 aggregation) that vector retrieval genuinely can't
  answer well, which is the case for the hybrid path Phase 5 will measure against this.

## Phase 3 — complete (question routing)

- **`src/kgrag/router.py`**: `route_question()` calls Gemini with a Pydantic-forced
  `RouteDecision` (`vector` / `graph` / `both` / `out_of_scope`, a `query_type`
  (`connection` / `multi_hop` / `comparison` / `aggregation` / `none`), extracted entity
  names + one-line reasoning) — same structured-output pattern as `extract_sec_entities.py`.
  The prompt now carries ~10 hand-written **few-shot** examples (`ROUTER_FEW_SHOT`),
  deliberately disjoint from the eval set. `execute_route()` dispatches to
  `retrieval.vector_search()` and/or the graph layer; no model-written Cypher anywhere.
- **`src/kgrag/graph_retrieval.py`**: fixed, parameterized Cypher templates, now a
  **template library keyed by `query_type`** (the spec's wording) rather than an
  entity-count heuristic:
  - `resolve_entity()` — exact name match first, substring fallback, Company-type tiebreak.
  - `connection` / `multi_hop` → `entity_paths_between()` (cross-entity `RELATED_TO` paths).
  - `comparison` → each entity's neighborhood, tagged with `anchor` so a caller can diff them.
  - `aggregation` → `entity_relation_summary()` — group an entity's `RELATED_TO` edges by
    type with counts and sample targets; `graph_aggregate()` is the entry point,
    `execute_route()` puts its rows in `graph_aggregates` (shape differs from `GraphFact`).
  - no/unknown `query_type` → the old heuristic (2+ entities ⇒ connection, else neighborhood).
- **Two real bugs found and fixed during testing, not just assumed working:**
  1. Querying a hub entity like "Apple Inc." alone returned a flood of irrelevant
     facts (30-50 unrelated relationships). Fixed by preferring direct paths *between*
     multiple named entities in a question over each entity's full neighborhood.
  2. A bare name like "Apple" fuzzy-matched 5 entities (Apple Inc. + 4 products), and
     picking the wrong one caused irrelevant paths. Fixed with exact-match-first
     resolution, falling back to a Company-type tiebreak only when still ambiguous.
- **Routing accuracy measured (Phase 3 gate)**, on the 27-query eval set (24 original +
  3 added to exercise `comparison` / `aggregation` / `multi_hop` templates), each with an
  `expected_path` assigned by running the graph per query and checking real output, not
  guessed from wording (`scripts/eval_routing.py`).
  **Accuracy: 96.3% (26/27)**, `data/eval/results/routing_20260828T122107Z.json`
  (up from 87.5% / 21-of-24 before the few-shot examples were added and tuned). The one
  miss is q021 choosing `both` where `vector` was labelled — an over-retrieval, not a wrong
  path.
- **Honest scope note:** on this corpus, only ~4 of 27 test questions genuinely need the
  graph (Epic Games lawsuit, App Store legal matters, and the two added
  comparison/aggregation queries) — most filing content was never
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
  whether the fallback fired, entities, query_type, reasoning). Verified with two real calls: a
  high-confidence question (0.9) stayed on its single path; a deliberately vague one
  ("What's the deal with Apple and its partners?", confidence 0.3) correctly triggered the
  fallback and both paths ran.

## Phase 4 — complete (merge graph + vector into one grounded answer)

- **`src/kgrag/answer.py`** — the synthesis layer.
  - `build_evidence()` collapses `execute_route()`'s output into one `Evidence` pool keyed
    by `chunk_id`, with `origin` ∈ {`vector`, `graph`, `both`}. Graph facts resolve their
    `source_chunk_id` to the full chunk text (`retrieval.get_chunks_by_ids()`, a new PK
    fetch) and keep their extraction `description` as a one-line statement.
  - `render_context()` renders two labelled sections — `## GRAPH-DERIVED FACTS` (statement
    + source text) and `## PASSAGES` (vector text). Dedup is by `chunk_id`; a chunk from
    both paths appears once as `both`.
  - `synthesize()` — Gemini structured output `{answer_markdown, claims:[{text, citations}]}`
    (`GEMINI_ANSWER_MODEL` → `GEMINI_MODEL`; free tier, one call per question).
  - `validate_and_repair()` — re-prompts (default 2 retries) while any claim cites a
    `chunk_id` outside the evidence pool, then **drops** the still-unsupported claims and
    reports `claims_removed`. Invariant: the answer never cites a non-retrieved chunk
    (`tests/test_answer.py`).
  - `answer_question()` is the single entry point; `python -m kgrag.answer "<q>"` is the CLI.
- **`src/kgrag/api.py`** — FastAPI. `POST /ask {question, k?, hops?}` → JSON
  `{answer_markdown, claims, citations:[{chunk_id, section_name, filing_year, company,
  source_url, origin, snippet}], claims_removed, out_of_scope, route}`. `GET /health`.
  Synchronous. `out_of_scope` routes short-circuit to a canned refusal (no LLM call).
- **Aggregation made citable:** `entity_relation_summary` (the `query_type == "aggregation"`
  template) now also returns `collect(DISTINCT r.source_chunk_id)[..5]`, and
  `GraphRelationSummary` gained `source_chunk_ids`.
- **Verified against the live DBs** on four routes: `vector` (effective tax rate 24.1%,
  cited), `both`/`connection` (Epic Games lawsuit, chunk `apple-inc-2023-0043` shows as
  `both`), `graph`/`aggregation` (Apple's tax/regulatory obligations, cited to the sampled
  chunks), and `out_of_scope` (FY2027 guidance → canned refusal). Citation invariant held
  on every response.
- Deps added: `fastapi`, `uvicorn[standard]`.

## Phase 5 — complete (benchmark vs. the vector-only baseline)

- **Question set:** `data/eval/retrieval_queries.jsonl` = **53** questions
  (18 single-hop / 12 two-hop / 6 three-hop / 9 aggregation / 8 out-of-scope). The 18
  multi-hop questions are **entity-connection questions** — connection chains
  (`Apple —SUBJECT_TO→ DMA —LOCATED_IN→ EU`), comparisons across entities, and relationship
  tallies — that route to graph/both (12 both, 6 graph). Every row has `hops` and a `gold`
  answer key; `relevant_chunk_ids` is optional (11 benchmark-only rows have none,
  `eval_retrieval.py` skips them; still 24 scored, MRR 0.725).
- **`execute_route` change:** the `graph` route now also runs `vector_search()` — graph
  facts are terse one-liners, so the source passages give the synthesizer full context
  (this fixed q019, where `graph`-only previously lost the narrative). Graph facts augment
  the text rather than replacing it; the `graph`/`both` enum stays as a logged signal.
- **`scripts/benchmark.py`:** hybrid answerer vs. vector-only baseline
  (`answer_question(force_path="vector")`). Deterministic fact-checklist grading (an
  in-scope answer that hedges "does not contain…" can't score `correct`; two over-strict
  gold entries were corrected during hand review). Paces every Gemini call (~4.5 s,
  free-tier 15 rpm), retries 429s + 5xx, checkpoints to `benchmark_progress.jsonl` for
  resume. Writes `benchmark_<UTC>.json` + `benchmark_table.md`.
- **Result** (`benchmark_20260901T114932Z.json`, `gemini-3.1-flash-lite`): hybrid **0.85**
  vs. vector-only **0.68** overall (+0.17). By stratum: single-hop 0.89 vs 0.94, two-hop
  0.75 vs 0.67, three-hop 1.00 vs 1.00, aggregation 0.67 vs 0.56, **out-of-scope 1.00 vs 0.00**.
- **Latency / cost:** hybrid p50 8.5 s / p95 19.8 s vs. vector-only p50 6.4 s / p95 9.4 s.
  Modelled cost $1.25 vs $0.49 per 1k queries (hybrid ~2.8× the tokens); $0 actual on the
  free tier. One-time ingestion ~225 extraction calls, $0.
- **Honest read:** the hybrid's edge is where a graph is for — refusal (+1.00; vector-only
  can't decline, 0/8), aggregation over relationships (+0.11), and a real-but-noisy
  multi-hop gain (+0.08 two-hop; a second run put it at +0.17). Single-hop parity. Caveats:
  run-to-run variance is real at these strata sizes; the graph having a fact ≠ the answer
  using it (q025); retrieval recall (≈0.5) is the shared ceiling. Full write-up:
  `WHAT_WE_DID_AND_WHY.md` §15 + README "what didn't work".
- **Model:** `gemini-3.5-flash-lite` (the project's original) was retired by Google
  mid-build; switched to `gemini-3.1-flash-lite` in `.env` + the code defaults.

**All five phases are complete.**
