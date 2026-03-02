#!/usr/bin/env python3
"""Memory collection migration: fastembed (384d) ↔ Ollama bge-m3 (1024d).

Migrates all points in a Qdrant collection between embedding providers,
preserving point IDs and payloads. Old collection is backed up, not deleted.

Usage:
    python3 memory_migrate.py --to ollama       # fastembed 384d → bge-m3 1024d
    python3 memory_migrate.py --to fastembed    # bge-m3 1024d → fastembed 384d
    python3 memory_migrate.py --to ollama --dry-run   # preview only
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, List, Dict, Any

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION: str = os.environ.get("COLLECTION_NAME", "workflow_memory")
OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")

FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FASTEMBED_DIM = 384

OLLAMA_MODEL = "bge-m3"
OLLAMA_DIM = 1024

BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def embed_fastembed(texts: List[str]) -> List[List[float]]:
    """Embed texts using fastembed (all-MiniLM-L6-v2, 384d)."""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        print("[ERROR] fastembed is not installed. Run: pip install fastembed")
        sys.exit(1)

    embedder = TextEmbedding(model_name=FASTEMBED_MODEL)
    return [e.tolist() for e in embedder.embed(texts)]


def embed_ollama(texts: List[str]) -> List[List[float]]:
    """Embed texts one-by-one via Ollama bge-m3 API (1024d)."""
    vectors: List[List[float]] = []
    for text in texts:
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": OLLAMA_MODEL, "input": text},
            timeout=30,
        )
        r.raise_for_status()
        raw = r.json()["embeddings"][0]
        # Truncate to 1024 in case model returns more dimensions
        vectors.append(raw[:OLLAMA_DIM])
    return vectors


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def get_collection_info(name: str) -> Optional[Dict[str, Any]]:
    """Return collection info dict, or None if collection does not exist."""
    r = requests.get(f"{QDRANT_URL}/collections/{name}", timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["result"]


def get_vector_size(info: Dict[str, Any]) -> Optional[int]:
    """Extract vector size from collection info."""
    config = info.get("config", {})
    params = config.get("params", {})
    vectors = params.get("vectors", {})
    # Default (unnamed) vector config
    if isinstance(vectors, dict) and "size" in vectors:
        return vectors["size"]
    return None


def count_points(name: str) -> int:
    """Return total points count for a collection."""
    info = get_collection_info(name)
    if info is None:
        return 0
    return info.get("points_count", 0)


def create_collection(name: str, size: int) -> None:
    """Create a new Qdrant collection with Cosine distance."""
    r = requests.put(
        f"{QDRANT_URL}/collections/{name}",
        json={"vectors": {"size": size, "distance": "Cosine"}},
        timeout=10,
    )
    r.raise_for_status()


def delete_collection(name: str) -> None:
    """Delete a Qdrant collection."""
    r = requests.delete(f"{QDRANT_URL}/collections/{name}", timeout=10)
    r.raise_for_status()


def scroll_all(collection: str, batch_size: int = BATCH_SIZE) -> List[Dict[str, Any]]:
    """Scroll and return all points from a collection (payload only, no vectors)."""
    points: List[Dict[str, Any]] = []
    offset: Optional[str] = None

    while True:
        body: Dict[str, Any] = {
            "limit": batch_size,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset

        r = requests.post(
            f"{QDRANT_URL}/collections/{collection}/points/scroll",
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()["result"]
        batch = result.get("points", [])
        points.extend(batch)

        offset = result.get("next_page_offset")
        if offset is None or not batch:
            break

    return points


def upsert_points(collection: str, points: List[Dict[str, Any]]) -> None:
    """Upsert a batch of points (each must have id, vector, payload)."""
    r = requests.put(
        f"{QDRANT_URL}/collections/{collection}/points",
        json={"points": points},
        timeout=60,
    )
    r.raise_for_status()


def rename_collection(old_name: str, new_name: str) -> None:
    """Rename by copying to new_name then deleting old_name.

    Qdrant has no native rename — we create a new collection, copy all points
    with their original vectors (fetched this time), then delete the source.
    """
    # Get size of old collection to create new one correctly
    info = get_collection_info(old_name)
    if info is None:
        raise RuntimeError(f"Collection '{old_name}' not found")
    size = get_vector_size(info)
    if size is None:
        raise RuntimeError(f"Cannot determine vector size for '{old_name}'")

    create_collection(new_name, size)

    # Copy with vectors this time
    offset: Optional[str] = None
    while True:
        body: Dict[str, Any] = {
            "limit": BATCH_SIZE,
            "with_payload": True,
            "with_vector": True,
        }
        if offset is not None:
            body["offset"] = offset

        r = requests.post(
            f"{QDRANT_URL}/collections/{old_name}/points/scroll",
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()["result"]
        batch = result.get("points", [])

        if batch:
            upsert_points(
                new_name,
                [{"id": p["id"], "vector": p["vector"], "payload": p["payload"]} for p in batch],
            )

        offset = result.get("next_page_offset")
        if offset is None or not batch:
            break

    delete_collection(old_name)


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def check_ollama_ready() -> bool:
    """Return True if Ollama is running and bge-m3 is available."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        available = any(OLLAMA_MODEL in m for m in models)
        if not available:
            print(f"[ERROR] Ollama is running but model '{OLLAMA_MODEL}' is not pulled.")
            print(f"        Run: ollama pull {OLLAMA_MODEL}")
            return False
        return True
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Ollama not reachable at {OLLAMA_URL}")
        return False


def check_fastembed_ready() -> bool:
    """Return True if fastembed package is importable."""
    try:
        import importlib
        importlib.import_module("fastembed")
        return True
    except ImportError:
        print("[ERROR] fastembed not installed. Run: pip install fastembed")
        return False


def migrate(target: str, dry_run: bool) -> int:
    """Run migration to target provider. Returns 0 on success, 1 on error."""

    # Resolve target dimensions and source expectations
    if target == "ollama":
        src_dim = FASTEMBED_DIM
        dst_dim = OLLAMA_DIM
        src_label = f"fastembed ({src_dim}d)"
        dst_label = f"Ollama bge-m3 ({dst_dim}d)"
        backup_suffix = f"backup_{src_dim}d"
        embed_fn = embed_ollama
        ready_fn = check_ollama_ready
    else:  # fastembed
        src_dim = OLLAMA_DIM
        dst_dim = FASTEMBED_DIM
        src_label = f"Ollama bge-m3 ({src_dim}d)"
        dst_label = f"fastembed ({dst_dim}d)"
        backup_suffix = f"backup_{src_dim}d"
        embed_fn = embed_fastembed
        ready_fn = check_fastembed_ready

    print(f"[MIGRATE] {src_label} → {dst_label}")

    # --- Check source collection ---
    info = get_collection_info(COLLECTION)
    if info is None:
        print(f"[ERROR] Collection '{COLLECTION}' not found in Qdrant at {QDRANT_URL}")
        return 1

    actual_dim = get_vector_size(info)
    total = info.get("points_count", 0)

    print(f"[INFO] Current collection: {COLLECTION} ({actual_dim}d, {total} records)")

    if actual_dim != src_dim:
        print(
            f"[WARN] Expected source dimension {src_dim}d but found {actual_dim}d. "
            "Proceeding anyway — re-embedding all points."
        )

    # --- Dry run ---
    if dry_run:
        print(f"[DRY-RUN] Would create backup: {COLLECTION}_{backup_suffix}")
        print(f"[DRY-RUN] Would create new collection: {COLLECTION} ({dst_dim}d)")
        print(f"[DRY-RUN] Would re-embed and migrate {total} records")
        print(f"[DRY-RUN] No changes made.")
        return 0

    # --- Check provider readiness ---
    if not ready_fn():
        return 1

    # --- Step 1: Backup current collection ---
    backup_name = f"{COLLECTION}_{backup_suffix}"
    existing_backup = get_collection_info(backup_name)
    if existing_backup is not None:
        print(f"[WARN] Backup collection '{backup_name}' already exists — skipping backup step.")
        print("       Delete it manually if you want a fresh backup: "
              f"DELETE {QDRANT_URL}/collections/{backup_name}")
    else:
        print(f"[INFO] Creating backup: {backup_name}...")
        rename_collection(COLLECTION, backup_name)
        print(f"[OK] Backup created: {backup_name}")

    # --- Step 2: Create new empty collection with target dimensions ---
    existing_target = get_collection_info(COLLECTION)
    if existing_target is not None:
        print(f"[WARN] Collection '{COLLECTION}' already exists after backup step — deleting it.")
        delete_collection(COLLECTION)

    print(f"[INFO] Creating new collection: {COLLECTION} ({dst_dim}d)...")
    create_collection(COLLECTION, dst_dim)

    # --- Step 3: Scroll all points from backup, re-embed, upsert ---
    print(f"[INFO] Reading all points from {backup_name}...")
    all_points = scroll_all(backup_name)
    total_read = len(all_points)

    if total_read == 0:
        print("[WARN] No points found in backup collection. Nothing to migrate.")
        return 0

    migrated = 0
    # Process in batches for efficiency (single embed call per batch for fastembed;
    # ollama embeds one-by-one internally but batching the upsert still helps)
    for batch_start in range(0, total_read, BATCH_SIZE):
        batch = all_points[batch_start : batch_start + BATCH_SIZE]

        # Extract text for embedding
        texts = [p.get("payload", {}).get("data", "") for p in batch]

        # Re-embed
        try:
            vectors = embed_fn(texts)
        except Exception as e:
            print(f"[ERROR] Embedding failed at offset {batch_start}: {e}")
            print("        Migration is incomplete. Backup is preserved as "
                  f"'{backup_name}'.")
            return 1

        # Build upsert payload
        upsert_batch = [
            {
                "id": p["id"],
                "vector": vectors[i],
                "payload": p.get("payload", {}),
            }
            for i, p in enumerate(batch)
        ]

        try:
            upsert_points(COLLECTION, upsert_batch)
        except Exception as e:
            print(f"[ERROR] Upsert failed at offset {batch_start}: {e}")
            print("        Migration is incomplete. Backup is preserved as "
                  f"'{backup_name}'.")
            return 1

        migrated += len(batch)
        print(f"[PROGRESS] Migrated {migrated}/{total_read} records...")

    # --- Step 4: Summary ---
    final_count = count_points(COLLECTION)
    backup_count = count_points(backup_name)

    print(f"[OK] Migration complete: {migrated} records migrated")
    print(f"[OK] Backup: {backup_name} ({backup_count} records, {src_dim}d)")

    if target == "ollama":
        print("[INFO] Update .env: EMBEDDING_PROVIDER=ollama")
    else:
        print("[INFO] Update .env: EMBEDDING_PROVIDER=fastembed")

    if final_count != total_read:
        print(
            f"[WARN] Point count mismatch: migrated {total_read}, "
            f"collection now shows {final_count}. "
            "Qdrant may still be indexing — recheck shortly."
        )

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Qdrant memory collection between embedding providers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--to",
        required=True,
        choices=["ollama", "fastembed"],
        help="Target embedding provider",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making any changes",
    )
    args = parser.parse_args()

    sys.exit(migrate(target=args.to, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
