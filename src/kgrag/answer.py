"""Phase 4: merge graph + vector retrieval into one grounded, cited answer.

Pipeline: ``router.route_question`` -> ``router.execute_route`` -> ``build_evidence``
-> ``render_context`` -> ``synthesize`` (Gemini structured output) ->
``validate_and_repair``.

Every claim in the answer carries >=1 citation, and every citation must resolve to a
``chunk_id`` that was actually retrieved for this question. Claims that still cite a
non-retrieved chunk after the repair budget is exhausted are dropped (and counted),
so the returned answer is always grounded in retrieved evidence.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Literal

from google import genai
from pydantic import BaseModel, Field

from . import retrieval, router

ANSWER_MODEL = os.getenv("GEMINI_ANSWER_MODEL", os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))
MAX_ANSWER_RETRIES = int(os.getenv("ANSWER_MAX_RETRIES", "2"))
SNIPPET_CHARS = 240

OUT_OF_SCOPE_MESSAGE = (
    "This question can't be answered from Apple's SEC 10-K filings for fiscal years "
    "2023-2025, which is the corpus this system covers."
)

Origin = Literal["vector", "graph", "both"]


# --- evidence assembly -----------------------------------------------------


@dataclass
class Evidence:
    chunk_id: str
    text: str
    section_name: str
    filing_year: str
    company: str
    source_url: str | None
    origin: Origin
    vector_score: float | None = None
    graph_statements: list[str] = field(default_factory=list)


def build_evidence(result: dict, *, conn=None) -> list[Evidence]:
    """Collapse ``execute_route``'s raw output into one chunk-keyed evidence pool.

    Vector hits and graph facts both resolve to a chunk; a chunk seen from both paths
    is marked ``origin="both"``. Graph facts also contribute their extraction
    ``description`` as a one-line statement kept on the evidence (rendered under a
    distinct "GRAPH-DERIVED" heading).
    """
    by_id: dict[str, Evidence] = {}

    for h in result.get("vector_hits", []):
        by_id[h.chunk_id] = Evidence(
            chunk_id=h.chunk_id,
            text=h.text,
            section_name=h.section_name,
            filing_year=h.filing_year,
            company=h.company,
            source_url=h.source_url,
            origin="vector",
            vector_score=h.score,
        )

    graph_stmts: dict[str, list[str]] = {}
    for f in result.get("graph_facts", []):
        if not f.source_chunk_id:
            continue
        stmt = f.description or f"{f.source} {f.relation_type} {f.target}"
        graph_stmts.setdefault(f.source_chunk_id, []).append(stmt)
    for s in result.get("graph_aggregates", []):
        stmt = f"{s.entity_name}: {s.relation_type} - {s.count} ({', '.join(s.targets[:8])})"
        for cid in s.source_chunk_ids:
            if cid:
                graph_stmts.setdefault(cid, []).append(stmt)

    missing = [cid for cid in graph_stmts if cid not in by_id]
    fetched = retrieval.get_chunks_by_ids(missing, conn=conn) if missing else {}

    for cid, stmts in graph_stmts.items():
        stmts = list(dict.fromkeys(stmts))
        ev = by_id.get(cid)
        if ev is not None:
            ev.origin = "both"
            ev.graph_statements.extend(stmts)
        else:
            c = fetched.get(cid)
            if c is None:
                continue  # chunk no longer in the store; skip rather than emit an uncitable statement
            by_id[cid] = Evidence(
                chunk_id=cid,
                text=c.text,
                section_name=c.section_name,
                filing_year=c.filing_year,
                company=c.company,
                source_url=c.source_url,
                origin="graph",
                graph_statements=list(stmts),
            )

    def sort_key(e: Evidence) -> tuple[int, float]:
        graph_first = 0 if e.origin in ("graph", "both") else 1
        return (graph_first, -(e.vector_score or 0.0))

    return sorted(by_id.values(), key=sort_key)


def render_context(evidence: list[Evidence]) -> str:
    graph_ev = [e for e in evidence if e.origin in ("graph", "both")]
    vec_ev = [e for e in evidence if e.origin == "vector"]

    parts: list[str] = []
    if graph_ev:
        parts.append(
            "## GRAPH-DERIVED FACTS\n"
            "(relationships extracted into the knowledge graph; the passage that sourced each follows)"
        )
        for e in graph_ev:
            fact = "; ".join(dict.fromkeys(e.graph_statements))
            parts.append(
                f"[{e.chunk_id}] ({e.section_name}, FY{e.filing_year})\n"
                f"FACT: {fact}\n"
                f"SOURCE TEXT: {e.text}"
            )
    if vec_ev:
        parts.append("## PASSAGES\n(semantically retrieved filing text)")
        for e in vec_ev:
            parts.append(f"[{e.chunk_id}] ({e.section_name}, FY{e.filing_year})\n{e.text}")

    return "\n\n".join(parts)


# --- synthesis + citation validation -------------------------------------


class Claim(BaseModel):
    text: str = Field(description="One factual sentence from the answer.")
    citations: list[str] = Field(
        description=(
            "chunk_id(s) from the context that support this claim. At least one; each "
            "must be a chunk id shown in the context."
        )
    )


class AnswerDraft(BaseModel):
    answer_markdown: str = Field(
        description=(
            "The full answer as markdown prose, with an inline [chunk_id] marker after each "
            "supported statement."
        )
    )
    claims: list[Claim] = Field(
        description="Every factual claim in the answer, each with its supporting citations."
    )


SYNTH_PROMPT = """You are answering a question about Apple's SEC 10-K filings (fiscal years 2023-2025) \
using only the retrieved context below.

Rules:
- Use only information present in the context. Do not add outside knowledge.
- Every factual statement in your answer must be supported by at least one citation, \
written as [chunk_id] using the exact chunk ids shown in the context.
- In `claims`, list each factual statement separately with its supporting chunk id(s).
- If the context does not contain enough information to answer, say so plainly in \
answer_markdown and return an empty claims list.
- Be concise and directly responsive to the question.

CONTEXT:
{context}

QUESTION: {question}
""".strip()


def synthesize(
    question: str, context: str, *, client: genai.Client, extra_instruction: str = ""
) -> AnswerDraft:
    prompt = SYNTH_PROMPT.format(context=context, question=question)
    if extra_instruction:
        prompt = f"{prompt}\n\n{extra_instruction}"
    response = client.models.generate_content(
        model=ANSWER_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": AnswerDraft},
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, AnswerDraft):
        return parsed
    if parsed is not None:
        return AnswerDraft.model_validate(parsed)
    return AnswerDraft.model_validate_json(response.text)


def _bad_citations(claim: Claim, allowed: set[str]) -> list[str]:
    if not claim.citations:
        return ["<no citation>"]
    return [c for c in claim.citations if c not in allowed]


def validate_and_repair(
    question: str,
    context: str,
    draft: AnswerDraft,
    allowed: set[str],
    *,
    client: genai.Client,
    max_retries: int = MAX_ANSWER_RETRIES,
) -> tuple[AnswerDraft, int]:
    """Re-prompt while any claim cites a chunk not in ``allowed``; after the budget,
    drop the still-bad claims and report how many were removed."""
    for _ in range(max_retries):
        problems = {c.text: bad for c in draft.claims if (bad := _bad_citations(c, allowed))}
        if not problems:
            return draft, 0
        lines = "\n".join(f"- claim {t!r} cited {b}, not present in the context" for t, b in problems.items())
        instruction = (
            "Your previous answer had unsupported citations:\n"
            f"{lines}\n"
            "Rewrite so every claim cites only chunk ids present in the context above, "
            "or drop the claim entirely."
        )
        draft = synthesize(question, context, client=client, extra_instruction=instruction)

    kept = [c for c in draft.claims if not _bad_citations(c, allowed)]
    removed = len(draft.claims) - len(kept)
    if removed:
        draft = AnswerDraft(answer_markdown=draft.answer_markdown, claims=kept)
    return draft, removed


# --- entry point --------------------------------------------------------


@dataclass
class Citation:
    chunk_id: str
    section_name: str
    filing_year: str
    company: str
    source_url: str | None
    origin: Origin
    snippet: str


@dataclass
class AnswerResult:
    question: str
    out_of_scope: bool
    answer_markdown: str
    claims: list[dict]
    citations: list[Citation]
    claims_removed: int
    route: dict


def _route_meta(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "path",
            "effective_path",
            "query_type",
            "entities",
            "confidence",
            "fallback_triggered",
            "reasoning",
        )
    }


def answer_question(
    question: str, *, k: int = 5, hops: int = 2, client: genai.Client | None = None, conn=None
) -> AnswerResult:
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    decision = router.route_question(question, client=client)
    result = router.execute_route(decision, question, k=k, hops=hops)
    route_meta = _route_meta(result)

    if result["effective_path"] == "out_of_scope":
        return AnswerResult(question, True, OUT_OF_SCOPE_MESSAGE, [], [], 0, route_meta)

    evidence = build_evidence(result, conn=conn)
    if not evidence:
        return AnswerResult(
            question,
            False,
            "No relevant information was retrieved from the filings for this question.",
            [],
            [],
            0,
            route_meta,
        )

    context = render_context(evidence)
    allowed = {e.chunk_id for e in evidence}

    draft = synthesize(question, context, client=client)
    draft, removed = validate_and_repair(question, context, draft, allowed, client=client)

    answer_md = draft.answer_markdown
    if removed:
        answer_md += f"\n\n_Note: {removed} statement(s) removed - not grounded in retrieved evidence._"

    ev_by_id = {e.chunk_id: e for e in evidence}
    cited_ids = [cid for cl in draft.claims for cid in cl.citations]
    citations = [
        Citation(
            chunk_id=cid,
            section_name=ev_by_id[cid].section_name,
            filing_year=ev_by_id[cid].filing_year,
            company=ev_by_id[cid].company,
            source_url=ev_by_id[cid].source_url,
            origin=ev_by_id[cid].origin,
            snippet=" ".join(ev_by_id[cid].text.split())[:SNIPPET_CHARS],
        )
        for cid in dict.fromkeys(cited_ids)
        if cid in ev_by_id
    ]

    return AnswerResult(
        question=question,
        out_of_scope=False,
        answer_markdown=answer_md,
        claims=[{"text": c.text, "citations": c.citations} for c in draft.claims],
        citations=citations,
        claims_removed=removed,
        route=route_meta,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 answerer smoke test.")
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--hops", type=int, default=2)
    args = parser.parse_args()

    res = answer_question(args.question, k=args.k, hops=args.hops)
    print(f"route: {res.route['path']} -> {res.route['effective_path']}  ({res.route['query_type']})\n")
    print(res.answer_markdown)
    if res.citations:
        print("\nCitations:")
        for c in res.citations:
            print(f"  [{c.chunk_id}] {c.origin}  ({c.section_name}, FY{c.filing_year})")
            print(f"      {c.snippet}")
    if res.claims_removed:
        print(f"\n({res.claims_removed} claim(s) removed as ungrounded)")


if __name__ == "__main__":
    _main()
