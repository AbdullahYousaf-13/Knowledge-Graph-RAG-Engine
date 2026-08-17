from __future__ import annotations

import json
import os
import re
import random
import time
from pathlib import Path
from typing import Any

from google import genai
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "chunks.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "processed" / "sec_filings"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "extractions.jsonl"
PROGRESS_PATH = OUTPUT_DIR / "extractions_progress.json"

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "20"))
MIN_CHARS = int(os.getenv("MIN_CHARS", "600"))
MIN_WORDS = int(os.getenv("MIN_WORDS", "80"))
MIN_DELAY_SECONDS = float(os.getenv("MIN_DELAY_SECONDS", "13"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "6"))
RESUME = os.getenv("RESUME", "true").lower() not in {"0", "false", "no"}
RESET_OUTPUT = os.getenv("RESET_OUTPUT", "false").lower() in {"1", "true", "yes"}

SECTION_TITLE_BLACKLIST = {
    "business",
    "risk factors",
    "unresolved staff comments",
    "properties",
    "legal proceedings",
    "mine safety disclosures",
    "management's discussion and analysis of financial condition and results of operations",
    "market for registrants common equity, related stockholder matters and issuer purchases of equity securities",
    "financial statements and supplementary data",
    "controls and procedures",
    "quantitative and qualitative disclosures about market risk",
}


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


def load_progress(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_progress(path: Path, progress: dict[str, dict[str, Any]]) -> None:
    path.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def load_existing_chunk_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()

    chunk_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk_id = row.get("chunk_id")
            if isinstance(chunk_id, str):
                chunk_ids.add(chunk_id)
    return chunk_ids


def is_substantive_chunk(chunk: dict[str, Any]) -> bool:
    text = chunk.get("text", "").strip()
    if len(text) < MIN_CHARS:
        return False

    words = text.split()
    if len(words) < MIN_WORDS:
        return False

    section_name = str(chunk.get("section_name", "")).upper()
    if section_name in {
        "ITEM 1. BUSINESS",
        "ITEM 1A. RISK FACTORS",
        "ITEM 1B. UNRESOLVED STAFF COMMENTS",
        "ITEM 2. PROPERTIES",
        "ITEM 3. LEGAL PROCEEDINGS",
    } and chunk.get("section_chunk_index", 0) == 1 and len(text) < (MIN_CHARS * 2):
        return False

    heading_like_lines = sum(
        1
        for line in text.splitlines()
        if re.fullmatch(r"(?i)(item\s+\d+[a-z]?\..*|part\s+[ivx]+.*|[0-9]+)", line.strip())
    )
    if heading_like_lines >= max(3, len(text.splitlines()) // 2):
        return False

    return True


def filter_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [chunk for chunk in chunks if is_substantive_chunk(chunk)]


def normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("\u2019", "'")
    return value


def normalize_relationship_type(value: str) -> str:
    value = normalize_text(value).upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "RELATED_TO"


def is_section_title_entity(entity: dict[str, Any], chunk: dict[str, Any]) -> bool:
    name = normalize_text(str(entity.get("name", "")))
    if not name:
        return True

    section_name = normalize_text(str(chunk.get("section_name", "")))

    if name in SECTION_TITLE_BLACKLIST:
        return True
    if name == section_name:
        return True
    if name.startswith("item ") or name.startswith("part "):
        return True
    if name in {"business", "risk factors", "legal proceedings", "properties", "mine safety disclosures"}:
        return True
    return False


def post_process_extraction(chunk: dict[str, Any], extraction: ChunkExtraction) -> ChunkExtraction:
    entities_by_key: dict[tuple[str, str], Entity] = {}
    kept_entity_names: set[str] = set()

    for entity in extraction.entities:
        if is_section_title_entity(entity.model_dump(), chunk):
            continue
        key = (normalize_text(entity.name), entity.entity_type.lower())
        existing = entities_by_key.get(key)
        if existing is None or entity.confidence >= existing.confidence:
            entities_by_key[key] = entity

    cleaned_entities = list(entities_by_key.values())
    kept_entity_names = {normalize_text(entity.name) for entity in cleaned_entities}

    cleaned_relationships: list[Relationship] = []
    seen_relationships: set[tuple[str, str, str]] = set()
    for relationship in extraction.relationships:
        source = normalize_text(relationship.source_entity)
        target = normalize_text(relationship.target_entity)
        if source not in kept_entity_names or target not in kept_entity_names:
            continue

        normalized_type = normalize_relationship_type(relationship.relation_type)
        key = (source, normalized_type, target)
        if key in seen_relationships:
            continue
        seen_relationships.add(key)

        cleaned_relationships.append(
            Relationship(
                source_entity=relationship.source_entity,
                relation_type=normalized_type,
                target_entity=relationship.target_entity,
                description=relationship.description,
                confidence=relationship.confidence,
            )
        )

    notes = list(extraction.notes)
    removed_entities = len(extraction.entities) - len(cleaned_entities)
    removed_relationships = len(extraction.relationships) - len(cleaned_relationships)
    if removed_entities or removed_relationships:
        notes.append(f"Filtered {removed_entities} low-value entities and {removed_relationships} unsupported relationships.")

    return ChunkExtraction(
        chunk_id=extraction.chunk_id,
        section_name=extraction.section_name,
        filing_year=extraction.filing_year,
        company=extraction.company,
        summary=extraction.summary,
        entities=cleaned_entities,
        relationships=cleaned_relationships,
        notes=notes,
    )


def retry_delay_from_error(exc: Exception) -> float | None:
    message = str(exc)

    patterns = [
        r"retry in\s+([0-9.]+)s",
        r"retryDelay[^0-9]*([0-9.]+)s",
        r"'retryDelay':\s*'([0-9.]+)s'",
        r'"retryDelay":\s*"([0-9.]+)s"',
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except ValueError:
                continue
    return None


def should_retry(exc: Exception) -> bool:
    message = str(exc)
    return "429" in message or "RESOURCE_EXHAUSTED" in message or "quota" in message.lower()


def paced_sleep(last_call_at: float | None) -> float:
    if last_call_at is None:
        return time.monotonic()

    elapsed = time.monotonic() - last_call_at
    wait_seconds = max(0.0, MIN_DELAY_SECONDS - elapsed)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    return time.monotonic()


def build_prompt(chunk: dict[str, Any]) -> str:
    return f"""
You are extracting structured knowledge from an SEC filing chunk.

Extract only information supported by the chunk.
Prefer stable, canonical names for entities.
Ignore section headers, table-of-contents lines, page numbers, and boilerplate unless they are truly part of the substantive filing content.
If the chunk only mentions an entity without enough detail for a relationship, include the entity but leave relationships empty.
Do not invent entities or relationships.
Do not extract section titles as entities unless the chunk contains substantive discussion of them as real business concepts.

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
    chunks = filter_chunks(chunks)
    if MAX_CHUNKS > 0:
        chunks = chunks[:MAX_CHUNKS]

    if RESET_OUTPUT:
        if OUTPUT_PATH.exists():
            OUTPUT_PATH.unlink()
        if PROGRESS_PATH.exists():
            PROGRESS_PATH.unlink()

    print(f"Loaded {len(chunks)} substantive chunks from {INPUT_PATH.name}")
    print(f"Using model: {MODEL_NAME}")
    print(f"Chunk filter: MIN_CHARS={MIN_CHARS}, MIN_WORDS={MIN_WORDS}")
    print(f"Reset output: {RESET_OUTPUT}")

    progress = load_progress(PROGRESS_PATH) if RESUME else {}
    completed_chunk_ids = set(progress.keys()) if RESUME else set()
    if RESUME:
        completed_chunk_ids.update(load_existing_chunk_ids(OUTPUT_PATH))

    print(f"Resume mode: {RESUME}")
    print(f"Already completed chunks: {len(completed_chunk_ids)}")
    print(f"Rate pacing: MIN_DELAY_SECONDS={MIN_DELAY_SECONDS}")
    print(f"Retry policy: MAX_RETRIES={MAX_RETRIES}")

    written = 0
    processed = 0
    last_call_at: float | None = None

    with OUTPUT_PATH.open("a", encoding="utf-8") as out:
        for index, chunk in enumerate(chunks, start=1):
            chunk_id = chunk["chunk_id"]
            if RESUME and chunk_id in completed_chunk_ids:
                print(f"[{index}/{len(chunks)}] skip {chunk_id} (already completed)")
                continue

            attempt = 0
            while True:
                attempt += 1
                try:
                    last_call_at = paced_sleep(last_call_at)
                    extraction = extract_chunk(client, chunk)
                    if extraction is None:
                        print(f"[skip] {chunk_id} returned no structured output")
                        break
                    extraction = post_process_extraction(chunk, extraction)

                    record = {
                        "chunk_id": extraction.chunk_id,
                        "company": extraction.company,
                        "filing_year": extraction.filing_year,
                        "filing_type": chunk["filing_type"],
                        "filing_date": chunk["filing_date"],
                        "period_end_date": chunk["period_end_date"],
                        "source_url": chunk["source_url"],
                        "local_file": chunk["local_file"],
                        "section_name": extraction.section_name,
                        "section_chunk_index": chunk["section_chunk_index"],
                        "chunk_index": chunk["chunk_index"],
                        "text": chunk["text"],
                        "char_count": chunk["char_count"],
                        "summary": extraction.summary,
                        "entities": [entity.model_dump() for entity in extraction.entities],
                        "relationships": [relationship.model_dump() for relationship in extraction.relationships],
                        "notes": extraction.notes,
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()

                    progress[chunk_id] = {
                        "status": "completed",
                        "attempts": attempt,
                        "output_path": str(OUTPUT_PATH.relative_to(BASE_DIR)),
                    }
                    save_progress(PROGRESS_PATH, progress)
                    completed_chunk_ids.add(chunk_id)
                    written += 1
                    processed += 1
                    print(f"[{index}/{len(chunks)}] wrote {chunk_id} | entities={len(record['entities'])} relationships={len(record['relationships'])}")
                    break
                except Exception as exc:
                    if not should_retry(exc) or attempt >= MAX_RETRIES:
                        progress[chunk_id] = {
                            "status": "failed",
                            "attempts": attempt,
                            "error": str(exc),
                        }
                        save_progress(PROGRESS_PATH, progress)
                        print(f"[error] {chunk_id}: {exc}")
                        break

                    server_delay = retry_delay_from_error(exc)
                    backoff = min(120.0, (2 ** (attempt - 1)) * 5.0)
                    wait_seconds = max(server_delay or 0.0, backoff)
                    wait_seconds = wait_seconds + random.uniform(0.0, 2.0)
                    print(f"[retry] {chunk_id} attempt {attempt}/{MAX_RETRIES} after {wait_seconds:.1f}s: {exc}")
                    time.sleep(wait_seconds)

    print(f"\nDone. Wrote {written} extraction records to {OUTPUT_PATH.relative_to(BASE_DIR)}")
    print(f"Processed this run: {processed}")


if __name__ == "__main__":
    main()
