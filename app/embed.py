"""Embedding models. Real model runs on CPU; a fake one keeps tests fast."""
from __future__ import annotations
import hashlib, os
from typing import Protocol
import numpy as np

DIM = 384
# Multilingual: the feed mixes English and Malay. Runs on CPU, 384 dims.
# Chosen by evals/cross_lingual.py: trained on translation pairs, so English and Malay
# descriptions of the same business land close together (R@5 0.80 vs 0.29 for e5-small).
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

class Embedder(Protocol):
    def embed(self, text: str) -> np.ndarray: ...

class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device="cpu")
    def embed(self, text: str) -> np.ndarray:
        return self.model.encode(text, normalize_embeddings=True)  # no prefix needed for this model

class HashEmbedder:
    """Deterministic fake for tests: same text -> same vector."""
    def embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
        return v / np.linalg.norm(v)

def load_embedder() -> Embedder:
    return HashEmbedder() if os.environ.get("EMBEDDER") == "hash" else SentenceTransformerEmbedder()
