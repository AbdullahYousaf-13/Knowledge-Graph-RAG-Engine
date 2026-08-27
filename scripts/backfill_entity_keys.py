"""One-time, idempotent migration: add and populate ``sec_chunk_embeddings.entity_keys``.

`build_pgvector_index.py` only does ``CREATE TABLE IF NOT EXISTS``, so it can't add a
column to the already-live table. This script:

  1. ALTERs the table to add ``entity_keys TEXT[]`` + a GIN index (idempotent).
  2. Backfills every row from ``extractions.jsonl``, applying the post-merge canonical
     entity-key remap (``kgrag.entity_keys``).
  3. Swaps the vector index from ``ivfflat`` to ``hnsw`` (unless SKIP_HNSW=1).
  4. Verifies; with ``--check-neo4j`` asserts every backfilled key exists in the graph.

Re-runnable: the backfill writes a deterministic value, DDL is guarded.

Env flags: DRY_RUN=1, SKIP_HNSW=1, VECTOR_TABLE (default sec_chunk_embeddings).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from statistics import median

from kgrag.db import VECTOR_TABLE, connect, neo4j_driver, NEO4J_DATABASE
from kgrag.entity_keys import load_entity_keys_by_chunk

DRY_RUN = os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"}
SKIP_HNSW = os.getenv("SKIP_HNSW", "").lower() in {"1", "true", "yes"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EMBEDDING_IDX = f"{VECTOR_TABLE}_embedding_idx"
ENTITY_KEYS_IDX = f"{VECTOR_TABLE}_entity_keys_idx"


def migrate_schema(conn) -> None:
    if DRY_RUN:
        print(f"  DRY  would ensure {VECTOR_TABLE}.entity_keys column + {ENTITY_KEYS_IDX}")
        return
    with conn.cursor() as cur:
        cur.execute(
            f"ALTER TABLE {VECTOR_TABLE} "
            f"ADD COLUMN IF NOT EXISTS entity_keys TEXT[] NOT NULL DEFAULT '{{}}'"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {ENTITY_KEYS_IDX} "
            f"ON {VECTOR_TABLE} USING gin (entity_keys)"
        )
    conn.commit()
    print(f"schema: {VECTOR_TABLE}.entity_keys + {ENTITY_KEYS_IDX} ensured")


def backfill(conn) -> None:
    keys_by_chunk = load_entity_keys_by_chunk()

    with conn.cursor() as cur:
        cur.execute(f"SELECT chunk_id FROM {VECTOR_TABLE}")
        db_ids = {r[0] for r in cur.fetchall()}

    missing_in_db = sorted(set(keys_by_chunk) - db_ids)
    missing_in_extractions = sorted(db_ids - set(keys_by_chunk))
    if missing_in_db:
        print(f"  note: {len(missing_in_db)} extraction chunks not in the vector table (skipped): {missing_in_db[:5]}...")
    if missing_in_extractions:
        print(f"  note: {len(missing_in_extractions)} vector rows have no extraction record: {missing_in_extractions[:5]}...")

    targets = sorted(db_ids & set(keys_by_chunk))
    empties = [cid for cid in targets if not keys_by_chunk[cid]]
    print(f"backfill: {len(targets)} rows to update ({len(empties)} with no entities)")

    if DRY_RUN:
        for cid in targets[:10]:
            print(f"  DRY  {cid} -> {keys_by_chunk[cid][:8]}")
        print("  DRY_RUN set - no writes")
        return

    with conn.cursor() as cur:
        for cid in targets:
            keys = keys_by_chunk[cid]
            cur.execute(
                f"""
                UPDATE {VECTOR_TABLE}
                   SET entity_keys = %(keys)s,
                       metadata = jsonb_set(metadata, '{{entity_keys}}', %(keys_json)s::jsonb),
                       updated_at = NOW()
                 WHERE chunk_id = %(chunk_id)s
                """,
                {"keys": keys, "keys_json": json.dumps(keys), "chunk_id": cid},
            )
    conn.commit()
    print(f"backfill: committed {len(targets)} rows")


def switch_to_hnsw(conn) -> None:
    if SKIP_HNSW:
        print("hnsw: SKIP_HNSW set - leaving index as-is")
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", (EMBEDDING_IDX,)
        )
        row = cur.fetchone()
        if row and "hnsw" in row[0].lower():
            print("hnsw: embedding index already HNSW - nothing to do")
            return
        if DRY_RUN:
            print(f"  DRY  would DROP {EMBEDDING_IDX} and recreate as HNSW")
            return
        cur.execute(f"DROP INDEX IF EXISTS {EMBEDDING_IDX}")
        cur.execute(
            f"""
            CREATE INDEX {EMBEDDING_IDX}
            ON {VECTOR_TABLE} USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            """
        )
    conn.commit()
    print(f"hnsw: {EMBEDDING_IDX} rebuilt as HNSW (m=16, ef_construction=64)")


def verify(conn, check_neo4j: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {VECTOR_TABLE}")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {VECTOR_TABLE} WHERE entity_keys = '{{}}'")
        empty = cur.fetchone()[0]
        cur.execute(
            f"SELECT coalesce(array_length(entity_keys, 1), 0) FROM {VECTOR_TABLE}"
        )
        lengths = sorted(r[0] for r in cur.fetchall())

    print("\n--- verify ---")
    print(f"rows: {total}   empty entity_keys: {empty}")
    if lengths:
        print(f"entity_keys per row: min={lengths[0]} median={median(lengths):.0f} max={lengths[-1]}")

    if not check_neo4j:
        return

    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT unnest(entity_keys) FROM {VECTOR_TABLE}")
        vector_keys = {r[0] for r in cur.fetchall()}

    driver = neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            graph_keys = {
                r["k"] for r in session.run("MATCH (e:Entity) RETURN e.entity_key AS k")
            }
    finally:
        driver.close()

    orphans = sorted(vector_keys - graph_keys)
    print(f"neo4j: {len(graph_keys)} Entity nodes; {len(vector_keys)} distinct keys on vector rows")
    if orphans:
        print(f"  MISMATCH: {len(orphans)} vector keys not in graph: {orphans[:20]}")
        sys.exit(1)
    print("  OK: every vector entity_key exists in Neo4j")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-neo4j", action="store_true", help="Assert vector keys exist in the graph.")
    args = parser.parse_args()

    print(f"table: {VECTOR_TABLE}   DRY_RUN={DRY_RUN}   SKIP_HNSW={SKIP_HNSW}")
    conn = connect()
    try:
        migrate_schema(conn)
        backfill(conn)
        switch_to_hnsw(conn)
        if DRY_RUN:
            print("\nDRY_RUN set - skipping verify (column may not exist yet)")
        else:
            verify(conn, check_neo4j=args.check_neo4j)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
