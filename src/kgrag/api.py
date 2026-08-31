"""Phase 4 FastAPI app: POST /ask -> one grounded, cited answer.

Run: ``uvicorn kgrag.api:app --reload``
"""

from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import answer

app = FastAPI(title="Knowledge Graph RAG Engine", version="0.4.0")

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


class AskRequest(BaseModel):
    question: str = Field(min_length=3, description="Natural-language question about Apple's FY2023-2025 10-Ks.")
    k: int = Field(default=5, ge=1, le=20, description="Vector top-k.")
    hops: int = Field(default=2, ge=1, le=3, description="Graph traversal depth.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    result = answer.answer_question(req.question, k=req.k, hops=req.hops, client=_get_client())
    return asdict(result)
