"""Phase 4 FastAPI app: POST /ask -> one grounded, cited answer.

Run: ``uvicorn kgrag.api:app --reload``
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import answer

log = logging.getLogger("kgrag")

# Question length ceiling. Every question is fed verbatim to the router and the
# synthesizer, so an unbounded string is an unbounded token bill (and a cheap DoS).
MAX_QUESTION_CHARS = 2000

app = FastAPI(title="Knowledge Graph RAG Engine", version="0.4.0")

# Local-demo CORS: allow a dev front-end on localhost, nothing else. Deliberately
# explicit rather than relying on the framework default. Widen the origins list
# (or front the app with a proxy) before exposing this anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never leak an internal error message to the client. Exception text from the
    DB/driver layers can embed the connection string (host, user, password), so only
    the exception *type* is logged and the response body is generic."""
    log.error("ask failed: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=MAX_QUESTION_CHARS,
        description="Natural-language question about Apple's FY2023-2025 10-Ks.",
    )
    k: int = Field(default=5, ge=1, le=20, description="Vector top-k.")
    hops: int = Field(default=2, ge=1, le=3, description="Graph traversal depth.")

    @field_validator("question")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("question must be at least 3 non-whitespace characters")
        return v


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    result = answer.answer_question(req.question, k=req.k, hops=req.hops, client=_get_client())
    return asdict(result)
