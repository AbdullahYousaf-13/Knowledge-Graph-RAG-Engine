# Retrieval evaluation set

`retrieval_queries.jsonl` is a hand-labeled query set used to measure vector-retrieval
quality (`scripts/eval_retrieval.py`) before any routing logic is built (Phase 2 gate).

## Schema

One JSON object per line:

| field | meaning |
|---|---|
| `id` | stable short id (`q001`, ...) |
| `question` | the natural-language query |
| `category` | `single-hop` \| `multi-hop` \| `aggregation` \| `out-of-scope` |
| `relevant_chunk_ids` | chunk ids that genuinely answer the question (order irrelevant). Empty for `out-of-scope`. |
| `filing_years` | which filing years the answer appears in (informational) |
| `notes` | why these chunks — the rationale for the label |
| `expected_path` | `vector` \| `graph` \| `both` \| `out_of_scope` — used by `scripts/eval_routing.py` (Phase 3 gate). Assigned by actually running the router's entity extraction + `kgrag.graph_retrieval.graph_search()` per query and checking whether real, relevant facts came back — not guessed from the question's wording or its `category`. On this corpus only ~4/27 questions genuinely need the graph (most filing content was never captured as a graph relationship to begin with, e.g. `SUPPLIES` has zero instances across the whole graph) — see `docs/WHAT_WE_DID_AND_WHY.md` for the full finding. |
| `query_type` | (graph queries only) `connection` \| `multi_hop` \| `comparison` \| `aggregation` — which parameterized Cypher template `graph_search` should use. |

The corpus is 225 substantive chunks (Apple 10-K, 2023–2025), so chunk ids are stable.
When a disclosure repeats across years (e.g. the segment list), list **every** recurring
chunk id so recall@k credits retrieving any of them.

## Ground-truth rule

`relevant_chunk_ids` come from **reading the filing**, never from what the retriever
returned. The system under test does not get to define its own answer key.

## How to add a query

1. Pick a question a reader could actually answer from the filings.
2. Find the chunk(s) that answer it — scan `data/processed/sec_filings/extractions.jsonl`
   (`summary` / `section_name` / `text` fields) or use
   `python -m kgrag.retrieval "<question>" -k 10` as a *hint* (not as the label).
3. Add a line; keep `id` sequential.
4. `python scripts/eval_retrieval.py --validate` — asserts every chunk id exists and
   categories are valid.

## Categories

- **single-hop** — one chunk answers it. Core recall signal; if `recall@5` is weak here
  the index/embedding is broken.
- **multi-hop** — needs ≥2 chunks, often across sections/years. Vector-only is expected
  to underperform; that gap is what the Phase 5 hybrid comparison targets.
- **aggregation** — the full answer is spread over several chunks (a list), or is a tally of
  one entity's graph relationships.
- **out-of-scope** — not answerable from the corpus. Scored on score distribution only
  (a Phase 3 router-threshold signal), not recall.

## Running

```
python scripts/eval_retrieval.py                 # report + write data/eval/results/retrieval_<UTC>.json
python scripts/eval_retrieval.py --k 1,3,5,10
python scripts/eval_retrieval.py --ef-search 200          # single HNSW ef_search override
python scripts/eval_retrieval.py --ef-sweep 32,64,100,200,400  # sweep + exact-recall ceiling
```

Metrics on 27 queries × 225 chunks are **directional, not statistically tight** — use
them to catch regressions and gross failures, not to fine-tune.
