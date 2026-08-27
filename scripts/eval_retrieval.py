"""Measure vector-retrieval quality against a hand-labeled query set.

Phase 2 gate: "measure retrieval quality before building any routing logic."
This computes recall@k / hit@k / MRR (broken down by query category) over
``data/eval/retrieval_queries.jsonl`` and writes a timestamped results file that
becomes the Phase 5 vector-only baseline.

Usage:
    python scripts/eval_retrieval.py --validate      # check the query set only
    python scripts/eval_retrieval.py                 # run, print report, write JSON
    python scripts/eval_retrieval.py --k 1,3,5,10 --ef-search 64
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kgrag.db import VECTOR_TABLE, connect
from kgrag import retrieval

BASE_DIR = Path(__file__).resolve().parent.parent
QUERY_PATH = BASE_DIR / "data" / "eval" / "retrieval_queries.jsonl"
RESULTS_DIR = BASE_DIR / "data" / "eval" / "results"

VALID_CATEGORIES = {"single-hop", "multi-hop", "aggregation", "out-of-scope"}
SCORED_CATEGORIES = VALID_CATEGORIES - {"out-of-scope"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_queries(path: Path = QUERY_PATH) -> list[dict]:
    queries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    return queries


def file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def git_rev() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BASE_DIR, text=True
        ).strip()
    except Exception:
        return None


def validate(queries: list[dict], conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SELECT chunk_id FROM {VECTOR_TABLE}")
        known = {r[0] for r in cur.fetchall()}

    ok = True
    seen_ids = set()
    for q in queries:
        qid = q.get("id", "<no id>")
        if qid in seen_ids:
            print(f"  {qid}: duplicate id")
            ok = False
        seen_ids.add(qid)
        if q.get("category") not in VALID_CATEGORIES:
            print(f"  {qid}: bad category {q.get('category')!r}")
            ok = False
        rel = q.get("relevant_chunk_ids", [])
        if q.get("category") == "out-of-scope":
            if rel:
                print(f"  {qid}: out-of-scope query must have empty relevant_chunk_ids")
                ok = False
        else:
            if not rel:
                print(f"  {qid}: no relevant_chunk_ids")
                ok = False
            for cid in rel:
                if cid not in known:
                    print(f"  {qid}: relevant chunk {cid!r} not in {VECTOR_TABLE}")
                    ok = False
    print(f"validate: {len(queries)} queries, {'OK' if ok else 'FAILED'}")
    return ok


def evaluate(queries: list[dict], ks: list[int], conn) -> dict:
    model = retrieval.get_model()
    max_k = max(ks)
    per_query = []

    for q in queries:
        hits = retrieval.vector_search(q["question"], k=max_k, conn=conn, model=model)
        retrieved_ids = [h.chunk_id for h in hits]
        rel = set(q.get("relevant_chunk_ids", []))

        rec = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "relevant_chunk_ids": sorted(rel),
            "retrieved_chunk_ids": retrieved_ids,
            "top_scores": [round(h.score, 4) for h in hits[:5]],
        }

        if q["category"] != "out-of-scope" and rel:
            first_rank = next(
                (i + 1 for i, cid in enumerate(retrieved_ids) if cid in rel), None
            )
            rec["reciprocal_rank"] = 1.0 / first_rank if first_rank else 0.0
            for k in ks:
                topk = set(retrieved_ids[:k])
                rec[f"recall@{k}"] = len(rel & topk) / len(rel)
                rec[f"hit@{k}"] = 1.0 if rel & topk else 0.0
        per_query.append(rec)

    # Aggregate over scored categories.
    scored = [r for r in per_query if r["category"] in SCORED_CATEGORIES]
    agg: dict = {"n_scored": len(scored), "by_category": {}}
    if scored:
        agg["MRR"] = round(sum(r["reciprocal_rank"] for r in scored) / len(scored), 4)
        for k in ks:
            agg[f"recall@{k}"] = round(sum(r[f"recall@{k}"] for r in scored) / len(scored), 4)
            agg[f"hit@{k}"] = round(sum(r[f"hit@{k}"] for r in scored) / len(scored), 4)

    for cat in sorted(VALID_CATEGORIES):
        rows = [r for r in per_query if r["category"] == cat]
        if not rows:
            continue
        entry: dict = {"n": len(rows)}
        if cat == "out-of-scope":
            top1 = [r["top_scores"][0] for r in rows if r["top_scores"]]
            top5 = [min(r["top_scores"]) for r in rows if r["top_scores"]]
            entry["mean_top1_score"] = round(sum(top1) / len(top1), 4) if top1 else None
            entry["mean_top5_floor_score"] = round(sum(top5) / len(top5), 4) if top5 else None
        else:
            entry["MRR"] = round(sum(r["reciprocal_rank"] for r in rows) / len(rows), 4)
            for k in ks:
                entry[f"recall@{k}"] = round(sum(r[f"recall@{k}"] for r in rows) / len(rows), 4)
                entry[f"hit@{k}"] = round(sum(r[f"hit@{k}"] for r in rows) / len(rows), 4)
        agg["by_category"][cat] = entry

    return {"aggregate": agg, "per_query": per_query}


def index_type(conn) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            (f"{VECTOR_TABLE}_embedding_idx",),
        )
        row = cur.fetchone()
    if not row:
        return None
    d = row[0].lower()
    return "hnsw" if "hnsw" in d else "ivfflat" if "ivfflat" in d else "other"


def print_report(result: dict, ks: list[int]) -> None:
    agg = result["aggregate"]
    print("\n=== retrieval quality ===")
    print(f"scored queries: {agg['n_scored']}   MRR: {agg.get('MRR')}")
    header = "category".ljust(14) + "n   " + "  ".join(f"R@{k}".rjust(6) for k in ks) + "   " + "  ".join(f"H@{k}".rjust(6) for k in ks) + "    MRR"
    print(header)
    print("-" * len(header))
    for cat, e in agg["by_category"].items():
        if cat == "out-of-scope":
            continue
        line = cat.ljust(14) + f"{e['n']:<4}"
        line += "  ".join(f"{e[f'recall@{k}']:.3f}".rjust(6) for k in ks) + "   "
        line += "  ".join(f"{e[f'hit@{k}']:.3f}".rjust(6) for k in ks) + f"   {e['MRR']:.3f}"
        print(line)
    oos = agg["by_category"].get("out-of-scope")
    if oos:
        print(f"\nout-of-scope (n={oos['n']}): mean top-1 score {oos['mean_top1_score']}, "
              f"mean top-5 floor {oos['mean_top5_floor_score']}  "
              f"(should sit below in-scope top-1 -> Phase 3 router threshold signal)")

    print("\nper-query:")
    for r in result["per_query"]:
        if r["category"] == "out-of-scope":
            print(f"  {r['id']:<6} OOS   top1={r['top_scores'][0] if r['top_scores'] else None}")
            continue
        hit5 = r.get("hit@5", 0.0)
        mark = "hit " if hit5 else "MISS"
        print(f"  {r['id']:<6} {mark}  RR={r['reciprocal_rank']:.2f}  gold={r['relevant_chunk_ids']}  got={r['retrieved_chunk_ids'][:5]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate", action="store_true", help="Only check the query set.")
    parser.add_argument("--k", default="1,3,5,10", help="Comma-separated k values.")
    parser.add_argument("--ef-search", type=int, default=None, help="Override HNSW ef_search.")
    parser.add_argument("--out", default=None, help="Results JSON path (default: data/eval/results/retrieval_<UTC>.json).")
    args = parser.parse_args()

    ks = sorted(int(x) for x in args.k.split(","))
    if args.ef_search is not None:
        retrieval.HNSW_EF_SEARCH = args.ef_search

    queries = load_queries()
    conn = connect()
    try:
        if not validate(queries, conn):
            sys.exit(1)
        if args.validate:
            return

        result = evaluate(queries, ks, conn)
        idx = index_type(conn)
    finally:
        conn.close()

    result["config"] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "embedding_model": retrieval.EMBEDDING_MODEL,
        "embedding_dim": retrieval.get_model().get_sentence_embedding_dimension(),
        "hnsw_ef_search": retrieval.HNSW_EF_SEARCH,
        "vector_index_type": idx,
        "k_values": ks,
        "query_set": str(QUERY_PATH.relative_to(BASE_DIR)),
        "query_set_sha1": file_sha1(QUERY_PATH),
        "n_queries": len(queries),
    }

    print_report(result, ks)

    out_path = Path(args.out) if args.out else RESULTS_DIR / f"retrieval_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
