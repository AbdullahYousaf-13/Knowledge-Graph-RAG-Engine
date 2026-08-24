# Course: Vector Databases: from Embeddings to Applications

**Platform:** DeepLearning.AI × Weaviate
**Course link:** https://www.deeplearning.ai/courses/vector-databases-embeddings-applications
**Duration:** ~1 hr total
**Status:** in progress — see `LEARNING_PATH.md` for checklist status

One section per lesson below, added as we go. Each section is built from the actual lesson content (transcript/page), not reconstructed from general knowledge — sourced where possible.

---

## Lesson: How to Obtain Vector Representations of Data

**Source:** https://learn.deeplearning.ai/courses/vector-databases-embeddings-applications/lesson/lkotq/how-to-obtain-vector-representations-of-data (~11 min, video + code)

> These notes summarize the actual lesson transcript, not exact wording — if you need verbatim text for something, rewatch the source lesson.

### The core idea: a variational autoencoder (VAE) produces the embedding

**Correction from earlier notes:** having now seen the actual code, this is specifically a **Variational Autoencoder (VAE)**, not a plain autoencoder — it has a `sampling()` function using `mu`/`log_var` and a KL-divergence loss term (see the code below), which a plain autoencoder doesn't have. A VAE learns a *probability distribution* for each embedding rather than a single fixed point, which makes the embedding space smoother/more continuous — useful for generative tasks, though not something this project needs (MiniLM is a plain deterministic encoder, no VAE machinery).

A VAE still has the same two halves as any autoencoder:
- **Encoder** — compresses the input down into a small vector (here, a distribution over a small vector).
- **Decoder** — tries to reconstruct the original input *from just that small vector*.

The key trick: the network is forced through a narrow **bottleneck layer** in the middle. Since the decoder has to rebuild the whole image from only that bottleneck vector, the network is forced to compress everything meaningful about the image into those few numbers. That bottleneck vector **is** the embedding — as the lesson puts it, *"the output is generated using only the vector in the middle so that vector contains the meaning of that image and we call that the embedding."*

### The specific architecture used in the demo

```
Input image (28×28 pixels) → flattened to 784 numbers
         ↓
Encoder: 784 → 256 → 128 → 2   (progressively smaller layers)
         ↓
Embedding: 2-dimensional vector  (the bottleneck)
         ↓
Decoder: 2 → 128 → 256 → 784   (progressively larger layers, mirror of encoder)
         ↓
Reconstructed image (784 numbers → reshaped back to 28×28)
```

**Training setup:**
- Batch size: 100 objects per training step
- Training epochs: 50
- Target embedding size: 2 dimensions (deliberately tiny, so the resulting embeddings can be plotted directly on a 2D graph for visualization)

**Why 2 dimensions specifically:** a teaching choice, not a real-world one — compressing all the way down to 2 numbers lets you literally plot every digit's embedding on an x/y scatter plot and *see* the clustering happen visually. Real embeddings (like the 384-dimensional ones used in this project) use far more dimensions to capture much richer meaning; you'd never actually plot those directly.

### What the visualization showed

Once every MNIST digit gets run through the trained encoder, similar digits' embeddings land close together in the 2D space — e.g. all the images of "0" cluster together, all the "9"s cluster together, separate from each other. Same underlying idea as `ML_CONCEPTS_NOTES.md`'s "GPS coordinates for meaning" analogy, just visualized directly since it's only 2 dimensions here instead of 384.

### Four ways to measure how similar two vectors are

| Metric | Formula | What it measures | Lower or higher = more similar? |
|---|---|---|---|
| **Euclidean distance** | `√(Σ(Aᵢ − Bᵢ)²)` | The straight-line ("as the crow flies") distance between two points | Lower |
| **Manhattan distance** | `Σ\|Aᵢ − Bᵢ\|` | Distance measured only along the axes (like walking city blocks, no diagonals) | Lower |
| **Dot product** | `Σ(Aᵢ × Bᵢ)` = `A · B` | The magnitude of one vector's projection onto the other | Higher |
| **Cosine distance** | `1 − (A·B)/(\|A\|×\|B\|)` | The angle between two vectors, ignoring their length | Smaller angle (= smaller cosine distance) |

Note the inconsistent direction: Euclidean/Manhattan are *distance* metrics (lower = more alike), while dot product is a *similarity* score (higher = more alike). This project uses cosine **similarity** (see `ML_CONCEPTS_NOTES.md` §5.6 for the full formula), where 1.0 = identical — not cosine distance.

### Connecting back to text (not just images)

The lesson extends the same idea beyond images: **sentence transformers** generate embeddings for text with hundreds of dimensions — the lesson's own example uses **384 dimensions**, the exact same size as `all-MiniLM-L6-v2`, the model this project actually uses in `build_pgvector_index.py`. Same underlying principle as the MNIST autoencoder demo: a neural network compresses the input (a sentence instead of an image) down into a fixed-size vector that captures its meaning, and similar meanings land close together in that vector space.

### How this maps onto this project

| Lesson concept | This project's equivalent |
|---|---|
| VAE encoder half | `all-MiniLM-L6-v2` (a pretrained sentence-transformer, not something you train yourself, and not a VAE — but the same "compress meaning into a fixed vector" idea) |
| 2-dimensional bottleneck (for visualization) | 384-dimensional real embedding (too many dimensions to plot directly) |
| MNIST digit clustering | Your SEC filing chunks clustering by topic in `sec_chunk_embeddings` |
| The four distance metrics | pgvector's `vector_cosine_ops` index specifically uses cosine similarity — see `ivfflat` notes in `ML_CONCEPTS_NOTES.md` §5.5 |

### Full code, verbatim from the actual lesson notebook

Source notebook: `L1_Embeddings.ipynb` from the official course code repository. Every cell below, in order, with a short description of what it does.

**1. Imports**
```python
import numpy as np
import matplotlib.pyplot as plt

from tensorflow.keras.datasets import mnist
from tensorflow.keras.layers import Input, Dense, Lambda
from tensorflow.keras.models import Model
from tensorflow.keras import backend as K
from tensorflow.keras import losses
from scipy.stats import norm
```
Pulls in TensorFlow/Keras for building the neural network, NumPy for the manual distance-metric math later, and Matplotlib for plotting.

**2. Load the MNIST dataset**
```python
(x_tr, y_tr), (x_te, y_te) = mnist.load_data()
```
Downloads/loads the standard MNIST handwritten-digit dataset, already split into training (`x_tr`/`y_tr`) and test (`x_te`/`y_te`) sets. `x_*` are the images, `y_*` are the actual digit labels (0-9).

**3. Normalize and flatten the images**
```python
x_tr, x_te = x_tr.astype('float32')/255., x_te.astype('float32')/255.
x_tr_flat, x_te_flat = x_tr.reshape(x_tr.shape[0], -1), x_te.reshape(x_te.shape[0], -1)
```
Pixel values start as integers 0-255; dividing by 255 rescales them to 0.0-1.0 (standard practice — neural nets train better on small, normalized numbers). Then each 28×28 image gets flattened into a single 784-length vector, since the `Dense` layers below expect a flat vector input, not a 2D image.

**4. Sanity-check the shapes**
```python
print(x_tr.shape, x_te.shape)
print(x_tr_flat.shape, x_te_flat.shape)
```
Just prints the array shapes to confirm the reshape worked as expected (e.g. `(60000, 28, 28)` → `(60000, 784)`).

**5. Set the model's hyperparameters**
```python
batch_size, n_epoch = 100, 50
n_hidden, z_dim = 256, 2
```
Defines the training config: 100 images per batch, 50 passes over the full dataset, hidden layers sized 256, and the target embedding size (`z_dim`) of 2 — deliberately tiny so it can be plotted directly.

**6. Preview one training image**
```python
plt.imshow(x_tr[1]);
```
Just displays one raw digit image, to visually confirm the data loaded correctly.

**7. The VAE's sampling function (reparameterization trick)**
```python
def sampling(args):
    mu, log_var = args
    eps = K.random_normal(shape=(batch_size, z_dim), mean=0., stddev=1.0)
    return mu + K.exp(log_var) * eps
```
This is the piece that makes it a *variational* autoencoder rather than a plain one: instead of the encoder outputting one fixed embedding vector, it outputs a mean (`mu`) and log-variance (`log_var`) describing a probability distribution, then this function *samples* a random point from that distribution (`eps` is random noise) to use as the actual embedding. This is what lets the VAE learn a smooth, continuous embedding space.

**8. Build the encoder**
```python
inputs_flat = Input(shape=(x_tr_flat.shape[1:]))
x_flat = Dense(n_hidden, activation='relu')(inputs_flat)          # 784 → 256
x_flat = Dense(n_hidden//2, activation='relu')(x_flat)             # 256 → 128

mu_flat = Dense(z_dim)(x_flat)
log_var_flat = Dense(z_dim)(x_flat)
z_flat = Lambda(sampling, output_shape=(z_dim,))([mu_flat, log_var_flat])
```
Defines the actual encoder: takes the 784-number flattened image, shrinks it through two dense layers (784→256→128), then produces `mu`/`log_var` (each 2-dimensional) and samples the final embedding `z_flat` using the sampling function from step 7.

**9. Build the decoder**
```python
latent_inputs = Input(shape=(z_dim,))
z_decoder1 = Dense(n_hidden//2, activation='relu')
z_decoder2 = Dense(n_hidden, activation='relu')
y_decoder = Dense(x_tr_flat.shape[1], activation='sigmoid')
z_decoded = z_decoder1(latent_inputs)
z_decoded = z_decoder2(z_decoded)
y_decoded = y_decoder(z_decoded)
decoder_flat = Model(latent_inputs, y_decoded, name="decoder_conv")

outputs_flat = decoder_flat(z_flat)
```
The mirror image of the encoder: takes the 2-dimensional embedding and expands it back through 128→256→784, ending in a `sigmoid` activation so outputs land between 0 and 1 (matching the normalized pixel range from step 3).

**10. Define the VAE loss and compile the model**
```python
reconstruction_loss = losses.binary_crossentropy(inputs_flat, outputs_flat) * x_tr_flat.shape[1]
kl_loss = 0.5 * K.sum(K.square(mu_flat) + K.exp(log_var_flat) - log_var_flat - 1, axis=-1)
vae_flat_loss = reconstruction_loss + kl_loss

vae_flat = Model(inputs_flat, outputs_flat)
vae_flat.add_loss(vae_flat_loss)
vae_flat.compile(optimizer='adam')
```
The loss has two parts: **reconstruction loss** (how different is the decoder's output from the original image — this is what forces the embedding to actually capture the image's content), and **KL loss** (a VAE-specific term that keeps the learned distributions well-behaved/smooth, rather than collapsing to arbitrary spread-out points). The two get added together and the model is compiled with the Adam optimizer.

**11. Train**
```python
vae_flat.fit(
    x_tr_flat,
    shuffle=True,
    epochs=n_epoch,
    batch_size=batch_size,
    validation_data=(x_te_flat, None),
    verbose=1
)
```
Actually runs training — 50 epochs, shuffling the data each epoch, in batches of 100, checking against the held-out test set along the way.

**12. Extract just the encoder (for generating embeddings)**
```python
encoder_f = Model(inputs_flat, z_flat)
```
Once trained, you don't need the decoder anymore for generating embeddings — this builds a standalone model that goes straight from an input image to its 2D embedding, discarding the decoder half.

**13. Visualize all the embeddings**
```python
x_te_latent = encoder_f.predict(x_te_flat, batch_size=batch_size, verbose=0)
plt.figure(figsize=(8, 6))
plt.scatter(x_te_latent[:, 0], x_te_latent[:, 1], c=y_te, alpha=0.75)
plt.title('MNIST 2D Embeddings')
plt.colorbar()
plt.show()
```
Runs every test image through the encoder to get its 2D embedding, then scatter-plots all of them, colored by their true digit label (`y_te`). This is the plot that visually shows same-digit embeddings clustering together.

**14. Preview three specific digits**
```python
plt.imshow(x_te_flat[10].reshape(28,28));   # a "0"
plt.imshow(x_te_flat[13].reshape(28,28));   # another "0"
plt.imshow(x_te_flat[2].reshape(28,28));    # a "1"
```
Displays three specific test images to set up a hands-on similarity comparison next: two different images of "0" and one image of "1".

**15. Pull out their actual embedding vectors**
```python
zero_A = x_te_latent[10]
zero_B = x_te_latent[13]
one = x_te_latent[2]

print(f"Embedding for the first ZERO is  {zero_A}")
print(f"Embedding for the second ZERO is {zero_B}")
print(f"Embedding for the ONE is         {one}")
```
Grabs the 2-number embedding vectors for those three specific images, ready to compare with distance metrics below.

---

**Text embeddings, using a real pretrained sentence-transformer (not something trained in this notebook):**

**16. Load a sentence-transformer model**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
```
Loads a pretrained model — note this is `paraphrase-MiniLM-L6-v2`, a close *sibling* of this project's `all-MiniLM-L6-v2`, both from the same MiniLM family and both outputting 384-dimensional vectors, but trained with slightly different objectives (paraphrase-detection vs. general semantic similarity).

**17. Define example sentences**
```python
sentence = ['The team enjoyed the hike through the meadow',
            'The national park had great views',
            'Olive oil drizzled over pizza tastes delicious']
```
Two sentences about the outdoors, one completely unrelated (pizza) — set up to demonstrate that the outdoor sentences should embed closer together than either does to the pizza sentence.

**18. Generate the embeddings**
```python
embedding = model.encode(sentence)
print(embedding)
```
This is the actual embedding step — same method (`model.encode()`) as `build_pgvector_index.py`'s `embed_batch()` function in this project, just called directly instead of in a batch loop.

**19. Check the shape**
```python
embedding.shape
```
Confirms each sentence became a 384-number vector (shape `(3, 384)` — 3 sentences × 384 dimensions).

**20. Visualize one embedding as a heatmap**
```python
import seaborn as sns
import matplotlib.pyplot as plt

sns.heatmap(embedding[0].reshape(-1,384), cmap="Greys", center=0, square=False)
plt.gcf().set_size_inches(10,1)
plt.axis('off')
plt.show()
# (repeated for embedding[1] and embedding[2])
```
Since 384 numbers can't be scatter-plotted like the 2D image embeddings were, this instead visualizes each embedding as a strip of grey-scale cells (one per dimension) — not something you can interpret by eye, but it illustrates that a real embedding really is just "a long list of numbers with no obvious individual meaning," as covered in `ML_CONCEPTS_NOTES.md`'s embeddings section.

---

**Distance metrics, computed by hand (matches `ML_CONCEPTS_NOTES.md` §5.2 and §5.6, same math, real numbers here):**

**21. Euclidean distance — manual formula**
```python
L2 = [(zero_A[i] - zero_B[i])**2 for i in range(len(zero_A))]
L2 = np.sqrt(np.array(L2).sum())
print(L2)
```
Implements the Euclidean distance formula by hand: square each dimension's difference, sum them, take the square root.

**22. Euclidean distance — the shortcut**
```python
np.linalg.norm((zero_A - zero_B), ord=2)
```
Same result as step 21, but using NumPy's built-in `norm()` function with `ord=2` (L2 norm = Euclidean distance) instead of writing the formula out manually.

**23. Compare all three pairs**
```python
print("Distance zeroA-zeroB:", np.linalg.norm((zero_A - zero_B), ord=2))
print("Distance zeroA-one:  ", np.linalg.norm((zero_A - one), ord=2))
print("Distance zeroB-one:  ", np.linalg.norm((zero_B - one), ord=2))
```
The actual demonstration: the two "0" embeddings should have a *smaller* Euclidean distance between them than either does to the "1" embedding.

**24. Manhattan distance — manual formula**
```python
L1 = [zero_A[i] - zero_B[i] for i in range(len(zero_A))]
L1 = np.abs(L1).sum()
print(L1)
```
Manhattan (L1) distance: take the absolute difference in each dimension, sum them directly (no squaring/square-rooting like Euclidean).

**25. Manhattan distance — the shortcut, and all three pairs**
```python
np.linalg.norm((zero_A - zero_B), ord=1)

print("Distance zeroA-zeroB:", np.linalg.norm((zero_A - zero_B), ord=1))
print("Distance zeroA-one:  ", np.linalg.norm((zero_A - one), ord=1))
print("Distance zeroB-one:  ", np.linalg.norm((zero_B - one), ord=1))
```
Same comparison as step 23, using `ord=1` (L1 norm) instead of `ord=2`.

**26. Dot product**
```python
np.dot(zero_A, zero_B)

print("Distance zeroA-zeroB:", np.dot(zero_A, zero_B))
print("Distance zeroA-one:  ", np.dot(zero_A, one))
print("Distance zeroB-one:  ", np.dot(zero_B, one))
```
`np.dot()` is literally the dot product formula: multiply matching dimensions and sum. Note the direction flips here versus Euclidean/Manhattan — a *higher* dot product means more similar, not lower.

**27. Cosine distance — manual formula**
```python
cosine = 1 - np.dot(zero_A,zero_B)/(np.linalg.norm(zero_A)*np.linalg.norm(zero_B))
print(f"{cosine:.6f}")
```
This is `1 - cosine_similarity`, matching the exact formula from `ML_CONCEPTS_NOTES.md` §5.6 (`(A·B)/(|A|×|B|)`) — just expressed as a *distance* (0 = identical) instead of a *similarity* (1 = identical).

**28. Reusable cosine distance function**
```python
def cosine_distance(vec1,vec2):
  cosine = 1 - (np.dot(vec1, vec2)/(np.linalg.norm(vec1)*np.linalg.norm(vec2)))
  return cosine
```
Wraps the formula from step 27 into a reusable function, used for both the image embeddings and the sentence embeddings below.

**29. Cosine distance for the three digit embeddings**
```python
print(f"Distance zeroA-zeroB: {cosine_distance(zero_A, zero_B): .6f}")
print(f"Distance zeroA-one:   {cosine_distance(zero_A, one): .6f}")
print(f"Distance zeroB-one:   {cosine_distance(zero_B, one): .6f}")
```
Same three-way comparison as before, using cosine distance instead of Euclidean/Manhattan/dot product.

**30. Dot product for the sentence embeddings**
```python
print("Distance 0-1:", np.dot(embedding[0], embedding[1]))
print("Distance 0-2:", np.dot(embedding[0], embedding[2]))
print("Distance 1-2:", np.dot(embedding[1], embedding[2]))
```
Now applying the same math to the real 384-dimensional sentence embeddings from step 18. The lesson notes that dot product and cosine distance are the two metrics most commonly used in NLP specifically (as opposed to Euclidean/Manhattan, more common for other data types) — this is why the sentence-embedding section only demonstrates these two.

**31. Cosine distance for the sentence embeddings**
```python
print("Distance 0-1: ", cosine_distance(embedding[0], embedding[1]))
print("Distance 0-2: ", cosine_distance(embedding[0], embedding[2]))
print("Distance 1-2: ", cosine_distance(embedding[1], embedding[2]))
```
The final demonstration: sentences 0 and 1 (both about the outdoors) should show a smaller cosine distance (more similar) than either does to sentence 2 (about pizza) — proving the embedding captured *meaning*, not just word overlap.

---

## Lesson: Search for Similar Vectors

**Source:** https://learn.deeplearning.ai/courses/vector-databases-embeddings-applications/lesson/3/search-for-similar-vectors
**Notebook:** `L2_kNN.ipynb` from the official course code repository

> Notes summarize the lesson, built primarily from the actual notebook's markdown/code cells (the more reliable source here) rather than the video transcript.

### The core idea: brute-force kNN

Once you have embeddings (previous lesson), the next question is: given a new query vector, how do you find the most similar vectors already stored? The simplest possible approach is **brute-force k-Nearest Neighbors (kNN)** — literally compare the query against *every single* stored vector, compute a distance/similarity for each, and return the `k` closest.

**Why "semantic search" and "vector search" mean this:** vectors capture meaning (from the previous lesson), so finding data similar in *meaning* to a query reduces to finding the closest points in vector space — that's the entire mechanism behind semantic search.

The lesson's real point, though, is to demonstrate **why brute-force doesn't scale** — setting up the motivation for Approximate Nearest Neighbors (ANN) in the next lesson, which is what this project's `ivfflat` index actually uses (see `ML_CONCEPTS_NOTES.md` §5.5).

### Part 1: a tiny, visualizable example (20 points, 2 dimensions)

**1. Imports**
```python
import numpy as np
import matplotlib.pyplot as plt
from sklearn.neighbors import NearestNeighbors
import time
np.random.seed(42)
```
Uses scikit-learn's `NearestNeighbors` (a ready-made brute-force/kNN implementation) instead of hand-writing it, plus `time` to measure query speed later. `np.random.seed(42)` makes the random data reproducible.

**2. Generate toy data**
```python
X = np.random.rand(20,2)
```
20 random points in 2D — small and low-dimensional enough to plot directly, standing in for "20 stored embeddings."

**3. Plot the points**
```python
n = range(len(X))
fig, ax = plt.subplots()
ax.scatter(X[:,0], X[:,1], label='Embeddings')
ax.legend()
for i, txt in enumerate(n):
    ax.annotate(txt, (X[i,0], X[i,1]))
```
Scatter-plots all 20 points, labeling each with its index number so you can visually identify "which point is #7" etc. in the next steps.

**4. Build the brute-force kNN index**
```python
k = 4
neigh = NearestNeighbors(n_neighbors=k, algorithm='brute', metric='euclidean')
neigh.fit(X)
```
Configures scikit-learn to find the `k=4` nearest neighbors using brute-force search (`algorithm='brute'` — explicitly checks every point, no shortcuts) and Euclidean distance. `.fit(X)` just registers the 20 points as the searchable dataset — nothing to "train" here since brute force needs no model.

**5. Plot a query point**
```python
n = range(len(X))
fig, ax = plt.subplots()
ax.scatter(X[:,0], X[:,1])
ax.scatter(0.45,0.2, c='red',label='Query')
ax.legend()
for i, txt in enumerate(n):
    ax.annotate(txt, (X[i,0], X[i,1]))
```
Adds a new red point at `(0.45, 0.2)` — this stands in for "a new question just came in, embedded as this vector," and visually, you can eyeball which of the 20 points should come back as neighbors.

**6. Run the actual search**
```python
neighbours = neigh.kneighbors([[0.45,0.2]], k, return_distance=True)
print(neighbours)
```
Finds the 4 closest stored points to the query, returning both their distances and their indices — this is the literal "search for similar vectors" the lesson is named for.

**7. Time a single query**
```python
t0 = time.time()
neighbours = neigh.kneighbors([[0.45,0.2]], k, return_distance=True)
t1 = time.time()

query_time = t1-t0
print(f"Runtime: {query_time: .4f} seconds")
```
Measures how long that one search took — with only 20 points, this should be near-instant, setting a baseline before scaling up.

### Part 2: proving brute-force gets slow as data grows

**8. A reusable speed-test function**
```python
def speed_test(count):
    data = np.random.rand(count,2)

    k=4
    neigh = NearestNeighbors(n_neighbors=k, algorithm='brute', metric='euclidean')
    neigh.fit(data)

    t0 = time.time()
    neighbours = neigh.kneighbors([[0.45,0.2]], k, return_distance=True)
    t1 = time.time()

    total_time = t1-t0
    print (f"Runtime: {total_time: .4f}")

    return total_time
```
Generalizes steps 2-7 into a function: generate `count` random 2D points, build a brute-force index, time one query. Lets you rerun the exact same experiment at different dataset sizes.

**9. Run it at 20,000 points**
```python
time20k = speed_test(20_000)
```
First real test of the scaling function — 20,000 stored points instead of 20.

**10. Push to millions of points**
```python
time200k = speed_test(200_000)
time2m = speed_test(2_000_000)
time20m = speed_test(20_000_000)
time200m = speed_test(200_000_000)
```
Runs the same single-query search against datasets from 200 thousand up to 200 *million* points. **This is the whole point of the lesson**: query time grows roughly linearly with dataset size, because brute-force literally has to touch every single point — there's no way around it. At 200 million points, a single query becomes noticeably, impractically slow.

### Part 3: brute-force kNN by hand, on realistic 768-dimensional embeddings

**11. Generate realistic-sized embeddings**
```python
documents = 1000
dimensions = 768

embeddings = np.random.randn(documents, dimensions) # 1000 documents, 768-dimensional embeddings
embeddings = embeddings / np.sqrt((embeddings**2).sum(1, keepdims=True)) # L2 normalize the rows, as is common

query = np.random.randn(768) # the query vector
query = query / np.sqrt((query**2).sum()) # normalize query
```
768 dimensions is a common real-world embedding size (used by many BERT-family models) — bigger than this project's 384-dim MiniLM vectors, but the same idea. **L2 normalization** (dividing each vector by its own length) is the key trick here: once every vector has length exactly 1, a plain **dot product** between two normalized vectors becomes mathematically equivalent to **cosine similarity** — so this step is what makes the next cell's simple dot-product search behave like a proper similarity search.

**12. Brute-force search via dot product**
```python
t0 = time.time()
similarities = embeddings.dot(query)
sorted_ix = np.argsort(-similarities)
t1 = time.time()

total = t1-t0
print(f"Runtime for dim={dimensions}, documents_n={documents}: {np.round(total,3)} seconds")

print("Top 5 results:")
for k in sorted_ix[:5]:
    print(f"Point: {k}, Similarity: {similarities[k]}")
```
`embeddings.dot(query)` computes the dot product between the query and *all 1000* stored embeddings at once (a single matrix-vector multiplication — this is the "brute-force" part, checking everything). `np.argsort(-similarities)` sorts them highest-similarity-first (the negative sign flips ascending sort into descending). The top 5 indices are the closest matches.

**13. Scale up the realistic-dimension test**
```python
n_runs = [1_000, 10_000, 100_000, 500_000]

for n in n_runs:
    embeddings = np.random.randn(n, dimensions) #768-dimensional embeddings
    query = np.random.randn(768) # the query vector

    t0 = time.time()
    similarities = embeddings.dot(query)
    sorted_ix = np.argsort(-similarities)
    t1 = time.time()

    total = t1-t0
    print(f"Runtime for 1 query with dim={dimensions}, documents_n={n}: {np.round(total,3)} seconds")
```
Repeats the dot-product search at growing document counts (1K → 500K), showing the same linear slowdown pattern as Part 2, now with realistic 768-dimensional data instead of toy 2D points.

**14. Extrapolate to a realistic workload**
```python
print (f"To run 1,000 queries: {total * 1_000/60 : .2f} minutes")
```
Takes the last measured single-query time and multiplies it out to estimate how long *1,000* queries would take — turning an abstract "query time" number into something that actually sounds like a real user-facing problem (minutes of wait time), which is the lesson's closing argument for why brute-force search alone isn't viable at production scale.

### How this maps onto this project

| Lesson concept | This project's equivalent |
|---|---|
| Brute-force kNN (`algorithm='brute'`) | What *isn't* used — this project skips straight to an approximate index, `ivfflat` |
| Linear slowdown as dataset grows | The exact problem `ivfflat`'s clustering solves — see `ML_CONCEPTS_NOTES.md` §5.5 |
| L2-normalized dot product = cosine similarity | Same math as pgvector's `vector_cosine_ops`, just computed by hand here instead of by the database |
| 768-dimensional embeddings | This project uses 384-dimensional (`all-MiniLM-L6-v2`) — smaller, so even brute-force would be somewhat faster here, but the same scaling problem applies at large corpus sizes |
| Manually timing queries at growing scale | Real justification for why the project's Neo4j/pgvector setup uses AuraDB/Supabase infrastructure instead of a naive in-memory search over 8GB-RAM hardware |
