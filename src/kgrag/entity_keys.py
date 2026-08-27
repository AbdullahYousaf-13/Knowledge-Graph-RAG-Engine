"""Cross-database entity identity.

Neo4j `Entity` nodes are keyed by ``entity_key = slugify(name)``. The vector store
(`sec_chunk_embeddings.entity_keys`) reuses the exact same slug so the two stores
join on a plain string with no separate id system.

Two things live here so there is a single source of truth:

1. ``slugify`` - MUST stay byte-for-byte identical to ``scripts/load_to_neo4j.py``'s
   ``slugify``. If they drift, the vector-side keys silently stop matching the graph.
2. ``MERGE_GROUPS`` - the entity-resolution merges that were already applied to the
   live graph (see ``scripts/apply_entity_merges.py``). ``extractions.jsonl`` still
   holds the *pre-merge* entity names, so slugifying a name from it can produce a key
   that no longer exists in Neo4j. ``canonical_key`` remaps those to the survivor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EXTRACTIONS_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "extractions.jsonl"

# Keep in sync with scripts/apply_entity_merges.py::MERGE_GROUPS (that script already
# ran against the live AuraDB and must not be re-touched; this is a deliberate copy).
# Format: (canonical_entity_key, [duplicate_entity_keys])
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

DUP_TO_CANON: dict[str, str] = {
    dup: canon for canon, dups in MERGE_GROUPS for dup in dups
}


def slugify(value: str) -> str:
    """Identical to scripts/load_to_neo4j.py::slugify - do not let these drift."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def canonical_key(name: str) -> str:
    """Slug for an entity name, remapped to its post-merge survivor if it was merged."""
    key = slugify(name)
    return DUP_TO_CANON.get(key, key)


def entity_keys_for_record(record: dict) -> list[str]:
    """Sorted, de-duplicated canonical entity keys for one extractions.jsonl record."""
    keys = {
        canonical_key(entity["name"])
        for entity in record.get("entities", [])
        if entity.get("name")
    }
    keys.discard("")
    return sorted(keys)


def load_entity_keys_by_chunk(path: Path | str = EXTRACTIONS_PATH) -> dict[str, list[str]]:
    """Map every chunk_id in the extractions file to its canonical entity keys."""
    result: dict[str, list[str]] = {}
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            result[record["chunk_id"]] = entity_keys_for_record(record)
    return result
