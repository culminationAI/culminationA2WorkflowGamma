# Query Optimization Protocol

## Overview

Classify every user request before execution. Saves 50-70% of token budget by preventing over-delegation.

## Tier Classification

| Tier | Pattern | Action | Examples |
|------|---------|--------|----------|
| T1 | Show, find, list, check | Direct tool (Grep/Glob/Read) | "Where is X defined?", "Show me the config" |
| T2 | Add, edit, fix (simple) | General-purpose subagent (sonnet) | "Add a comment to this function", "Fix the typo" |
| T3 | Write, create, design | Specialized subagent | "Write a knowledge base article", "Design the schema" |
| T4 | Analyze, audit, review | Multiple subagents (sequential) | "Audit all knowledge files", "Review cross-domain consistency" |
| T5 | Architect, restructure | Multiple subagents (parallel + sequential) | "Redesign the agent hierarchy", "Restructure the project" |

## Rules

1. **Start response with `[T{n}]` marker** — makes tier visible
2. **Default to lower tier** — escalate only if insufficient
3. **T1 = NEVER delegate** — direct tool is 100x cheaper than a subagent
4. **T2 = general-purpose** — use sonnet model, no specialized agent needed
5. **T3+ = specialized** — route to the right subagent (see agent table)
6. **Coordinator never executes T2+** — only routes and synthesizes

## Prompt Checklist (before delegating T3+)

1. **Scope** — what files/dirs does the agent work with?
2. **Format** — what output format? (JSON, markdown, Cypher DDL)
3. **Length** — expected output size? (route large outputs to files)
4. **Context** — what memories/files to inject?
5. **Validation** — how to verify the result?

## Planning Rule (T3+)

Minimal context before planning:
1. Read index files only: CATALOG.md, PLAN.md (first 50 lines), ToDo.md
2. Do NOT read content files unless required
3. Max 1 Explore agent per planning session, with specific question
4. For T4+: clarify domain/scope with user first, then explore

## Subagent Routing

| Task Domain | Agent |
|-------------|-------|
| Psychology, narrative, character design | narrative-designer |
| Neo4j, Qdrant, data modeling | data-architect |
| Python, Docker, infrastructure | engineer |
| Physics, chemistry, biology | science-researcher |
| Prompt design, context engineering, LLM behavior | llm-engineer |
| Psychology, sociology, linguistics, neurolinguistics | humanities-researcher |
| Consciousness, mysticism, religion | consciousness-researcher |
| Metadata, chunking, catalogs | knowledge-curator |

## Anti-patterns

- Using a subagent for "find where X is defined" (T1 — use Grep)
- Reading 50 files before planning (read indexes only)
- Delegating a one-line fix to a specialized agent (T1-T2)
- Running parallel subagents when tasks are dependent (use sequential)
- Coordinator doing T3+ work directly instead of delegating
