#!/usr/bin/env python3
"""Shared embedding module — routes between fastembed and Ollama.

Controlled by environment variables:
    EMBEDDING_PROVIDER  "fastembed" (default) | "ollama"
    EMBEDDING_MODEL     fastembed model name (default: sentence-transformers/all-MiniLM-L6-v2)
    OLLAMA_URL          Ollama base URL       (default: http://localhost:11434)
    OLLAMA_MODEL        Ollama model name     (default: bge-m3)
"""

from __future__ import annotations

import os

# --- Config ---
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "fastembed")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3")

# Vector dimensions and names per provider
_DIMS = {
    "fastembed": 384,
    "ollama": 1024,
}
_VECTOR_NAMES = {
    "fastembed": "fast-all-minilm-l6-v2",
    "ollama": "bge-m3",
}

# Lazy-init fastembed embedder
_fastembed_embedder = None


def get_vector_size() -> int:
    """Return the embedding dimension for the active provider."""
    return _DIMS.get(EMBEDDING_PROVIDER, 384)


def get_vector_name() -> str:
    """Return the named vector key for the active provider (matches MCP Qdrant)."""
    return _VECTOR_NAMES.get(EMBEDDING_PROVIDER, "fast-all-minilm-l6-v2")


def _get_fastembed_embedder():
    """Lazy-init fastembed TextEmbedding (avoids slow import at module load time)."""
    global _fastembed_embedder
    if _fastembed_embedder is None:
        from fastembed import TextEmbedding
        _fastembed_embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _fastembed_embedder


def _embed_fastembed(text: str) -> list[float]:
    embedder = _get_fastembed_embedder()
    embeddings = list(embedder.embed([text]))
    return embeddings[0].tolist()[:_DIMS["fastembed"]]


def _embed_ollama(text: str) -> list[float]:
    import requests
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": OLLAMA_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # Ollama returns {"embeddings": [[...]]} for batch or {"embedding": [...]} for single
    if "embeddings" in data:
        return data["embeddings"][0]
    return data["embedding"]


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for text using the configured provider."""
    if EMBEDDING_PROVIDER == "ollama":
        return _embed_ollama(text)
    return _embed_fastembed(text)
