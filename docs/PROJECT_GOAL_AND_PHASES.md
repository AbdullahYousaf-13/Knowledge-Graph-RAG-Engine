# Project Goal and Phases

## Goal

This project is a hybrid knowledge graph RAG system built over SEC filings.

The goal is to answer multi-hop questions by combining graph retrieval and vector retrieval with citations.

In practice, the system should:

- extract entities and relationships into Neo4j
- build a vector index over the same document chunks in pgvector
- route each question to the best retrieval path
- merge graph and vector results into one grounded answer
- return citations for every claim
- benchmark the system against a vector-only baseline

## Project Phases

### Phase 1: Extract entities and relationships into Neo4j

- Choose a small set of SEC filings from the public EDGAR data source.
- Define a limited ontology before coding.
- Chunk documents and extract structured entities and relationships.
- Resolve duplicate entities so the same real-world item becomes one graph node.
- Store source chunk IDs so every edge can be traced back to evidence.

### Phase 2: Build the vector index alongside the graph

- Embed the same chunks into pgvector.
- Store metadata such as document id, section path, date, and referenced entity ids.
- Use shared chunk IDs between the graph and vector store.
- Measure retrieval quality before building any routing logic.

### Phase 3: Route questions to the right retrieval path

- Add a lightweight router that chooses graph retrieval, vector retrieval, or both.
- Use graph retrieval for multi-hop, comparison, and relationship questions.
- Use vector retrieval for definitions, policy lookups, and single-fact questions.
- Keep graph queries parameterized instead of letting the model write raw Cypher.

### Phase 4: Merge both sources into one grounded answer

- Convert graph paths into readable statements.
- Combine graph facts and retrieved passages into one context block.
- Deduplicate overlapping evidence.
- Require a citation for every claim and verify that each citation resolves to retrieved data.

### Phase 5: Benchmark against plain vector RAG

- Build a labeled question set with single-hop, multi-hop, aggregation, and out-of-scope questions.
- Compare the hybrid system to a vector-only baseline.
- Report accuracy by hop count, plus latency and cost per query.
- Put the benchmark results at the top of the README.

## Done When

The project is complete when a FastAPI endpoint can answer questions with validated citations and the README shows a benchmark table proving the hybrid approach against a vector-only baseline on SEC filings.
