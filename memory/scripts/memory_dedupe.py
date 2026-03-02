#!/usr/bin/env python3
"""Find and remove duplicate memory records in Qdrant.

Duplicates are identified by matching hash values.

Usage:
    python3 memory_dedupe.py --dry-run
    python3 memory_dedupe.py --execute
"""

import argparse
import os
import requests
from collections import defaultdict
from typing import Any

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "workflow_memory"


def get_all_points() -> list[dict[str, Any]]:
    """Scroll through all points."""
    points = []
    offset = None
    
    while True:
        body: dict[str, Any] = {"limit": 100, "with_payload": True}
        if offset:
            body["offset"] = offset
        
        resp = requests.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()["result"]
        
        batch = data.get("points", [])
        if not batch:
            break
        
        points.extend(batch)
        offset = data.get("next_page_offset")
        if not offset:
            break
    
    return points


def find_duplicates(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group points by hash, return groups with >1 point."""
    by_hash: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    
    for p in points:
        h = p.get("payload", {}).get("hash", "")
        if h:
            by_hash[h].append(p)
    
    return {h: pts for h, pts in by_hash.items() if len(pts) > 1}


def delete_points(point_ids: list[str]) -> None:
    resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
        json={"points": point_ids},
        timeout=10,
    )
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    dry_run = not args.execute
    
    print("Scanning all points...")
    points = get_all_points()
    print(f"Total points: {len(points)}")
    
    dupes = find_duplicates(points)
    
    if not dupes:
        print("No duplicates found ✓")
        return
    
    to_delete = []
    for h, pts in dupes.items():
        # Keep the oldest (first created), delete the rest
        pts.sort(key=lambda p: p.get("payload", {}).get("created_at", ""))
        keep = pts[0]

        text = keep.get("payload", {}).get("data", "")[:50]
        print(f"\n  Hash {h[:12]}... ({len(pts)} copies): \"{text}...\"")
        print(f"    Keep: {keep['id']} (created {keep.get('payload',{}).get('created_at','')})")
        for r in pts[1:]:
            print(f"    Delete: {r['id']}")
            to_delete.append(r["id"])
    
    print(f"\n{'DRY RUN — ' if dry_run else ''}Would delete {len(to_delete)} duplicates")
    
    if not dry_run and to_delete:
        delete_points(to_delete)
        print(f"Deleted {len(to_delete)} points ✓")


if __name__ == "__main__":
    main()
