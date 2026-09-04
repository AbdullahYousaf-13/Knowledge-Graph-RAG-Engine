"""Security properties that don't need a network or an LLM call.

Covers the Phase-6 hardening pass: request-input bounds and the catch-all exception
handler that must never echo an internal error message (which can carry the DB DSN).
The live-LLM prompt-injection checks live in ``scripts/injection_probe.py`` instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kgrag.api import MAX_QUESTION_CHARS, AskRequest


def test_question_rejects_overlong():
    with pytest.raises(ValidationError):
        AskRequest(question="x" * (MAX_QUESTION_CHARS + 1))


def test_question_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        AskRequest(question="        ")


def test_question_is_stripped():
    assert AskRequest(question="  What is Apple's revenue?  ").question == "What is Apple's revenue?"


def test_k_and_hops_bounds():
    with pytest.raises(ValidationError):
        AskRequest(question="valid question", k=0)
    with pytest.raises(ValidationError):
        AskRequest(question="valid question", k=999)
    with pytest.raises(ValidationError):
        AskRequest(question="valid question", hops=4)
    ok = AskRequest(question="valid question", k=10, hops=3)
    assert ok.k == 10 and ok.hops == 3


def test_unhandled_error_is_not_leaked_to_client(monkeypatch):
    starlette_testclient = pytest.importorskip("starlette.testclient")

    from kgrag import answer as answer_mod
    from kgrag.api import app

    def _boom(*args, **kwargs):
        raise RuntimeError("host=db.internal user=admin password=hunter2")

    monkeypatch.setattr(answer_mod, "answer_question", _boom)

    with starlette_testclient.TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/ask", json={"question": "How is Apple connected to the EU?"})

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal error"}
    assert "hunter2" not in resp.text and "password" not in resp.text
