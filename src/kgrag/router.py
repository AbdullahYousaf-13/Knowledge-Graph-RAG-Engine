"""Phase 3 question router: decide graph vs vector vs both vs out-of-scope.

Same structured-output pattern as ``scripts/extract_sec_entities.py`` - a Pydantic
schema forces Gemini's JSON output, so the model can only choose from a closed set of
paths and never writes a query itself. Graph retrieval always goes through
``graph_retrieval.py``'s fixed, parameterized Cypher templates.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from google import genai
from pydantic import BaseModel, Field

from . import graph_retrieval, retrieval

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
CONFIDENCE_THRESHOLD = float(os.getenv("ROUTER_CONFIDENCE_THRESHOLD", "0.6"))

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_PATH = BASE_DIR / "data" / "logs" / "routing_log.jsonl"

RoutePath = Literal["vector", "graph", "both", "out_of_scope"]


class RouteDecision(BaseModel):
    path: RoutePath = Field(
        description=(
            "vector: single-fact, definition, or policy-lookup question answerable from "
            "chunk text alone. graph: multi-hop, comparison, or relationship question about "
            "specific named entities (e.g. suppliers, competitors, regulations, lawsuits) "
            "where the connection between entities matters more than the surrounding prose. "
            "both: a relationship question that also needs supporting narrative detail. "
            "out_of_scope: not answerable from Apple's SEC 10-K filings for fiscal years "
            "2023-2025 - a different company, forward-looking guidance, or a disclosure Apple "
            "does not make (e.g. unit sales figures)."
        )
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Entity names mentioned in the question, for graph lookup. Empty if path is vector or out_of_scope.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How confident this routing decision is, 0-1. Low confidence for ambiguous or borderline questions.",
    )
    reasoning: str = Field(description="One sentence on why this path was chosen.")


ROUTER_PROMPT = """
You are routing a user's question to the right retrieval system for a hybrid RAG \
pipeline over Apple's SEC 10-K filings, fiscal years 2023, 2024, and 2025 only.

The system has two retrieval paths:
- A vector index over filing text chunks, good for single facts, definitions, and \
policy lookups.
- A knowledge graph of entities (companies, people, products, locations, metrics, \
regulations) and the relationships between them (OWNS, COMPETES_WITH, \
LOCATED_IN, SUBJECT_TO, SUES, etc.), good for multi-hop and relationship questions.

Decide which path (or both, or neither) best answers the question. If the question \
names specific entities and the answer depends on how those entities relate to each \
other (suppliers, competitors, regulators, lawsuits, ownership), prefer graph or both. \
If the question is a single fact, number, or definition, prefer vector. If the \
question cannot be answered from Apple's 10-K filings for 2023-2025 (wrong company, \
future guidance, a disclosure Apple does not make), choose out_of_scope.

Also rate your confidence in this decision from 0 to 1. Give a lower confidence when \
the question is ambiguous, could plausibly fit more than one path, or you are unsure \
whether the named entities actually exist as tracked entities. A caller may choose to \
run more than one retrieval path when confidence is low, so an honest low score is \
more useful than a falsely confident one.

Question: {question}
""".strip()


def route_question(question: str, *, client: genai.Client | None = None) -> RouteDecision:
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=ROUTER_PROMPT.format(question=question),
        config={
            "response_mime_type": "application/json",
            "response_schema": RouteDecision,
        },
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, RouteDecision):
        return parsed
    if parsed is not None:
        return RouteDecision.model_validate(parsed)
    return RouteDecision.model_validate_json(response.text)


def log_route_decision(question: str, decision: RouteDecision, effective_path: str, fallback_triggered: bool) -> None:
    """Append one line per real routing decision. Not called by the eval scripts
    (which log their own comparison against expected_path) - this is the ongoing
    production-style log the spec asks for, since this data can't be reconstructed
    after the fact if it's never captured."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "decided_path": decision.path,
        "effective_path": effective_path,
        "confidence": decision.confidence,
        "fallback_triggered": fallback_triggered,
        "entities": decision.entities,
        "reasoning": decision.reasoning,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def execute_route(decision: RouteDecision, question: str, *, k: int = 5, hops: int = 2) -> dict:
    """Dispatch to vector_search / graph_search per the decision. Returns raw results
    for Phase 4 to consume - no answer synthesis happens here.

    Low-confidence decisions run both retrieval paths regardless of the stated path,
    since a router unsure between vector and graph is better off over-retrieving than
    silently picking the wrong single path. ``decision.path`` still records the
    router's original pick for logging/transparency - it is not overwritten.
    """
    low_confidence = decision.confidence < CONFIDENCE_THRESHOLD
    fallback_triggered = low_confidence and decision.path != "out_of_scope"
    effective_path = "both" if fallback_triggered else decision.path

    result: dict = {
        "path": decision.path,
        "effective_path": effective_path,
        "confidence": decision.confidence,
        "fallback_triggered": fallback_triggered,
        "entities": decision.entities,
        "reasoning": decision.reasoning,
    }

    if effective_path == "out_of_scope":
        result["vector_hits"] = []
        result["graph_facts"] = []
    else:
        result["vector_hits"] = retrieval.vector_search(question, k=k) if effective_path in ("vector", "both") else []
        result["graph_facts"] = (
            graph_retrieval.graph_search(decision.entities, hops=hops)
            if effective_path in ("graph", "both") and decision.entities
            else []
        )

    log_route_decision(question, decision, effective_path, fallback_triggered)
    return result


def _main() -> None:
    parser = argparse.ArgumentParser(description="Router smoke test.")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--hops", type=int, default=2)
    args = parser.parse_args()

    decision = route_question(args.question)
    print(f"path: {decision.path}  confidence: {decision.confidence}")
    print(f"entities: {decision.entities}")
    print(f"reasoning: {decision.reasoning}\n")

    result = execute_route(decision, args.question, k=args.k, hops=args.hops)
    if result["fallback_triggered"]:
        print(f"[low confidence -> ran both paths instead of just '{decision.path}']\n")

    print(f"{len(result['vector_hits'])} vector hit(s):")
    for h in result["vector_hits"]:
        print(f"  {h.score:.3f}  {h.chunk_id}  [{h.section_name}]")

    print(f"\n{len(result['graph_facts'])} graph fact(s):")
    for f in result["graph_facts"]:
        print(f"  {f.source} -[{f.relation_type}]-> {f.target}   ({f.source_chunk_id})")


if __name__ == "__main__":
    _main()
