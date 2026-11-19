"""Embedding models. Real model runs on CPU; a fake one keeps tests fast."""
from __future__ import annotations
import hashlib, os
from typing import Protocol
import numpy as np

DIM = 384
# Multilingual: the feed mixes English and Malay. Runs on CPU, 384 dims.
DEFAULT_MODEL = "intfloat/multilingual-e5-small"

class Embedder(Protocol):
    def embed(self, text: str) -> np.ndarray: ...

class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device="cpu")
    def embed(self, text: str) -> np.ndarray:
        # e5 expects a prefix; "query: " on both sides suits symmetric similarity.
        return self.model.encode(f"query: {text}", normalize_embeddings=True)

class HashEmbedder:
    """Deterministic fake for tests: same text -> same vector."""
    def embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
        return v / np.linalg.norm(v)

def load_embedder() -> Embedder:
    return HashEmbedder() if os.environ.get("EMBEDDER") == "hash" else SentenceTransformerEmbedder()
