## Benchmark — hybrid vs. vector-only baseline

Apple 10-K corpus (FY2023–2025, 225 chunks). 53 questions, graded by a deterministic fact checklist. Model: `gemini-3.5-flash-lite`. 2026-09-01.

| Question type | n | Vector-only accuracy | Hybrid accuracy | Δ |
|---|--:|--:|--:|--:|
| single-hop | 18 | 0.94 | 0.89 | -0.05 |
| two-hop | 12 | 0.83 | 0.92 | +0.08 |
| three-hop | 6 | 0.67 | 0.67 | +0.00 |
| aggregation | 9 | 0.56 | 0.56 | +0.00 |
| out-of-scope | 8 | 0.00 | 1.00 | +1.00 |
| **overall** | 53 | **0.68** | **0.83** | **+0.15** |

**Latency** (model + retrieval only, excludes free-tier pacing): vector-only p50 5209 ms / p95 7636 ms · hybrid p50 6276 ms / p95 13152 ms

**Cost per 1,000 queries** (modelled at $0.10/$0.40 per 1M tokens; $0 actual on the free tier): vector-only $0.54 · hybrid $0.85

**One-time graph ingestion**: ~225 Gemini extraction calls (one per chunk), $0 on the free tier used. Embeddings run locally on CPU; the Neo4j + pgvector loads are free.
