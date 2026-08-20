# Learning Path

Free courses mapped to Project 1's concepts, in the order to take them. Check items off as you go. See `ML_CONCEPTS_NOTES.md` for the deep-dive notes on each concept once you've taken the course.

## Already implemented — reinforce these first

- [x] **Cypher Fundamentals** (Neo4j GraphAcademy, ~1 hr, free)
  ```
  https://graphacademy.neo4j.com/courses/cypher-fundamentals
  Covers: Cypher query language — reinforces every query you've run in Neo4j Browser.
  See `CYPHER_CHEATSHEET.md` for a project-specific quick reference.
  ```

- [x] **Neo4j Fundamentals** (Neo4j GraphAcademy, ~1 hr, free)
  ```
  https://graphacademy.neo4j.com/courses/neo4j-fundamentals
  Covers: graph modeling, nodes/edges — reinforces your `Entity`/`Chunk`/`Filing` schema.
  ```

- [ ] **Building Knowledge Graphs with LLMs** (Neo4j GraphAcademy, ~2 hrs, free)
  ```
  https://graphacademy.neo4j.com/courses/llm-knowledge-graph-construction/
  Covers: NER, relationship extraction, entity resolution — reinforces `extract_sec_entities.py` + `load_to_neo4j.py`.
  ```

- [ ] **Vector Databases: from Embeddings to Applications** (DeepLearning.AI × Weaviate, ~1 hr, free)
  ```
  https://www.deeplearning.ai/courses/vector-databases-embeddings-applications
  Covers: embeddings, cosine similarity, vector search fundamentals — reinforces `build_pgvector_index.py`.
  ```

- [ ] **Knowledge Graphs for RAG** (DeepLearning.AI × Neo4j, ~60 min, free)
  ```
  https://www.deeplearning.ai/courses/knowledge-graphs-rag
  Covers: combining a knowledge graph with a vector index — your exact architecture. Uses financial documents as the demo corpus.
  ```



## About to implement — prioritize these next

- [ ] **Neo4j & Generative AI Certification** (Neo4j GraphAcademy, ~18 hrs full prep path + 1 hr exam, free)
  ```
  https://graphacademy.neo4j.com/certifications/genai-certification/
  Covers: routing, entity linking, Text2Cypher, hybrid search — this is Phase 3 (routing) taught before you build it.
  The ~18 hrs is the full recommended 10-course prep path; you can take just the specific
  courses you need (e.g. "Neo4j & GenerativeAI Fundamentals") without doing all 10 before
  attempting the 1-hr exam.
  ```

- [ ] **Building and Evaluating Advanced RAG** (DeepLearning.AI, ~2 hrs, free)
  ```
  https://www.deeplearning.ai/courses/building-evaluating-advanced-rag
  Covers: merging sources, deduplication, citation grounding, RAG evaluation (context relevance, groundedness, answer relevance) — this is Phase 4 (merging/citations) and the vocabulary for Phase 5 (benchmarking).
  ```

- [ ] **FastAPI Official Tutorial** (~3-4 hrs estimated for the full tutorial, free)
  ```
  https://fastapi.tiangolo.com/tutorial/
  Covers: building the endpoint needed for Project 1's "Done when" criteria.
  No single official duration is published for this one — estimate based on its length;
  you likely only need the first few sections (path/query params, request bodies) to
  get Project 1's endpoint working, not the entire tutorial.
  ```



## Notes

Add anything you learn that surprises you, or that contradicts what's in `ML_CONCEPTS_NOTES.md`, here — then update the notes file to match.