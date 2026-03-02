#!/usr/bin/env python3
"""Delete garbage/wrong memory records from Qdrant.

Usage:
    python3 memory_cleanup.py --pattern "loves to play cricket" --dry-run
    python3 memory_cleanup.py --pattern "loves to play cricket" --execute
    python3 memory_cleanup.py --ids "uuid1,uuid2" --execute
"""

import argparse
import os
import requests

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "workflow_memory"


def scroll_all() -> list[dict]:
    points = []
    offset = None
    while True:
        body = {"limit": 100, "with_payload": True}
        if offset:
            body["offset"] = offset
        resp = requests.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
            json=body, timeout=30,
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


def delete_points(ids: list[str]):
    resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
        json={"points": ids}, timeout=10,
    )
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", "-p", help="Text pattern to match (case-insensitive)")
    parser.add_argument("--ids", help="Comma-separated point IDs to delete")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    to_delete = []

    if args.ids:
        to_delete = [x.strip() for x in args.ids.split(",")]
        print(f"Will delete {len(to_delete)} points by ID")
    elif args.pattern:
        pattern = args.pattern.lower()
        print(f"Searching for pattern: \"{args.pattern}\"")
        points = scroll_all()
        for p in points:
            text = p.get("payload", {}).get("data", "").lower()
            if pattern in text:
                print(f"  Match: [{p['id']}] {p['payload'].get('data', '')[:80]}")
                to_delete.append(p["id"])
        print(f"\nFound {len(to_delete)} matches")
    else:
        print("Specify --pattern or --ids")
        return

    if not to_delete:
        print("Nothing to delete")
        return

    if args.dry_run:
        print(f"DRY RUN — would delete {len(to_delete)} points")
    else:
        delete_points(to_delete)
        print(f"Deleted {len(to_delete)} points ✓")


if __name__ == "__main__":
    main()
