#!/usr/bin/env python3
"""Direct memory search via Qdrant vector similarity.

Usage:
    python3 memory_search.py "query text" --limit 10
"""

from __future__ import annotations

import json
import os
import sys
import argparse
import requests

NEO4J_URL = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "workflow")

from embedding import get_embedding, get_vector_name

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "workflow_memory"


VECTOR_NAME = get_vector_name()


def search(query: str, limit: int = 10, user_id: str | None = None) -> list[dict]:
    vector = get_embedding(query)

    body = {
        "vector": {"name": VECTOR_NAME, "vector": vector},
        "limit": limit,
        "with_payload": True,
    }
    
    if user_id:
        body["filter"] = {
            "must": [{"key": "user_id", "match": {"value": user_id}}]
        }
    
    resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
        json=body,
        timeout=10,
    )
    resp.raise_for_status()
    
    results = []
    for point in resp.json().get("result", []):
        payload = point.get("payload", {})
        results.append({
            "id": point["id"],
            "score": round(point["score"], 4),
            "memory": payload.get("data", ""),
            "user_id": payload.get("user_id"),
            "agent_id": payload.get("agent_id"),
            "metadata": payload.get("metadata"),
            "created_at": payload.get("created_at"),
        })
    return results


def graph_search(query: str, limit: int = 10) -> list[dict]:
    """Search Neo4j for nodes matching query, then return 2-hop neighborhood."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return [{"error": "neo4j driver not installed. Run: pip install neo4j"}]

    driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))

    cypher = """
    CALL db.index.fulltext.queryNodes('memory_fulltext', $search_text)
    YIELD node, score
    WITH node, score ORDER BY score DESC LIMIT $limit
    CALL {
        WITH node
        MATCH path = (node)-[*1..2]-(neighbor)
        RETURN collect(DISTINCT {
            id: elementId(neighbor),
            labels: labels(neighbor),
            name: neighbor.name,
            type: neighbor.type
        }) AS neighbors,
        collect(DISTINCT {
            type: type(relationships(path)[-1]),
            from: elementId(startNode(relationships(path)[-1])),
            to: elementId(endNode(relationships(path)[-1]))
        }) AS rels
    }
    RETURN elementId(node) AS id, labels(node) AS labels,
           node.name AS name, node.data AS data, score,
           neighbors, rels
    """

    results = []
    with driver.session() as session:
        try:
            records = session.run(cypher, search_text=query, limit=limit)
            for rec in records:
                results.append({
                    "id": rec["id"],
                    "labels": rec["labels"],
                    "name": rec["name"],
                    "data": rec["data"],
                    "score": rec["score"],
                    "neighbors": rec["neighbors"],
                    "relationships": rec["rels"],
                })
        except Exception as e:
            # Fallback: fulltext index may not exist, try label search
            fallback = """
            MATCH (n) WHERE toLower(n.name) CONTAINS toLower($search_text)
            WITH n LIMIT $limit
            OPTIONAL MATCH path = (n)-[*1..2]-(m)
            RETURN elementId(n) AS id, labels(n) AS labels,
                   n.name AS name, n.data AS data, 1.0 AS score,
                   collect(DISTINCT {
                       id: elementId(m), labels: labels(m),
                       name: m.name, type: m.type
                   }) AS neighbors,
                   collect(DISTINCT {
                       type: type(relationships(path)[-1]),
                       from: elementId(startNode(relationships(path)[-1])),
                       to: elementId(endNode(relationships(path)[-1]))
                   }) AS rels
            """
            records = session.run(fallback, search_text=query, limit=limit)
            for rec in records:
                results.append({
                    "id": rec["id"],
                    "labels": rec["labels"],
                    "name": rec["name"],
                    "data": rec["data"],
                    "score": rec["score"],
                    "neighbors": rec["neighbors"],
                    "relationships": rec["rels"],
                })

    driver.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", "-l", type=int, default=10)
    parser.add_argument("--user-id", "-u", default="user")
    parser.add_argument("--graph", "-g", action="store_true",
                        help="Use Neo4j graph traversal (2-hop neighborhood) instead of vector search")
    args = parser.parse_args()

    if args.graph:
        results = graph_search(args.query, args.limit)
    else:
        results = search(args.query, args.limit, args.user_id)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
