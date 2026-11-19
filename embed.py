"""Embedding models. The real model runs on CPU; a fake one keeps tests fast and offline."""
from __future__ import annotations

import hashlib
import os
from typing import Protocol

import numpy as np

DIM = 384
# Multilingual because the feed mixes English and Malay descriptions; runs on CPU, 384 dims.
DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class Embedder(Protocol):
    def embed(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer  # heavy import, only when used
        self.model = SentenceTransformer(model_name, device="cpu")

    def embed(self, text: str) -> np.ndarray:
        # e5 models expect a prefix; "query: " on both sides suits symmetric similarity.
        return self.model.encode(f"query: {text}", normalize_embeddings=True)


class HashEmbedder:
    """Deterministic fake for tests: same text -> same vector, no model download."""

    def embed(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
        return v / np.linalg.norm(v)


def load_embedder() -> Embedder:
    return HashEmbedder() if os.environ.get("EMBEDDER") == "hash" else SentenceTransformerEmbedder()
