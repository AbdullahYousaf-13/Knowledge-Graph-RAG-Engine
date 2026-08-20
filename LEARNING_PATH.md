# Learning Path

Free courses mapped to Project 1's concepts, in the order to take them. Check items off as you go. See `ML_CONCEPTS_NOTES.md` for the deep-dive notes on each concept once you've taken the course.

## Already implemented — reinforce these first

- [ ] **Cypher Fundamentals** (Neo4j GraphAcademy, ~1 hr, free)
      https://graphacademy.neo4j.com/courses/cypher-fundamentals
      Covers: Cypher query language — reinforces every query you've run in Neo4j Browser.

- [ ] **Neo4j Fundamentals** (Neo4j GraphAcademy, free)
      https://graphacademy.neo4j.com/courses/neo4j-fundamentals
      Covers: graph modeling, nodes/edges — reinforces your `Entity`/`Chunk`/`Filing` schema.

- [ ] **Building Knowledge Graphs with LLMs** (Neo4j GraphAcademy, free)
      https://graphacademy.neo4j.com/courses/llm-knowledge-graph-construction/
      Covers: NER, relationship extraction, entity resolution — reinforces `extract_sec_entities.py` + `load_to_neo4j.py`.

- [ ] **Vector Databases: from Embeddings to Applications** (DeepLearning.AI × Weaviate, free)
      https://www.deeplearning.ai/courses/vector-databases-embeddings-applications
      Covers: embeddings, cosine similarity, vector search fundamentals — reinforces `build_pgvector_index.py`.

- [ ] **Knowledge Graphs for RAG** (DeepLearning.AI × Neo4j, ~60 min, free)
      https://www.deeplearning.ai/courses/knowledge-graphs-rag
      Covers: combining a knowledge graph with a vector index — your exact architecture. Uses financial documents as the demo corpus.

## About to implement — prioritize these next

- [ ] **Neo4j & Generative AI Certification** (Neo4j GraphAcademy, free)
      https://graphacademy.neo4j.com/certifications/genai-certification/
      Covers: routing, entity linking, Text2Cypher, hybrid search — this is Phase 3 (routing) taught before you build it.

- [ ] **Building and Evaluating Advanced RAG** (DeepLearning.AI, ~2 hrs, free)
      https://www.deeplearning.ai/courses/building-evaluating-advanced-rag
      Covers: merging sources, deduplication, citation grounding, RAG evaluation (context relevance, groundedness, answer relevance) — this is Phase 4 (merging/citations) and the vocabulary for Phase 5 (benchmarking).

- [ ] **FastAPI Official Tutorial** (free)
      https://fastapi.tiangolo.com/tutorial/
      Covers: building the endpoint needed for Project 1's "Done when" criteria.

## Notes

Add anything you learn that surprises you, or that contradicts what's in `ML_CONCEPTS_NOTES.md`, here — then update the notes file to match.
