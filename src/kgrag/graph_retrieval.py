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
    anchor: str = ""  # for comparison queries: which question entity this fact was pulled for


@dataclass
class GraphRelationSummary:
    """One row of an aggregation query: how many of a given relation type an entity has,
    and (a sample of) what's on the other end. ``source_chunk_ids`` is a few of the
    chunks that sourced these edges, so aggregation claims stay citable (Phase 4)."""
    entity_key: str
    entity_name: str
    relation_type: str
    count: int
    targets: list[str]
    source_chunk_ids: list[str]


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


def entity_relation_summary(entity_key: str, *, driver=None, limit: int = 50) -> list[GraphRelationSummary]:
    """Aggregation template: group one entity's outgoing RELATED_TO edges by relation
    type, with a count and a sample of the entities on the other end. Answers
    "which regulations is Apple subject to?" / "who does Apple compete with?" style
    questions where the shape of the answer is a tally, not a path."""
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            result = session.run(
                """
                MATCH (a:Entity {entity_key: $entity_key})-[r:RELATED_TO]->(b:Entity)
                RETURN a.entity_key AS entity_key, a.name AS entity_name,
                       r.relation_type AS relation_type,
                       count(*) AS count,
                       collect(DISTINCT b.name)[..25] AS targets,
                       collect(DISTINCT r.source_chunk_id)[..5] AS source_chunk_ids
                ORDER BY count DESC
                LIMIT $limit
                """,
                entity_key=entity_key,
                limit=limit,
            )
            return [GraphRelationSummary(**dict(r)) for r in result]
    finally:
        if own_driver:
            driver.close()


def _resolve_groups(entity_names: list[str], driver) -> list[list[EntityMatch]]:
    return [matches for name in entity_names if (matches := resolve_entity(name, driver=driver))]


def _pairwise_path_facts(groups: list[list[EntityMatch]], *, hops: int, driver) -> list[GraphFact]:
    facts: dict[tuple, GraphFact] = {}
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            for a in groups[i]:
                for b in groups[j]:
                    for fact in entity_paths_between(a.entity_key, b.entity_key, hops=hops, driver=driver):
                        facts[(fact.source, fact.relation_type, fact.target, fact.source_chunk_id)] = fact
    return list(facts.values())


def _neighborhood_facts(groups: list[list[EntityMatch]], *, hops: int, driver) -> list[GraphFact]:
    facts: dict[tuple, GraphFact] = {}
    for match in {m.entity_key: m for group in groups for m in group}.values():
        for fact in entity_neighbors(match.entity_key, hops=hops, driver=driver):
            facts[(fact.source, fact.relation_type, fact.target, fact.source_chunk_id)] = fact
    return list(facts.values())


def _comparison_facts(groups: list[list[EntityMatch]], *, hops: int, driver) -> list[GraphFact]:
    """Each entity's neighborhood, kept separate (tagged with ``anchor``) so a caller
    can line the two sets up side by side."""
    out: list[GraphFact] = []
    for match in {m.entity_key: m for group in groups for m in group}.values():
        seen: set[tuple] = set()
        for fact in entity_neighbors(match.entity_key, hops=hops, driver=driver):
            key = (fact.source, fact.relation_type, fact.target, fact.source_chunk_id)
            if key in seen:
                continue
            seen.add(key)
            fact.anchor = match.name
            out.append(fact)
    return out


# query_type -> which template(s) graph_search uses. The router fills the enum; this
# is the "template library keyed by query type" the spec asks for. Aggregation is
# handled by graph_aggregate() since its return shape differs.
def _infer_query_type(groups: list[list[EntityMatch]]) -> str:
    """Fallback when the router gave no usable query_type: two+ entities => look for
    what connects them, one entity => its neighborhood."""
    return "connection" if len(groups) >= 2 else "neighborhood"


def graph_search(
    entity_names: list[str], *, query_type: str | None = None, hops: int = 2, driver=None
) -> list[GraphFact]:
    """Resolve each named entity, then pick a Cypher template by ``query_type``:

    - connection / multi_hop -> cross-entity paths (``entity_paths_between``); falls back
      to neighborhoods if nothing connects the entities.
    - comparison -> each entity's neighborhood, tagged with ``anchor``.
    - neighborhood / none / unknown -> ``_infer_query_type`` heuristic (2+ entities =>
      connection, else neighborhood).

    ``aggregation`` is not handled here - the router calls ``graph_aggregate`` for that.
    The model only ever supplies the enum and the entity names; it never writes Cypher.
    """
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        groups = _resolve_groups(entity_names, driver)
        if not groups:
            return []

        qt = query_type if query_type in {"connection", "multi_hop", "comparison"} else _infer_query_type(groups)

        if qt == "comparison":
            return _comparison_facts(groups, hops=1, driver=driver)

        if qt in {"connection", "multi_hop"}:
            facts = _pairwise_path_facts(groups, hops=hops, driver=driver)
            if facts:
                return facts

        return _neighborhood_facts(groups, hops=1, driver=driver)
    finally:
        if own_driver:
            driver.close()


def graph_aggregate(entity_names: list[str], *, hops: int = 2, driver=None) -> list[GraphRelationSummary]:
    """Entry point for ``query_type == "aggregation"``. Resolves each name and runs the
    aggregation template per resolved entity. ``hops`` is accepted for a uniform call
    signature but unused - aggregation looks at direct relations only."""
    own_driver = driver is None
    driver = driver or neo4j_driver()
    try:
        out: list[GraphRelationSummary] = []
        seen: set[str] = set()
        for name in entity_names:
            for match in resolve_entity(name, driver=driver):
                if match.entity_key in seen:
                    continue
                seen.add(match.entity_key)
                out.extend(entity_relation_summary(match.entity_key, driver=driver))
        return out
    finally:
        if own_driver:
            driver.close()


def _main() -> None:
    parser = argparse.ArgumentParser(description="Graph retrieval smoke test.")
    parser.add_argument("entity", nargs="+", help="Entity name(s) (or partial names) to look up.")
    parser.add_argument("--hops", type=int, default=2)
    parser.add_argument(
        "--query-type",
        choices=["connection", "multi_hop", "comparison", "aggregation"],
        default=None,
    )
    args = parser.parse_args()

    for name in args.entity:
        matches = resolve_entity(name)
        print(f"Resolved {len(matches)} entity match(es) for '{name}':")
        for m in matches:
            print(f"  {m.entity_key}  ({m.entity_type})  {m.name}")

    if args.query_type == "aggregation":
        rows = graph_aggregate(args.entity)
        print(f"\n{len(rows)} aggregate row(s):")
        for r in rows:
            print(f"  {r.entity_name}: {r.relation_type} x{r.count} -> {', '.join(r.targets[:8])}")
        return

    facts = graph_search(args.entity, query_type=args.query_type, hops=args.hops)
    print(f"\n{len(facts)} graph fact(s) within {args.hops} hop(s):")
    for f in facts:
        tag = f"  [{f.anchor}]" if f.anchor else ""
        print(f"  {f.source} -[{f.relation_type}]-> {f.target}   ({f.source_chunk_id}){tag}")
        print(f"      {f.description}")


if __name__ == "__main__":
    _main()
