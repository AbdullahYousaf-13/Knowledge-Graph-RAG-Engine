from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google import genai
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "chunks.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "processed" / "sec_filings"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "extractions.jsonl"

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "20"))


class Entity(BaseModel):
    name: str = Field(description="Canonical name of the entity.")
    entity_type: str = Field(description="Entity category such as Company, Person, Product, Location, Metric, Regulation, or Other.")
    aliases: list[str] = Field(default_factory=list, description="Alternate names used in the filing.")
    description: str = Field(description="Short description of the entity in this chunk.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence that the entity is correctly extracted.")


class Relationship(BaseModel):
    source_entity: str = Field(description="Name of the source entity.")
    relation_type: str = Field(description="Relationship type such as OWNS, SUPPLIES, COMPETES_WITH, LOCATED_IN, MENTIONS, RELATES_TO, or other concise verb phrase.")
    target_entity: str = Field(description="Name of the target entity.")
    description: str = Field(description="Short explanation of why the relationship exists.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence that the relationship is correctly extracted.")


class ChunkExtraction(BaseModel):
    chunk_id: str
    section_name: str
    filing_year: str
    company: str
    summary: str = Field(description="One-paragraph summary of the chunk.")
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def load_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_prompt(chunk: dict[str, Any]) -> str:
    return f"""
You are extracting structured knowledge from an SEC filing chunk.

Extract only information supported by the chunk.
Prefer stable, canonical names for entities.
If the chunk only mentions an entity without enough detail for a relationship, include the entity but leave relationships empty.
Do not invent entities or relationships.

Return data that fits the schema exactly.

Metadata:
- chunk_id: {chunk["chunk_id"]}
- company: {chunk["company"]}
- filing_year: {chunk["filing_year"]}
- filing_type: {chunk["filing_type"]}
- filing_date: {chunk["filing_date"]}
- period_end_date: {chunk["period_end_date"]}
- source_url: {chunk["source_url"]}
- section_name: {chunk["section_name"]}

Chunk text:
{chunk["text"]}
""".strip()


def extract_chunk(client: genai.Client, chunk: dict[str, Any]) -> ChunkExtraction | None:
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=build_prompt(chunk),
        config={
            "response_mime_type": "application/json",
            "response_schema": ChunkExtraction,
        },
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ChunkExtraction):
        return parsed
    if parsed is not None:
        return ChunkExtraction.model_validate(parsed)
    if getattr(response, "text", None):
        return ChunkExtraction.model_validate_json(response.text)
    return None


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)
    chunks = load_chunks(INPUT_PATH)
    if MAX_CHUNKS > 0:
        chunks = chunks[:MAX_CHUNKS]

    print(f"Loaded {len(chunks)} chunks from {INPUT_PATH.name}")
    print(f"Using model: {MODEL_NAME}")

    written = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for index, chunk in enumerate(chunks, start=1):
            try:
                extraction = extract_chunk(client, chunk)
                if extraction is None:
                    print(f"[skip] {chunk['chunk_id']} returned no structured output")
                    continue

                record = {
                    "chunk_id": extraction.chunk_id,
                    "company": extraction.company,
                    "filing_year": extraction.filing_year,
                    "section_name": extraction.section_name,
                    "summary": extraction.summary,
                    "entities": [entity.model_dump() for entity in extraction.entities],
                    "relationships": [relationship.model_dump() for relationship in extraction.relationships],
                    "notes": extraction.notes,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                print(f"[{index}/{len(chunks)}] wrote {chunk['chunk_id']} | entities={len(record['entities'])} relationships={len(record['relationships'])}")
            except Exception as exc:
                print(f"[error] {chunk['chunk_id']}: {exc}")

    print(f"\nDone. Wrote {written} extraction records to {OUTPUT_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
