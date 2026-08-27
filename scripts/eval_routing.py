"""Measure routing accuracy against a hand-labeled query set.

Phase 3 gate, same discipline as Phase 2's eval_retrieval.py: don't call the router
"done" without a measured number. Computes accuracy (and a confusion breakdown) of
kgrag.router.route_question() against data/eval/retrieval_queries.jsonl's
expected_path field, and writes a timestamped results file to data/eval/results/.

expected_path was assigned by actually running the router's entity extraction +
graph_retrieval.graph_search() per query and checking what came back - not guessed
from question wording (see data/eval/README.md).

Usage:
    python scripts/eval_routing.py --validate   # check expected_path is set for every query
    python scripts/eval_routing.py               # run, print report, write JSON
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google import genai

from kgrag import router

BASE_DIR = Path(__file__).resolve().parent.parent
QUERY_PATH = BASE_DIR / "data" / "eval" / "retrieval_queries.jsonl"
RESULTS_DIR = BASE_DIR / "data" / "eval" / "results"

VALID_PATHS = {"vector", "graph", "both", "out_of_scope"}
MIN_DELAY_SECONDS = 4.0

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_queries(path: Path = QUERY_PATH) -> list[dict]:
    queries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def git_rev() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, text=True).strip()
    except Exception:
        return None


def validate(queries: list[dict]) -> bool:
    ok = True
    seen_ids = set()
    for q in queries:
        qid = q.get("id", "<no id>")
        if qid in seen_ids:
            print(f"  {qid}: duplicate id")
            ok = False
        seen_ids.add(qid)
        if q.get("expected_path") not in VALID_PATHS:
            print(f"  {qid}: missing/invalid expected_path {q.get('expected_path')!r}")
            ok = False
    print(f"validate: {len(queries)} queries, {'OK' if ok else 'FAILED'}")
    return ok


def evaluate(queries: list[dict]) -> dict:
    client = genai.Client()
    per_query = []
    last_call_at = None

    for q in queries:
        if last_call_at is not None:
            elapsed = time.monotonic() - last_call_at
            wait = max(0.0, MIN_DELAY_SECONDS - elapsed)
            if wait:
                time.sleep(wait)
        decision = router.route_question(q["question"], client=client)
        last_call_at = time.monotonic()

        correct = decision.path == q["expected_path"]
        per_query.append(
            {
                "id": q["id"],
                "question": q["question"],
                "expected_path": q["expected_path"],
                "actual_path": decision.path,
                "correct": correct,
                "entities": decision.entities,
                "reasoning": decision.reasoning,
            }
        )
        print(f"  {q['id']}  expected={q['expected_path']:<12} actual={decision.path:<12} {'OK' if correct else 'MISS'}")

    n = len(per_query)
    n_correct = sum(1 for r in per_query if r["correct"])
    confusion = Counter((r["expected_path"], r["actual_path"]) for r in per_query)

    return {
        "accuracy": round(n_correct / n, 4) if n else None,
        "n": n,
        "n_correct": n_correct,
        "confusion": {f"{exp}->{act}": count for (exp, act), count in sorted(confusion.items())},
        "per_query": per_query,
    }


def print_report(result: dict) -> None:
    print("\n=== routing accuracy ===")
    print(f"accuracy: {result['accuracy']}  ({result['n_correct']}/{result['n']})")
    print("\nconfusion (expected -> actual : count):")
    for key, count in result["confusion"].items():
        marker = "" if key.split("->")[0] == key.split("->")[1] else "  <-- mismatch"
        print(f"  {key}: {count}{marker}")

    misses = [r for r in result["per_query"] if not r["correct"]]
    if misses:
        print(f"\n{len(misses)} miss(es):")
        for r in misses:
            print(f"  {r['id']}  expected={r['expected_path']}  got={r['actual_path']}  entities={r['entities']}")
            print(f"      router reasoning: {r['reasoning']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate", action="store_true", help="Only check expected_path is set for every query.")
    parser.add_argument("--out", default=None, help="Results JSON path (default: data/eval/results/routing_<UTC>.json).")
    args = parser.parse_args()

    queries = load_queries()
    if not validate(queries):
        sys.exit(1)
    if args.validate:
        return

    result = evaluate(queries)
    result["config"] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "model": router.MODEL_NAME,
        "query_set": str(QUERY_PATH.relative_to(BASE_DIR)),
        "query_set_sha1": file_sha1(QUERY_PATH),
        "n_queries": len(queries),
    }

    print_report(result)

    out_path = Path(args.out) if args.out else RESULTS_DIR / f"routing_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
