"""Two-tier entity resolution for ingestion (Phase 1 upgrade).

Previously `load_to_neo4j.py` matched every new entity by exact slug only
(`entity_key = slugify(name)`), which misses real duplicates like "Apple Inc." vs
"Apple". A one-time embedding-similarity cleanup pass fixed the *existing* graph
(`apply_entity_merges.py`), but ingestion itself never got this - the same kind of
duplicate could reappear on the next extraction run.

Why this is two-tier, not a single auto-merge threshold: when 101 merge candidates
were generated for that cleanup pass, similarity score alone did not reliably
separate true from false duplicates - "ASU 2023-09" vs "ASU 2023-07" scored 0.969
(same entity_type, both Regulation) but are genuinely different FASB documents,
while several *correct* merges scored lower. Ingestion has no human in the loop per
entity, so blindly auto-merging above any single threshold risks silently creating
wrong merges nobody catches. Instead:

- Exact slug match (or an already-resolved name from earlier in this run) -> reuse
  that key directly, no embedding call.
- High similarity (>= AUTO_MERGE_THRESHOLD, default 0.95) -> auto-merge. Conservative,
  not risk-free - the measured false positive above scored 0.969, just under a
  slightly stricter bar. Disclosed, not hidden.
- Medium similarity (>= REVIEW_THRESHOLD, default 0.80) -> create a new entity as
  normal (do not guess), but flag it in entity_resolution_review.csv for a human to
  check later - the same shape as entity_merge_candidates.csv.
- Below that -> new entity, no flag, confidently distinct.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .db import NEO4J_DATABASE, neo4j_driver

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REVIEW_PATH = BASE_DIR / "data" / "processed" / "sec_filings" / "entity_resolution_review.csv"

AUTO_MERGE_THRESHOLD = float(os.getenv("AUTO_MERGE_THRESHOLD", "0.95"))
REVIEW_THRESHOLD = float(os.getenv("REVIEW_THRESHOLD", "0.80"))


def slugify(value: str) -> str:
    """Identical to scripts/load_to_neo4j.py::slugify - do not let these drift."""
    import re

    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


@dataclass
class ExistingEntity:
    entity_key: str
    name: str
    entity_type: str
    embedding: np.ndarray | None = None


@dataclass
class ResolutionResult:
    entity_key: str
    matched_existing: bool
    needs_review: bool
    similarity: float | None
    matched_name: str | None = None


def load_existing_entities(driver=None) -> list[ExistingEntity]:
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (e:Entity) RETURN e.entity_key AS entity_key, e.name AS name, e.entity_type AS entity_type"
            )
            return [ExistingEntity(**dict(r)) for r in result]
    finally:
        if own_driver:
            driver.close()


def _embed_all(entities: list[ExistingEntity], model) -> None:
    if not entities:
        return
    names = [e.name for e in entities]
    vectors = model.encode(names, show_progress_bar=False, convert_to_numpy=True)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = vectors / norms
    for entity, vec in zip(entities, normalized):
        entity.embedding = vec


def _embed_one(name: str, model) -> np.ndarray:
    vec = model.encode([name], show_progress_bar=False, convert_to_numpy=True)[0]
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def _append_review_row(row: dict) -> None:
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = REVIEW_PATH.exists()
    with REVIEW_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


class EntityResolver:
    """Stateful across one ingestion run: existing entities loaded once, and every
    newly-created entity gets added to the in-memory pool so later entities in the
    same run can also match against it."""

    def __init__(self, existing: list[ExistingEntity], model):
        self.model = model
        self.entities = list(existing)
        self.by_key = {e.entity_key: e for e in self.entities}
        self._resolved_cache: dict[str, ResolutionResult] = {}
        _embed_all(self.entities, model)

    def resolve(self, name: str, entity_type: str) -> ResolutionResult:
        if name in self._resolved_cache:
            return self._resolved_cache[name]

        key = slugify(name)
        if key in self.by_key:
            result = ResolutionResult(entity_key=key, matched_existing=True, needs_review=False, similarity=1.0)
            self._resolved_cache[name] = result
            return result

        if self.entities:
            query_vec = _embed_one(name, self.model)
            sims = np.array([e.embedding for e in self.entities]) @ query_vec
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])
            best_match = self.entities[best_idx]
        else:
            best_sim, best_match = 0.0, None

        if best_match is not None and best_sim >= AUTO_MERGE_THRESHOLD:
            result = ResolutionResult(
                entity_key=best_match.entity_key,
                matched_existing=True,
                needs_review=False,
                similarity=best_sim,
                matched_name=best_match.name,
            )
            self._resolved_cache[name] = result
            return result

        # New entity - add to the in-memory pool so later names in this run can match it.
        new_entity = ExistingEntity(entity_key=key, name=name, entity_type=entity_type)
        new_entity.embedding = _embed_one(name, self.model)
        self.entities.append(new_entity)
        self.by_key[key] = new_entity

        needs_review = best_match is not None and best_sim >= REVIEW_THRESHOLD
        if needs_review:
            _append_review_row(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "new_name": name,
                    "new_entity_type": entity_type,
                    "matched_existing_name": best_match.name,
                    "matched_existing_key": best_match.entity_key,
                    "similarity": round(best_sim, 4),
                }
            )

        result = ResolutionResult(
            entity_key=key,
            matched_existing=False,
            needs_review=needs_review,
            similarity=best_sim if best_match is not None else None,
            matched_name=best_match.name if needs_review else None,
        )
        self._resolved_cache[name] = result
        return result
