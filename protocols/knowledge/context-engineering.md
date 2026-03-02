# Context Engineering Protocol

## Overview

Manage what goes into each LLM call. Every token counts. Plan context budget before dispatch, compress aggressively, prevent context rot.

## Context Budget Planning

Before each agent call, estimate input size:

| Component | Typical size | Notes |
|-----------|-------------|-------|
| System prompt | ~2K tokens | Agent definition + role |
| Memory context | ~1K tokens | Top-5 search results |
| Protocol context | ~1K tokens | Loaded on-demand, not all protocols |
| Task description | ~1-3K tokens | Scope, format, constraints |
| Tool definitions | ~2K tokens | MCP tools available to agent |
| Contract input | ~0.5-2K tokens | File path + brief description only |

Target budgets by tier:

| Tier | Max input | Rationale |
|------|-----------|-----------|
| T2-T3 | <10K tokens | Simple tasks, one agent |
| T4 | <20K tokens | Multi-step, needs more context |
| T5 | <30K tokens | Complex research, multiple sources |

If estimate exceeds target: compress (see next section) or split into subtasks.

## Prompt Compression

When context is too large, apply in order:

1. **Remove examples** if agent has done this task before — it knows the pattern
2. **Trim memory** to top-5 most relevant results (not all 20)
3. **Use file paths** instead of file contents — agent reads files itself
4. **Compress sibling context** to 1-2 sentences per sibling
5. **Drop protocol context** if agent has loaded it in a previous turn
6. **Summarize contract input** — "Semantic Model at `path`, covers 12 properties for Memory node" instead of quoting the model

Never compress: task scope, output format, file paths, constraints.

## Context Rot Prevention

What goes stale and what doesn't:

### ALWAYS inject (fresh every call)
- Task scope and constraints
- Output format and language
- File paths (validated via Glob)
- Relevant memory context (search each time)

### NEVER inject
- Full conversation history (scoped handoffs only)
- Large JSON blobs (pass file path)
- All protocols at once (load on-demand)
- Raw file contents in prompt (agent reads itself)
- Previous subagent's full output (use report_file path)

### REFRESH every call
- Memory context — always `memory_search.py` fresh, don't reuse from 5 minutes ago
- File paths — Glob to verify existence before injecting
- PLAN.md status — re-read if task depends on other executors

## Minimal Context Rule

For planning and exploration:

1. **Read index files first**: CATALOG.md, PLAN.md (first 50 lines), ToDo.md
2. **Read content files ONLY when task requires them** — not "just in case"
3. **Max 1 Explore agent** per planning session, with a specific question
4. **For T4+**: clarify domain/scope with user first, then explore
5. **Never pre-load** all knowledge files — there are 259 of them

## Token Counting Heuristics

Quick estimates without a tokenizer:

| Content type | Ratio | Example |
|-------------|-------|---------|
| English text | ~4 chars/token, ~0.75 words/token | 1000 words ~ 1300 tokens |
| Russian text | ~2-3 chars/token | 1000 chars ~ 350-500 tokens (Cyrillic is expensive) |
| JSON | ~3 chars/token | 3000 chars JSON ~ 1000 tokens |
| Markdown | ~10% overhead vs plain text | Headers, tables, formatting |
| Code (Python) | ~3.5 chars/token | Variable names, syntax |
| File paths | ~3 chars/token | Slashes and dots add up |

Rules of thumb:
- A 100-line markdown file ~ 1.5-2K tokens
- A JSON-summary block ~ 150-300 tokens
- Memory search results (5 items) ~ 500-1000 tokens
- A full protocol file (80-120 lines) ~ 1-1.5K tokens

## Checklist (before every dispatch)

```
[ ] Estimated total input tokens
[ ] Within tier budget?
[ ] Memory context is fresh (searched, not cached)
[ ] File paths validated (Glob)
[ ] No large blobs in prompt (file paths only)
[ ] Only relevant protocols loaded
[ ] Sibling context compressed (if parallel)
[ ] Contract input is path + 1-line summary (not full content)
```
