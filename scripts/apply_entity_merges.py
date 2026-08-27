from __future__ import annotations

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

# (canonical_entity_key, [duplicate_entity_keys]) - approved merge groups.
# The DMA pair appears in 3 approved rows but is really one 3-way group.
MERGE_GROUPS: list[tuple[str, list[str]]] = [
    ("digital-markets-act", ["eu-digital-markets-act", "european-union-digital-markets-act"]),
    ("deferred-tax-asset", ["deferred-tax-assets"]),
    ("securities-and-exchange-commission", ["u-s-securities-and-exchange-commission"]),
    ("u-s-department-of-justice", ["department-of-justice"]),
    ("internal-revenue-service", ["u-s-internal-revenue-service"]),
    ("asu-2023-07", ["asu-no-2023-07"]),
    ("wearables-home-and-accessories", ["wearables-and-accessories"]),
    ("united-states", ["u-s"]),
    ("apple-inc-non-employee-director-stock-plan", ["non-employee-director-stock-plan"]),
    ("covid-19", ["covid-19-pandemic"]),
    ("apple-inc-2014-employee-stock-plan", ["2014-employee-stock-plan"]),
    ("apple-inc-2022-employee-stock-plan", ["2022-employee-stock-plan"]),
    ("rule-10b5-1", ["rule-10b5-1-c"]),
]


def redirect_mentions(tx, dup_key: str, canon_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})
        MATCH (canon:Entity {entity_key: $canon_key})
        MATCH (c:Chunk)-[m:MENTIONS]->(dup)
        MERGE (c)-[:MENTIONS]->(canon)
        DELETE m
        """,
        dup_key=dup_key,
        canon_key=canon_key,
    )


def redirect_related_to_outgoing(tx, dup_key: str, canon_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})
        MATCH (canon:Entity {entity_key: $canon_key})
        MATCH (dup)-[r:RELATED_TO]->(other)
        WHERE other.entity_key <> $canon_key
        MERGE (canon)-[r2:RELATED_TO {source_chunk_id: r.source_chunk_id}]->(other)
        SET r2 += properties(r)
        DELETE r
        """,
        dup_key=dup_key,
        canon_key=canon_key,
    )


def redirect_related_to_incoming(tx, dup_key: str, canon_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})
        MATCH (canon:Entity {entity_key: $canon_key})
        MATCH (other)-[r:RELATED_TO]->(dup)
        WHERE other.entity_key <> $canon_key
        MERGE (other)-[r2:RELATED_TO {source_chunk_id: r.source_chunk_id}]->(canon)
        SET r2 += properties(r)
        DELETE r
        """,
        dup_key=dup_key,
        canon_key=canon_key,
    )


def drop_self_loop_edges(tx, dup_key: str, canon_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})-[r:RELATED_TO]-(canon:Entity {entity_key: $canon_key})
        DELETE r
        """,
        dup_key=dup_key,
        canon_key=canon_key,
    )


def merge_aliases(tx, dup_key: str, canon_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})
        MATCH (canon:Entity {entity_key: $canon_key})
        SET canon.aliases = reduce(
            acc = coalesce(canon.aliases, []),
            x IN (coalesce(dup.aliases, []) + [dup.name]) |
            CASE WHEN x IN acc THEN acc ELSE acc + x END
        )
        """,
        dup_key=dup_key,
        canon_key=canon_key,
    )


def delete_duplicate(tx, dup_key: str) -> None:
    tx.run(
        """
        MATCH (dup:Entity {entity_key: $dup_key})
        DETACH DELETE dup
        """,
        dup_key=dup_key,
    )


def main() -> None:
    if not NEO4J_PASSWORD:
        raise RuntimeError("NEO4J_PASSWORD is not set.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    merged = 0
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            for canon_key, dup_keys in MERGE_GROUPS:
                for dup_key in dup_keys:
                    session.execute_write(redirect_mentions, dup_key, canon_key)
                    session.execute_write(redirect_related_to_outgoing, dup_key, canon_key)
                    session.execute_write(redirect_related_to_incoming, dup_key, canon_key)
                    session.execute_write(drop_self_loop_edges, dup_key, canon_key)
                    session.execute_write(merge_aliases, dup_key, canon_key)
                    session.execute_write(delete_duplicate, dup_key)
                    merged += 1
                    print(f"Merged '{dup_key}' -> '{canon_key}'")
    finally:
        driver.close()

    print(f"\nDone. Merged {merged} duplicate entities across {len(MERGE_GROUPS)} groups.")


if __name__ == "__main__":
    main()
