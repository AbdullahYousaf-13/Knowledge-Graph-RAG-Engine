"""One-off diagnostic: for each labeled eval query, extract entities via the router's
Gemini call and run graph_search, so expected_path can be assigned by looking at real
output instead of guessing from question phrasing. Not part of the permanent pipeline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from google import genai

from kgrag import graph_retrieval, router

BASE_DIR = Path(__file__).resolve().parent.parent
QUERIES_PATH = BASE_DIR / "data" / "eval" / "retrieval_queries.jsonl"


def main() -> None:
    client = genai.Client()
    queries = []
    with QUERIES_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))

    for q in queries:
        print(f"\n{'=' * 80}")
        print(f"{q['id']} [{q['category']}]: {q['question']}")
        print(f"  notes: {q['notes']}")

        decision = router.route_question(q["question"], client=client)
        print(f"  router entities: {decision.entities}  (router's own path guess: {decision.path})")

        if q["category"] == "out-of-scope":
            print("  (skipping graph_search - out of scope)")
            time.sleep(4)
            continue

        facts = graph_retrieval.graph_search(decision.entities, hops=1) if decision.entities else []
        print(f"  graph facts (1 hop): {len(facts)}")
        for fact in facts[:8]:
            print(f"    {fact.source} -[{fact.relation_type}]-> {fact.target}   ({fact.source_chunk_id})")
        if len(facts) > 8:
            print(f"    ... and {len(facts) - 8} more")

        time.sleep(4)


if __name__ == "__main__":
    main()
