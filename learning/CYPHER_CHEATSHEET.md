# Cypher Cheat Sheet

Every example here runs directly against your actual graph (Neo4j Browser, `f2c530c8` database). Your schema:

```
(:Filing)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATED_TO {relation_type, description, source_chunk_id}]->(:Entity)
```

Paste any query below and hit Run — these aren't hypothetical, they're built for your data.

---

## 1. The core idea: patterns that look like the graph

Cypher queries are literal ASCII drawings of what you're looking for. Parentheses `()` are nodes, square brackets `[]` are relationships, arrows `->` show direction.

```cypher
(a:Entity)-[:RELATED_TO]->(b:Entity)
```
Reads as: "a node labeled Entity, connected by a RELATED_TO relationship, to another node labeled Entity." That's the whole trick — everything below is variations on this one idea.

---

## 2. MATCH + RETURN — the basic read

```cypher
MATCH (e:Entity)
RETURN e
LIMIT 25
```
Find 25 Entity nodes, give them back.

```cypher
MATCH (e:Entity)
RETURN e.name, e.entity_type
LIMIT 25
```
Return specific *properties* instead of the whole node — much more readable in Table view.

**Common mistake (you hit this earlier):** `MATCH (n) RETURN n` only returns nodes, no relationships, so the graph view shows disconnected dots. To see connections, always include the relationship in what you return:
```cypher
MATCH (n)-[r]->(m)
RETURN n, r, m
LIMIT 100
```

---

## 3. Filtering with WHERE

```cypher
MATCH (e:Entity)
WHERE e.entity_type = "Company"
RETURN e.name
```
Finds every Entity node whose `entity_type` property is exactly `"Company"`, and returns just their names.

```cypher
MATCH (c:Chunk)
WHERE c.filing_year = "2024"
RETURN c.chunk_id, c.section_name
LIMIT 10
```
Finds Chunk nodes from the 2024 filing year, returns their id and section name, capped at 10 results.

**Text search (case-insensitive contains):**
```cypher
MATCH (e:Entity)
WHERE toLower(e.name) CONTAINS "apple"
RETURN e.name, e.entity_type
```
Lowercases each entity's name before comparing, so it matches "Apple Inc.", "APPLE", "apple" — anything containing the substring `"apple"` regardless of case.

**Multiple conditions:**
```cypher
MATCH (c:Chunk)
WHERE c.filing_year = "2024" AND c.section_name CONTAINS "RISK"
RETURN c.chunk_id
```
Finds only chunks that satisfy *both* conditions at once: from 2024, AND from a section whose name contains "RISK" (e.g. "ITEM 1A. RISK FACTORS").

---

## 4. Following relationships (the whole point of a graph database)

**One hop — what does a chunk mention?**
```cypher
MATCH (c:Chunk {chunk_id: "apple-inc-2024-0058"})-[:MENTIONS]->(e:Entity)
RETURN e.name, e.entity_type
```
Starts at one specific chunk (filtered inline by `chunk_id`), follows every outgoing `MENTIONS` edge, and returns every entity that chunk talks about.

**One hop — what is an entity related to?**
```cypher
MATCH (a:Entity {name: "Apple Inc."})-[r:RELATED_TO]->(b:Entity)
RETURN a.name, r.relation_type, b.name
```
Starts at the "Apple Inc." node, follows every outgoing `RELATED_TO` edge, and returns each connected entity along with what kind of relationship connects them (`r.relation_type`, e.g. `SUPPLIES` or `COMPETES_WITH`).

**Two hops — a friend of a friend, graph-style:**
```cypher
MATCH (a:Entity {name: "Apple Inc."})-[:RELATED_TO]->(mid:Entity)-[:RELATED_TO]->(b:Entity)
RETURN a.name, mid.name, b.name
LIMIT 25
```
This is the actual "multi-hop question" the whole project is built to answer — a plain vector search can't do this, only graph traversal can.

**Relationships in either direction** (drop the arrowhead):
```cypher
MATCH (a:Entity {name: "Apple Inc."})-[r:RELATED_TO]-(b:Entity)
RETURN a.name, r.relation_type, b.name
```
Same as the query above, but finds relationships pointing *either* into or out of Apple — useful when you don't know or don't care which direction a relationship was extracted in.

**Filter by relationship type:**
```cypher
MATCH (a:Entity)-[r:RELATED_TO {relation_type: "SUPPLIES"}]->(b:Entity)
RETURN a.name, b.name
```
Filters the relationship itself, not just the nodes — only follows `RELATED_TO` edges whose `relation_type` property is exactly `"SUPPLIES"`, so you get supplier pairs only, not every relationship type mixed together.

---

## 5. Aggregation — counting and grouping

```cypher
MATCH (n)
RETURN labels(n) AS label, count(*) AS n
ORDER BY n DESC
```
This is the exact query used to verify your graph's state throughout this project (225 Chunks, 279 Entities, 3 Filings).

**Which entities are mentioned the most?**
```cypher
MATCH (e:Entity)<-[:MENTIONS]-(c:Chunk)
RETURN e.name, count(c) AS mention_count
ORDER BY mention_count DESC
LIMIT 10
```
For every entity, counts how many distinct chunks mention it (note the arrow points *into* `e`, since `Chunk-[:MENTIONS]->Entity`), then sorts to show the 10 most-mentioned entities first — a quick way to see which companies/products dominate the corpus.

**Group relationships by type:**
```cypher
MATCH ()-[r:RELATED_TO]->()
RETURN r.relation_type, count(*) AS n
ORDER BY n DESC
```
The empty `()` on both ends means "any node, don't care what" — this only cares about the relationship. Groups all `RELATED_TO` edges by their `relation_type` value and counts how many of each exist, e.g. `SUPPLIES: 42, COMPETES_WITH: 18`.

**Collect into a list instead of counting:**
```cypher
MATCH (c:Chunk {chunk_id: "apple-inc-2024-0058"})-[:MENTIONS]->(e:Entity)
RETURN collect(e.name) AS entities
```
Same traversal as the "what does a chunk mention" query above, but `collect()` packs all the matched names into a single list in one row, instead of returning one row per entity.

---

## 6. ORDER BY, LIMIT, DISTINCT

```cypher
MATCH (c:Chunk)
RETURN DISTINCT c.filing_year
ORDER BY c.filing_year
```
Lists every unique `filing_year` value present in your Chunk nodes, sorted ascending — a quick way to confirm exactly which years actually made it into the graph (e.g. `2023, 2024, 2025`), without seeing 225 repeated rows.

```cypher
MATCH (e:Entity)
RETURN e.name
ORDER BY e.confidence DESC
LIMIT 5
```
Sorts all entities by their extraction `confidence` score, highest first, and shows only the top 5 — useful for spot-checking Gemini's most confident extractions (or, sorted the other way with `ASC`, its shakiest ones).

---

## 7. Writing data: CREATE vs. MERGE (this is the important one)

**CREATE always makes a new node/relationship — even a duplicate:**
```cypher
CREATE (e:Entity {name: "Test Corp"})
```
Run this twice, you get two separate nodes. Dangerous for re-runnable pipelines.

**MERGE finds-or-creates — this is what your project actually uses everywhere:**
```cypher
MERGE (e:Entity {entity_key: "apple-inc"})
SET e.name = "Apple Inc.", e.entity_type = "Company"
```
Run this twice, you still get exactly one node. This is *why* `load_to_neo4j.py` can be re-run safely without creating duplicate entities — every `upsert_entity()`/`upsert_relationship()` call is a `MERGE`, not a `CREATE`. **Rule of thumb: in this project, you should basically never write `CREATE` — always `MERGE`.**

**Creating a relationship the same way:**
```cypher
MATCH (a:Entity {entity_key: "apple-inc"}), (b:Entity {entity_key: "foxconn"})
MERGE (a)-[r:RELATED_TO {source_chunk_id: "apple-inc-2024-0058"}]->(b)
SET r.relation_type = "SUPPLIES"
```
First finds the two already-existing entity nodes by their keys, then finds-or-creates a `RELATED_TO` edge between them (keyed by which chunk sourced it, so the same fact from a different chunk creates a separate edge rather than colliding), then sets its type. This is the exact pattern `upsert_relationship()` uses.

---

## 8. SET, REMOVE, DELETE

```cypher
MATCH (e:Entity {entity_key: "apple-inc"})
SET e.confidence = 0.95
```
Finds the Apple entity node and overwrites (or adds, if it didn't exist) its `confidence` property to `0.95`. `SET` doesn't care whether the property existed before — it just makes it true now.

```cypher
MATCH (e:Entity {entity_key: "apple-inc"})
REMOVE e.confidence
```
Finds the same node and deletes the `confidence` property entirely — the property stops existing on that node, as opposed to `SET`ting it to null/empty.

**DELETE a node — fails if it still has relationships:**
```cypher
MATCH (e:Entity {name: "Test Corp"})
DELETE e
```
Deletes the matched node — but Neo4j will throw an error here if "Test Corp" still has any `MENTIONS` or `RELATED_TO` edges attached, since a graph database won't let you leave a "dangling" relationship pointing at a node that no longer exists.

**DETACH DELETE — deletes the node AND all its relationships in one go.** This is what was used to purge the old 2021 data from your graph:
```cypher
MATCH (c:Chunk {filing_year: "2021"})
DETACH DELETE c
```

---

## 9. Parameters (never hardcode values into a query string)

Instead of baking a value into the query text, use a `$parameter`:
```cypher
MATCH (e:Entity {name: $entity_name})
RETURN e
```
This is exactly what `upsert_entity(tx, entity, record)` in `load_to_neo4j.py` does — the Cypher text is a fixed template, and Python passes in `chunk_id`, `name`, `entity_type`, etc. as parameters via `tx.run(query, chunk_id=..., name=...)`. **This is also the security mechanism the guide insists on for Phase 3**: never let an LLM write the query text itself, only let it fill in parameter values into a template you already wrote.

---

## 10. Paths — useful for "how are these two things connected"

```cypher
MATCH path = (a:Entity {name: "Apple Inc."})-[:RELATED_TO*1..3]-(b:Entity {name: "Samsung"})
RETURN path
LIMIT 5
```
`*1..3` means "1 to 3 hops, any number of relationships in between" — finds a connection even if it's not direct. Useful for genuinely multi-hop questions.

---

## 11. EXISTS — checking without retrieving

```cypher
MATCH (e:Entity {name: "Apple Inc."})
WHERE EXISTS { (e)-[:RELATED_TO]->(:Entity {name: "Samsung"}) }
RETURN e.name
```
"Give me Apple only if it's directly related to Samsung" — doesn't return the relationship itself, just filters.

---

## Quick syntax reference

| Symbol | Meaning |
|---|---|
| `(n)` | A node, stored in variable `n` |
| `(n:Label)` | A node with a specific label (e.g. `Entity`, `Chunk`) |
| `(n:Label {prop: "val"})` | A node filtered by a property inline |
| `[r]` | A relationship, stored in variable `r` |
| `[r:TYPE]` | A relationship of a specific type (e.g. `RELATED_TO`) |
| `-->` | Relationship pointing right (direction matters) |
| `--` | Relationship, direction ignored |
| `*1..3` | Variable-length path, 1 to 3 hops |
| `$param` | A parameter passed in from code, not hardcoded |

| Clause | Purpose |
|---|---|
| `MATCH` | Find a pattern in the graph |
| `WHERE` | Filter results |
| `RETURN` | Output values |
| `CREATE` | Always insert new — can duplicate |
| `MERGE` | Find-or-create — idempotent, use this instead of CREATE |
| `SET` | Update/add a property |
| `REMOVE` | Delete a property |
| `DELETE` | Remove a node/relationship (node must have no relationships) |
| `DETACH DELETE` | Remove a node and all its relationships at once |
| `ORDER BY` | Sort results |
| `LIMIT` | Cap the number of results |
| `DISTINCT` | Remove duplicate rows |
| `count()`, `collect()` | Aggregate results |

## What actually matters for this project

You don't need to memorize all of Cypher. The patterns you'll actually reuse in Phase 3 (routing) are:
1. **Entity linking**: `MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($question_entity) RETURN e` — turning a name from a user's question into a real graph node.
2. **Relationship lookup**: `MATCH (a:Entity {entity_key: $key})-[r:RELATED_TO]->(b) RETURN a, r, b` — the actual "answer this relationship question" query.
3. **Multi-hop traversal**: the `*1..3` pattern from section 10, for genuinely multi-hop questions.
4. **Parameterized templates**: section 9 — every query you write for Phase 3 should take `$parameters`, never string-concatenate user input into Cypher directly.
