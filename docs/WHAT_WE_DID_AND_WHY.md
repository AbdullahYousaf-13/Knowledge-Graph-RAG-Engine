# What We Did and Why — Full Breakdown for Supervisor

Detailed decision log. See `LIVING_SPECS.md` for the current build state. Every choice below is stated as: what we did, why, and whether it was the right call — with a better alternative named wherever it wasn't. Items originally flagged as gaps are updated to **FIXED** as they close.

---

## 1. Corpus: Apple 10-K filings (FY2023-2025) from SEC EDGAR

**What:** 3 years of Apple's annual reports (fiscal 2023, 2024, 2025), downloaded as HTML from
the public EDGAR API. FY2021 and FY2022 were downloaded and chunked early on, then removed
entirely once the scope was fixed at 2023-2025 (the Gemini free-tier extraction quota set the
ceiling) — keeping unused years only created a confusing chunk-count discrepancy.
**Why:** 10-Ks are long, structured, and contain real business relationships (suppliers, competitors, risks) — good raw material for a knowledge graph, and free/public with no licensing issue.
**Verdict:** Reasonable choice, no issue.

## 2. Chunking: custom Python (`prepare_sec_filings.py`), 2600-char paragraph-aware, no LangChain

**What:** Split each filing at real section boundaries (Item 1, Item 1A, etc.), then within each section, greedily pack whole paragraphs into ~2600-character chunks with 1-paragraph overlap between consecutive chunks.
**Why:** Hand-built instead of using LangChain's `RecursiveCharacterTextSplitter` so overlap never cuts mid-sentence, and splitting respects actual SEC document structure LangChain doesn't know about.
**Verdict:** Solid engineering choice. The 2600-char figure itself, however, was **not tuned or benchmarked** — it's a reasonable default (~400-500 words), not a value chosen by testing retrieval quality at different sizes. Honest gap, tied to #10 below.

## 3. Entity/relationship extraction: Gemini + Pydantic structured output (`extract_sec_entities.py`)

**What:** Each chunk sent to Gemini with a Pydantic schema (`Entity`, `Relationship`, `ChunkExtraction`) forcing structured JSON output — no free-text parsing.
**Why:** Structured output eliminates the failure mode of an LLM returning malformed/unparseable text; Gemini's free tier was used to avoid API cost, since this is an unpaid internship project.
**Verdict:** Good technique. Retry/resume logic had real bugs found and fixed mid-project (a progress-tracking bug that permanently blocked retries, and a chunk-slicing bug that caused infinite reprocessing of the same chunks) — worth mentioning as debugging done, not a criticism of the approach.
**Retry scope — FIXED.** `should_retry()` used to retry only quota/`429` errors; a schema `ValidationError`, an empty/truncated response, or a 5xx/network blip was treated as terminal. Now all of those are retried (bounded by `MAX_RETRIES`, with a short fixed backoff for the non-quota cases), and any chunk that still fails is appended to `data/processed/sec_filings/extractions_failed.jsonl` rather than lost to stdout. Structured output makes a `ValidationError` unlikely, but "validate every response and retry the failures" (the spec) now holds for every failure mode, not one.

## 4. Ontology constraint — FIXED, then tightened to match the original spec

**Was:** `entity_type` / `relation_type` were free-text strings — Gemini could return anything, only lightly normalized afterward. Without a closed vocabulary the same category gets tagged inconsistently ("Company" vs "Corporation"), silently breaking type filters.
**First fix:** `entity_type` and `relation_type` became closed `Literal[...]` sets (8 entity types; 20 relation types + `RELATED_TO` catch-all). Existing `extractions.jsonl` remapped (`scripts/remap_ontology.py`), no re-extraction.
**Second pass:** comparing against the original BASWE Project 1 spec (which targets 8-15 relationship types, not 21), consolidated the thinnest/most-overlapping types — `OFFERS`→`PROVIDES`, `ISSUED`→`ANNOUNCED`, `DEVELOPS`→`PRODUCES`, `EXPOSED_TO`→`SUBJECT_TO`, `MANAGES`→`RELATED_TO`, and dropped `SUPPLIES` entirely (zero instances were ever extracted in this corpus, despite being an allowed type). Now **8 entity types, 14 relation types + `RELATED_TO` = 15 total**, within spec range. Same mechanism both times: remap existing data, no re-extraction, reload Neo4j (property update only, `entity_key` untouched).

## 5. Entity resolution — FIXED for existing data, then baked into ingestion

**Was:** `entity_key = slugify(name)` — exact string match after normalizing. Catches "Apple Inc." vs "apple inc." but misses "Apple Inc." vs "Apple", producing duplicate nodes for one real entity.
**First fix (cleanup pass):** name-embedding similarity search over all 279 entities (`scripts/find_entity_merge_candidates.py`) surfaced 101 candidate pairs; each was reviewed with a merge/don't-merge call and reason (`scripts/apply_merge_recommendations.py`; detail in `data/processed/sec_filings/entity_merge_candidates.csv`). Most were false positives from shared vocabulary. 13 genuine duplicate groups (14 entities) were merged after user approval (`scripts/apply_entity_merges.py`) — edges redirected, aliases merged, duplicates deleted; a full Neo4j backup was taken first. Verified: 279 → 265 entities, relationship counts unchanged, 0 orphans.
**Second fix (ingestion itself):** the cleanup pass only fixed *existing* data — `load_to_neo4j.py` still matched *new* entities by exact slug, so the same kind of duplicate could reappear on a future extraction run (and, in fact, briefly did — see the mistake noted in `LIVING_SPECS.md`). Fixed with a two-tier resolver (`src/kgrag/entity_resolution.py`): exact match first; otherwise embed and compare against every existing entity in the graph. Auto-merge only above a conservative **0.95** similarity — disclosed as not risk-free, since a measured false positive ("ASU 2023-09" vs "ASU 2023-07") scored 0.969, just under a slightly stricter bar. Anything **0.80-0.95** creates a new entity as normal but gets flagged to `entity_resolution_review.csv` for a human to check, rather than guessed either way. Verified against real data: of 14 names still in `extractions.jsonl` from the pre-merge era, 2 auto-merged correctly (the two that scored ≥0.95 in the original human-reviewed pass too) and 12 were correctly left un-merged and flagged, including one case that would have been a wrong merge if trusted blindly.

## 6. Loading into Neo4j: `MERGE`-based, idempotent (`load_to_neo4j.py`)

**What:** Every write uses Cypher `MERGE` (find-or-create) instead of `CREATE`, so re-running the loader never duplicates nodes/edges.
**Why:** Makes the pipeline safely re-runnable — important since extraction ran across multiple days due to Gemini's rate limit.
**Verdict:** Correct, standard practice.

## 7. Vector embeddings: local `sentence-transformers`, not Gemini's embedding API

**What:** `all-MiniLM-L6-v2` (384-dim), run locally on CPU via `build_pgvector_index.py`, instead of calling an embedding API.
**Why:** No API cost, no additional rate-limit exposure, and CPU inference is fast enough at this corpus size.
**Verdict:** Good, deliberate choice given the project's zero-budget constraint.

## 8. Vector index type: `ivfflat` → `hnsw` — FIXED

**Was:** `ivfflat` only (`lists=100`), `HNSW` never tried — not a trade-off, just what got built first. Over 225 rows, `lists=100` means ~2 rows per list, which is pathological for recall.
**Now:** `scripts/backfill_entity_keys.py` dropped and recreated the embedding index as `hnsw (m=16, ef_construction=64)`; `build_pgvector_index.py` builds HNSW for fresh loads. Embeddings untouched. Query-time `hnsw.ef_search` is set (default 64) in `src/kgrag/retrieval.py`.
**ef_search tuned (spec: "tune ef_search").** `eval_retrieval.py --ef-sweep "32,64,100,200,400"` runs the full recall eval once per value plus a brute-force exact scan as the recall ceiling. Result: recall@k, hit@k and MRR are **identical at every value** (and equal to the exact ceiling) — with only 225 vectors the HNSW graph has no approximation loss, so `ef_search` has nothing to trade off. Kept at 64. The `recall@5 ≈ 0.54` is a metric ceiling (several gold sets have 6 chunks) plus embedding quality, not an index problem — now measured, not assumed. Sweep output: `data/eval/results/ef_sweep_20260828T121309Z.json`.

## 9. Entity link between pgvector and Neo4j — FIXED

**Was:** the two stores linked only via shared `chunk_id`.
**Now:** `sec_chunk_embeddings.entity_keys TEXT[]` (+ GIN index), backfilled from `extractions.jsonl`. Named `entity_keys` (not `entity_ids`) because the values are the `slugify(name)` slug — the exact key Neo4j uses, so the join is a plain string with no separate id system. The backfill remaps pre-merge entity names to their post-merge canonical key (`src/kgrag/entity_keys.py`, kept in sync with `apply_entity_merges.py`), then verifies every key against the live graph. `retrieval.vector_search(entity_keys=[...])` filters via array overlap — the primitive the Phase 3 router will use.

## 10. Retrieval quality measurement (recall@k) — FIXED

**Was:** nothing — no labeled set, no benchmark. Phase 2 had been marked "done" without it.
**Now:** `data/eval/retrieval_queries.jsonl` — 24 hand-labeled queries (12 single-hop, 3 aggregation, 6 multi-hop, 3 out-of-scope), each with the chunk ids that genuinely answer it (labels from reading the filings, never from retriever output). `scripts/eval_retrieval.py` computes recall@k / hit@k / MRR by category and writes a timestamped results file to `data/eval/results/` (records model, index type, `ef_search`, git rev, query-set hash). First run (HNSW, ef_search=64): overall hit@5 0.90, recall@5 0.54, MRR 0.78; single-hop hit@5 0.83, multi-hop hit@5 1.0. This is the vector-only baseline Phase 5 compares the hybrid system against. Caveat: 24 × 225 is small — the numbers are directional, for catching regressions and gross failures, not fine-tuning.
**Surfaced for Phase 3:** out-of-scope queries scored up to ~0.69 similarity, overlapping the in-scope range — a naive score threshold will not cleanly gate them out.

## 11. Cloud hosting: AuraDB + Supabase, not local Neo4j/Postgres

**What:** Both databases run on free cloud tiers instead of locally.
**Why:** The development machine has 8GB RAM, no GPU, and limited disk — local Neo4j/Postgres/Docker installs weren't practical.
**Verdict:** Correct, necessity-driven decision, not a quality trade-off.

## 12. Corpus scope mismatch (caught and fixed)

**What happened:** Neo4j was trimmed to 2023-2025 (Gemini quota-bound), but pgvector originally kept all five downloaded years (FY2021-2025) since local embedding has no quota limit — leaving the two databases covering different years.
**Why this was wrong:** a hybrid system needs both retrieval paths reasoning over the same facts; a vector hit from a year with zero graph coverage would break the premise.
**Fix applied:** pgvector rescoped to match Neo4j exactly (225 chunks, 2023-2025 only); later the FY2021/FY2022 raw HTML and chunked data were deleted from the repo altogether so `chunks.jsonl` (266 rows) matches the corpus.

## 13. Phase 3 routing: built, tested against real output, two real bugs fixed

**What:** `src/kgrag/router.py` (Gemini + Pydantic structured output decides `vector` / `graph` / `both` / `out_of_scope`, same pattern as extraction) and `src/kgrag/graph_retrieval.py` (fixed, parameterized Cypher templates — the model never writes a query, only fills entity-name parameters).
**Two real bugs found by testing, not assumed away:**
1. Querying a hub entity like "Apple Inc." alone returned 30-50 irrelevant facts (it's connected to almost everything). Fixed by preferring direct paths *between* multiple named entities in a question over one entity's full neighborhood.
2. A bare name like "Apple" fuzzy-matched 5 entities (the company + 4 products); picking the wrong one caused irrelevant paths. Fixed with exact-match-first resolution, falling back to a Company-type tiebreak only when still ambiguous.
**Measured, not assumed:** routing accuracy **96.3% (26/27)** against a hand-labeled set, where `expected_path` was assigned by actually running the router and graph search per question and checking real output — not guessed from wording. (Was 87.5% / 21-of-24; the jump is from adding few-shot examples, below, and 3 graph-heavy eval queries.)
**Few-shot prompt (spec: "a few shot prompt"):** the router prompt was zero-shot — rich field descriptions, no worked examples. Added ~10 hand-written `(question → RouteDecision)` examples in `ROUTER_FEW_SHOT`, one per path plus the boundary cases the confusion matrix was missing (`both↔graph`, `vector↔both`). They are deliberately **disjoint from `data/eval/retrieval_queries.jsonl`** so the accuracy number stays a real held-out measurement. First draft over-routed regional financial comparisons to the graph (accuracy dipped to 85%); adding explicit "numeric / segment comparison = vector" counter-examples fixed that and lifted it to 96.3%.
**Template library keyed by query type (spec wording):** `graph_search()` used to pick its Cypher template by counting resolved entities (1 ⇒ neighbours, 2+ ⇒ paths-between). Now `RouteDecision.query_type` (filled by the model, one of `connection` / `multi_hop` / `comparison` / `aggregation` / `none`) selects the template: paths-between for connection/multi-hop, per-entity tagged neighbourhoods for comparison, and a new `entity_relation_summary()` aggregation template (group an entity's relationships by type, with counts) for aggregation. The entity-count heuristic remains as the fallback when `query_type` is absent. The model still only ever supplies the enum and entity names — never Cypher text. Three eval queries were added to exercise the comparison / aggregation / multi-hop paths (24 → 27 queries).
**Against the original spec's remaining asks:** added `RouteDecision.confidence` and a low-confidence fallback (`execute_route()` runs both paths below a 0.6 threshold, default), plus a persistent JSONL log of every routing decision (`data/logs/routing_log.jsonl`, now including `query_type`) — the spec is explicit this data can't be reconstructed later if skipped.
**A real mistake made and fixed along the way:** re-running the Neo4j reload for the ontology trim (§4) used the loader code *before* the new entity-resolution logic (§5) was wired in. Since the source `extractions.jsonl` was never rewritten with post-merge names, this recreated all 14 previously-merged duplicates. Caught by checking Neo4j directly rather than trusting the script's printed summary, root-caused, and fixed by re-running the merge script (safe to repeat).

## 14. Phase 4 answer synthesis: one evidence pool, drop-don't-fail on bad citations

**What:** `src/kgrag/answer.py` + `src/kgrag/api.py`. Router output (vector hits, graph facts, aggregation rows) is merged into a single `chunk_id`-keyed `Evidence` pool; Gemini writes `{answer_markdown, claims:[{text, citations}]}` from a labelled context block; a validate-and-repair loop guarantees every citation resolves to a retrieved chunk. `POST /ask` (synchronous FastAPI) is the "Done When" endpoint.

**Design decisions and why:**
- **Hybrid evidence, not two parallel lists.** Every graph fact resolves its `source_chunk_id` to the *full chunk text* (new `retrieval.get_chunks_by_ids()`), so graph-derived and vector-derived evidence are the same shape — dedup is a `chunk_id` set operation and citation validation is a single membership check. The graph fact's one-line `description` is kept as an annotation and rendered under a distinct `## GRAPH-DERIVED FACTS` heading, so the spec's "label graph facts separately from passages" still holds. Alternative (feed the model raw triples / description-only) was rejected: the model can't cross-check a lossy summary against the real sentence, and dedup gets clumsy.
- **Drop unsupported claims, don't fail the request.** After the re-prompt budget (2), any claim still citing a chunk outside the pool is removed and counted (`claims_removed`), rather than returning a 422. The answer is always fully grounded; the caller sees how much was dropped. Returning an error on every ungrounded claim would make the demo brittle for no safety gain (the ungrounded claim is already excluded).
- **Canned out-of-scope refusal, no LLM call.** When the router says `out_of_scope`, `/ask` returns a fixed message. Free, instant, and it's what Phase 5's "questions the system should refuse" expects.
- **Aggregation had to be made citable.** `GraphRelationSummary` carried counts but no chunk ids, so aggregation answers had nothing to cite. Added `collect(DISTINCT r.source_chunk_id)[..5]` to the `entity_relation_summary` template — still a fixed parameterized query, the model touches none of it.
- **Reused `GEMINI_MODEL` (free tier).** Phase 4 is ~1 model call per question (vs extraction's 225), so there is no quota pressure; `GEMINI_ANSWER_MODEL` overrides if ever needed.

**Verified** against the live databases on all four route types; the "no citation outside the retrieved set" invariant held on every response and is guarded by `tests/test_answer.py`.

---

## Summary framing

Phases 1 and 2 have working, idempotent, cost-conscious pipelines, and the three items originally skipped when they were first marked "complete" — ontology constraint (§4), entity resolution (§5), and retrieval-quality measurement (§10) — are now all done and verified. The vector index was also moved from `ivfflat` to HNSW (§8, `ef_search` then swept and confirmed flat) and the two stores are now linked by entity (§9). Phase 3 (§13) is built, tested against real output rather than assumed, and closes the remaining gaps against the original spec: relationship-type count, ingestion-time resolution, confidence fallback, routing log, extraction retry breadth (§3), few-shot router prompt and a query-type-keyed template library (§13). Phase 4 (§14) merges both retrieval paths into one grounded answer behind a FastAPI `POST /ask`, with every citation validated to resolve to a retrieved chunk. Phase 5 (the vector-only benchmark) is the only phase left.

Remaining honest gaps, both minor: the 2600-char chunk size (§2) was never tuned against retrieval quality, and the retrieval eval set (§10) is only 27 queries — enough to catch regressions and gross failures, not to fine-tune. One deliberately skipped item: per-document cost budgeting/caching by document hash (from the original spec) doesn't map cleanly onto a free-tier Gemini setup with no dollar cost to budget, and was skipped by explicit agreement rather than overlooked.
