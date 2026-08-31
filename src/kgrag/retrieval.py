"""Reusable vector search over ``sec_chunk_embeddings``.

Imported by ``scripts/eval_retrieval.py`` now and by the Phase 3 router / Phase 4
answer-merger later. The ``entity_keys`` filter (array overlap against the GIN index)
is the exact primitive the router will call for entity-scoped retrieval.

The query MUST be embedded with the same model used to build the index
(``all-MiniLM-L6-v2``, 384-dim). ``get_model`` enforces the dimension.
"""

from __future__ import annotations

import argparse
import functools
import os
from dataclasses import dataclass

from .db import VECTOR_TABLE, connect

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

# HNSW is approximate; ef_search trades recall for latency at query time. Set to a
# known operating point so the eval is reproducible. Swept over {32..400} + an exact
# ceiling (scripts/eval_retrieval.py --ef-sweep): recall is flat at this corpus size
# (225 vectors, no approximation loss), so 64 is as good as any.
HNSW_EF_SEARCH = int(os.getenv("HNSW_EF_SEARCH", "64"))


@dataclass
class RetrievedChunk:
    chunk_id: str
    company: str
    filing_year: str
    section_name: str
    text: str
    entity_keys: list[str]
    score: float  # cosine similarity in [-1, 1]; higher is closer


@functools.lru_cache(maxsize=2)
def get_model(name: str | None = None):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(name or EMBEDDING_MODEL)
    get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    dim = get_dim()
    if dim != EMBEDDING_DIM:
        raise SystemExit(
            f"Embedding model '{name or EMBEDDING_MODEL}' has dim {dim}, expected {EMBEDDING_DIM}. "
            "The index was built with a different model - retrieval would be meaningless."
        )
    return model


def embed_query(question: str, model=None) -> list[float]:
    model = model or get_model()
    return model.encode([question], show_progress_bar=False, convert_to_numpy=True)[0].tolist()


def vector_search(
    question: str,
    k: int = 10,
    *,
    conn=None,
    entity_keys: list[str] | None = None,
    model=None,
) -> list[RetrievedChunk]:
    """Top-k chunks by cosine similarity, optionally restricted to chunks that mention
    at least one of ``entity_keys``."""
    q = embed_query(question, model=model)

    where = ""
    # pgvector accepts its text form "[f, f, ...]"; a Python list's repr is exactly that.
    params: dict = {"q": str(q), "k": k}
    if entity_keys:
        where = "WHERE entity_keys && %(ek)s"
        params["ek"] = list(entity_keys)

    sql = f"""
        SELECT chunk_id, company, filing_year, section_name, text, entity_keys,
               1 - (embedding <=> %(q)s::vector) AS score
        FROM {VECTOR_TABLE}
        {where}
        ORDER BY embedding <=> %(q)s::vector
        LIMIT %(k)s
    """

    own_conn = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            # SET does not take bind params; HNSW_EF_SEARCH is coerced to int above.
            cur.execute(f"SET LOCAL hnsw.ef_search = {int(HNSW_EF_SEARCH)}")
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        if own_conn:
            conn.close()

    return [
        RetrievedChunk(
            chunk_id=r[0],
            company=r[1],
            filing_year=r[2],
            section_name=r[3],
            text=r[4],
            entity_keys=list(r[5] or []),
            score=float(r[6]),
        )
        for r in rows
    ]


def _main() -> None:
    parser = argparse.ArgumentParser(description="Vector search smoke test.")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--entity", action="append", help="Restrict to chunks mentioning this entity_key (repeatable).")
    parser.add_argument("-f", "--full", action="store_true", help="Print each chunk's full text.")
    parser.add_argument("--chars", type=int, default=140, help="Preview length when not --full (default 140).")
    args = parser.parse_args()

    hits = vector_search(args.question, k=args.k, entity_keys=args.entity)
    for i, h in enumerate(hits, 1):
        print(f"\n{'=' * 70}")
        print(f"{i:>2}. {h.score:.3f}  {h.chunk_id}  [{h.section_name}]")
        print(f"    entities: {', '.join(h.entity_keys) or '(none)'}")
        print("-" * 70)
        if args.full:
            print(h.text.strip())
        else:
            print(" ".join(h.text.split())[: args.chars] + " ...")


if __name__ == "__main__":
    _main()
