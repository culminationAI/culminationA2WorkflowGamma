# Dispatcher — Coordinator Reference

> Not a subagent. The coordinator applies these rules mentally on every request.

## Pre-Classification: Gap Check (T1-T2)

Before classifying by tier, check if the task domain has known coverage gaps:

1. If `docs/self-architecture/capability-map.md` exists — scan for domain coverage
2. If domain coverage score < 0.5 → trigger deep gap analysis (`protocols/core/gap-analysis.md`) BEFORE dispatching
3. If an active build covers the domain → route normally (build provides capability)
4. If a buffered build covers the domain → recommend reactivation to user

Skip this check for T1 tasks (always covered by direct tools).

> **T3+ tasks use parallel gap-check instead** — see § Parallel Gap-Check (T3+) below.

## Parallel Gap-Check (T3+)

For T3+ requests, gap analysis runs IN PARALLEL with task dispatch — never blocks main work.

### Process

1. Coordinator classifies request as T3+ (normal tier classification)
2. **Fork:** Two parallel tracks start simultaneously:
   - **Track A (Main Task):** Select subagent, apply prompt checklist, dispatch normally
   - **Track B (Gap Check):** Two-stage process:
     a. **Quick check (coordinator, ~2 seconds):**
        - `Glob` → verify `docs/self-architecture/capability-map.md` exists and is fresh (<24h)
        - `Read` → check `docs/self-architecture/build-registry.json` for active build TTL warnings
        - `Read` → scan last 5 entries in `docs/self-architecture/request-history.json` for domain match
        - If capability-map is fresh AND domain is covered → **Track B complete, no pathfinder needed**
     b. **Deep check (pathfinder, only if needed):**
        - Capability-map stale (>24h) OR domain unknown → dispatch pathfinder
        - Pathfinder: Neo4j graph traversal (agents ↔ protocols ↔ MCP coverage) + Qdrant semantic scoring
        - Output: gap score + recommendations

3. **Join conditions:**
   - Track A completes first, Track B pending → log Track B result when it arrives. No interruption.
   - Track B completes first with NO GAP (score > 0.8) → discard result, Track A continues.
   - Track B completes first with GAP DETECTED (score <= 0.8):
     a. If severity >= high → **MANDATORY user notification**: "Gap detected in {domain}: {summary}. Recommend: {action}."
     b. If severity < high → append gap warning to coordinator's synthesis response.
   - Both complete → merge results, gap analysis logged to `gap-analysis-log.md`.

### Constraints

- Pathfinder is non-blocking (Rule 5)
- Max 1 parallel gap-check at a time — skip if one already running
- Quick check uses coordinator's direct tools only (Glob, Read) — no subagent
- KNOWLEDGE gap found → log silently, auto-schedule memory strengthening after Track A completes
- STRUCTURAL gap with severity >= high → user notification MANDATORY (even if Track A succeeded)

## Request Classification (by verb)

| Verb | Tier | Steps | Output |
|------|------|-------|--------|
| show, find, open | T1 | 1 | <500 tok |
| add, edit, fix | T2 | 2-3 | <2K tok |
| write, create, analyze | T3 | 4-8 | 2-5K tok |
| design, architect, debug | T4 | 8-20 | 5-15K tok |
| research, prove, compare 5+ sources | T5 | 20+ | 15K+ tok |

## Model and Thinking

| Tier | Model | Thinking |
|------|-------|----------|
| T1 | haiku | off |
| T2 | sonnet | off |
| T3 | sonnet | effort: medium |
| T4 | opus | effort: high |
| T5 | opus | effort: max |

## Routing

| Tier | Delegate to |
|------|-------------|
| T1 | **Direct tool** (Grep, Glob, Read) — NEVER use subagents for T1. Subagents load 30K+ baseline context, wasting 100x tokens vs direct tool (~500 tok). |
| T2 | general-purpose (sonnet) |
| T3+ | Specialized subagent by domain |

### Base agents (always available)

| Domain | Subagent |
|--------|----------|
| Project exploration, architecture analysis, codebase scanning | pathfinder |
| Memory management: verify, validate, dedupe, cleanup, maintenance | pathfinder |
| Post-refactor verification, connection mapping, knowledge extraction | pathfinder |
| Web research for project analysis | pathfinder |
| Self-architecture scan, capability mapping, gap detection | pathfinder (self-explore mode) |
| Protocol creation, organization, search, indexing | protocol-manager |
| Protocol directory maintenance, cross-reference management | protocol-manager |
| Python, Docker, API, scripts, tests, infrastructure | engineer |
| Prompt design, context engineering, model routing, agent creation | llm-engineer |

### Domain agents (created during initialization)

> No domain agents created for this workspace. Domain agents are project-specific
> and created during initialization Phase 4 based on project archetype.
> Check `.claude/agents/` for available agents beyond the base four.

## Command Routing

Explicit slash-command overrides. Take precedence over verb-based tier classification.

| Command | Tier | Executor | Description |
|---------|------|----------|-------------|
| `/meditate quick` | T3 | coordinator (direct tools) | Quick meditation — coordinator-only scan |
| `/meditate` or `/meditate deep` | T4 | pathfinder | Deep meditation — full introspection with connection weaving |
| `/meditate full` | T5 | pathfinder | Full meditation — deep + universal reach + Neo4j analysis |

## Prompt Checklist

Before delegating to a subagent — verify the prompt includes:

- [ ] **What to do** — one sentence, task core
- [ ] **Scope out** — what is NOT part of the task
- [ ] **Format** — markdown/JSON/text, structure
- [ ] **Length** — max_length in tokens
- [ ] **Language** — English for prompts
- [ ] **File path (VALIDATED)** — if result must be written to a file, **MUST run Glob to verify the path exists** before dispatching. Never assume file names from memory — always check filesystem.
- [ ] **Context** — minimally necessary (don't overload)
- [ ] **Memory context** — search memory by task, include relevant context in prompt
- [ ] **Protocol context** — search memory for relevant protocols, inject key rules into prompt
- [ ] **Contract version** — if task depends on a contract, verify it's current
- [ ] **Executor lock** — verify no other subagent is working on the same files
- [ ] **Parallel context** — if running parallel tasks, inject brief summary of sibling tasks (see § Parallel Task Protocol)

## Contract Handoffs Between Subagents

When subagent A creates an artifact for subagent B — pass `report_file` explicitly in B's prompt, don't retell contents:

| Junction | What to pass |
|----------|-------------|
| domain-agent → data-architect | `report_file` Semantic Model |
| data-architect → engineer | `report_file` Data Spec |
| engineer → domain-agent | `report_file` Implementation Report |
| domain-agent → llm-engineer | `report_file` Agent Spec (what agent should know) |
| llm-engineer → engineer | `report_file` Prompt Spec (optimized system prompt) |
| researcher → knowledge-curator | list of `files_changed` |

**Prompt format:** "Use the Data Spec from `path/to/spec.md` (created by data-architect)" — subagent reads the file itself.

## Post-Dispatch Verification

After EVERY subagent completes:

1. **Check `files_changed`** — verify each file exists using Glob. If missing → agent silently failed, retry or escalate.
2. **Check `report_file`** — if non-null, verify file exists. If null but agent should have written output → flag as contract violation.
3. **Store to memory** — search memory for key phrase → check duplicates → write to memory with metadata `{type, agent_id}`. This is MANDATORY, not optional.
4. **Log decision** — if the subagent made a design decision worth preserving, store it as `{type: "decision"}`.
5. **Append request history** (T3+ only) — coordinator appends entry to `docs/self-architecture/request-history.json` (using Read + Edit):
   - `id`: `"req-{YYYY-MM-DD}-{HHmm}-{NNN}"`
   - `timestamp`: ISO8601
   - `tier`: T3|T4|T5
   - `verb`: extract first action verb from original request
   - `domain`: classify from subagent used + `files_changed` directories (semantic cluster, not static list)
   - `subagents_used`: list of agents dispatched
   - `task_summary`: one sentence, max 100 chars
   - `gap_detected`: bool (from parallel gap-check result if available)
   - `gap_severity`: null | "low" | "medium" | "high" | "critical"
   - `build_used`: build ID or null
   - `outcome`: "success" | "partial" | "failed"
   - `phase_hint`: classify verb → DESIGN|IMPLEMENTATION|TESTING|DEPLOYMENT|null
   - If `entries.length >= 100`: archive oldest 50 to `request-history-archive.json`, keep newest 50
   - **No subagent dispatch** — coordinator does this directly

## Parallel Task Protocol

When running 2+ subagents in parallel on related topics:

1. **Before dispatch**: include in EACH agent's prompt a 1-2 sentence summary of what sibling agents are working on:
   ```
   Note: In parallel, [agent-A] is covering [topic X] and [agent-B] is covering [topic Y].
   Include cross-references to their output files in your "Related Documents" section.
   ```
2. **Sibling file paths**: provide the output file paths of ALL parallel agents, so each can add cross-references.
3. **After all complete**: coordinator writes a synthesis document linking all parallel outputs (for T4+ tasks).

## Rules

1. **Classify by the REQUEST VERB**, not by file state
2. **When in doubt** between adjacent tiers — choose lower, escalate if needed
3. **Coordinator never executes domain tasks directly** — only routes and synthesizes
4. **Max subagents:** 2 for T3, 3 for T4, unlimited for T5
5. **Pathfinder is non-blocking** — pathfinder can run in parallel with any other agent
6. **Start response with `[T{n}]`** so the user sees the classification
7. **Respond to user in the project language** (set in CLAUDE.md)
8. **Scoped handoffs** — each subagent gets only file paths + task description, not full conversation history
9. **T1 = direct tool** — never delegate T1 to subagent. If one Grep/Glob/Read can answer it, use it directly.
10. **Validate paths before dispatch** — run Glob to confirm file existence. Never construct paths from memory.
11. **Auto-protocol creation** — if a new rule or feature is introduced, coordinator MUST dispatch protocol-manager to evaluate formalization
12. **Coordinator NEVER writes files** — if the task creates or modifies a file (code, scripts, docs, configs), it MUST be delegated to a subagent. Coordinator only writes plan files and memory records.

## Tool Allocation

| Operation | Who | Tool | Why |
|-----------|-----|------|-----|
| File search/existence check | Coordinator | Glob | ~0.1s, no agent needed |
| Content search | Coordinator | Grep | Pattern matching, no reasoning |
| Read JSON configs/registries | Coordinator | Read | Trivial parse |
| Write/edit configs/registries | Coordinator | Write, Edit | Mechanical append/update |
| Post-dispatch file verification | Coordinator | Glob | Verify files_changed exist |
| Lightweight gap scan | Coordinator | Read + Bash | Read 3 files, no agent |
| Graph cross-reference analysis | Pathfinder | Neo4j Cypher | Agent↔protocol↔routing integrity |
| Semantic coverage scoring | Pathfinder | Qdrant search | Domain similarity analysis |
| Architecture classification | Pathfinder | Reasoning | Archetype detection |
| Domain task execution | Specialized agent | Per domain | engineer, data-architect, etc. |

**Rule:** Coordinator handles file I/O + simple logic. Pathfinder handles graph + semantic + reasoning. Specialized agents handle domain expertise.
