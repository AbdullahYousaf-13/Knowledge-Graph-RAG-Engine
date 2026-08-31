"""Phase 4 safety property: the answer can never cite a chunk that was not retrieved.

``validate_and_repair`` re-prompts while any claim cites an unknown chunk, then drops
whatever still fails so the returned answer is always grounded in the evidence pool.
"""

from __future__ import annotations

from kgrag import answer
from kgrag.answer import AnswerDraft, Claim, Evidence, build_evidence, render_context


def test_validate_and_repair_drops_unsupported_claims():
    allowed = {"apple-inc-2023-0043"}
    draft = AnswerDraft(
        answer_markdown="A. B.",
        claims=[
            Claim(text="A", citations=["apple-inc-2023-0043"]),
            Claim(text="B", citations=["fake-chunk-999"]),
            Claim(text="C", citations=[]),
        ],
    )
    repaired, removed = answer.validate_and_repair(
        "q", "ctx", draft, allowed, client=None, max_retries=0
    )
    assert removed == 2
    assert [c.text for c in repaired.claims] == ["A"]


def test_validate_and_repair_passes_clean_draft():
    allowed = {"c1", "c2"}
    draft = AnswerDraft(
        answer_markdown="x",
        claims=[Claim(text="x", citations=["c1", "c2"])],
    )
    repaired, removed = answer.validate_and_repair(
        "q", "ctx", draft, allowed, client=None, max_retries=0
    )
    assert removed == 0
    assert repaired is draft


def test_build_evidence_merges_graph_and_vector_by_chunk_id():
    class FakeChunk:
        def __init__(self, cid):
            self.chunk_id = cid
            self.text = f"text of {cid}"
            self.section_name = "ITEM 3"
            self.filing_year = "2023"
            self.company = "Apple Inc."
            self.source_url = None
            self.score = 0.42

    class FakeFact:
        source, relation_type, target = "Apple Inc.", "SUES", "Epic Games"
        description = "Epic sued Apple over the App Store."
        source_chunk_id = "apple-inc-2023-0043"

    result = {
        "vector_hits": [FakeChunk("apple-inc-2023-0043"), FakeChunk("apple-inc-2024-0009")],
        "graph_facts": [FakeFact()],
        "graph_aggregates": [],
    }
    evidence = build_evidence(result, conn=object())  # conn unused: no missing chunks to fetch
    by_id = {e.chunk_id: e for e in evidence}
    assert by_id["apple-inc-2023-0043"].origin == "both"
    assert by_id["apple-inc-2023-0043"].graph_statements == ["Epic sued Apple over the App Store."]
    assert by_id["apple-inc-2024-0009"].origin == "vector"
    # graph-origin evidence sorts first
    assert evidence[0].chunk_id == "apple-inc-2023-0043"


def test_render_context_labels_the_two_sources():
    ev = [
        Evidence("g1", "graph text", "ITEM 3", "2023", "Apple Inc.", None, "graph",
                 graph_statements=["Epic sued Apple."]),
        Evidence("v1", "passage text", "ITEM 7", "2024", "Apple Inc.", None, "vector",
                 vector_score=0.5),
    ]
    ctx = render_context(ev)
    assert "## GRAPH-DERIVED FACTS" in ctx
    assert "## PASSAGES" in ctx
    assert "[g1]" in ctx and "[v1]" in ctx
    assert "Epic sued Apple." in ctx
