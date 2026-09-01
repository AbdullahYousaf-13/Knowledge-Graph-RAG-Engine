# Evaluation query set

`retrieval_queries.jsonl` (53 hand-labeled questions) drives three evals:

- `scripts/eval_retrieval.py` — vector-retrieval recall@k / hit@k / MRR (Phase 2 gate).
- `scripts/eval_routing.py` — router accuracy vs. `expected_path` (Phase 3 gate).
- `scripts/benchmark.py` — end-to-end answer accuracy, hybrid vs. vector-only baseline,
  by hop count, plus latency and modelled cost (Phase 5).

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
| `hops` | `1` \| `2` \| `3` \| `"agg"` \| `0` — difficulty stratum for the Phase 5 benchmark. `0` = out-of-scope. `3` on this single-company corpus is mostly 3-year-trend questions (genuine graph 3-hop barely exists here). |
| `gold` | the answer key for `scripts/benchmark.py`. Either `{"facts": [...]}` or `{"must_refuse": true}` (out-of-scope). |

The corpus is 225 substantive chunks (Apple 10-K, 2023–2025), so chunk ids are stable.
When a disclosure repeats across years (e.g. the segment list), list **every** recurring
chunk id so recall@k credits retrieving any of them.

`relevant_chunk_ids` is **optional**: the ~21 benchmark-only questions (added in Phase 5)
have `gold` but no verified chunk ids, and `eval_retrieval.py` skips them from scoring.

## Ground-truth rules

`relevant_chunk_ids` come from **reading the filing**, never from what the retriever
returned. The system under test does not get to define its own answer key.

`gold.facts` grading (`benchmark.py`): each list item is a required substring, or a
nested list of alternatives (any one satisfies it). The answer text and the facts are
normalised — lowercase, strip `$` and `,`, `%` → ` percent`, collapse whitespace — then
each fact is checked as a substring. `correct` = all facts present; `partial` = some;
`wrong` = none. `must_refuse` = `correct` iff the system returned the out-of-scope
refusal. Keep facts short and distinctive (`"$110 billion"`, `"Ernst & Young"`,
`"24.1%"`); review every `wrong`/`partial` by hand after a run — the grader is strict on
phrasing.

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
- **multi-hop** — entity-connection reasoning: connection chains (A → B → C), comparisons
  across entities, and aggregations over relationships. These are the questions BASWE
  Phase 3 says to route to the graph.
- **aggregation** — the full answer is spread over several chunks (a list), or is a tally of
  one entity's graph relationships.
- **out-of-scope** — not answerable from the corpus. Scored on score distribution only
  (a Phase 3 router-threshold signal), not recall.

## Running

```
python scripts/eval_retrieval.py                          # recall@k report + retrieval_<UTC>.json
python scripts/eval_retrieval.py --ef-sweep 32,64,100,200,400
python scripts/eval_routing.py                            # routing accuracy + routing_<UTC>.json
python scripts/benchmark.py --validate                    # check hops + gold on every row
python scripts/benchmark.py --limit 6                     # smoke a few
python scripts/benchmark.py                               # full run -> benchmark_<UTC>.json + benchmark_table.md
```

53 questions × 225 chunks is **directional, not statistically tight** — use these numbers
to catch regressions and gross failures, not to fine-tune.
