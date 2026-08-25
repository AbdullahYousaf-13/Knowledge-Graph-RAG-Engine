from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from pgvector.psycopg import register_vector
except ImportError as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "Missing dependencies for pgvector indexing. Run `pip install -r requirements.txt` first."
    ) from exc

try:
    from sentence_transformers import SentenceTransformer
except ImportError as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "Missing sentence-transformers. Run `pip install -r requirements.txt` first."
    ) from exc

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "chunks.jsonl"

TABLE_NAME = os.getenv("VECTOR_TABLE", "sec_chunk_embeddings")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
POSTGRES_DSN = os.getenv("POSTGRES_DSN")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_graph_rag")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

FILING_YEARS = {
    year.strip() for year in os.getenv("FILING_YEARS", "2023,2024,2025").split(",") if year.strip()
}
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "0"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "32"))
MIN_CHARS = int(os.getenv("MIN_CHARS", "600"))
MIN_WORDS = int(os.getenv("MIN_WORDS", "80"))
RESUME = os.getenv("RESUME", "true").lower() not in {"0", "false", "no"}
RESET_TABLE = os.getenv("RESET_TABLE", "false").lower() in {"1", "true", "yes"}

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


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("\u2019", "'")
    return value


def is_substantive_chunk(chunk: dict[str, Any]) -> bool:
    text = str(chunk.get("text", "")).strip()
    if len(text) < MIN_CHARS:
        return False

    if len(text.split()) < MIN_WORDS:
        return False

    section_name = normalize_text(str(chunk.get("section_name", "")))
    if section_name in SECTION_TITLE_BLACKLIST:
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
    return [
        chunk
        for chunk in chunks
        if is_substantive_chunk(chunk)
        and (not FILING_YEARS or str(chunk.get("filing_year")) in FILING_YEARS)
    ]


def make_dsn() -> str:
    if POSTGRES_DSN:
        return POSTGRES_DSN
    if not POSTGRES_PASSWORD:
        raise SystemExit("Set POSTGRES_DSN or POSTGRES_PASSWORD before running the loader.")
    return (
        f"host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} password={POSTGRES_PASSWORD}"
    )


def create_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                chunk_id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                filing_type TEXT NOT NULL,
                filing_year TEXT NOT NULL,
                filing_date DATE,
                period_end_date DATE,
                source_url TEXT,
                local_file TEXT,
                section_name TEXT,
                section_chunk_index INTEGER,
                chunk_index INTEGER,
                text TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding VECTOR({EMBEDDING_DIM}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {TABLE_NAME}_embedding_idx
            ON {TABLE_NAME}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """
        )
    conn.commit()


def load_existing_chunk_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT chunk_id FROM {TABLE_NAME}")
        return {row[0] for row in cur.fetchall()}


def clear_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {TABLE_NAME}")
    conn.commit()


def embed_batch(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True).tolist()


def upsert_rows(conn, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME} (
                    chunk_id,
                    company,
                    filing_type,
                    filing_year,
                    filing_date,
                    period_end_date,
                    source_url,
                    local_file,
                    section_name,
                    section_chunk_index,
                    chunk_index,
                    text,
                    metadata,
                    embedding,
                    updated_at
                )
                VALUES (
                    %(chunk_id)s,
                    %(company)s,
                    %(filing_type)s,
                    %(filing_year)s,
                    %(filing_date)s,
                    %(period_end_date)s,
                    %(source_url)s,
                    %(local_file)s,
                    %(section_name)s,
                    %(section_chunk_index)s,
                    %(chunk_index)s,
                    %(text)s,
                    %(metadata)s,
                    %(embedding)s,
                    NOW()
                )
                ON CONFLICT (chunk_id) DO UPDATE SET
                    company = EXCLUDED.company,
                    filing_type = EXCLUDED.filing_type,
                    filing_year = EXCLUDED.filing_year,
                    filing_date = EXCLUDED.filing_date,
                    period_end_date = EXCLUDED.period_end_date,
                    source_url = EXCLUDED.source_url,
                    local_file = EXCLUDED.local_file,
                    section_name = EXCLUDED.section_name,
                    section_chunk_index = EXCLUDED.section_chunk_index,
                    chunk_index = EXCLUDED.chunk_index,
                    text = EXCLUDED.text,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
                """,
                row,
            )
    conn.commit()


def main() -> None:
    chunks = filter_chunks(load_chunks(INPUT_PATH))
    if MAX_CHUNKS > 0:
        chunks = chunks[:MAX_CHUNKS]

    print(f"Loaded {len(chunks)} substantive chunks from {INPUT_PATH.name}")
    print(f"Filing years: {sorted(FILING_YEARS) if FILING_YEARS else 'all'}")
    print(f"Embedding model: {EMBEDDING_MODEL} (local, dim={EMBEDDING_DIM})")
    print(f"Resume mode: {RESUME}")
    print(f"Reset table: {RESET_TABLE}")
    print(f"Batch size: {BATCH_SIZE}")

    model = SentenceTransformer(EMBEDDING_MODEL)
    with psycopg.connect(make_dsn()) as conn:
        create_schema(conn)
        register_vector(conn)

        if RESET_TABLE:
            clear_table(conn)

        completed_chunk_ids = load_existing_chunk_ids(conn) if RESUME else set()
        print(f"Already indexed chunks: {len(completed_chunk_ids)}")

        pending = [chunk for chunk in chunks if chunk["chunk_id"] not in completed_chunk_ids]
        if not pending:
            print("Nothing to do. All chunks are already indexed.")
            return

        written = 0
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            batch_ids = [chunk["chunk_id"] for chunk in batch]
            batch_texts = [str(chunk["text"]) for chunk in batch]

            embeddings = embed_batch(model, batch_texts)
            if len(embeddings) != len(batch):
                raise RuntimeError(
                    f"Embedding count mismatch for batch {batch_ids}: "
                    f"got {len(embeddings)} embeddings for {len(batch)} chunks"
                )

            rows: list[dict[str, Any]] = []
            for chunk, embedding in zip(batch, embeddings):
                rows.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "company": chunk["company"],
                        "filing_type": chunk["filing_type"],
                        "filing_year": chunk["filing_year"],
                        "filing_date": chunk.get("filing_date"),
                        "period_end_date": chunk.get("period_end_date"),
                        "source_url": chunk.get("source_url"),
                        "local_file": chunk.get("local_file"),
                        "section_name": chunk.get("section_name"),
                        "section_chunk_index": chunk.get("section_chunk_index"),
                        "chunk_index": chunk.get("chunk_index"),
                        "text": chunk["text"],
                        "metadata": json.dumps(
                            {
                                "chunk_id": chunk["chunk_id"],
                                "source_url": chunk.get("source_url"),
                                "local_file": chunk.get("local_file"),
                                "section_name": chunk.get("section_name"),
                                "section_chunk_index": chunk.get("section_chunk_index"),
                                "chunk_index": chunk.get("chunk_index"),
                            }
                        ),
                        "embedding": embedding,
                    }
                )

            upsert_rows(conn, rows)
            written += len(rows)
            print(f"[{start + len(batch)}/{len(pending)}] wrote {batch_ids[0]}..{batch_ids[-1]}")

        print(f"\nDone. Indexed {written} chunks into {TABLE_NAME}")


if __name__ == "__main__":
    main()
