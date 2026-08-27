from __future__ import annotations

import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "entity_merge_candidates.csv"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.80"))

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")


def fetch_entities(session) -> list[dict]:
    result = session.run(
        """
        MATCH (e:Entity)
        OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(e)
        RETURN e.entity_key AS entity_key, e.name AS name, e.entity_type AS entity_type,
               count(c) AS mention_count
        """
    )
    return [dict(r) for r in result]


def main() -> None:
    if not NEO4J_PASSWORD:
        raise RuntimeError("NEO4J_PASSWORD is not set.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            entities = fetch_entities(session)
    finally:
        driver.close()

    print(f"Fetched {len(entities)} entities from Neo4j (read-only).")

    model = SentenceTransformer(EMBEDDING_MODEL)
    names = [e["name"] for e in entities]
    embeddings = model.encode(names, show_progress_bar=False, convert_to_numpy=True)

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / norms
    similarity_matrix = normalized @ normalized.T

    candidates = []
    n = len(entities)
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(similarity_matrix[i, j])
            if sim >= SIMILARITY_THRESHOLD:
                candidates.append(
                    {
                        "similarity": round(sim, 4),
                        "name_a": entities[i]["name"],
                        "type_a": entities[i]["entity_type"],
                        "mentions_a": entities[i]["mention_count"],
                        "entity_key_a": entities[i]["entity_key"],
                        "name_b": entities[j]["name"],
                        "type_b": entities[j]["entity_type"],
                        "mentions_b": entities[j]["mention_count"],
                        "entity_key_b": entities[j]["entity_key"],
                    }
                )

    candidates.sort(key=lambda c: c["similarity"], reverse=True)

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "similarity",
                "name_a",
                "type_a",
                "mentions_a",
                "entity_key_a",
                "name_b",
                "type_b",
                "mentions_b",
                "entity_key_b",
                "recommendation",
                "reason",
            ],
        )
        writer.writeheader()
        for c in candidates:
            c["recommendation"] = ""
            c["reason"] = ""
            writer.writerow(c)

    print(f"Found {len(candidates)} candidate pairs at similarity >= {SIMILARITY_THRESHOLD}")
    print(f"Wrote report to {OUTPUT_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
