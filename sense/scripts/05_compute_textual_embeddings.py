"""
Phase I.9 — Real textual-semantic features (Methodology §3.3.3).

Closes the `textual_proxy` gap: previously `body_character_count`/
`title_word_count` stood in for "pre-trained language-model embeddings,
specifically BERT contextual embeddings and Word2Vec word embeddings"
(§3.3.3) - see analyze/run_ablation.py's own docstring, which named this
placeholder explicitly rather than hiding it.

Two embedding families, both computed from each PR's title + body:

  - Word2Vec: trained directly on THIS project's own PR-title/body corpus
    (gensim) - not a generic pretrained model, genuinely "learned from the
    data" the way Word2Vec is meant to be used here.
  - BERT: `sentence-transformers/all-MiniLM-L6-v2`, a small (~80MB),
    CPU-friendly pretrained sentence-embedding model - real BERT-family
    contextual embeddings, not hand-rolled features.

Both are PCA-reduced to 5 dimensions each before being written back into
`feature_table.json` as `w2v_embed_0..4`/`bert_embed_0..4`: the dataset has
only ~300-500 rows, nowhere near enough to support 384+ raw embedding
dimensions without overfitting, so PCA keeps this tractable and honest
rather than silently blowing up the feature space.

PCA output is signed (components can be negative), but one of the four
Analyze-layer baselines (MultinomialNB - see analyze/train_models.py) hard-
requires non-negative features. Rather than push that constraint onto every
downstream consumer, each PCA output is MinMax-scaled to [0, 1] right here,
once, before being written - by construction, every FEATURES column in
feature_table.json stays non-negative from this point on, and the
train_models.py assertion of that invariant keeps validating it without
needing to know embeddings exist at all.

The fitted Word2Vec model, both PCA transformers, and both MinMax scalers
are persisted to analyze/models/ (word2vec.model, w2v_pca.joblib,
bert_pca.joblib, w2v_scaler.joblib, bert_scaler.joblib) so live inference
(act/github-action/live_predict.py) can reuse the EXACT same fitted
transforms rather than refitting per PR - refitting per PR would silently
drift the feature distribution away from what the classifiers were actually
trained on.

Usage:
    python sense/scripts/05_compute_textual_embeddings.py
"""

import json
import re
from pathlib import Path

import joblib
import numpy as np
from gensim.models import Word2Vec
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA
from sklearn.preprocessing import MinMaxScaler

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
MODEL_DIR = ROOT / "analyze" / "models"

W2V_DIM = 50
PCA_DIM = 5
BERT_MODEL_NAME = "all-MiniLM-L6-v2"

TOKEN_RE = re.compile(r"[a-zA-Z]+")


def tokenize(text: str) -> list:
    return TOKEN_RE.findall(text.lower())


def load_rows() -> list:
    paths = sorted(PROCESSED_DIR.glob("pr_*/feature_table.json"))
    rows = []
    for path in paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        row["_path"] = path
        rows.append(row)
    return rows


def pr_text(row: dict) -> str:
    return f"{row.get('title', '')}. {row.get('body', '')}"


def compute_word2vec_features(rows: list) -> np.ndarray:
    tokenized = [tokenize(pr_text(row)) for row in rows]
    # min_count=1: this corpus is small (a few hundred PRs); the default
    # min_count=5 would drop most vocabulary entirely.
    model = Word2Vec(sentences=tokenized, vector_size=W2V_DIM, window=5, min_count=1, workers=1, seed=42)

    vectors = np.zeros((len(rows), W2V_DIM), dtype=np.float64)
    for i, tokens in enumerate(tokenized):
        word_vecs = [model.wv[t] for t in tokens if t in model.wv]
        if word_vecs:
            vectors[i] = np.mean(word_vecs, axis=0)
        # else: leave as zero vector - a PR with no recognizable words
        # (empty title/body) gets no signal, not a crash.

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(MODEL_DIR / "word2vec.model"))
    return vectors


def compute_bert_features(rows: list) -> np.ndarray:
    print(f"Loading sentence-transformers model '{BERT_MODEL_NAME}' "
          "(downloads on first use, then cached)...")
    model = SentenceTransformer(BERT_MODEL_NAME)
    texts = [pr_text(row) for row in rows]
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)
    return np.asarray(embeddings, dtype=np.float64)


def main() -> None:
    rows = load_rows()
    if not rows:
        raise RuntimeError("No feature_table.json rows found - run 03_build_feature_table.py first")
    print(f"Computing textual embeddings for {len(rows)} PRs...")

    print("\n--- Word2Vec (trained on this project's own PR corpus) ---")
    w2v_raw = compute_word2vec_features(rows)
    w2v_pca = PCA(n_components=PCA_DIM, random_state=42)
    w2v_pca_out = w2v_pca.fit_transform(w2v_raw)
    w2v_scaler = MinMaxScaler()
    w2v_reduced = w2v_scaler.fit_transform(w2v_pca_out)
    joblib.dump(w2v_pca, MODEL_DIR / "w2v_pca.joblib")
    joblib.dump(w2v_scaler, MODEL_DIR / "w2v_scaler.joblib")
    print(f"Word2Vec PCA explained variance ratio: {w2v_pca.explained_variance_ratio_.sum():.3f}")

    print("\n--- BERT (sentence-transformers, pretrained) ---")
    bert_raw = compute_bert_features(rows)
    bert_pca = PCA(n_components=PCA_DIM, random_state=42)
    bert_pca_out = bert_pca.fit_transform(bert_raw)
    bert_scaler = MinMaxScaler()
    bert_reduced = bert_scaler.fit_transform(bert_pca_out)
    joblib.dump(bert_pca, MODEL_DIR / "bert_pca.joblib")
    joblib.dump(bert_scaler, MODEL_DIR / "bert_scaler.joblib")
    print(f"BERT PCA explained variance ratio: {bert_pca.explained_variance_ratio_.sum():.3f}")

    print("\nWriting embeddings back into each PR's feature_table.json...")
    for i, row in enumerate(rows):
        path = row.pop("_path")
        for j in range(PCA_DIM):
            row[f"w2v_embed_{j}"] = float(w2v_reduced[i, j])
            row[f"bert_embed_{j}"] = float(bert_reduced[i, j])
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")

    print(f"\nDone. Enriched {len(rows)} PRs with {PCA_DIM} Word2Vec + {PCA_DIM} BERT "
          "dimensions each.")
    print(f"Persisted fitted transforms to {MODEL_DIR}: word2vec.model, w2v_pca.joblib, "
          "bert_pca.joblib - reused (not refit) at live-inference time.")


if __name__ == "__main__":
    main()
