#!/usr/bin/env python3
"""Custom MCP Qdrant server entry point using Ollama for embeddings.

Implements EmbeddingProvider using Ollama's /api/embed endpoint,
then starts QdrantMCPServer with this custom provider.

Environment variables:
    OLLAMA_URL       Ollama base URL        (default: http://localhost:11434)
    OLLAMA_MODEL     Ollama model name      (default: bge-m3)
    COLLECTION_NAME  Qdrant collection name (default: workflow_memory)
    QDRANT_URL       Qdrant base URL        (default: http://localhost:6333)
"""

from __future__ import annotations

import asyncio
import os

import requests
from mcp_server_qdrant.embeddings.base import EmbeddingProvider
from mcp_server_qdrant.mcp_server import QdrantMCPServer

# --- Config ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "bge-m3")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "workflow_memory")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

# bge-m3 produces 1024-dimensional vectors
_VECTOR_SIZE = 1024
_VECTOR_NAME = "bge-m3"


class OllamaEmbeddingProvider(EmbeddingProvider):
    """EmbeddingProvider backed by Ollama /api/embed."""

    def _embed(self, text: str) -> list[float]:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": OLLAMA_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # Ollama returns {"embeddings": [[...]]} for batch input
        if "embeddings" in data:
            return data["embeddings"][0]
        return data["embedding"]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        """Embed a list of documents (runs synchronous HTTP in executor)."""
        loop = asyncio.get_event_loop()
        results = []
        for doc in documents:
            vector = await loop.run_in_executor(None, self._embed, doc)
            results.append(vector)
        return results

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._embed, query)

    def get_vector_name(self) -> str:
        return _VECTOR_NAME

    def get_vector_size(self) -> int:
        return _VECTOR_SIZE


if __name__ == "__main__":
    from mcp_server_qdrant.settings import QdrantSettings, ToolSettings

    provider = OllamaEmbeddingProvider()
    server = QdrantMCPServer(
        tool_settings=ToolSettings(),
        qdrant_settings=QdrantSettings(),
        embedding_provider=provider,
    )
    server.run()
