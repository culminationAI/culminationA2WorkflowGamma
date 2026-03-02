# Exploration Report — _follower_

> Generated during Phase 3 of initialization.

## Project Overview
- **Name:** _follower_
- **Type:** CulminationA2 Workflow instance (secondary agent)
- **Archetype:** Framework/OSS (multi-agent orchestration)
- **Relation:** Follower to _primal_ (OkiAra, primary agent)

## Stack
- **Language:** Python 3.9
- **Infrastructure:** Docker Compose (shared Qdrant + Neo4j with _primal_)
- **Memory:** Qdrant (384d, cosine, fastembed) + Neo4j (graph)
- **Agents:** 4 base (pathfinder, protocol-manager, engineer, llm-engineer)
- **Protocols:** 18 (core: 8, quality: 3, agents: 3, knowledge: 3, project: 1)

## Architecture Classification
- **Primary archetype:** Framework/OSS
- **Secondary:** None
- **Signal count:** pyproject absent, Docker Compose present, agents/, protocols/, memory/

## Detected Patterns
- Shared infrastructure with _primal_ (same Qdrant collection, same Neo4j)
- Data attribution via `_source: _follower_` tag
- No user code — project IS the workflow
