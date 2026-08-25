# Tech Stack — Locked

What we use, why, for every stage. See `PROJECT_GOAL_AND_PHASES.md` for the phase-by-phase build plan, and `LIVING SPECS.md` for live project status and open items.

## Phase 1-2 — built

| Stage | Tool | Why |
|---|---|---|
| Chunking | Plain Python/regex, hand-built (`prepare_sec_filings.py`) | Structure-aware (SEC section boundaries + whole-paragraph overlap) — more precise than a generic splitter for this one document type. No LangChain. |
| Entity/relationship extraction | `google-genai` SDK + Pydantic structured output (`extract_sec_entities.py`) | Forces valid JSON from Gemini, no parsing failures, full control over the schema |
| Graph storage | `neo4j` Python driver + hand-written Cypher `MERGE` queries, AuraDB free tier (`load_to_neo4j.py`) | `MERGE` keeps ingestion idempotent; official driver gives full query control |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, local CPU) (`build_pgvector_index.py`) | Free, no quota, fast enough at this corpus size — avoids a paid embedding API |
| Vector storage/search | `psycopg` + `pgvector` extension, Supabase free tier, **HNSW index** | HNSW gives better recall than `ivfflat` at similar query speed, free to switch to. *(Locked decision — code currently still uses `ivfflat`; the code change is tracked as a separate follow-up, not yet applied.)* |
| Hosting | AuraDB + Supabase, both free tier | Dev machine has 8GB RAM, no GPU, no budget for paid tiers |

## Phase 3-5 — planned

| Stage | Tool | Why |
|---|---|---|
| Question routing | Plain Python + direct Gemini SDK call, structured output | Same pattern as extraction — a classify-and-dispatch step doesn't need a framework |
| Answer generation/merging | Plain Python + direct Gemini SDK | Consistent with the rest of the pipeline |
| API | FastAPI | Needed for the "Done When" criterion — a queryable endpoint |

**No LangChain, anywhere in this project.** Same reasoning that ruled it out for chunking applies to routing/orchestration: a framework adds overhead without adding value for steps this project can implement directly with a couple of SDK calls. Revisit only if a specific piece of Phase 3/4 genuinely turns out to need multi-step chain/agent orchestration once it's actually being built — not decided in advance.

## Corpus state

Both Neo4j and pgvector scoped to 2023-2025, 225 chunks each — matching, per the corpus-scope fix documented in `LIVING SPECS.md`.

## Constraints

- Development machine has 8GB RAM, no GPU, and very limited free disk space — Neo4j and Postgres run on cloud free tiers instead of locally, and embeddings run on a small local CPU model instead of a paid API.
- No budget for paid API usage (free internship project). All external services must stay on free tiers.
