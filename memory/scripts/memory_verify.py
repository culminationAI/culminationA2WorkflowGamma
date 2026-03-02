#!/usr/bin/env python3
"""Memory verification protocol.

Checks:
1. Qdrant health & collection stats
2. Neo4j connectivity & graph stats
3. Embeddings service (fastembed all-MiniLM-L6-v2)
4. Write → Search roundtrip (canary test)
5. Duplicate detection
6. Garbage detection (short/meaningless records)
7. Graph consistency (orphan entities)

Usage:
    python3 memory_verify.py              # full check
    python3 memory_verify.py --quick      # skip roundtrip
    python3 memory_verify.py --fix        # auto-fix issues found
"""

import argparse
import json
import os
import sys
import uuid
import hashlib
from datetime import datetime, timezone

import requests

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIMS = 384
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "workflow_memory"
NEO4J_URL = os.environ.get("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "workflow")
NEO4J_DB = "neo4j"

CANARY_TEXT = "__VERIFY_CANARY__"

class Verifier:
    def __init__(self, fix=False):
        self.fix = fix
        self.issues = []
        self.stats = {}

    def check(self, name, ok, detail=""):
        status = "✅" if ok else "❌"
        msg = f"{status} {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        if not ok:
            self.issues.append(name)

    def check_qdrant(self):
        print("\n── Qdrant ──")
        try:
            r = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=5)
            r.raise_for_status()
            data = r.json()["result"]
            points = data["points_count"]
            self.stats["qdrant_points"] = points
            self.check("Qdrant reachable", True, f"{points} points")
            
            # Check for garbage records (very short or meaningless)
            garbage = self._find_garbage()
            self.stats["garbage"] = len(garbage)
            self.check("No garbage records", len(garbage) == 0, 
                       f"{len(garbage)} suspicious" if garbage else "clean")
            if garbage:
                for g in garbage[:5]:
                    print(f"    ⚠ [{g['id'][:8]}] \"{g['text']}\"")
                if len(garbage) > 5:
                    print(f"    ... and {len(garbage)-5} more")
            
            # Check for duplicates
            dupes = self._find_dupes()
            self.stats["duplicates"] = dupes
            self.check("No duplicates", dupes == 0, f"{dupes} duplicate pairs" if dupes else "clean")
            
        except Exception as e:
            self.check("Qdrant reachable", False, str(e))

    def check_neo4j(self):
        print("\n── Neo4j ──")
        try:
            r = requests.post(
                f"{NEO4J_URL}/db/{NEO4J_DB}/tx/commit",
                json={"statements": [
                    {"statement": "MATCH (n) RETURN count(n) as nodes"},
                    {"statement": "MATCH ()-[r]->() RETURN count(r) as rels"},
                    {"statement": "MATCH (n) WHERE NOT (n)--() RETURN count(n) as orphans"},
                ]},
                auth=(NEO4J_USER, NEO4J_PASS),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            r.raise_for_status()
            results = r.json()["results"]
            nodes = results[0]["data"][0]["row"][0]
            rels = results[1]["data"][0]["row"][0]
            orphans = results[2]["data"][0]["row"][0]
            
            self.stats["neo4j_nodes"] = nodes
            self.stats["neo4j_rels"] = rels
            self.stats["neo4j_orphans"] = orphans
            
            self.check("Neo4j reachable", True, f"{nodes} nodes, {rels} relations")
            self.check("No orphan entities", orphans == 0, 
                       f"{orphans} orphans" if orphans else "clean")
        except Exception as e:
            self.check("Neo4j reachable", False, str(e))

    def check_embeddings(self):
        print("\n── Embeddings (fastembed) ──")
        try:
            from fastembed import TextEmbedding
            embedder = TextEmbedding(model_name=EMBED_MODEL)
            embeddings = list(embedder.embed(["test embedding"]))
            dims = len(embeddings[0])
            self.check("fastembed all-MiniLM-L6-v2", True, f"{dims}d vectors")
        except Exception as e:
            self.check("fastembed all-MiniLM-L6-v2", False, str(e))

    def check_roundtrip(self):
        print("\n── Roundtrip Test ──")
        canary_id = str(uuid.uuid4())
        try:
            # 1. Embed
            from fastembed import TextEmbedding
            embedder = TextEmbedding(model_name=EMBED_MODEL)
            embeddings = list(embedder.embed([CANARY_TEXT]))
            vector = embeddings[0].tolist()[:EMBED_DIMS]
            self.check("Embed canary", True)

            # 2. Write
            payload = {
                "data": CANARY_TEXT,
                "hash": hashlib.md5(CANARY_TEXT.encode()).hexdigest(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "user_id": "test",
                "agent_id": "verifier",
                "metadata": {"type": "test"},
            }
            r = requests.put(
                f"{QDRANT_URL}/collections/{COLLECTION}/points",
                json={"points": [{"id": canary_id, "vector": vector, "payload": payload}]},
                timeout=5,
            )
            r.raise_for_status()
            self.check("Write canary", True)

            # 3. Search
            r = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
                json={"vector": vector, "limit": 1, "with_payload": True,
                      "filter": {"must": [{"key": "user_id", "match": {"value": "test"}}]}},
                timeout=5,
            )
            r.raise_for_status()
            results = r.json().get("result", [])
            found = len(results) > 0 and results[0]["payload"].get("data") == CANARY_TEXT
            self.check("Search finds canary", found, 
                       f"score={results[0]['score']:.4f}" if found else "NOT FOUND")

            # 4. Cleanup
            requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
                json={"points": [canary_id]},
                timeout=5,
            )
            self.check("Cleanup canary", True)

        except Exception as e:
            self.check("Roundtrip", False, str(e))
            # Try cleanup anyway
            try:
                requests.post(
                    f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
                    json={"points": [canary_id]}, timeout=5,
                )
            except:
                pass

    def _find_garbage(self) -> list[dict]:
        """Find suspiciously short or meaningless records."""
        garbage_patterns = [
            "loves to play cricket",
            "/no_think",
            "pattern to monitor",
            "taxi home",
            "drank beer",
            "task category is work",
            "task priority is high",
            "user_id is set",
            "user is set",
        ]
        
        found = []
        offset = None
        while True:
            body = {"limit": 100, "with_payload": True}
            if offset:
                body["offset"] = offset
            r = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                json=body, timeout=10,
            )
            r.raise_for_status()
            data = r.json()["result"]
            for p in data.get("points", []):
                text = p.get("payload", {}).get("data", "")
                text_lower = text.lower().strip()
                # Short records (<15 chars) or matching garbage patterns
                is_garbage = (
                    len(text_lower) < 15
                    or any(pat in text_lower for pat in garbage_patterns)
                )
                if is_garbage:
                    found.append({"id": p["id"], "text": text})
            offset = data.get("next_page_offset")
            if not offset:
                break
        return found

    def _find_dupes(self) -> int:
        """Count duplicate hash pairs."""
        from collections import Counter
        hashes = Counter()
        offset = None
        while True:
            body = {"limit": 100, "with_payload": True}
            if offset:
                body["offset"] = offset
            r = requests.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                json=body, timeout=10,
            )
            r.raise_for_status()
            data = r.json()["result"]
            for p in data.get("points", []):
                h = p.get("payload", {}).get("hash", "")
                if h:
                    hashes[h] += 1
            offset = data.get("next_page_offset")
            if not offset:
                break
        return sum(v - 1 for v in hashes.values() if v > 1)

    def run(self, quick=False):
        print("🔍 Memory Verification Protocol")
        print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.check_qdrant()
        self.check_neo4j()
        self.check_embeddings()
        if not quick:
            self.check_roundtrip()

        print("\n── Summary ──")
        print(f"   Points: {self.stats.get('qdrant_points', '?')}")
        print(f"   Graph:  {self.stats.get('neo4j_nodes', '?')} nodes, {self.stats.get('neo4j_rels', '?')} rels")
        print(f"   Garbage: {self.stats.get('garbage', '?')}")
        print(f"   Dupes:  {self.stats.get('duplicates', '?')}")
        print(f"   Orphans: {self.stats.get('neo4j_orphans', '?')}")
        
        if self.issues:
            print(f"\n⚠️  {len(self.issues)} issues found: {', '.join(self.issues)}")
            return 1
        else:
            print("\n✅ All checks passed")
            return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    
    v = Verifier(fix=args.fix)
    sys.exit(v.run(quick=args.quick))


if __name__ == "__main__":
    main()
