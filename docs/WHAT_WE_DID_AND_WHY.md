# What We Did and Why — Full Breakdown for Supervisor

Detailed version. See `PROGRESS_SUMMARY.md` for the short version. Every choice below is stated as: what we did, why, and whether it was the right call — with a better alternative named wherever it wasn't.

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

## 4. Ontology: NOT constrained — real gap

**What was supposed to happen:** a fixed, predefined list of allowed entity types (e.g. `Company, Person, Product, Regulation`) and relationship types (e.g. `SUPPLIES, COMPETES_WITH`), decided before extraction.
**What we actually did:** `entity_type` and `relation_type` are free-text strings — Gemini can return anything, only lightly normalized (uppercased, snake-cased) afterward, not restricted to a closed set.
**Why this is wrong:** without a closed vocabulary, the same real-world category can end up tagged inconsistently across chunks (e.g. "Company" vs "Corporation"), which silently breaks queries filtering by type.
**Better choice:** define `Literal["Company", "Person", "Product", ...]` in the Pydantic schema so Gemini is forced to pick from a fixed list — not just prompted to.

## 5. Entity resolution: exact-match only — real gap

**What was supposed to happen:** merge different mentions of the same real-world entity (e.g. "Apple Inc." vs "Apple" vs "AAPL") into one graph node, using similarity-based matching.
**What we actually did:** `entity_key = slugify(name)` — exact string match after lowercasing/normalizing. Catches "Apple Inc." vs "apple inc." (same after normalizing) but misses "Apple Inc." vs "Apple" (genuinely different strings). Gemini has no role in this step — it only extracts entities per chunk in isolation; the matching/merging logic is entirely our own Python code, run after extraction.
**Why this is wrong:** likely produces duplicate nodes in the graph for the same real entity, mentioned differently in different chunks — not yet audited how bad this is in the actual 279-entity graph.
**Better choice:** embedding-similarity matching — compare a new entity's name-embedding against existing entities, merge if cosine similarity exceeds a threshold.

## 6. Loading into Neo4j: `MERGE`-based, idempotent (`load_to_neo4j.py`)

**What:** Every write uses Cypher `MERGE` (find-or-create) instead of `CREATE`, so re-running the loader never duplicates nodes/edges.
**Why:** Makes the pipeline safely re-runnable — important since extraction ran across multiple days due to Gemini's rate limit.
**Verdict:** Correct, standard practice.

## 7. Vector embeddings: local `sentence-transformers`, not Gemini's embedding API

**What:** `all-MiniLM-L6-v2` (384-dim), run locally on CPU via `build_pgvector_index.py`, instead of calling an embedding API.
**Why:** No API cost, no additional rate-limit exposure, and CPU inference is fast enough at this corpus size.
**Verdict:** Good, deliberate choice given the project's zero-budget constraint.

## 8. Vector index type: `ivfflat`, not HNSW — real gap

**What was available:** pgvector (the installed version) supports both `ivfflat` (cluster-based) and `HNSW` (graph-based, generally better recall at similar speed).
**What we actually did:** `ivfflat` only, `HNSW` never tried.
**Why this happened:** not a deliberate trade-off — just what got built first, never revisited.
**Better choice:** switch to `HNSW`. Low-risk change — doesn't touch existing embeddings, just rebuilds the index structure.

## 9. No `entity_ids` link between pgvector and Neo4j — real gap

**What was supposed to happen:** each vector-store row should store which entities that chunk mentions, so you can filter vector search by entity in one query.
**What we actually did:** the two databases link only via shared `chunk_id` — no direct entity cross-reference on the vector side.
**Better choice:** add an `entity_ids` column to the pgvector table, backfilled from `extractions.jsonl`.

## 10. No retrieval quality measurement (recall@k) — real gap, most important one

**What was supposed to happen (per `PROJECT_GOAL_AND_PHASES.md`):** "Measure retrieval quality before building any routing logic."
**What we actually did:** nothing — no labeled query set, no recall@k benchmark, ever built. Phase 2 was marked "done" without this step.
**Why this matters most:** without it, there's no actual evidence the vector search retrieves the right chunks — it's untested, not just unoptimized.
**Better choice:** build a small labeled set (a handful of questions with manually-identified correct chunks) and compute recall@k before trusting the retrieval layer.

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

Phases 1 and 2 have working, idempotent, cost-conscious pipelines — the engineering fundamentals (structured extraction, MERGE-based idempotency, local embeddings) are solid. But three things are genuinely unfinished, not just "different choices": no ontology constraint, no proper entity resolution, and no retrieval quality measurement. Those aren't stylistic — they're steps the project's own spec (`PROJECT_GOAL_AND_PHASES.md`) calls for that got skipped when Phase 1/2 were marked complete.
