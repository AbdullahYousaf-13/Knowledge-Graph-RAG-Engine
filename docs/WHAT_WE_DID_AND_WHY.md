# What We Did and Why — Full Breakdown for Supervisor

Detailed decision log. See `LIVING_SPECS.md` for the current build state. Every choice below is stated as: what we did, why, and whether it was the right call — with a better alternative named wherever it wasn't. Items originally flagged as gaps are updated to **FIXED** as they close.

---

## 1. Corpus: Apple 10-K filings (2021-2025) from SEC EDGAR

**What:** 5 years of Apple's annual reports, downloaded as HTML from the public EDGAR API.
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

## 4. Ontology constraint — FIXED

**Was:** `entity_type` / `relation_type` were free-text strings — Gemini could return anything, only lightly normalized afterward. Without a closed vocabulary the same category gets tagged inconsistently ("Company" vs "Corporation"), silently breaking type filters.
**Now:** `entity_type` and `relation_type` are closed `Literal[...]` sets in the Pydantic schema (8 entity types; 20 relation types + `RELATED_TO` catch-all), so Gemini must pick from the list. Existing `extractions.jsonl` was remapped to the closed set (`scripts/remap_ontology.py`) and reloaded into Neo4j — no re-extraction, since only type labels changed, not entity names.

## 5. Entity resolution — FIXED (for existing data)

**Was:** `entity_key = slugify(name)` — exact string match after normalizing. Catches "Apple Inc." vs "apple inc." but misses "Apple Inc." vs "Apple", producing duplicate nodes for one real entity.
**Now:** name-embedding similarity search over all 279 entities (`scripts/find_entity_merge_candidates.py`) surfaced 101 candidate pairs; each was reviewed with a merge/don't-merge call and reason (`scripts/apply_merge_recommendations.py`; detail in `data/processed/sec_filings/entity_merge_candidates.csv`). Most were false positives from shared vocabulary. 13 genuine duplicate groups (14 entities) were merged after user approval (`scripts/apply_entity_merges.py`) — edges redirected, aliases merged, duplicates deleted; a full Neo4j backup was taken first. Verified: 279 → 265 entities, relationship counts unchanged, 0 orphans.
**Still true:** ingestion-time matching in `load_to_neo4j.py` is exact-match by design — this was a one-time cleanup of existing data, not a change to how new entities are matched.

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
**Now:** `scripts/backfill_entity_keys.py` dropped and recreated the embedding index as `hnsw (m=16, ef_construction=64)`; `build_pgvector_index.py` builds HNSW for fresh loads. Embeddings untouched. Query-time `hnsw.ef_search` is pinned (default 64) in `src/kgrag/retrieval.py` so recall is reproducible; `eval_retrieval.py --ef-search` can sweep the recall/latency trade-off.

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

**What happened:** Neo4j was trimmed to 2023-2025 (Gemini quota-bound), but pgvector originally kept all 5 years (2021-2025) since local embedding has no quota limit — leaving the two databases covering different years.
**Why this was wrong:** a hybrid system needs both retrieval paths reasoning over the same facts; a vector hit from a year with zero graph coverage would break the premise.
**Fix already applied:** pgvector rescoped to match Neo4j exactly (225 chunks, 2023-2025 only).

---

## Summary framing

Phases 1 and 2 have working, idempotent, cost-conscious pipelines, and the three items originally skipped when they were first marked "complete" — ontology constraint (§4), entity resolution (§5), and retrieval-quality measurement (§10) — are now all done and verified. The vector index was also moved from `ivfflat` to HNSW (§8) and the two stores are now linked by entity (§9).

Remaining honest gaps, both minor: the 2600-char chunk size (§2) was never tuned against retrieval quality, and the retrieval eval set (§10) is only 24 queries — enough to catch regressions and gross failures, not to fine-tune.
