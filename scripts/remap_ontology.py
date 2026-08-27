from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EXTRACTIONS_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "extractions.jsonl"

ENTITY_TYPES = {
    "Company",
    "Person",
    "Product",
    "Location",
    "Metric",
    "Regulation",
    "Organization",
    "Other",
}

ENTITY_TYPE_REMAP = {
    "Organization": "Organization",
    "Market": "Organization",
    "Government Body": "Organization",
}

RELATION_TYPES = {
    "OWNS",
    "COMPETES_WITH",
    "LOCATED_IN",
    "OPERATES_IN",
    "PRODUCES",
    "SELLS",
    "PROVIDES",
    "USES",
    "WORKS_FOR",
    "REPORTS",
    "ANNOUNCED",
    "HAS_METRIC",
    "SUBJECT_TO",
    "SUES",
    "RELATED_TO",
}

# Consolidation pass (Phase 1 -> 14-type trim, see docs/WHAT_WE_DID_AND_WHY.md):
# folds the thinnest/most-overlapping types into a close semantic neighbor instead
# of leaving them as one-off categories. SUPPLIES had zero instances ever extracted,
# so it just falls through to the RELATED_TO catch-all below like any other unknown value.
RELATION_TYPE_REMAP = {
    "OFFERS": "PROVIDES",
    "ISSUED": "ANNOUNCED",
    "DEVELOPS": "PRODUCES",
    "EXPOSED_TO": "SUBJECT_TO",
    "MANAGES": "RELATED_TO",
}

FALLBACK_RELATION_TYPE = "RELATED_TO"


def remap_entity_type(value: str) -> str:
    if value in ENTITY_TYPES:
        return value
    return ENTITY_TYPE_REMAP.get(value, "Other")


def remap_relation_type(value: str) -> str:
    if value in RELATION_TYPES:
        return value
    return RELATION_TYPE_REMAP.get(value, FALLBACK_RELATION_TYPE)


def main() -> None:
    records = []
    with EXTRACTIONS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    entities_changed = 0
    relationships_changed = 0

    for record in records:
        for entity in record.get("entities", []):
            new_type = remap_entity_type(entity["entity_type"])
            if new_type != entity["entity_type"]:
                entities_changed += 1
                entity["entity_type"] = new_type

        for relationship in record.get("relationships", []):
            new_type = remap_relation_type(relationship["relation_type"])
            if new_type != relationship["relation_type"]:
                relationships_changed += 1
                relationship["relation_type"] = new_type

    with EXTRACTIONS_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Remapped {entities_changed} entity_type values to the closed set.")
    print(f"Remapped {relationships_changed} relation_type values to the closed set.")
    print(f"Wrote {len(records)} records back to {EXTRACTIONS_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
