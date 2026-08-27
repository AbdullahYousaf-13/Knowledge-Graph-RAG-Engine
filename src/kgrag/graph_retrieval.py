"""Parameterized graph retrieval over the Neo4j knowledge graph.

Imported by ``src/kgrag/router.py`` (Phase 3) and later Phase 4. Every query here is a
fixed Cypher template with bound parameters - the model never writes or extends Cypher
text itself (see ``learning/CYPHER_CHEATSHEET.md`` section 9: "never let an LLM write
the query text itself, only let it fill in parameter values into a template you
already wrote").

Query shapes are the ones already validated in the cheat sheet: fuzzy entity lookup
(section 4), variable-length path traversal (section 10).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from .db import NEO4J_DATABASE, neo4j_driver


@dataclass
class EntityMatch:
    entity_key: str
    name: str
    entity_type: str


@dataclass
class GraphFact:
    source: str
    relation_type: str
    target: str
    description: str
    source_chunk_id: str
    confidence: float


def resolve_entity(name: str, *, driver=None, limit: int = 5) -> list[EntityMatch]:
    """Resolve a name to graph entities: exact match first, substring match only as
    a fallback when nothing matches exactly.

    Without the exact-match-first step, a name like "Apple" would loosely match
    every entity containing that substring - "Apple TV 4K", "Apple Watch Series 9",
    "Apple Vision Pro", not just "Apple Inc." - and pull unrelated products into
    results downstream. Prefer the precise match; only fall back to fuzzy substring
    search when the name genuinely isn't an exact entity name (e.g. "outsourcing
    partners", which never was one).
    """
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            exact = session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) = toLower($name)
                RETURN e.entity_key AS entity_key, e.name AS name, e.entity_type AS entity_type
                LIMIT $limit
                """,
                name=name,
                limit=limit,
            )
            exact_matches = [EntityMatch(**dict(r)) for r in exact]
            if exact_matches:
                return exact_matches

            fuzzy = session.run(
                """
                MATCH (e:Entity)
                WHERE toLower(e.name) CONTAINS toLower($name)
                RETURN e.entity_key AS entity_key, e.name AS name, e.entity_type AS entity_type
                LIMIT $limit
                """,
                name=name,
                limit=limit,
            )
            fuzzy_matches = [EntityMatch(**dict(r)) for r in fuzzy]

            # Ambiguous fuzzy match (e.g. bare "Apple" also matches "Apple TV 4K",
            # "Apple Watch Series 9", etc.) - if exactly one candidate is a Company,
            # prefer it. A generic name almost always means the business, not one of
            # its specific products, once product-specific wording isn't present
            # (a search for "Apple TV" instead would have hit the exact-match branch
            # above and never reached here).
            companies = [m for m in fuzzy_matches if m.entity_type == "Company"]
            if len(fuzzy_matches) > 1 and len(companies) == 1:
                return companies

            return fuzzy_matches
    finally:
        if own_driver:
            driver.close()


def entity_neighbors(entity_key: str, *, hops: int = 2, driver=None, limit: int = 25) -> list[GraphFact]:
    """RELATED_TO paths of 1..hops from one resolved entity, in either direction."""
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                f"""
                MATCH (a:Entity {{entity_key: $entity_key}})-[r:RELATED_TO*1..{int(hops)}]-(b:Entity)
                UNWIND r AS rel
                WITH DISTINCT rel
                MATCH (src:Entity)-[rel]->(tgt:Entity)
                RETURN src.name AS source, rel.relation_type AS relation_type, tgt.name AS target,
                       rel.description AS description, rel.source_chunk_id AS source_chunk_id,
                       rel.confidence AS confidence
                LIMIT $limit
                """,
                entity_key=entity_key,
                limit=limit,
            )
            return [GraphFact(**dict(r)) for r in result]
    finally:
        if own_driver:
            driver.close()


def entity_paths_between(
    key_a: str, key_b: str, *, hops: int = 2, driver=None, limit: int = 25
) -> list[GraphFact]:
    """RELATED_TO facts along direct paths connecting two specific resolved entities.

    Precise where ``entity_neighbors`` is not: a hub entity like "Apple Inc." has so
    many relationships that fanning out from it alone floods results with irrelevant
    facts. Constraining the path to end at a *second* named entity (e.g. Apple AND
    Epic Games) surfaces only what actually connects them.
    """
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                f"""
                MATCH path = (a:Entity {{entity_key: $key_a}})-[:RELATED_TO*1..{int(hops)}]-(b:Entity {{entity_key: $key_b}})
                WITH path LIMIT 10
                UNWIND relationships(path) AS rel
                WITH DISTINCT rel
                MATCH (src:Entity)-[rel]->(tgt:Entity)
                RETURN src.name AS source, rel.relation_type AS relation_type, tgt.name AS target,
                       rel.description AS description, rel.source_chunk_id AS source_chunk_id,
                       rel.confidence AS confidence
                LIMIT $limit
                """,
                key_a=key_a,
                key_b=key_b,
                limit=limit,
            )
            return [GraphFact(**dict(r)) for r in result]
    finally:
        if own_driver:
            driver.close()


def graph_search(entity_names: list[str], *, hops: int = 2, driver=None) -> list[GraphFact]:
    """Resolve each named entity and find what connects them. The one entry point
    ``router.execute_route`` calls - mirrors ``retrieval.vector_search()``'s shape.

    Prefers precise cross-entity paths (e.g. Apple <-> Epic Games) over a single
    entity's raw neighborhood, since a hub entity's full neighbor list is mostly noise.
    Falls back to per-entity neighbors only when there's one resolved entity, or when
    no direct path connects any pair (the entities genuinely aren't linked in the graph).
    """
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        groups: list[list[EntityMatch]] = [
            matches for name in entity_names if (matches := resolve_entity(name, driver=driver))
        ]

        facts: dict[tuple[str, str, str, str], GraphFact] = {}

        if len(groups) >= 2:
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    for a in groups[i]:
                        for b in groups[j]:
                            for fact in entity_paths_between(a.entity_key, b.entity_key, hops=hops, driver=driver):
                                key = (fact.source, fact.relation_type, fact.target, fact.source_chunk_id)
                                facts[key] = fact

        if not facts:
            for match in {m.entity_key: m for group in groups for m in group}.values():
                for fact in entity_neighbors(match.entity_key, hops=1, driver=driver):
                    key = (fact.source, fact.relation_type, fact.target, fact.source_chunk_id)
                    facts[key] = fact

        return list(facts.values())
    finally:
        if own_driver:
            driver.close()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Graph retrieval smoke test.")
    parser.add_argument("entity", help="Entity name (or partial name) to look up.")
    parser.add_argument("--hops", type=int, default=2)
    args = parser.parse_args()

    matches = resolve_entity(args.entity)
    print(f"Resolved {len(matches)} entity match(es) for '{args.entity}':")
    for m in matches:
        print(f"  {m.entity_key}  ({m.entity_type})  {m.name}")

    facts = graph_search([args.entity], hops=args.hops)
    print(f"\n{len(facts)} graph fact(s) within {args.hops} hop(s):")
    for f in facts:
        print(f"  {f.source} -[{f.relation_type}]-> {f.target}   ({f.source_chunk_id})")
        print(f"      {f.description}")


if __name__ == "__main__":
    _main()
