# Project Goal and Phases

## Goal

This project is a hybrid knowledge graph RAG system built over SEC filings.

The goal is to answer multi-hop questions by combining graph retrieval and vector retrieval with citations.

In practice, the system should:

- extract entities and relationships into Neo4j
- build a vector index over the same document chunks in pgvector
- route each question to the best retrieval path
- merge graph and vector results into one grounded answer
- return citations for every claim
- benchmark the system against a vector-only baseline

## Project Phases

### Phase 1: Extract entities and relationships into Neo4j

- Choose a small set of SEC filings from the public EDGAR data source. — **Done**
- Define a limited ontology before coding. — **Done, tightened to match spec range (8-15 relationship types).** `entity_type`/`relation_type` are a closed set (8 entity types, 14 relation types + `RELATED_TO` catch-all = 15 total), enforced via `Literal[...]` in the Pydantic schema. Existing data remapped twice, not re-extracted either time.
- Chunk documents and extract structured entities and relationships. — **Done.** Extraction
  retries every transient failure (schema `ValidationError`, empty/truncated response, 5xx/network),
  not just quota; chunks that exhaust retries land in `extractions_failed.jsonl`.
- Resolve duplicate entities so the same real-world item becomes one graph node. — **Done, and now baked into ingestion, not just a one-time cleanup.** Original pass: name-embedding similarity search found 101 candidate pairs, each reviewed before applying (13 groups merged). Follow-up: `src/kgrag/entity_resolution.py` wires two-tier resolution into `load_to_neo4j.py` itself — exact match, then embedding similarity with a conservative auto-merge bar and a human-review queue for anything less certain — so new extraction runs won't silently recreate the same duplicates.
- Store source chunk IDs so every edge can be traced back to evidence. — **Done**

**Phase 1 is complete.**

### Phase 2: Build the vector index alongside the graph

- Embed the same chunks into pgvector. — **Done**
- Store metadata such as document id, section path, date, and referenced entity ids. — **Done.** `sec_chunk_embeddings` has an `entity_keys TEXT[]` column (+ GIN index), backfilled from `extractions.jsonl` with the post-merge canonical-key remap and verified against Neo4j (`scripts/backfill_entity_keys.py`). Named `entity_keys`, not `entity_ids`, because the values are `slugify(name)` slugs — the same key Neo4j uses.
- Use shared chunk IDs between the graph and vector store. — **Done**
- Measure retrieval quality before building any routing logic. — **Done.** Hand-labeled queries (`data/eval/retrieval_queries.jsonl`), recall@k / hit@k / MRR by category via `scripts/eval_retrieval.py`, baseline results in `data/eval/results/`. Overall hit@5 0.90 / recall@5 0.54 / MRR 0.78.
- Tune `ef_search`. — **Done.** `scripts/eval_retrieval.py --ef-sweep` runs the eval over {32,64,100,200,400} plus a brute-force exact-recall ceiling; recall/MRR are flat at every value (225 vectors ⇒ no HNSW approximation loss), so `ef_search` stays at 64. `data/eval/results/ef_sweep_20260828T121309Z.json`.

Also switched the vector index from `ivfflat` to `hnsw` (the `lists=100` ivfflat over 225 rows was pathological). Shared retrieval/db code moved into `src/kgrag/`.

**Phase 2 is complete.** The recall@k baseline is what Phase 5 compares the hybrid system against.

See `LIVING_SPECS.md` for current data counts and build state, and `WHAT_WE_DID_AND_WHY.md` for full reasoning.

### Phase 3: Route questions to the right retrieval path

**Approach:** plain Python + direct Gemini SDK call with structured output (same pattern as extraction) — no LangChain. See `TECH_STACK.md` for the full tool table and reasoning.

- Add a lightweight router (a **few-shot** prompt returning an enum) that chooses graph, vector, both, or out-of-scope. — **Done.** `src/kgrag/router.py`; ~10 hand-written examples in `ROUTER_FEW_SHOT`, disjoint from the eval set.
- Use graph retrieval for multi-hop, comparison, and relationship questions. — **Done**, with a caveat: on this corpus only ~4/27 labeled test questions genuinely need it (most filing content isn't captured as a graph relationship).
- Use vector retrieval for definitions, policy lookups, and single-fact questions. — **Done**
- Keep graph queries parameterized instead of letting the model write raw Cypher, in a **template library keyed by query type**. — **Done.** `RouteDecision.query_type` (`connection` / `multi_hop` / `comparison` / `aggregation` / `none`) selects the Cypher template in `src/kgrag/graph_retrieval.py`; the model fills only the enum and entity names. Includes a new aggregation template (`entity_relation_summary`).
- Measure routing accuracy before calling it done. — **Done.** 96.3% (26/27) on the labeled set, `scripts/eval_routing.py` (was 87.5% before the few-shot examples). See `LIVING_SPECS.md` for the full breakdown.
- Low-confidence fallback that runs both paths, and a persistent log of every routing decision. — **Done.** `RouteDecision.confidence` + `execute_route()` fallback (default threshold 0.6), `data/logs/routing_log.jsonl` (includes `query_type`).

**Phase 3 is complete.** See `LIVING_SPECS.md` for the two real bugs found and fixed during testing (hub-node noise, ambiguous name matching), and for a real mistake made and fixed while trimming the ontology (a stale reload script briefly recreated 14 already-merged duplicate entities before being caught and corrected).

### Phase 4: Merge both sources into one grounded answer

**Approach:** plain Python + direct Gemini SDK, FastAPI endpoint — no LangChain. `src/kgrag/answer.py` + `src/kgrag/api.py`.

- Convert graph paths into readable statements. — **Done.** Each `GraphFact.description` (a natural-language sentence written at extraction time) becomes a "FACT:" line under a `## GRAPH-DERIVED FACTS` heading, followed by the source chunk's full text.
- Combine graph facts and retrieved passages into one context block. — **Done.** `build_evidence()` collapses everything into one `chunk_id`-keyed `Evidence` pool (`origin` = vector / graph / both); `render_context()` renders `## GRAPH-DERIVED FACTS` and `## PASSAGES` as labelled sections.
- Deduplicate overlapping evidence. — **Done.** Merge is by `chunk_id`; a chunk retrieved by both paths appears once, marked `origin="both"`, carrying both its passage text and its graph statement(s).
- Require a citation for every claim and verify that each citation resolves to retrieved data. — **Done.** Gemini returns structured `{answer_markdown, claims:[{text, citations}]}`; `validate_and_repair()` re-prompts (default 2 retries) while any claim cites a `chunk_id` not in the evidence pool, then drops the still-unsupported claims and reports `claims_removed`. The answer can never cite a chunk that was not retrieved (guarded by `tests/test_answer.py`).
- `entity_relation_summary` (the aggregation Cypher) now also returns a sample of `source_chunk_id`s so aggregation claims are citable.
- `POST /ask` (synchronous) → route → retrieve → build context → synthesize → validate → JSON `{answer_markdown, claims, citations, claims_removed, route, out_of_scope}`. `GET /health`. `out_of_scope` routes return a canned refusal with no LLM call.

**Phase 4 is complete.** Run: `uvicorn kgrag.api:app` or `python -m kgrag.answer "<question>"`.

### Phase 5: Benchmark against plain vector RAG

**Approach:** plain Python — no LangChain, no external benchmarking framework needed for a labeled-set recall/accuracy comparison at this scale.

- Build a labeled question set with single-hop, multi-hop, aggregation, and out-of-scope questions.
- Compare the hybrid system to a vector-only baseline.
- Report accuracy by hop count, plus latency and cost per query.
- Put the benchmark results at the top of the README.

## Done When

The project is complete when a FastAPI endpoint can answer questions with validated citations and the README shows a benchmark table proving the hybrid approach against a vector-only baseline on SEC filings.
