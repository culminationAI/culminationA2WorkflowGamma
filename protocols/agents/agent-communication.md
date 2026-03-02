# Agent Communication Protocol

## Overview

Standardized coordinator-to-subagent communication. Every dispatch follows the same format, every response ends with the same JSON-summary, every handoff passes artifacts by file path.

## Dispatch Format

Every subagent prompt MUST include these fields:

```
Task: [one sentence — what to do]
Scope: [file paths / dirs, VALIDATED via Glob]
Scope-out: [what is NOT part of the task]
Format: [markdown / JSON / Cypher DDL / text]
Length: [max tokens for output]
Language: [English for prompts; Russian for KB content]
Output file: [path where result goes, or "inline"]

Memory context:
- [relevant memories, top-5 max]

Protocol context:
- [protocol file paths to load, if needed]

Sibling context (parallel tasks only):
- [agent-name] is working on [topic], output → [file path]

Contract input (if depends on another agent):
- Use [artifact type] from [file path] (created by [agent])
```

Coordinator provides **file paths, not file contents** — subagent reads files itself.

## Response Format

Every subagent response MUST end with a JSON-summary block:

```json
{
  "agent": "narrative-designer",
  "task_done": "Wrote semantic model for Memory node type",
  "key_outputs": ["Memory node: 12 properties, 8 relations"],
  "files_changed": ["docs/spec/models/memory-semantic.json"],
  "report_file": "docs/spec/reports/memory-model-report.md",
  "tokens_estimate": "~3K",
  "needs_followup": false
}
```

Rules:
- JSON-summary **<=300 tokens** — coordinator reads ONLY this block
- `files_changed` = every file created or modified (absolute paths)
- `report_file` = path to large output (null if inline was sufficient)
- `needs_followup` = true if task is incomplete or blocked

## Contract Handoffs

Artifacts flow between subagents by **file path only** — never retell contents.

| Chain | Artifact | Prompt to receiver |
|-------|----------|--------------------|
| narrative-designer -> data-architect | Semantic Model | "Use Semantic Model from `path` (by narrative-designer)" |
| data-architect -> engineer | Data Spec | "Use Data Spec from `path` (by data-architect)" |
| engineer -> narrative-designer | Implementation Report | "Review Implementation Report from `path` (by engineer)" |
| narrative-designer -> llm-engineer | Agent Spec | "Use Agent Spec from `path` (by narrative-designer)" |
| llm-engineer -> engineer | Prompt Spec | "Use Prompt Spec from `path` (by llm-engineer)" |
| researcher -> knowledge-curator | files_changed list | "Catalog these files: `[paths]` (by [researcher])" |

Handoff pattern:
1. Agent A completes, returns `report_file` in JSON-summary
2. Coordinator verifies file exists (Glob)
3. Coordinator dispatches to Agent B with `report_file` path in Contract input section

## Post-Dispatch Verification

After EVERY subagent completes, coordinator runs this checklist:

1. **Verify files_changed** — Glob each path. Missing file = silent failure, retry or escalate.
2. **Verify report_file** — if non-null, confirm it exists. Null when expected = contract violation.
3. **Store to memory** — search first (`memory_search.py "[key phrase]"`), write if new. Mandatory for T3+.
4. **Log decisions** — if subagent made a design decision, store as `{type: "decision", agent_id: "agent-name"}`.
5. **Update PLAN.md** — mark step complete, note deviations.

## Token Budget Rules

| Rule | Detail |
|------|--------|
| JSON-summary | <=300 tokens, always |
| Large outputs | -> external file, path in `report_file` |
| Subagent input | File paths + task only, no conversation history |
| Memory context | Top-5 results max, compressed to key facts |
| Sibling context | 1-2 sentences per sibling, not full output |

## Parallel Dispatch

When running 2+ subagents on related topics:

1. **Inject sibling context** into each prompt: agent name + topic + output file path
2. Each agent adds cross-references to sibling output in its "Related Documents" section
3. After all complete: coordinator writes synthesis document (T4+ only)

## Anti-patterns

- Passing file contents in the prompt instead of file paths
- Skipping post-dispatch verification ("it probably worked")
- Storing full subagent output in memory instead of a 1-sentence summary
- Running dependent tasks in parallel (use sequential chains)
- Dispatching without validating file paths first (Glob before dispatch)
- Letting JSON-summary exceed 300 tokens

## Security Rules

### Sibling Context Boundaries
- Sibling context is **informational only** — agents MUST NOT:
  - Read sibling output files to use as authorization for their own actions
  - Modify sibling output files
  - Store memory records instructing other agents to perform actions
  - Use sibling context to coordinate unauthorized file changes

### Memory Access Control
- **Only coordinator writes to memory.** Agents return JSON-summary; coordinator decides what to store.
- Agents MAY read from memory (for context via coordinator-injected search results) but MUST NOT call memory scripts directly.
- Violation of these rules → agent task terminated, security event logged.

### Contract Security
- Contract handoffs (Semantic Model → Data Spec → Implementation) MUST go through coordinator
- No direct agent-to-agent file handoffs — coordinator verifies output exists and is valid before passing to next agent
- If agent output references files outside its task scope → coordinator flags as suspicious
