"""Shared database connections for Postgres/pgvector and Neo4j.

Every script used to re-implement its own ``load_dotenv()`` + DSN handling + driver
setup. This is the single home for that. ``.env`` is loaded on import.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# --- Postgres / pgvector -----------------------------------------------------

POSTGRES_DSN = os.getenv("POSTGRES_DSN")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_graph_rag")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

VECTOR_TABLE = os.getenv("VECTOR_TABLE", "sec_chunk_embeddings")


def make_dsn() -> str:
    """Prefer a full POSTGRES_DSN; fall back to discrete POSTGRES_* parts."""
    if POSTGRES_DSN:
        return POSTGRES_DSN
    if not POSTGRES_PASSWORD:
        raise SystemExit("Set POSTGRES_DSN or POSTGRES_PASSWORD before connecting to Postgres.")
    return (
        f"host={POSTGRES_HOST} port={POSTGRES_PORT} dbname={POSTGRES_DB} "
        f"user={POSTGRES_USER} password={POSTGRES_PASSWORD}"
    )


def connect(*, register_pgvector: bool = True):
    """Open a psycopg connection with the pgvector type adapters wired in."""
    import psycopg

    conn = psycopg.connect(make_dsn())
    if register_pgvector:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    return conn


# --- Neo4j -----------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")


def neo4j_driver():
    """GraphDatabase driver from NEO4J_* env vars."""
    from neo4j import GraphDatabase

    if not NEO4J_PASSWORD:
        raise SystemExit("NEO4J_PASSWORD is not set.")
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
