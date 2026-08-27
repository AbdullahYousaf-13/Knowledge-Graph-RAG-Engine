"""Shared library for the hybrid knowledge-graph + vector RAG engine.

Submodules are imported lazily on attribute access so that ``python -m kgrag.retrieval``
does not import ``retrieval`` twice (once here, once by runpy).
"""

_EXPORTS = {
    "connect": "kgrag.db",
    "make_dsn": "kgrag.db",
    "neo4j_driver": "kgrag.db",
    "MERGE_GROUPS": "kgrag.entity_keys",
    "canonical_key": "kgrag.entity_keys",
    "entity_keys_for_record": "kgrag.entity_keys",
    "load_entity_keys_by_chunk": "kgrag.entity_keys",
    "slugify": "kgrag.entity_keys",
    "RetrievedChunk": "kgrag.retrieval",
    "embed_query": "kgrag.retrieval",
    "get_model": "kgrag.retrieval",
    "vector_search": "kgrag.retrieval",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_EXPORTS[name]), name)
