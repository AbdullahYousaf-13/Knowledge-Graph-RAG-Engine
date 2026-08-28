# ML Concepts Notes

Personal reference notes for the concepts used in this project (and a few related ones worth knowing). Organized as a hierarchy — each concept sits *inside* a bigger one, the same way a car engine sits inside a car.

Each term has three parts:

- **Simple definition** — no jargon.
- **Real-life analogy** — something to picture instantly.
- **In this project** — where it actually shows up in our code/data.

---

## The Big Picture (hierarchy)

```
Artificial Intelligence (AI)
└── Machine Learning (ML)
    └── Deep Learning
        └── Large Language Models (LLMs)   ← Gemini lives here
            ├── Tokens & Tokenization
            ├── Context Window
            ├── Prompting
            ├── Structured Output
            └── Embeddings                  ← MiniLM lives here
                ├── Vector Length (Magnitude / Norm)
                ├── Why Training Objective Matters More Than Size
                │   (raw BERT vs Sentence-BERT vs MiniLM, tested hands-on)
                └── Vector / Semantic Search
                    ├── Vector Database (pgvector)
                    │   ├── B-trees (why they can't do this)
                    │   ├── ivfflat (ANN index, used at first)
                    │   └── HNSW (ANN index, used now — switched from ivfflat)
                    ├── Cosine Similarity
                    └── Chunking

Retrieval-Augmented Generation (RAG)         ← the whole project's category
├── Vector RAG (uses Embeddings above)         — built
├── Knowledge Graph RAG (uses Entities/Relationships below) — built
│   ├── Named Entity Recognition
│   ├── Entity Resolution / Deduplication
│   └── Graph Database (Neo4j + Cypher)
├── Hybrid RAG                               ← what YOU are building
│   ├── Routing                                — built (Phase 3, 87.5% measured accuracy)
│   └── Citation Grounding                     — not built yet (Phase 4)
└── Agents                                   ← a layer on top of all this
```

Read it top to bottom: AI is the biggest umbrella, everything else is a smaller box living inside a bigger box.

---

## 1. Artificial Intelligence (AI)

**Simple definition:** Any computer system that does something we'd normally say requires "intelligence" — recognizing patterns, making decisions, understanding language.

**Analogy:** AI is the entire subject of "medicine." It's the whole field, not one specific treatment.

**In this project:** The umbrella term for everything you're building. Not a specific tool.

---

## 2. Machine Learning (ML)

**Simple definition:** A way of building AI where the computer *learns patterns from data* instead of being told exact rules by a programmer.

**Analogy:** Instead of writing a rulebook for "what a cat looks like" (pointy ears, whiskers, etc.), you show the computer 10,000 photos labeled "cat" or "not cat," and it figures out the pattern itself.

**In this project:** Every model you use (Gemini, MiniLM) was *trained* this way — nobody hand-wrote rules for "what counts as a relationship in a 10-K filing." The models learned that from huge amounts of text.

---

## 3. Deep Learning

**Simple definition:** A specific ML technique using "neural networks" — many layers of simple math units stacked on top of each other, loosely inspired by neurons in a brain.

**Analogy:** Think of an assembly line with many stations. Each station does one tiny transformation to the product passing through. No single station understands the whole picture, but by the time the product exits the last station, something sophisticated has happened.

**In this project:** Both Gemini and `all-MiniLM-L6-v2` are deep learning models under the hood. You never touch the layers directly — you just call the model and get an output.

---

## 4. Large Language Models (LLMs)

**Simple definition:** A deep learning model trained on enormous amounts of text, whose job is to predict "what word/token comes next" — and this simple trick turns out to be enough to answer questions, summarize, extract structured facts, hold conversations, etc.

**Analogy:** Your brother's analogy is the right one here — **think of an LLM as a brain.** It can think, reason, and generate language, but on its own it has no hands — it can't click buttons, fetch live data, or take actions in the world.

**In this project:** **Gemini** (`gemini-3.5-flash-lite`) is your LLM. It reads a chunk of SEC filing text and reasons about it — "what entities are mentioned here, and how do they relate to each other" — and outputs its answer in a strict schema you defined.

### 4.1 Tokens & Tokenization

**Simple definition:** LLMs don't read letters or whole words — they break text into small pieces called *tokens* (roughly ¾ of a word on average) and process those.

**Analogy:** Like reading a sentence not letter-by-letter or word-by-word, but in Lego-brick-sized chunks that sometimes split a word ("chunk-ing" might be 2 tokens).

**In this project:** This is why your chunk size (2,600 characters) matters — every chunk you send to Gemini gets tokenized first, and there's a limit to how many tokens a model can handle in one go (its context window, next term).

### 4.2 Context Window

**Simple definition:** The maximum amount of text (measured in tokens) an LLM can "look at" at once when generating a response.

**Analogy:** Like a person's short-term memory span during a conversation — say too much at once and the earlier parts get pushed out.

**In this project:** Your chunks (2,600 chars ≈ 650 tokens) are deliberately small enough to fit comfortably inside Gemini's context window with room for the prompt instructions and the response schema.

### 4.3 Prompting

**Simple definition:** The instructions/text you send to an LLM to tell it what you want.

**Analogy:** Giving directions to a very capable but literal-minded assistant — the clearer and more specific your instructions, the better the result.

**In this project:** `build_prompt()` in `extract_sec_entities.py` — it tells Gemini exactly what to extract, what to ignore (section headers, boilerplate), and what format to respond in.

### 4.4 Structured Output

**Simple definition:** Forcing an LLM's response into a strict, predictable format (like a specific set of fields) instead of free-form text — so your code can reliably parse it.

**Analogy:** Instead of asking someone to "tell me about this person" (you'd get a paragraph), you hand them a form with labeled boxes: Name, Age, Occupation — much easier to process afterward.

**In this project:** Your `Entity` and `Relationship` Pydantic classes in `extract_sec_entities.py` *are* this structured format. Gemini's response is forced to match that schema exactly (`response_schema=ChunkExtraction`), so every extraction is guaranteed usable by your code, no manual text-parsing needed.

---

## 5. Embeddings

**Simple definition:** A way of converting text into a list of numbers (a "vector") that captures its *meaning* — texts with similar meaning end up as numbers that are mathematically close together.

**Analogy:** Imagine every sentence gets a GPS coordinate on a giant map, but instead of "physical location," the map represents "meaning." "The cat sat on the mat" and "A feline rested on the rug" would land near each other on this map, even though they don't share a single word.

**In this project:** `all-MiniLM-L6-v2` turns every chunk of filing text into a list of **384 numbers**. You did NOT design these numbers — the model learned, during its own training, how to place similar meanings close together.

**Toy example (2 dimensions, made up, for intuition only):**


| Word  | Dim 1 | Dim 2 |
| ----- | ----- | ----- |
| king  | 0.9   | 0.8   |
| queen | 0.9   | 0.2   |
| man   | 0.1   | 0.8   |
| woman | 0.1   | 0.2   |


`king − man + woman = (0.9−0.1+0.1, 0.8−0.8+0.2) = (0.9, 0.2)` = queen's exact coordinates. Relationships between meanings become actual arithmetic once you have good coordinates. **Caveat:** real embeddings' 384 dimensions don't each have a clean human label like "royalty" the way this toy example pretends — this is a simplification to build intuition. In reality, meaning is smeared across all 384 numbers in a tangled way nobody designed and nobody can read dimension-by-dimension. The *geometry* (distances, angles) is meaningful; the individual numbers usually aren't.

### 5.1 Vector Length (Magnitude / Norm)

**Simple definition:** How far a vector's point is from the origin (the all-zeros point) — the generalization of the Pythagorean theorem to any number of dimensions.

**Formula:**

```
|v| = √(v₁² + v₂² + v₃² + ... + vₙ²)
```

**Analogy:** If a vector is an arrow drawn from the center of a map to some point, its "length" is just how long that arrow is, regardless of direction. `[3, 4]` has length `√(3² + 4²) = √25 = 5` — literally the Pythagorean theorem, just applied to a vector instead of a triangle.

**Why it matters:** Cosine similarity (next section) divides by both vectors' lengths specifically to cancel out "how big the numbers are" and leave only "which direction they point" — so a longer or more repetitive chunk of text doesn't get scored as "more similar" just because its raw numbers happen to be bigger.

### 5.2 Vector / Semantic Search

**Simple definition:** Searching by *meaning similarity* instead of exact keyword matching.

**Analogy:** A librarian who, instead of only finding books with your exact search words in the title, understands what you're actually asking about and hands you the right book even if it uses totally different words.

**In this project:** This is the whole point of Phase 2 — a user's question gets embedded the same way, then you find the chunks whose embeddings are closest to it.

### 5.3 Vector Database

**Simple definition:** A database built (or extended) to efficiently store these number-lists and quickly find the closest ones to a given query vector, even across millions of rows.

**Analogy:** A normal database is like a filing cabinet sorted alphabetically — great for "find the file named X." A vector database is more like a friend who's memorized where every book *feels* similar to every other book, and can instantly point you to the closest match even with no exact name.

**In this project:** **pgvector**, an extension bolted onto Postgres (hosted on **Supabase**). Your table `sec_chunk_embeddings` stores each chunk's text alongside its 384-number embedding in a `VECTOR(384)` column — plus normal structured columns (`chunk_id`, `company`, `filing_year`, `section_name`, etc.) that are queried the regular relational way. **It's not "vector DB instead of relational DB"** — it's one database using two different index types for two genuinely different kinds of question.

### 5.4 Why Relational Indexes (B-trees) Can't Do This

**Simple definition:** A normal SQL index (**B-tree**) works by keeping values in sorted order, so the database can binary-search to a value instantly — e.g. jump straight to `filing_year = 2023`. This only works because a single column has one natural sort order.

**The problem with embeddings:** an embedding is 384 numbers *at once*. There is no single sort order that captures "closeness across all 384 dimensions simultaneously" — sorting by dimension 1's value tells you nothing reliable about overall closeness. So a B-tree fundamentally cannot answer "find the nearest vectors" — not because relational databases are slow, but because the question doesn't reduce to a sortable line the way `filing_year` does.

**Analogy:** A B-tree is like alphabetizing library books by title — perfect for "find the book called X." But "find me a book that *feels* like this one" has no alphabetical shortcut; you'd need someone who's actually read every book and remembers how they relate to each other. That's what the specialized vector index (next section) provides.

**In this project:** your `chunk_id`, `company`, `filing_year` columns get normal (implicit) B-tree-style indexing from Postgres — fast, exact, sorted lookups. Your `embedding` column needs a completely different index type, because "closest by meaning" isn't a sortable single-column question.

### 5.5 HNSW (the actual index type used now — switched from ivfflat)

**Simple definition:** The specific index pgvector uses to make "find nearest vectors" fast without checking every single row. Stands for **H**ierarchical **N**avigable **S**mall **W**orld — a multi-layer graph of connections between vectors, not a clustering scheme.

**Analogy:** Imagine a library where every book has little strings tied to a handful of its most-similar neighbors, and there are a few "express" books at the top level connected to distant parts of the collection. Starting from one of those express books, you hop string to string, always moving toward books more similar to what you're looking for, narrowing in a few hops instead of walking every shelf.

**Why this replaced ivfflat:** ivfflat's clustering approach (grouping vectors into `lists` buckets via k-means, then only searching the nearest bucket) turned out to be a poor fit for this project's small corpus. With `lists = 100` set against only 225 rows, each bucket held roughly 2 vectors on average — far too fine-grained to be useful, and with the default `probes = 1` (only search the single nearest bucket), there was real risk of missing a genuinely close match sitting in a neighboring bucket. HNSW doesn't have this "how many buckets, how many rows per bucket" tuning problem at all — its graph-based structure adapts naturally to dataset size.

**How it's actually configured in this project:** `src/kgrag/retrieval.py` pins `hnsw.ef_search` (default 64) — HNSW's equivalent of ivfflat's `probes`, controlling how many candidate neighbors get explored per search (higher = more accurate, slower). This is pinned specifically so retrieval results are reproducible for the recall@k evaluation — if `ef_search` silently varied between runs, comparing "did this change actually help" would be unreliable.

**Why it's still called "approximate":** even a well-built HNSW graph can occasionally miss the true single best match if it isn't reachable in the number of hops explored — same underlying idea as ivfflat's risk, just a different mechanism. This category of technique is called **Approximate Nearest Neighbor (ANN)** search, as opposed to exact/brute-force k-NN (compare against literally every row, guaranteed-correct but slow at scale). The industry term for "how often the approximate method actually finds the true best match" is **recall** — this is exactly what `scripts/eval_retrieval.py` measures (overall recall@5 of 0.54 on the current baseline).

**The build-time knobs:** HNSW's index-build parameters are `m` (how many connections each vector gets to its neighbors) and `ef_construction` (how thorough the search is while building those connections). This project uses `m=16, ef_construction=64` — reasonable defaults, not tuned against measured results, same honest caveat as several other parameters in this project (chunk size, hop count in graph traversal).

**For history — the ivfflat approach this replaced:** ivfflat groups vectors into `lists` clusters via k-means (each cluster gets a **centroid** — the "average point" of everything assigned to it), then at query time only searches inside the closest cluster(s). Reasonable at large scale, but pathological at 225 rows as explained above.

### 5.6 Cosine Similarity

**Simple definition:** The specific math formula used to measure "how close" two vectors are — it looks at the *angle* between them rather than raw distance.

**Analogy:** Two arrows pointing in almost the same direction are "similar," even if one is much longer than the other. Cosine similarity cares about direction (meaning), not magnitude (word count).

**Formula:**

```
cosine_similarity(A, B) = (A · B) / (|A| × |B|)
```

where `A · B` is the **dot product** — multiply each matching pair of numbers and add them all up:

```
A · B = A₁×B₁ + A₂×B₂ + ... + Aₙ×Bₙ
```

and `|A|`, `|B|` are each vector's **length** (see 5.2 above). Dividing the dot product by both lengths is what turns "raw alignment" into "pure direction/angle," giving a result between **−1** (opposite meaning) and **1** (identical direction/meaning), with **0** meaning unrelated.

**Worked example** (toy 3-dimensional embeddings, for illustration):

```
chunk_A = [0.8, 0.1, 0.6]   →  "Apple's revenue grew due to strong iPhone sales"
chunk_B = [0.7, 0.2, 0.5]   →  "iPhone sales drove Apple's quarterly revenue up"
chunk_C = [0.0, 0.9, 0.1]   →  "The company faces ongoing litigation risk"
```

*Step 1 — dot product of A and B:*
`A · B = (0.8×0.7) + (0.1×0.2) + (0.6×0.5) = 0.56 + 0.02 + 0.30 = 0.88`

*Step 2 — lengths:*
`|A| = √(0.8² + 0.1² + 0.6²) = √1.01 ≈ 1.005`
`|B| = √(0.7² + 0.2² + 0.5²) = √0.78 ≈ 0.883`

*Step 3 — cosine similarity:*
`0.88 / (1.005 × 0.883) ≈ 0.99` → very similar (makes sense — both about the same topic)

*Same steps for A and C:*
`A · C = (0.8×0.0) + (0.1×0.9) + (0.6×0.1) = 0 + 0.09 + 0.06 = 0.15`
`|C| = √(0.0² + 0.9² + 0.1²) = √0.82 ≈ 0.906`
`0.15 / (1.005 × 0.906) ≈ 0.16` → weakly related (makes sense — different topics)

**In this project:** Your pgvector index uses `vector_cosine_ops` (set in `create_schema()` in `build_pgvector_index.py`) — this is the setting that tells Postgres to rank matches by cosine similarity when you eventually run a search query. You never compute this by hand — pgvector runs this exact formula (on real 384-dimensional vectors, not toy 3-dimensional ones) internally for every comparison.

**Related, worth knowing:** cosine similarity isn't the only distance metric — **Euclidean distance** (straight-line distance between two points, no angle involved) is another common one. pgvector supports both (`vector_cosine_ops` vs `vector_l2_ops`); cosine similarity is generally preferred for text embeddings because it ignores vector length differences caused by things like text length, focusing purely on meaning-direction.

### 5.7 Chunking

**Simple definition:** Breaking a long document into smaller pieces before embedding or feeding it to a model — because both LLMs and embedding models have limits on how much text they handle well at once.

**Analogy:** You wouldn't hand someone an entire encyclopedia and ask "what's on page 402" — you'd hand them just that page.

**In this project:** `prepare_sec_filings.py` splits each 10-K into ~2,600-character, paragraph-aware pieces (454 total across 5 years). This directly feeds both the embedding step and the extraction step.

### 5.8 Why Training Objective Matters More Than Model Size (tested hands-on, not just read about)

**Simple definition:** A bigger model with more parameters doesn't automatically produce better embeddings. What actually determines embedding quality is *what the model was specifically trained to do* — and whether it was ever taught "make similar meanings produce similar vectors" at all.

**Where this came from:** your supervisor asked you to run `bert-base-uncased` on Google Colab and compare it against your project's `all-MiniLM-L6-v2`, to see the difference for yourself rather than take it on faith. You actually ran this — three real models, on your own 225 chunks and 21 real evaluation questions:

| Model | Parameters | Ever trained for "similar meaning → similar vector"? | MRR | hit@5 |
|---|---|---|---|---|
| `bert-base-uncased` (raw, mean-pooled) | 110M | No — only trained to guess missing words | 0.064 | 0.095 |
| `bert-base-nli-mean-tokens` (SBERT-fine-tuned BERT) | 110M | Yes, but only on ~570K pairs (2019, one dataset) | 0.163 | 0.286 |
| `all-MiniLM-L6-v2` (yours) | 22M | Yes, on 1 billion+ pairs, many diverse sources, via knowledge distillation from a stronger teacher model | 0.781 | 0.905 |

**The surprising part:** the *smallest* model (MiniLM, 22M params) beat the *biggest* one (BERT-base, 110M params) by roughly **12x on MRR**. Size went the "wrong" direction — proof that parameter count isn't what determines embedding quality here.

**Why raw BERT failed so badly — the anisotropy problem:** BERT was trained only on masked-word prediction ("guess the blanked-out word") and next-sentence prediction. Nobody ever told it "these two sentences mean the same thing, place them near each other." The practical effect (a well-documented finding from the original Sentence-BERT paper, Reimers & Gurevych 2019): when you average-pool BERT's raw token outputs into one sentence vector, most sentences end up clustered artificially close together in vector space regardless of what they actually say — dominated by shared common subwords and sentence length rather than meaning. Cosine similarity between two such vectors ends up close to meaningless as a relevance signal. `hit@1: 0.0000` in your test — it never once got the #1 answer right across 21 questions — is what that looks like in practice.

**Why fine-tuning helped, but not enough on its own:** `bert-base-nli-mean-tokens` is literally the same BERT architecture, given the Sentence-BERT training treatment — teaching it, via example sentence pairs, to actually place similar meanings near each other. This closed some of the gap (roughly 2.6x better MRR than raw BERT) but still fell far short of MiniLM. The reason: *how much and how diverse* that training is matters enormously too. NLI's ~570K pairs from one source (2019) isn't remotely comparable to MiniLM's training on over a billion pairs pulled from many different kinds of text (paraphrases, question-answer pairs, forum comments, academic citations).

**The two-layer lesson to remember:**
1. **Training objective matters** — this is why raw BERT (no embedding-specific training at all) fails completely.
2. **Training scale and diversity matter just as much** — this is why even a properly fine-tuned but narrowly-trained model still loses badly to one trained at much greater scale and diversity, despite both using the same underlying technique.

**In this project:** this is the concrete, measured reason `all-MiniLM-L6-v2` was the right practical choice for `build_pgvector_index.py` and `src/kgrag/retrieval.py` — not because it's the biggest or newest model, but because it was specifically, extensively trained for exactly the task this project needs (semantic search), and the real numbers above prove that training regime beats raw model size decisively.

---

## 6. Retrieval-Augmented Generation (RAG)

**Simple definition:** Instead of relying purely on what an LLM memorized during training (which can be outdated or made up), you first *retrieve* real, relevant documents, then hand them to the LLM and say "answer using only this."

**Analogy:** Open-book exam vs. closed-book exam. An LLM answering from memory alone is closed-book (and might misremember). RAG hands it the actual textbook page first — open-book, more reliable, and you can point to exactly which page the answer came from.

**In this project:** This is the category your entire project belongs to. Specifically, you're building a **hybrid** RAG system — using two different retrieval methods together (see below).

### How Krish Naik Frames It

Source: Krish Naik's RAG intro video ("Introduction To Understanding RAG," from the `LEARNING_PATH.md` playlist) plus his companion written article covering the same material. **Caveat:** YouTube blocks direct transcript extraction, so this is sourced from his written companion piece covering the identical intro topic, not a word-for-word video transcript — treat it as a faithful proxy for his framing, not verbatim video text.

**The four problems he opens with** — a different emphasis than the "open-book exam" framing above, worth having both:
1. **Knowledge cutoff** — an LLM's training data has a hard stop date; anything after that, it simply doesn't know.
2. **Hallucination** — generating text that *sounds* plausible but is factually wrong.
3. **Lack of specialized/domain knowledge** — a general-purpose LLM was never trained deeply on *your* specific filings, codebase, or niche documents.
4. **Inability to cite sources** — even when an LLM happens to be right, it can't point to where that fact came from.

Notice this is a slightly wider framing than the notes above (which centered mainly on hallucination + citations) — knowledge cutoff and domain-specificity are two more concrete, separate reasons RAG exists, and they map directly onto why *this* project needed it: Gemini alone has never seen your specific Apple 10-K filings, no matter how recent its training cutoff is.

**His analogy:** RAG combines "the generative capabilities of LLMs with the precision of information retrieval systems" — like a librarian who doesn't just recite facts from memory, but actually walks to the shelf, pulls the real book, and reads from it before answering.

**His 7-step pipeline** — a more granular breakdown of the same "Retrieval before Generation" idea from the walkthrough below:

| Step | What happens | This project's equivalent |
|---|---|---|
| 1. Document Ingestion | Load and chunk raw files | `prepare_sec_filings.py` |
| 2. Embeddings Creation | Convert chunks into vectors | `build_pgvector_index.py` (`all-MiniLM-L6-v2`) |
| 3. Vector Database Storage | Index those embeddings | pgvector / `sec_chunk_embeddings` (§5.3–5.5) |
| 4. Query Processing | Convert the *user's question* into a vector | **Built** — `retrieval.embed_query()`, called by `router.execute_route()` |
| 5. Similarity Retrieval | Find the closest matching chunks | **Built** — `retrieval.vector_search()`, wired to live questions via the router |
| 6. Context Augmentation | Combine retrieved chunks + original question into one prompt | Not built yet — Phase 4 |
| 7. Response Generation | LLM answers using that augmented context | Not built yet — Phase 4 |

Steps 1–5 are exactly what you've already built (Phases 1–3). Steps 6–7 are exactly Phase 4 — his pipeline and this project's phase breakdown line up almost one-to-one, which is a good sign you're building something structurally standard, not something idiosyncratic.

**Tooling note, worth flagging honestly:** he teaches this using **LangChain** (an orchestration framework that wraps document loaders, text splitters, embedding calls, and vector-store queries into one library). This project deliberately does **not** use LangChain — everything is hand-written directly against the Gemini API, `sentence-transformers`, Neo4j's driver, and `psycopg`. Neither approach is "more correct" — LangChain trades some transparency for convenience/less boilerplate; this project's raw approach trades more boilerplate for full visibility into exactly what every step does (which has mattered several times already, e.g. debugging the `ivfflat`/extension-creation-order bug would have been harder to spot through a framework's abstraction layer).

**Advanced techniques he mentions** (worth knowing the names, even beyond what's built): hybrid search, multi-query retrieval, contextual compression, and **query routing** — that last one is literally this project's Phase 3, now built and measured (`src/kgrag/router.py`, 87.5% accuracy), confirming "routing" is a standard, named technique in the field, not something specific to this project's design.

### Walkthrough: One Question, Start to Finish

Everything below is easier to grasp as one continuous story than as separate definitions, so here's a single example question walked through end-to-end. Worth noting up front: sections 1–5 all map to code you've actually run and seen output from — the retrieval/routing side of sections 6+ is now real code too (Phases 1-3); only the final answer-generation step (Phase 4) is still ahead, so that's the one part below still described in future tense.

**Start here — what problem is RAG even solving?**

Imagine asking Gemini directly, with no help from your project at all: *"What did Apple say about iPhone revenue in its 2024 10-K?"* The problem: Gemini wasn't trained specifically on your exact filing text, and even if it vaguely remembers something about Apple, it might be outdated, mixed up with a different year, or flat-out invented ("hallucinated"). You'd have no way to check where the answer came from.

**RAG's fix:** before asking the LLM anything, first go **find the actual real passage** from Apple's real 2024 filing, hand *that exact text* to Gemini, and say "answer using only this — and you now have the receipt to prove it." Retrieval (find the real text) happens *before* Generation (the LLM writing an answer) — that's literally what "R-A-G" stands for.

**Path A — Vector RAG, walked through:** Question: *"What did Apple say about supply chain risks?"*
1. The question gets embedded (same `all-MiniLM-L6-v2` model used on your chunks) → a 384-number vector. **Built** — `retrieval.embed_query()`.
2. pgvector compares that vector against your stored chunk-vectors, finds the closest by cosine similarity. **Built** — `retrieval.vector_search()`.
3. The matching chunks' actual text gets pulled out — e.g. a real paragraph about component sourcing. **Built** — returned as `RetrievedChunk` objects, real text included.
4. That real text gets handed to Gemini: "answer using only this passage," producing a grounded answer. **Not built yet** — this is Phase 4 (answer generation).

Steps 1-3 are wired together and real: `router.py`'s `execute_route()` calls exactly this chain whenever it decides a question needs the vector path. Only step 4 — actually generating a final written answer from what gets retrieved — remains.

**Path B — Knowledge Graph RAG, walked through:** Question: *"What is the Epic Games lawsuit about?"* — a relationship question, not a "find similar text" one. This whole retrieval path is now **fully automated**, not just hand-written Cypher in Neo4j Browser anymore:
1. **NER (already done)** — Gemini read each chunk and pulled out things like "Apple Inc.", "Epic Games, Inc.", tagging what type each is (`extract_sec_entities.py`) — why you have 277 Entity nodes.
2. **Entity resolution (already done, at two points)** — first as a one-time cleanup pass (embedding-similarity search over all entities, human-reviewed merges), then baked directly into ingestion itself (`src/kgrag/entity_resolution.py`) so new extraction runs don't recreate the same duplicates.
3. **Graph storage (already done)** — entities and relationships (e.g. "Epic Games, Inc. SUES Apple Inc.") live in Neo4j as connected nodes.
4. **Automatic entity linking + Cypher (now built)** — `graph_retrieval.resolve_entity("Epic Games")` turns the plain-English name from a question into the real graph node, and `graph_search()` runs the actual parameterized Cypher traversal — no more writing Cypher by hand.

What's still missing: the resulting graph facts (e.g. `Epic Games, Inc. -[SUES]-> Apple Inc.`) get handed back as structured data, not yet phrased into a natural-language answer by Gemini — that phrasing step is Phase 4, same gap as Path A's step 4.

**Path C — Hybrid RAG:**
1. **Routing — now built.** `src/kgrag/router.py` decides, per question, whether to run Path A, Path B, or both — using Gemini with structured output (same pattern as extraction) to classify the question, not a hand-coded rule list. Measured accuracy against a 24-question labeled set: **87.5% (21/24)**. It also estimates its own confidence and automatically runs *both* paths when unsure, instead of committing to a possibly-wrong single guess.
2. **Citation grounding — still not built (Phase 4).** Once Gemini writes a final answer from retrieved facts/passages, double-check every claim traces back to a real `chunk_id` or `source_chunk_id`, catching anything the LLM added that isn't actually supported.

**One sentence to hold onto:** everything under this heading describes one machine with two intake pipes (vector search, graph search), a valve that decides which pipe(s) to open per question (the router), all feeding toward one output nozzle (Gemini writing a grounded answer). Both intake pipes and the valve are now fully built and tested. Only the final nozzle — turning retrieved facts/passages into one written, cited answer — remains (Phase 4).

### 6.1 Vector RAG

**Simple definition:** The "retrieve" step uses vector/semantic search (section 5.1) to find relevant chunks.

**Analogy:** Asking the librarian (from the embeddings analogy) to fetch the most relevant pages, then handing those pages to an expert to summarize an answer.

**In this project:** Built end-to-end from question to retrieved text — `src/kgrag/retrieval.py`, called by the router whenever a question routes to `vector` or `both`.

### 6.2 Knowledge Graph RAG

**Simple definition:** The "retrieve" step instead pulls structured facts from a graph of entities and relationships, rather than free-text passages.

**Analogy:** Instead of handing someone a stack of relevant pages, you hand them a family tree — precise, explicit connections ("Epic Games, Inc. SUES Apple Inc.") rather than prose they have to re-read to figure out the connection.

**In this project:** Built end-to-end from question to retrieved facts — `src/kgrag/graph_retrieval.py`, called by the router whenever a question routes to `graph` or `both`. Getting this right took real debugging: an early version returned 30-50 irrelevant facts when asked about a hub-like entity ("Apple Inc." is connected to almost everything) — fixed by preferring paths *between* multiple named entities in a question over one entity's full neighborhood.

#### 6.2.1 Named Entity Recognition (NER)

**Simple definition:** The task of finding and labeling "things" (people, companies, products, locations, etc.) mentioned in text.

**Analogy:** Highlighting every proper noun in a paragraph with a colored marker and writing next to it what *kind* of thing it is.

**In this project:** This is literally what Gemini does in `extract_sec_entities.py` — pulling out entities like "Apple Inc.", "iPhone", "Epic Games, Inc." and tagging each with a type, from a closed list of 8 (`Company`, `Person`, `Product`, `Location`, `Metric`, `Regulation`, `Organization`, `Other`).

#### 6.2.2 Entity Resolution / Deduplication

**Simple definition:** Recognizing that two different mentions actually refer to the *same real-world thing*, and merging them into one record instead of treating them as separate.

**Analogy:** "Bob," "Robert," and "Bob Smith from accounting" showing up in different emails — a smart assistant realizes these are one person, not three.

**In this project:** Every entity gets an `entity_key` (a slugified version of its name, e.g. "apple-inc"). When loading into Neo4j, `MERGE` on that key means "Apple Inc." mentioned in 40 different chunks becomes **one graph node**, not 40 duplicates — this is why your graph has 277 entity nodes even though 972 entity *mentions* exist across 225 chunks. But exact-key matching alone missed real duplicates worded differently ("Apple Inc." vs "Apple" would get *different* keys) — fixed twice: once as a one-time cleanup (embedding-similarity search over all 279 originally-extracted entities found 101 candidate pairs, 13 genuine groups merged after human review, landing at 265), and again by baking two-tier resolution directly into ingestion (`src/kgrag/entity_resolution.py`) so future extraction runs don't quietly recreate the same duplicates — auto-merging only above a conservative similarity bar, flagging anything less certain for review instead of guessing (landing at 277: a few borderline names correctly got left as separate entities rather than auto-merged).

#### 6.2.3 Graph Database

**Simple definition:** A database designed around nodes (things) and edges (relationships between things), instead of rows and tables.

**Analogy:** A normal (relational) database is a spreadsheet. A graph database is a literal diagram with dots and arrows — better suited when the *connections* between things matter as much as the things themselves.

**In this project:** **Neo4j**, hosted on **AuraDB**. Your `Entity`, `Chunk`, and `Filing` nodes, connected by `MENTIONS`, `RELATED_TO`, and `HAS_CHUNK` edges.

#### 6.2.4 Cypher

**Simple definition:** The query language used to ask questions of a graph database (the graph-database equivalent of SQL).

**Analogy:** If SQL is "English for spreadsheets," Cypher is "English for connect-the-dots diagrams." `MATCH (a)-[:KNOWS]->(b)` reads almost like a sentence: "match a node connected to another via a KNOWS relationship."

**In this project:** Every query you've run in Neo4j Browser (`MATCH (n)-[r]->(m) RETURN n, r, m`) is Cypher.

### 6.3 Hybrid RAG

**Simple definition:** Combining Vector RAG *and* Knowledge Graph RAG in one system, using each where it's strongest.

**Analogy:** Using both a search engine (fast, meaning-based, good for "what does this generally say about X") and a lawyer's case-reference system (precise, fact-based, good for "who exactly is connected to whom, and how") — instead of relying on just one.

**In this project:** This is literally your project's name and goal. Neo4j handles the precise-relationship side, pgvector handles the semantic-similarity side.

#### 6.3.1 Routing

**Simple definition:** Deciding, per incoming question, which retrieval method(s) to use.

**Analogy:** A receptionist at a hospital deciding whether you need the ER, a specialist, or both, based on what you say when you walk in.

**In this project:** Built — `src/kgrag/router.py`. Looks at a question and decides "this is a relationship question → query Neo4j" vs. "this is a definition question → query pgvector" vs. "both" vs. "out of scope" (not answerable from this corpus at all — different company, forward-looking guidance, etc.). Not a hand-coded rule list — Gemini makes the call, forced into a strict schema (same structured-output pattern as entity extraction) so it can only pick from those four options, never freeform text. It also self-rates its confidence, and the code automatically runs *both* retrieval paths when confidence is low rather than trusting a possibly-wrong single guess. Measured, not assumed: **87.5% accuracy (21/24)** against a hand-labeled question set, where the "correct" answer for each question was determined by actually running the retrieval and checking the real output, not by guessing from how the question sounded.

#### 6.3.2 Citation Grounding

**Simple definition:** Making sure every claim in the final answer can be traced back to a specific real source, and verifying that link actually holds before showing the answer.

**Analogy:** A well-written research paper where every sentence has a footnote pointing to exactly which source backs it up — and someone fact-checks that the footnote really does support the sentence.

**In this project:** Every chunk carries its `source_url` and `chunk_id`; every graph relationship carries `source_chunk_id`. Phase 4 (not built yet) will use these to attach citations to generated answers and verify they're real.

---

## 7. Agents

**Simple definition:** A system that uses an LLM (the "brain") *plus* the ability to take actions — call tools, run code, fetch data, write files — rather than just producing text.

**Analogy:** Your brother's framing is exactly right: **the LLM is the brain, the Agent gives it hands.** A brain alone can only think and talk. Give it hands (tools), and it can actually go do things — open a file, run a search, click a button.

**In this project:** I (Claude, working with you throughout this project) am an agent — I have an LLM brain, plus "hands" in the form of tools: reading/editing your files, running Python/PowerShell commands, querying your Neo4j and Postgres databases directly, browsing search results, etc. Gemini, as used inside `extract_sec_entities.py`, is *not* acting as an agent there — it's used purely as a brain-in-a-box: you send it text, it sends back structured text, no tool use, no independent action-taking.

---

## Quick-reference cheat sheet


| Term               | One-line memory hook                                         |
| ------------------ | ------------------------------------------------------------ |
| LLM                | The brain (Gemini)                                           |
| Agent              | Brain + hands (me, working in your terminal)                 |
| Token              | Lego-brick-sized piece of text                               |
| Context window     | Short-term memory limit                                      |
| Embedding          | Meaning turned into GPS coordinates (384 numbers)            |
| Vector database    | A librarian who finds books by *meaning*, not exact title    |
| Cosine similarity  | Comparing arrow *direction*, not length                      |
| Chunking           | Cutting the encyclopedia into single pages                   |
| NER                | Highlighting proper nouns and labeling their type            |
| Entity resolution  | Realizing "Bob" and "Robert" are the same person             |
| Graph database     | A diagram with dots and arrows, not a spreadsheet            |
| Cypher             | English for connect-the-dots diagrams                        |
| RAG                | Open-book exam instead of closed-book                        |
| Hybrid RAG         | Using both a search engine AND a lawyer's reference system   |
| Routing            | The hospital receptionist deciding ER vs. specialist — built, 87.5% accuracy |
| Citation grounding | A research paper where every sentence has a checked footnote |
| HNSW               | Books tied by string to their nearest neighbors, hop to the answer |
| Training objective | *What* a model practiced for — matters more than how big it is |


