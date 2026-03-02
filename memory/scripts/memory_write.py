#!/usr/bin/env python3
"""Direct memory writer: embed via fastembed all-MiniLM-L6-v2, store in Qdrant + Neo4j.

Usage:
    python3 memory_write.py '<json_array>'
    python3 memory_write.py --file /tmp/memories.json

Each record in the array:
{
    "text": "fact to remember",
    "user_id": "user",
    "agent_id": "finance-manager",
    "metadata": {"type": "...", ...},
    "entities": [{"name": "...", "type": "..."}],        # optional
    "relations": [{"source": "...", "relation": "...", "target": "..."}]  # optional
}
"""

from __future__ import annotations

import json
import re
import sys
import uuid
import hashlib
import argparse
from datetime import datetime, timezone
from typing import Any

import os
import requests

# --- Security: Input Validation ---

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,49}$")
MAX_TEXT_LEN = 5000
MAX_JSON_BYTES = 10 * 1024 * 1024  # 10MB


def sanitize_identifier(value: str, field: str = "identifier") -> str:
    """Whitelist-validate a Neo4j label or relationship type.
    Only allows: letters, digits, underscore. Max 50 chars. Must start with letter or underscore."""
    if not isinstance(value, str):
        raise ValueError(f"[SECURITY] {field}: not a string")
    cleaned = value.strip().lower().replace(" ", "_").replace("-", "_")
    if not IDENTIFIER_RE.match(cleaned):
        raise ValueError(
            f"[SECURITY] {field}: invalid identifier '{cleaned}' — "
            f"must match ^[a-zA-Z_][a-zA-Z0-9_]{{0,49}}$"
        )
    return cleaned


def validate_text(value: str, field: str = "text", max_len: int = MAX_TEXT_LEN) -> str:
    """Validate text field: length limit, no null bytes."""
    if not isinstance(value, str):
        raise ValueError(f"[SECURITY] {field}: not a string")
    if "\x00" in value:
        raise ValueError(f"[SECURITY] {field}: contains null bytes")
    if len(value) > max_len:
        print(f"[WARN] {field}: truncated from {len(value)} to {max_len} chars", file=sys.stderr)
        value = value[:max_len]
    return value


def safe_json_load(source, max_bytes: int = MAX_JSON_BYTES):
    """Load JSON with size limit. source can be file object or string."""
    if hasattr(source, "read"):
        content = source.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError(
                f"[SECURITY] JSON input exceeds {max_bytes // 1024 // 1024}MB limit"
            )
        return json.loads(content)
    else:
        if len(source) > max_bytes:
            raise ValueError(
                f"[SECURITY] JSON input exceeds {max_bytes // 1024 // 1024}MB limit"
            )
        return json.loads(source)

# --- Config ---
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIMS = 384
_embedder = None  # lazy init

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "workflow_memory"

NEO4J_URL = os.environ.get("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "workflow")
NEO4J_DB = "neo4j"


def _get_embedder():
    """Lazy-init fastembed TextEmbedding (avoids slow import at module load time)."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


def get_embedding(text: str) -> list[float]:
    """Get embedding via fastembed (local, no external API)."""
    embedder = _get_embedder()
    embeddings = list(embedder.embed([text]))
    return embeddings[0].tolist()[:EMBED_DIMS]


def qdrant_upsert(point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
    """Upsert a single point to Qdrant."""
    resp = requests.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload,
                }
            ]
        },
        timeout=10,
    )
    resp.raise_for_status()


def neo4j_run(statement: str, parameters: dict | None = None) -> list:
    """Execute a Cypher statement via Neo4j HTTP API."""
    body: dict[str, Any] = {"statements": [{"statement": statement}]}
    if parameters:
        body["statements"][0]["parameters"] = parameters
    resp = requests.post(
        f"{NEO4J_URL}/db/{NEO4J_DB}/tx/commit",
        json=body,
        auth=(NEO4J_USER, NEO4J_PASS),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("errors", [])
    if errors:
        raise RuntimeError(f"Neo4j errors: {errors}")
    return data.get("results", [])


def neo4j_upsert_entities_and_relations(
    entities: list[dict], relations: list[dict], user_id: str
) -> None:
    """Upsert entities and relations to Neo4j graph."""
    if not entities and not relations:
        return

    for ent in entities:
        # Validate entity name and type before embedding in Cypher
        raw_name = validate_text(ent["name"], field="entity.name", max_len=200)
        name = raw_name.lower().replace(" ", "_").replace("-", "_")
        ent_type = sanitize_identifier(
            ent.get("type", "entity"), field="entity.type"
        )
        props = {k: v for k, v in ent.items() if k not in ("name", "type")}
        props["user_id"] = user_id
        props["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Use __User__ label pattern consistent with mem0
        cypher = (
            f"MERGE (n:`{ent_type}` {{name: $name}}) "
            f"SET n += $props"
        )
        neo4j_run(cypher, {"name": name, "props": props})

    for rel in relations:
        # Validate relation endpoints and type before embedding in Cypher
        raw_source = validate_text(rel["source"], field="relation.source", max_len=200)
        raw_target = validate_text(rel["target"], field="relation.target", max_len=200)
        source = raw_source.lower().replace(" ", "_").replace("-", "_")
        target = raw_target.lower().replace(" ", "_").replace("-", "_")
        relation = sanitize_identifier(
            rel["relation"], field="relation.type"
        ).upper()

        cypher = (
            f"MERGE (a {{name: $source}}) "
            f"MERGE (b {{name: $target}}) "
            f"MERGE (a)-[r:`{relation}`]->(b) "
            f"SET r.updated_at = $ts"
        )
        neo4j_run(cypher, {
            "source": source,
            "target": target,
            "ts": datetime.now(timezone.utc).isoformat(),
        })


def write_memories(records: list[dict]) -> dict[str, int]:
    """Write a batch of memory records. Returns counts."""
    ok = 0
    failed = 0

    for i, rec in enumerate(records):
        text = validate_text(rec["text"], field="record.text")
        user_id = rec.get("user_id", "user")
        agent_id = rec.get("agent_id", "general")
        metadata = rec.get("metadata", {})
        entities = rec.get("entities", [])
        relations = rec.get("relations", [])

        try:
            # 1. Embed
            vector = get_embedding(text)

            # 2. Build payload (compatible with mem0 format)
            point_id = str(uuid.uuid4())
            text_hash = hashlib.md5(text.encode()).hexdigest()
            now = datetime.now(timezone.utc).isoformat()

            payload = {
                "data": text,  # mem0 uses "data" field
                "hash": text_hash,
                "created_at": now,
                "updated_at": None,
                "user_id": user_id,
                "agent_id": agent_id,
            }
            if metadata:
                payload["metadata"] = metadata

            # 3. Qdrant upsert
            qdrant_upsert(point_id, vector, payload)

            # 4. Neo4j graph
            neo4j_upsert_entities_and_relations(entities, relations, user_id)

            ok += 1
            print(f"[{i+1}/{len(records)}] ✓ {text[:60]}")

        except Exception as e:
            failed += 1
            print(f"[{i+1}/{len(records)}] ✗ {text[:40]}... ERROR: {e}")

    return {"ok": ok, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Direct memory writer")
    parser.add_argument("json_data", nargs="?", help="JSON array of records")
    parser.add_argument("--file", "-f", help="Read records from JSON file")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            records = safe_json_load(f)
    elif args.json_data:
        records = safe_json_load(args.json_data)
    else:
        # Read from stdin
        records = safe_json_load(sys.stdin)

    if not isinstance(records, list):
        records = [records]

    print(f"Writing {len(records)} memories...")
    result = write_memories(records)
    print(f"\nDone: {result['ok']} ok, {result['failed']} failed")
    sys.exit(1 if result["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
