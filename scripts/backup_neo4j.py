from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "data" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")


def fetch_nodes(session) -> list[dict]:
    result = session.run(
        """
        MATCH (n)
        RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS props
        """
    )
    return [
        {"element_id": r["element_id"], "labels": r["labels"], "properties": dict(r["props"])}
        for r in result
    ]


def fetch_relationships(session) -> list[dict]:
    result = session.run(
        """
        MATCH (a)-[r]->(b)
        RETURN elementId(r) AS element_id, type(r) AS rel_type,
               elementId(a) AS start_id, elementId(b) AS end_id,
               properties(r) AS props
        """
    )
    return [
        {
            "element_id": r["element_id"],
            "type": r["rel_type"],
            "start_id": r["start_id"],
            "end_id": r["end_id"],
            "properties": dict(r["props"]),
        }
        for r in result
    ]


def main() -> None:
    if not NEO4J_PASSWORD:
        raise RuntimeError("NEO4J_PASSWORD is not set.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            nodes = fetch_nodes(session)
            relationships = fetch_relationships(session)
    finally:
        driver.close()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = BACKUP_DIR / f"neo4j_backup_{timestamp}.json"
    out_path.write_text(
        json.dumps(
            {"exported_at": timestamp, "nodes": nodes, "relationships": relationships},
            indent=2,
            default=str,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Backed up {len(nodes)} nodes and {len(relationships)} relationships to {out_path.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
