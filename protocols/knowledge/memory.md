# Memory Protocol

## Overview

Zero-cost persistent episodic memory. Claude extracts facts → fastembed all-MiniLM-L6-v2 embeds (384d) → Qdrant vectors + Neo4j graph.

## Tools

```bash
# Search (vector, ~1s)
python3 memory/scripts/memory_search.py "query text" --limit 10

# Search (graph traversal)
python3 memory/scripts/memory_search.py "query" --graph

# Filter by source project
python3 memory/scripts/memory_search.py "query" --source personal

# Write (~2s)
python3 memory/scripts/memory_write.py '[{...}]' --source personal

# Deduplication
python3 memory/scripts/memory_dedupe.py

# Integrity check
python3 memory/scripts/memory_verify.py
```

## Interface Split

Two roles interact with memory. The split is by operation depth.

### Coordinator (direct shell access)

Fast operations, no subagent dispatch needed:

```bash
# Quick search — vector similarity, ~1s
python3 memory/scripts/memory_search.py "query" --limit 10

# Quick search — graph traversal
python3 memory/scripts/memory_search.py "query" --graph

# Write one or more records
python3 memory/scripts/memory_write.py '[{"text": "...", ...}]' --source personal
```

Use these at session start, before delegating, and after T3+ subagent work.

### Pathfinder (graph + semantic analysis)

Deep operations — delegate to pathfinder when you need more than a lookup:

- **Neo4j graph traversal** — finding connections and paths between memory records
- **Qdrant semantic similarity** — discovering related records by meaning across the full collection
- **Cross-reference verification** — confirming memory records match current codebase state
- **Maintenance operations** — deduplication, integrity check, cleanup:
  ```bash
  python3 memory/scripts/memory_dedupe.py     # remove duplicate records
  python3 memory/scripts/memory_verify.py     # Qdrant ↔ Neo4j integrity
  python3 memory/scripts/memory_cleanup.py    # purge stale/expired records
  ```

Pathfinder runs these as part of periodic maintenance or when memory quality degrades.

---

## Write Format

```json
[{
  "text": "English, ≤200 tokens, one fact per record",
  "user_id": "user",
  "agent_id": "coordinator|narrative-designer|...",
  "metadata": {
    "type": "decision|preference|build_up|task|contract|blocker|gap_analysis",
    "source_project": "personal|{project}|miner:personal|..."
  },
  "entities": [{"name": "Entity Name", "type": "person|project|metric|concept"}],
  "relations": [{"source": "A", "relation": "WORKS_ON", "target": "B"}]
}]
```

## Rules

1. **Search before write** — avoid duplicates
2. **English only** — max 200 tokens per record
3. **One fact per record** — atomic, searchable
4. **Always tag**: `user_id`, `agent_id`, `metadata.type`, `metadata.source_project`
5. **Session start**: search `"active tasks blockers recent decisions"`
6. **After T3+ work**: store key decisions and outcomes

## When to Store

| Trigger | metadata.type |
|---------|--------------|
| User corrects you | `build_up` (subtype: correction) |
| Wrong agent routed | `build_up` (subtype: routing) |
| Session-end review (T3+ work) | `build_up` (subtype: workflow) |
| User states preference | `preference` |
| Architecture/design decision | `decision` |
| Task completed | `task` |
| Blocker encountered | `blocker` |
| Gap analysis completed | `gap_analysis` |
| Build activated | `build_up` (subtype: build_activated) |
| Build deactivated | `build_up` (subtype: build_deactivated) |
| Build reactivated | `build_up` (subtype: build_reactivated) |
| Knowledge gap filled | `build_up` (subtype: knowledge_acquisition) |

## Conflict Resolution

When memory contains contradictory records:
1. Newer record wins (check timestamps)
2. Delete or flag the outdated record
3. Run `memory_dedupe.py` periodically

## Embedding Providers

### Default: Ollama bge-m3 (1024d)

Runs in Docker container `workflow-ollama`. Multilingual, 1024d vectors, higher recall for diverse content.

- Start: `docker compose up -d ollama` (in `infra/`)
- Model bge-m3 is pre-pulled in the container image
- ~1.5 GB RAM overhead

### Fallback: fastembed (all-MiniLM-L6-v2, 384d)

Runs in-process, no external service. Use when Ollama is unavailable or RAM is constrained.

- Enable: set `EMBEDDING_PROVIDER=fastembed` in `secrets/.env`
- ~90 MB model download on first use

### Routing

All memory scripts import from `memory/scripts/embedding.py`, which routes between providers based on `EMBEDDING_PROVIDER` env var. The MCP Qdrant server uses a custom entry point `mcp/ollama_qdrant_server.py` that applies the same routing.

### Switching providers

```bash
# Switch to fastembed (384d)
python3 memory/scripts/memory_migrate.py --to fastembed

# Switch to Ollama (1024d)
python3 memory/scripts/memory_migrate.py --to ollama

# Preview before running
python3 memory/scripts/memory_migrate.py --to fastembed --dry-run
```

Migration backs up the current collection, creates a new one at the target dimensions, re-embeds all records, then swaps in the new collection. Old data is preserved as `workflow_memory_backup_{N}d`.

After migration, update `EMBEDDING_PROVIDER` in `secrets/.env` and verify:
```bash
python3 memory/scripts/memory_verify.py
```
