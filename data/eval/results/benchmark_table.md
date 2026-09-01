## Benchmark — hybrid vs. vector-only baseline

Apple 10-K corpus (FY2023–2025, 225 chunks). 53 questions, graded by a deterministic fact checklist. Model: `gemini-3.1-flash-lite`. 2026-09-01.

| Question type | n | Vector-only accuracy | Hybrid accuracy | Δ |
|---|--:|--:|--:|--:|
| single-hop | 18 | 0.94 | 0.89 | -0.05 |
| two-hop | 12 | 0.67 | 0.75 | +0.08 |
| three-hop | 6 | 1.00 | 1.00 | +0.00 |
| aggregation | 9 | 0.56 | 0.67 | +0.11 |
| out-of-scope | 8 | 0.00 | 1.00 | +1.00 |
| **overall** | 53 | **0.68** | **0.85** | **+0.17** |

**Latency** (model + retrieval only, excludes free-tier pacing): vector-only p50 6444 ms / p95 9435 ms · hybrid p50 8517 ms / p95 19760 ms

**Cost per 1,000 queries** (modelled at $0.10/$0.40 per 1M tokens; $0 actual on the free tier): vector-only $0.49 · hybrid $1.25

**One-time graph ingestion**: ~225 Gemini extraction calls (one per chunk), $0 on the free tier used. Embeddings run locally on CPU; the Neo4j + pgvector loads are free.
