"""Shared library for the hybrid knowledge-graph + vector RAG engine."""

from .db import connect, make_dsn, neo4j_driver
from .entity_keys import (
    MERGE_GROUPS,
    canonical_key,
    entity_keys_for_record,
    load_entity_keys_by_chunk,
    slugify,
)
from .retrieval import RetrievedChunk, embed_query, get_model, vector_search

__all__ = [
    "connect",
    "make_dsn",
    "neo4j_driver",
    "MERGE_GROUPS",
    "canonical_key",
    "entity_keys_for_record",
    "load_entity_keys_by_chunk",
    "slugify",
    "RetrievedChunk",
    "embed_query",
    "get_model",
    "vector_search",
]
