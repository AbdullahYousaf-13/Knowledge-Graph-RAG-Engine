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

- [x] **Building Knowledge Graphs with LLMs** (Neo4j GraphAcademy, ~2 hrs, free)
  ```
  https://graphacademy.neo4j.com/courses/llm-knowledge-graph-construction/
  Covers: NER, relationship extraction, entity resolution — reinforces `extract_sec_entities.py` + `load_to_neo4j.py`.
  ```

- [ ] **YouTube Playlist: Complete RAG Playlist** (Krish Naik, 8 videos, free)
  ```
  https://www.youtube.com/watch?v=fZM3oX4xEyg&list=PLZoTAELRMXVM8Pf4U67L4UuDRgV4TNX9D

  Found by Abdullah, verified via YouTube's own RSS feed. Krish Naik is a well-established,
  highly credible ML/AI educator with a large, respected channel — stronger pick than the
  alternatives originally found here.

  Video order: Intro to RAG -> Build RAG Pipeline From Scratch (Data Ingestion to Vector DB),
  Part 1 -> Advanced Retrieval Query Pipeline, Part 2 -> RAG With Typesense (fast open-source
  search) -> Agentic RAG Bootcamp Announcement (skippable, not a lesson) -> Agentic RAG With
  LangGraph -> RAG With MongoDB Vector Search -> RAG Evaluation Crash Course.

  Covers: building an actual vector DB pipeline end-to-end (reinforces `build_pgvector_index.py`),
  advanced retrieval (Phase 3 routing territory, now built — see `src/kgrag/router.py`), and RAG
  evaluation (Phase 4/5 vocabulary) —
  replaces the "Vector Databases" and "Building and Evaluating Advanced RAG" DeepLearning.AI
  entries previously here, removed per feedback that the DL.AI teaching style wasn't working.

  Note: video 5 is a bootcamp announcement/ad, not course content — skip it.
  ```

## About to implement — prioritize these next

- [ ] **Neo4j & Generative AI Certification** (Neo4j GraphAcademy, ~18 hrs full prep path + 1 hr exam, free)
  ```
  https://graphacademy.neo4j.com/certifications/genai-certification/
  Covers: routing, entity linking, Text2Cypher, hybrid search — this is Phase 3 (routing) territory;
  Phase 3 itself is now built (96.3% measured routing accuracy), so this course would be reinforcement
  rather than prep at this point.
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

- **Supervisor-assigned exercise (Google Colab): raw `bert-base-uncased` vs `bert-base-nli-mean-tokens` vs this project's `all-MiniLM-L6-v2`, same 225 chunks + 21 real eval questions.** Result: MiniLM (22M params) beat raw BERT (110M params) by ~12x on MRR (0.781 vs 0.064) — a smaller model, decisively better. Fine-tuning BERT the Sentence-BERT way helped (MRR 0.163, ~2.6x better than raw BERT) but still fell far short of MiniLM, because *how much and how diverse* the fine-tuning data is matters as much as whether fine-tuning happened at all. Full writeup: `ML_CONCEPTS_NOTES.md` §5.8.