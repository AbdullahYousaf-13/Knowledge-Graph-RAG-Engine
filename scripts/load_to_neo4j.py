from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "extractions.jsonl"
CHUNKS_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "chunks.jsonl"

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_chunk_metadata(path: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            metadata[row["chunk_id"]] = row
    return metadata


def enrich_record(record: dict[str, Any], chunk_meta: dict[str, Any] | None) -> dict[str, Any]:
    if not chunk_meta:
        return record

    enriched = dict(chunk_meta)
    enriched.update(record)
    return enriched


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def entity_key(name: str) -> str:
    return slugify(name)


def ensure_constraints(tx) -> None:
    statements = [
        "CREATE CONSTRAINT filing_source_url IF NOT EXISTS FOR (f:Filing) REQUIRE f.source_url IS UNIQUE",
        "CREATE CONSTRAINT chunk_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
        "CREATE CONSTRAINT entity_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_key IS UNIQUE",
    ]
    for cypher in statements:
        tx.run(cypher)


def upsert_filing(tx, record: dict[str, Any]) -> None:
    tx.run(
        """
        MERGE (f:Filing {source_url: $source_url})
        SET f.company = $company,
            f.filing_type = $filing_type,
            f.filing_year = $filing_year,
            f.filing_date = $filing_date,
            f.period_end_date = $period_end_date,
            f.local_file = $local_file,
            f.updated_at = datetime()
        """,
        **record,
    )


def upsert_chunk(tx, record: dict[str, Any]) -> None:
    tx.run(
        """
        MATCH (f:Filing {source_url: $source_url})
        MERGE (c:Chunk {chunk_id: $chunk_id})
        SET c.company = $company,
            c.filing_type = $filing_type,
            c.filing_year = $filing_year,
            c.section_name = $section_name,
            c.text = $text,
            c.char_count = $char_count,
            c.section_chunk_index = $section_chunk_index,
            c.chunk_index = $chunk_index,
            c.updated_at = datetime()
        MERGE (f)-[:HAS_CHUNK]->(c)
        """,
        **record,
    )


def upsert_entity(tx, entity: dict[str, Any], record: dict[str, Any]) -> None:
    ek = entity_key(entity["name"])
    aliases = list(dict.fromkeys(entity.get("aliases", [])))
    tx.run(
        """
        MATCH (c:Chunk {chunk_id: $chunk_id})
        MERGE (e:Entity {entity_key: $entity_key})
        SET e.name = $name,
            e.entity_type = $entity_type,
            e.description = $description,
            e.confidence = $confidence,
            e.updated_at = datetime()
        SET e.aliases = CASE
            WHEN e.aliases IS NULL THEN $aliases
            ELSE reduce(x = e.aliases, y IN $aliases | CASE WHEN y IN x THEN x ELSE x + y END)
        END
        MERGE (c)-[:MENTIONS]->(e)
        """,
        chunk_id=record["chunk_id"],
        entity_key=ek,
        name=entity["name"],
        entity_type=entity["entity_type"],
        description=entity.get("description", ""),
        confidence=float(entity.get("confidence", 0.0)),
        aliases=aliases,
    )


def upsert_relationship(tx, relationship: dict[str, Any], record: dict[str, Any]) -> None:
    source_key = entity_key(relationship["source_entity"])
    target_key = entity_key(relationship["target_entity"])
    relation_type = slugify(relationship["relation_type"]).upper() or "RELATED_TO"

    tx.run(
        """
        MATCH (source:Entity {entity_key: $source_key})
        MATCH (target:Entity {entity_key: $target_key})
        MERGE (source)-[r:RELATED_TO {relation_type: $relation_type, source_chunk_id: $source_chunk_id}]->(target)
        SET r.description = $description,
            r.confidence = $confidence,
            r.company = $company,
            r.filing_year = $filing_year,
            r.updated_at = datetime()
        """,
        source_key=source_key,
        target_key=target_key,
        relation_type=relation_type,
        source_chunk_id=record["chunk_id"],
        description=relationship.get("description", ""),
        confidence=float(relationship.get("confidence", 0.0)),
        company=record["company"],
        filing_year=record["filing_year"],
    )


def ingest_records(driver, records: list[dict[str, Any]]) -> Counter:
    stats: Counter = Counter()
    chunk_metadata = load_chunk_metadata(CHUNKS_PATH)
    with driver.session(database=NEO4J_DATABASE) as session:
        session.execute_write(ensure_constraints)

        for record in records:
            full_record = enrich_record(record, chunk_metadata.get(record["chunk_id"]))
            session.execute_write(upsert_filing, full_record)
            session.execute_write(upsert_chunk, full_record)
            stats["chunks"] += 1

            for entity in record.get("entities", []):
                session.execute_write(upsert_entity, entity, full_record)
                stats["entities"] += 1

            for relationship in record.get("relationships", []):
                session.execute_write(upsert_relationship, relationship, full_record)
                stats["relationships"] += 1

    return stats


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_PATH}")

    records = load_records(INPUT_PATH)
    print(f"Loaded {len(records)} extraction records from {INPUT_PATH.relative_to(BASE_DIR)}")

    if DRY_RUN:
        print("DRY_RUN=1 set, skipping Neo4j writes.")
        print(f"Would ingest {sum(len(r.get('entities', [])) for r in records)} entities and {sum(len(r.get('relationships', [])) for r in records)} relationships.")
        return

    if not NEO4J_PASSWORD:
        raise RuntimeError("NEO4J_PASSWORD is not set.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        stats = ingest_records(driver, records)
    finally:
        driver.close()

    print("Ingestion complete.")
    print(f"Chunks: {stats['chunks']}")
    print(f"Entities: {stats['entities']}")
    print(f"Relationships: {stats['relationships']}")


if __name__ == "__main__":
    main()
