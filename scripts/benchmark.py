"""Phase 5: benchmark the hybrid answerer against a vector-only baseline.

Runs both systems over ``data/eval/retrieval_queries.jsonl``, grades each answer with a
deterministic fact checklist, and reports answer accuracy by hop count plus latency and
a modelled cost per query. Writes ``data/eval/results/benchmark_<UTC>.json`` and
``data/eval/results/benchmark_table.md``.

    python scripts/benchmark.py --validate      # check every row has hops + gold
    python scripts/benchmark.py --limit 6       # smoke a few questions
    python scripts/benchmark.py                 # full run (free-tier paced, ~40-60 min)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from google import genai

from kgrag import answer

BASE_DIR = Path(__file__).resolve().parent.parent
QUERY_PATH = BASE_DIR / "data" / "eval" / "retrieval_queries.jsonl"
RESULTS_DIR = BASE_DIR / "data" / "eval" / "results"
PROGRESS_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "extractions_progress.json"

# Free tier caps the flash-lite model at ~15 requests/minute; each question makes
# several Gemini calls (router + synthesis + repair, x2 systems). Pace every individual
# call and retry on 429 rather than pacing per question.
PER_CALL_DELAY = float(os.getenv("BENCH_PER_CALL_DELAY", "4.5"))
MAX_429_RETRIES = int(os.getenv("BENCH_MAX_429_RETRIES", "6"))

# Modelled cost only - the project runs on the Gemini free tier ($0 actual). Rates are
# for the gemini-2.5-flash-lite class, USD per 1M tokens. Verify for your configured
# model at https://ai.google.dev/gemini-api/docs/pricing and override via env.
PRICE_IN = float(os.getenv("PRICE_PER_1M_INPUT", "0.10"))
PRICE_OUT = float(os.getenv("PRICE_PER_1M_OUTPUT", "0.40"))

HOP_ORDER = ["1", "2", "3", "agg", "0"]
HOP_LABEL = {"1": "single-hop", "2": "two-hop", "3": "three-hop", "agg": "aggregation", "0": "out-of-scope"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --- token accounting -----------------------------------------------------


def _retry_delay(exc: Exception) -> float:
    m = re.search(r"retry(?:Delay)?[^0-9]*([0-9.]+)s", str(exc), re.IGNORECASE)
    return float(m.group(1)) if m else 0.0


class _CountingModels:
    def __init__(self, real):
        self._real = real
        self.in_tokens = 0
        self.out_tokens = 0
        self.slept = 0.0  # pacing/backoff seconds, excluded from the latency number
        self._last_call = 0.0

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
            self.slept += seconds

    def generate_content(self, **kwargs):
        for attempt in range(1, MAX_429_RETRIES + 1):
            self._sleep(PER_CALL_DELAY - (time.monotonic() - self._last_call))
            try:
                response = self._real.generate_content(**kwargs)
                self._last_call = time.monotonic()
                break
            except Exception as exc:  # noqa: BLE001 - narrow check below
                self._last_call = time.monotonic()
                msg = str(exc)
                rate = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                transient = any(m in msg for m in ("500", "502", "503", "504", "UNAVAILABLE",
                                                   "INTERNAL", "DEADLINE_EXCEEDED"))
                if not (rate or transient) or attempt == MAX_429_RETRIES:
                    raise
                backoff = (max(_retry_delay(exc), 15.0 * attempt) if rate else 8.0 * attempt) + 1.0
                print(f"    [{'429' if rate else '5xx'}] attempt {attempt}/{MAX_429_RETRIES}, sleeping {backoff:.0f}s")
                self._sleep(backoff)

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.in_tokens += getattr(usage, "prompt_token_count", 0) or 0
            self.out_tokens += getattr(usage, "candidates_token_count", 0) or 0
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class CountingClient:
    """Wraps genai.Client and sums usage_metadata token counts across every call, so a
    whole answer_question() run (router + synthesis + repair) is one measurement."""

    def __init__(self, real: genai.Client):
        self._real = real
        self.models = _CountingModels(real.models)

    def reset(self) -> None:
        self.models.in_tokens = 0
        self.models.out_tokens = 0
        self.models.slept = 0.0

    def __getattr__(self, name):
        return getattr(self._real, name)


# --- grading -------------------------------------------------------------


def _norm(text: str) -> str:
    text = text.lower().replace("$", "").replace(",", "").replace("%", " percent")
    return re.sub(r"\s+", " ", text).strip()


def _fact_present(fact, normed_text: str) -> bool:
    # a fact is a required substring, or a list of alternatives (any one satisfies it)
    if isinstance(fact, list):
        return any(_norm(alt) in normed_text for alt in fact)
    return _norm(fact) in normed_text


_REFUSAL_MARKERS = (
    "does not contain", "not contain information", "no mention of", "context does not",
    "cannot answer", "unable to answer", "no relevant information",
)


def grade(result: answer.AnswerResult, gold: dict) -> str:
    if gold.get("must_refuse"):
        return "correct" if result.out_of_scope else "wrong"
    facts = gold.get("facts", [])
    if not facts:
        return "unscored"
    text = _norm(result.answer_markdown)
    # an in-scope answer that punts can't be "correct" even if a gold string
    # coincidentally appears in the hedge (e.g. a wrong-year aside)
    if any(marker in text for marker in _REFUSAL_MARKERS):
        return "wrong"
    hits = sum(1 for f in facts if _fact_present(f, text))
    if hits == len(facts):
        return "correct"
    return "partial" if hits else "wrong"


# --- run ---------------------------------------------------------------


def load_queries() -> list[dict]:
    return [json.loads(line) for line in QUERY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def file_sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def git_rev() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, text=True).strip()
    except Exception:
        return None


def validate(queries: list[dict]) -> bool:
    ok = True
    for q in queries:
        qid = q.get("id", "<no id>")
        if "hops" not in q or str(q["hops"]) not in HOP_ORDER:
            print(f"  {qid}: missing/invalid hops {q.get('hops')!r}")
            ok = False
        gold = q.get("gold")
        if not isinstance(gold, dict) or not (gold.get("facts") or gold.get("must_refuse")):
            print(f"  {qid}: missing gold.facts / gold.must_refuse")
            ok = False
    print(f"validate: {len(queries)} queries, {'OK' if ok else 'FAILED'}")
    return ok


def run_one(q: dict, *, cc: CountingClient, force_path: str | None) -> dict:
    cc.reset()
    t0 = time.perf_counter()
    result = answer.answer_question(q["question"], client=cc, force_path=force_path)
    latency_ms = (time.perf_counter() - t0 - cc.models.slept) * 1000.0  # exclude pacing/backoff
    cost = (cc.models.in_tokens * PRICE_IN + cc.models.out_tokens * PRICE_OUT) / 1_000_000
    return {
        "id": q["id"],
        "hops": str(q["hops"]),
        "verdict": grade(result, q.get("gold", {})),
        "latency_ms": round(latency_ms, 1),
        "in_tokens": cc.models.in_tokens,
        "out_tokens": cc.models.out_tokens,
        "cost_usd": cost,
        "route": result.route["effective_path"],
        "n_claims": len(result.claims),
        "claims_removed": result.claims_removed,
        "answer": result.answer_markdown,
    }


CHECKPOINT = RESULTS_DIR / "benchmark_progress.jsonl"


def benchmark(queries: list[dict]) -> list[dict]:
    cc = CountingClient(genai.Client())

    # Resume: the free tier is flaky (rate limits, 503s). Every completed (id, system)
    # is appended to a checkpoint file and skipped on a re-run.
    per_query: list[dict] = []
    done: set[tuple[str, str]] = set()
    if CHECKPOINT.exists():
        for line in CHECKPOINT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                per_query.append(rec)
                done.add((rec["id"], rec["system"]))
        print(f"  resuming: {len(done)} (question, system) pairs already done")

    if not done:  # warm up connections + embedding model on a fresh run
        print("  (warmup)")
        try:
            answer.answer_question("What day does Apple's fiscal year end on?", client=cc, force_path="vector")
        except Exception as exc:
            print(f"  warmup failed (continuing): {exc}")

    with CHECKPOINT.open("a", encoding="utf-8") as ckpt:
        for idx, q in enumerate(queries, 1):
            for system, force_path in (("baseline", "vector"), ("hybrid", None)):
                if (q["id"], system) in done:
                    continue
                rec = run_one(q, cc=cc, force_path=force_path)
                rec["system"] = system
                per_query.append(rec)
                ckpt.write(json.dumps(rec) + "\n")
                ckpt.flush()
                print(f"  [{idx}/{len(queries)}] {q['id']:<6} {system:<9} {rec['verdict']:<8} "
                      f"{rec['latency_ms']:>7.0f}ms  route={rec['route']}")
    return per_query


# --- aggregate + render ------------------------------------------------


def _pct(xs: list, pct: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * pct))]


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    lat = [r["latency_ms"] for r in rows]
    return {
        "n": n,
        "accuracy": round(sum(r["verdict"] == "correct" for r in rows) / n, 3),
        "partial": round(sum(r["verdict"] == "partial" for r in rows) / n, 3),
        "mean_latency_ms": round(sum(lat) / n, 1),
        "p50_latency_ms": round(_pct(lat, 0.5), 1),
        "p95_latency_ms": round(_pct(lat, 0.95), 1),
        "mean_tokens": round(sum(r["in_tokens"] + r["out_tokens"] for r in rows) / n),
        "cost_per_1k_usd": round(sum(r["cost_usd"] for r in rows) / n * 1000, 4),
    }


def aggregate(per_query: list[dict]) -> dict:
    by_bucket: dict[tuple, list[dict]] = defaultdict(list)
    for r in per_query:
        by_bucket[(r["hops"], r["system"])].append(r)

    by_hop = []
    for hop in HOP_ORDER:
        entry = {"hop": hop, "label": HOP_LABEL[hop]}
        for system in ("baseline", "hybrid"):
            rows = by_bucket.get((hop, system))
            if rows:
                entry[system] = _summary(rows)
        if len(entry) > 2:
            by_hop.append(entry)

    overall = {system: _summary([r for r in per_query if r["system"] == system])
               for system in ("baseline", "hybrid")}
    return {"by_hop": by_hop, "overall": overall}


def ingestion_cost() -> dict:
    calls = 0
    try:
        prog = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        calls = sum(1 for v in prog.values() if isinstance(v, dict) and v.get("status") == "completed")
    except Exception:
        pass
    return {
        "extraction_calls": calls,
        "note": (f"~{calls} Gemini extraction calls (one per chunk), $0 on the free tier used. "
                 "Embeddings run locally on CPU; the Neo4j + pgvector loads are free."),
    }


def render_table(agg: dict, ingest: dict, n_queries: int) -> str:
    o = agg["overall"]
    lines = [
        "## Benchmark — hybrid vs. vector-only baseline",
        "",
        f"Apple 10-K corpus (FY2023–2025, 225 chunks). {n_queries} questions, graded by a "
        f"deterministic fact checklist. Model: `{answer.ANSWER_MODEL}`. "
        f"{datetime.now(timezone.utc):%Y-%m-%d}.",
        "",
        "| Question type | n | Vector-only accuracy | Hybrid accuracy | Δ |",
        "|---|--:|--:|--:|--:|",
    ]
    for row in agg["by_hop"]:
        b = row.get("baseline")
        h = row.get("hybrid")
        if not (b and h):
            continue
        delta = h["accuracy"] - b["accuracy"]
        lines.append(f"| {row['label']} | {b['n']} | {b['accuracy']:.2f} | {h['accuracy']:.2f} | "
                     f"{delta:+.2f} |")
    delta = o["hybrid"]["accuracy"] - o["baseline"]["accuracy"]
    lines.append(f"| **overall** | {o['baseline']['n']} | **{o['baseline']['accuracy']:.2f}** | "
                 f"**{o['hybrid']['accuracy']:.2f}** | **{delta:+.2f}** |")
    lines += [
        "",
        f"**Latency** (model + retrieval only, excludes free-tier pacing): "
        f"vector-only p50 {o['baseline']['p50_latency_ms']:.0f} ms / p95 {o['baseline']['p95_latency_ms']:.0f} ms · "
        f"hybrid p50 {o['hybrid']['p50_latency_ms']:.0f} ms / p95 {o['hybrid']['p95_latency_ms']:.0f} ms",
        "",
        f"**Cost per 1,000 queries** (modelled at ${PRICE_IN:.2f}/${PRICE_OUT:.2f} per 1M tokens; "
        f"$0 actual on the free tier): vector-only ${o['baseline']['cost_per_1k_usd']:.2f} · "
        f"hybrid ${o['hybrid']['cost_per_1k_usd']:.2f}",
        "",
        f"**One-time graph ingestion**: {ingest['note']}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate", action="store_true", help="Only check hops + gold on every row.")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N questions.")
    parser.add_argument("--fresh", action="store_true", help="Ignore any resume checkpoint and start over.")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    queries = load_queries()
    if not validate(queries):
        sys.exit(1)
    if args.validate:
        return
    if args.limit:
        queries = queries[: args.limit]
    if args.fresh and CHECKPOINT.exists():
        CHECKPOINT.unlink()

    started = time.monotonic()
    per_query = benchmark(queries)
    wall_clock_s = round(time.monotonic() - started, 1)

    agg = aggregate(per_query)
    ingest = ingestion_cost()
    table = render_table(agg, ingest, len(queries))

    result = {
        "aggregate": agg,
        "ingestion": ingest,
        "per_query": per_query,
        "config": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_rev": git_rev(),
            "model": answer.ANSWER_MODEL,
            "price_per_1m_input_usd": PRICE_IN,
            "price_per_1m_output_usd": PRICE_OUT,
            "query_set": str(QUERY_PATH.relative_to(BASE_DIR)),
            "query_set_sha1": file_sha1(QUERY_PATH),
            "n_queries": len(queries),
            "wall_clock_seconds": wall_clock_s,
        },
    }

    print("\n" + table)

    stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out_json = Path(args.out) if args.out else RESULTS_DIR / f"benchmark_{stamp}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    (RESULTS_DIR / "benchmark_table.md").write_text(table, encoding="utf-8")
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()  # full run finished cleanly
    print(f"\nwrote {out_json.relative_to(BASE_DIR)} and benchmark_table.md")


if __name__ == "__main__":
    main()
