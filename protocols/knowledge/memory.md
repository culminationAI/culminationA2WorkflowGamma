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

### Default: fastembed (all-MiniLM-L6-v2, 384d)

- Runs in-process, no external service
- ~90 MB model download on first use
- Matches MCP Qdrant server embedding model
- Sufficient for English memory records (≤200 tokens)

### Optional: Ollama bge-m3 (1024d)

Higher quality embeddings — multilingual, 1024d vectors. Trade-off: +1.5 GB RAM, requires Ollama service.

**Migration steps:**

1. Install Ollama: https://ollama.ai
2. Pull model:
   ```bash
   ollama pull bge-m3
   ```
3. Run migration:
   ```bash
   # Preview (no changes)
   python3 memory/scripts/memory_migrate.py --to ollama --dry-run

   # Execute migration
   python3 memory/scripts/memory_migrate.py --to ollama
   ```
4. The script will:
   - Create new Qdrant collection `workflow_memory_ollama_1024d`
   - Scroll all records from current collection (384d)
   - Re-embed each record with bge-m3 (1024d)
   - Upsert into new collection
   - Rename: old → `workflow_memory_backup`, new → `workflow_memory`
5. Update `secrets/.env`:
   ```
   EMBEDDING_PROVIDER=ollama
   ```
6. Verify:
   ```bash
   python3 memory/scripts/memory_verify.py
   ```

**Rollback:** To revert to fastembed:
```bash
python3 memory/scripts/memory_migrate.py --to fastembed
```

**Important:** MCP Qdrant server always uses fastembed 384d (configured in `mcp/mcp.json`). After migrating scripts to Ollama, the MCP server and Python scripts will use different collections. To avoid conflicts, use Python scripts as the primary memory interface after migration.
