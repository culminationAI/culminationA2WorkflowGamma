# Coordination Protocol

## Overview

Orchestrate parallel subagent execution with synchronization, time balancing, and task splitting. Ensures all parallel branches converge efficiently.

## Triggers

- T3+ task requiring 2+ subagents
- Single subagent receiving a task heavier than T3
- Multiple independent work items that can be parallelized

## Execution Patterns

### 1. Fan-out / Fan-in
**When:** Independent tasks, same deadline.
**How:** Dispatch N agents in a single message (multiple Task tool calls) → wait for all → synthesize results.
**Example:** 3 researchers explore different domains in parallel → coordinator merges findings.

### 2. Pipeline
**When:** Dependent chain (A produces what B needs).
**How:** Sequential dispatch with contract handoffs. A completes → coordinator verifies output → dispatches B with A's report_file.
**Example:** narrative-designer (Semantic Model) → data-architect (Data Spec) → engineer (Implementation).

### 3. Asymmetric Fork
**When:** One heavy task + several lighter tasks in the same flow.
**How:** Split the heavy task into 2-3 sub-tasks by data scope. Parallelize everything.
**Example:** Curator needs to process 12 files (T4) while engineer does a T2 fix → split curator into 3×4 files + engineer → all run parallel.

### 4. Background + Foreground
**When:** Mix of blocking and non-blocking work.
**How:** Start heavy agent with `run_in_background: true`. Do lighter work in foreground. Join when background completes.
**Example:** Research agent (background, 5min) + quick engineer fix (foreground, 30s) → join when research done.

### 5. Diagnostic Sidecar

**When:** T3+ task with parallel gap-check enabled.
**How:** Main task runs as primary track. Gap-check pathfinder runs as sidecar (background, non-blocking).
**Join:** If sidecar detects issue (structural gap, severity >= high) → inject warning into main result or notify user. If clean → log and discard.
**Example:** User requests "Design WebSocket streaming" (T4) → engineer dispatched for main task + pathfinder gap-check in parallel → pathfinder finds MCP gap → coordinator warns user: "Missing WebSocket MCP server. Consider build-up."

## Synchronization

1. **Launch:** All parallel agents in ONE message with multiple Task tool calls
2. **Join:** Coordinator waits for all results before proceeding
3. **Partial failure:** If 1 of N fails → retry the failed agent only, don't re-run succeeded ones
4. **Merge:** After join, coordinator synthesizes all outputs (for T4+ → write synthesis document)

## Time Balancing

### Before Dispatch
Estimate complexity of each branch using T-tier as proxy:

| Tier | Estimated turns | Relative time |
|------|----------------|---------------|
| T2 | ~10 | 1x (baseline) |
| T3 | ~15 | 1.5x |
| T4 | ~20 | 2x |
| T5 | ~30 | 3x |

### Balancing Strategy
If tier spread > 1 between parallel branches:
1. Identify the heaviest branch
2. Split it into 2-3 sub-tasks by **data scope** (different files, domains, entities)
3. Each sub-task becomes a separate Task call of the same `subagent_type`
4. All sub-tasks + lighter branches run in parallel → converge together

**CRITICAL:** Split by data (scope), NEVER by pipeline stages. Each sub-task must be independently completable.

### Model Selection for Balance
- Heavy/creative tasks: `model: "sonnet"` (default)
- Light/auxiliary tasks: `model: "haiku"` (faster, cheaper)
- Complex reasoning: `model: "opus"` (when quality matters most)

## Task Splitting (Same Agent Type)

When a single agent would take too long:

1. **Identify split axis** — files, domains, entities, chapters (any natural data boundary)
2. **Create sub-tasks** — each is a self-contained Task call with the same `subagent_type`
3. **Inject sibling context** — each sub-task knows about parallel siblings:
   ```
   Note: In parallel, another [agent-type] instance is handling [scope B].
   Your scope is [scope A]. Do not overlap.
   ```
4. **Set max_turns** — proportional to sub-task size, not full task size
5. **Merge** — coordinator collects all JSON-summaries and combines outputs

**Example:** knowledge-curator on 12 files:
- Sub-task 1: files 1-4 (domain A)
- Sub-task 2: files 5-8 (domain B)
- Sub-task 3: files 9-12 (domain C)
All three run in parallel → coordinator merges catalogs.

## Budget Management

**Subscription context:** Time is more valuable than tokens. Optimize for wall-clock speed.

| Rule | Detail |
|------|--------|
| Parallel ceiling | 3-4 simultaneous agents (>4 = rate limits + diminishing returns) |
| Background agents | Use for tasks >2 minutes; foreground for <1 minute |
| Model routing | haiku for research/exploration, sonnet for creation, opus for critical reasoning |
| Rate limiting | If rate limited → reduce parallelism to 2, increase max_turns |
| Idle agents | Never let a finished agent's result sit unused — process immediately |

## Rules

1. **Estimate complexity BEFORE dispatch** — never launch without sizing
2. **Parallel ceiling = 4 agents** — practical limit, respect rate limits
3. **Independent = parallel, dependent = sequential** — no exceptions
4. **Split by data, not by stages** — each sub-task must be self-contained
5. **Sibling context is mandatory** for every parallel prompt
6. **After join:** verify all outputs → synthesize → store memory
7. **Partial failure → retry failed only** — don't re-run succeeded agents

## Anti-patterns

- Sequential chain when parallel is possible (wastes 2-3x time)
- Parallel without sibling context (duplicated or conflicting work)
- One mega-agent when 3 smaller would converge faster
- Ignoring tier asymmetry (T4 + T2 parallel → T2 agent idle while T4 grinds)
- Splitting by pipeline stages instead of data scope (creates dependencies)
- Launching 5+ agents simultaneously (rate limits, context switching overhead)
