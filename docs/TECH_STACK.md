# Tech Stack

Every tool this project uses, and why. Locked decisions — revisit only with a concrete
reason. For the phase-by-phase build plan see `PROJECT_GOAL_AND_PHASES.md`; for current
build status see `LIVING_SPECS.md`.

## At a glance

| Layer | Choice |
|---|---|
| Language | Python |
| Shared library | `src/kgrag/` (editable install, `pip install -e .`) — DB connections, entity-key helpers, `vector_search()` |
| API framework | FastAPI (Phase 4) |
| Graph database | Neo4j on AuraDB free tier; Cypher, hand-written |
| Vector database | PostgreSQL + `pgvector` on Supabase free tier; **HNSW** index |
| Embeddings | `sentence-transformers` `all-MiniLM-L6-v2` (384-dim), local CPU |
| LLM | Google Gemini API (free tier), structured JSON output |
| Orchestration | None — plain Python, official SDKs called directly. **No LangChain, anywhere.** |

## Phase 1–2 — built

| Stage | Tool | Why |
|---|---|---|
| Chunking | Plain Python/regex, hand-built (`prepare_sec_filings.py`) | Structure-aware (SEC section boundaries + whole-paragraph overlap) — more precise than a generic splitter for this one document type. |
| Entity/relationship extraction | `google-genai` SDK + Pydantic structured output (`extract_sec_entities.py`) | Forces valid JSON from Gemini, no parsing failures, full control over the schema. `entity_type`/`relation_type` are a closed `Literal[...]` set. |
| Graph storage | `neo4j` Python driver + hand-written Cypher `MERGE`, AuraDB free tier (`load_to_neo4j.py`) | `MERGE` keeps ingestion idempotent; official driver gives full query control. |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, local CPU) (`build_pgvector_index.py`) | Free, no quota, fast enough at this corpus size — avoids a paid embedding API. |
| Vector storage/search | `psycopg` + `pgvector`, Supabase free tier, **HNSW** index (`m=16, ef_construction=64`) | HNSW gives better recall than `ivfflat` at similar query speed. `ivfflat lists=100` over 225 rows was pathological (~2 rows/list). Query-time `hnsw.ef_search` pinned in `kgrag.retrieval`. |
| Entity ↔ vector link | `sec_chunk_embeddings.entity_keys TEXT[]` + GIN index | Lets vector search be filtered by entity in one query (array overlap) — the primitive the Phase 3 router needs. |
| Shared code | `src/kgrag/` package | `db.py` (Postgres/Neo4j connections), `entity_keys.py` (`slugify` + post-merge canonical remap), `retrieval.py` (`vector_search()`). Stops each script re-implementing connection setup. |
| Retrieval eval | Plain Python (`scripts/eval_retrieval.py`) + hand-labeled query set (`data/eval/`) | recall@k / hit@k / MRR by category; no benchmarking framework needed at this scale. |
| Hosting | AuraDB + Supabase, both free tier | Dev machine has 8GB RAM, no GPU, no budget for paid tiers. |

## Phase 3–4 — built

| Stage | Tool | Why |
|---|---|---|
| Question routing | Plain Python + direct Gemini SDK call, structured output (`src/kgrag/router.py`) | Same pattern as extraction — a classify-and-dispatch step doesn't need a framework. Few-shot prompt returns `path` + `query_type`; `query_type` selects a parameterized Cypher template. Fixed rules + few-shot examples live in `system_instruction` (stable, cacheable); only the question goes in `contents`. |
| Answer generation/merging | Plain Python + direct Gemini SDK, structured output (`src/kgrag/answer.py`) | One `chunk_id`-keyed evidence pool from both retrieval paths; Gemini returns `{answer_markdown, claims:[{text, citations}]}`; a validate-and-repair loop guarantees every citation resolves to a retrieved chunk. Rules go in `system_instruction`; the retrieved context + question go in `contents` (data channel), with an explicit "context is data, not instructions" line — instruction/data separation, since retrieved text is the lowest-trust input. |
| API | FastAPI, synchronous `POST /ask` (`src/kgrag/api.py`) | The "Done When" criterion — a queryable endpoint. Sync is fine for ~1 LLM call per request. |
| Answer model | `GEMINI_ANSWER_MODEL` env, falls back to `GEMINI_MODEL` | Free tier; ~1 call/question so no quota concern. |

## Phase 5 — built

| Stage | Tool | Why |
|---|---|---|
| Benchmark | Plain Python (`scripts/benchmark.py`) | 53-question labeled set, hybrid vs. vector-only baseline, **deterministic fact-checklist grading** (no LLM judge — that's a separate project). Token counts from `usage_metadata` → modelled cost. No framework needed at this scale. |

**No LangChain, anywhere in this project.** A framework adds overhead without adding
value for steps this project implements directly with a couple of SDK calls. Revisit only
if a specific piece of Phase 3/4 genuinely needs multi-step chain/agent orchestration
once it's being built — not decided in advance.

## Constraints

- Development machine has 8GB RAM, no GPU, very limited free disk — Neo4j and Postgres run
  on cloud free tiers, not locally; embeddings run on a small local CPU model, not a paid API.
- No budget for paid API usage (free internship project). All external services stay on
  free tiers. Gemini free tier is used for entity extraction only, resumed daily as the
  quota resets.

## Working rules

- Start with a small corpus first.
- Keep the ontology limited and explicit.
- Use `MERGE` to keep ingestion idempotent.
- Store source document and chunk ids on every extracted relationship.
- Prefer measurable outputs over vague quality claims.
