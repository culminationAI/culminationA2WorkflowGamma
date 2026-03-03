# Gap Analysis Protocol

## Overview

Permanent analysis capability. Detects gaps between what a task requires and what the system can currently deliver. Runs at two intensities:

- **Lightweight** — every session start, no subagent dispatch, ~30 seconds
- **Deep** — triggered by complex tasks or explicitly requested, dispatches pathfinder in self-explore mode

Results are logged to `docs/self-architecture/gap-analysis-log.md` and stored in memory after every scan.

## Triggers

| Trigger | Intensity |
|---------|-----------|
| Session start (step 5, after memory load) | Lightweight |
| Coordinator detects task exceeding current capability | Deep |
| User requests `/gap-analysis` | Deep |
| 2+ consecutive T4+ task failures in same domain | Deep |

## Lightweight Scan

No subagents. Reads three sources, produces one paragraph.

**Steps:**
1. Read `docs/self-architecture/capability-map.md`
   - If missing → skip, schedule a deep scan for next opportunity
2. Read `docs/self-architecture/build-registry.json` — check active build TTLs for expiry warnings
2.5. Protocol TTL check (Neo4j):
   ```cypher
   MATCH (p:Protocol)
   WHERE p.last_triggered IS NULL
      OR date(p.last_triggered) + duration({days: p.ttl_days}) < date()
   RETURN p.name, p.category, p.ttl_days, p.last_triggered
   ORDER BY p.category, p.name
   ```
   - If stale protocols found → include count in output paragraph: "N protocols stale (never triggered or TTL expired)"
   - Stale core protocols (ttl_days=30) are higher priority than quality (ttl_days=60)
3. Search memory: `"gap analysis blocker capability"` `--limit 5`
4. Output: 1-paragraph status — one of:
   - No gaps detected since last analysis
   - N gaps found in last deep scan (list domains)
   - Build TTL warnings (list expiring builds)

## Deep Scan

Dispatches pathfinder. Produces scored gap report.

### Parallel Mode (T3+ trigger)

When triggered by dispatcher's parallel gap-check (not session start, not explicit `/gap-analysis`):

1. If `capability-map.md` exists and is fresh (<24h) → skip Step 1 (self-explore), run Steps 2-4 only
2. If `capability-map.md` stale or missing → run full Steps 1-4 with timeout of 60 seconds
3. Output includes additional `parallel_context` field:
   ```json
   {
     "parallel_context": {
       "triggered_by": "task summary or ID",
       "main_task_running": true,
       "interrupt_recommended": false
     }
   }
   ```
4. If any structural gap has severity >= high → set `interrupt_recommended: true`
5. Coordinator reads `interrupt_recommended` to decide on user notification

### Step 1: Explore

Dispatch pathfinder in self-explore mode → produce or refresh `docs/self-architecture/capability-map.md`.

### Step 2: Decompose

Break the task into a list of domain capabilities required. Each capability becomes a scored requirement.

### Step 3: Score

Score each requirement across 5 dimensions (0.0–1.0):

| Dimension | What it checks | 1.0 | 0.5 | 0.0 |
|-----------|---------------|-----|-----|-----|
| `AGENT_COVERAGE` | Agent in `.claude/agents/` covers this domain | covered | partial | missing |
| `PROTOCOL_COVERAGE` | Protocol in `protocols/` guides this workflow | exists | partial | missing |
| `MEMORY_COVERAGE` | Memory has relevant context (search by keywords) | >5 results | 1–5 results | empty |
| `MCP_COVERAGE` | Required tools available in active MCP profile | active | in full profile | not configured |
| `KNOWLEDGE_COVERAGE` | System knows enough about domain (memory + `docs/tech/`) | sufficient | partial | insufficient |

### Step 4: Aggregate

- Per-requirement score = average of its 5 dimension scores
- Overall gap score = average of all per-requirement scores

## Thresholds

| Overall score | Interpretation |
|--------------|----------------|
| > 0.8 | No structural gap — knowledge strengthening may help |
| 0.5–0.8 | Partial gap — build recommended |
| < 0.5 | Significant gap — build required |

## Gap Classification

Two gap types, detected per requirement:

**KNOWLEDGE gap** — MEMORY or KNOWLEDGE < 0.5, but AGENT + PROTOCOL + MCP all >= 0.5
→ Action: strengthen memory (dispatch researchers, web search, extract knowledge). Do NOT create a build.

**STRUCTURAL gap** — AGENT or PROTOCOL or MCP < 0.5
→ Action: create build (see `protocols/core/self-build-up.md`). Check buffered builds first.

## Buffered Build Check

Before recommending build creation, check `build-registry.json` for buffered builds:

1. Match gap against each buffered build's `what_task` field
2. Match gap against `components.agents[].description` in each buffered build
3. If match found → recommend **reactivation** of that build (provide build ID)
4. Reactivation is always preferred over creating a new build

## Protocol TTL

Protocol nodes in Neo4j carry `ttl_days`, `last_triggered`, and `category` properties. TTL tracks whether protocols are actively used or going stale.

### TTL Defaults

| Category | TTL (days) | Protocols |
|----------|-----------|-----------|
| core | 30 | dispatcher, evolution, build-up, etc. |
| agents | 45 | inter-agent-exchange, knowledge-sharing, etc. |
| knowledge | 45 | memory, exploration, context-engineering |
| quality | 60 | yoga, self-healing, retreat, testing, etc. |
| project | 60 | monorepo-orchestration, workflow-qa |

### Updating last_triggered

When a protocol is loaded and used during dispatch (T3+ tasks), coordinator SHOULD update:
```cypher
MATCH (p:Protocol {name: $name}) SET p.last_triggered = date()
```

This is a SHOULD (not MUST) — lightweight overhead, best-effort.

### Stale Protocol Actions

- **Never triggered** (last_triggered IS NULL): Informational only — new protocols haven't been exercised yet
- **TTL expired**: Include in gap-analysis output. If core protocol is stale → flag as priority.
- **No auto-action**: Stale protocols are reported but never auto-deactivated or deleted

## Available Spec Check

Before recommending build creation, also check `spec-registry.json` for available specs:

1. Coordinator reads `docs/self-architecture/spec-registry.json` (Read)
2. Match gap against each available spec's `description` and `definition` keywords
3. If matching specs found → recommend **spec assembly** (compose a new build from existing specs)
4. If matching spec + no other gaps → recommend **standalone spec activation**
5. Spec reuse is always preferred over creating new specs

Output field: `"available_specs_matching": ["spec-id-1"]`

## Severity Mapping

Computed per requirement from its average score:

| Avg score | Severity | Meaning |
|-----------|----------|---------|
| >= 0.8 | none | No action needed |
| 0.6 – 0.8 | low | Can probably work around it |
| 0.4 – 0.6 | medium | Build recommended |
| 0.2 – 0.4 | high | Build required |
| < 0.2 | critical | Multiple fundamental capabilities missing |

## Output Format

After every scan, append a JSON entry to `docs/self-architecture/gap-analysis-log.md`:

```json
{
  "scan_type": "lightweight|deep",
  "timestamp": "ISO8601",
  "overall_score": 0.72,
  "gaps": [
    {
      "requirement": "description of what's needed",
      "scores": {
        "agent": 1.0,
        "protocol": 0.5,
        "memory": 0.0,
        "mcp": 1.0,
        "knowledge": 0.5
      },
      "classification": "KNOWLEDGE|STRUCTURAL",
      "severity": "low|medium|high|critical",
      "recommendation": "strengthen_memory|create_build|reactivate_build:{id}"
    }
  ],
  "active_builds": ["build-id"],
  "buffered_builds_relevant": ["build-id"],
  "available_specs_matching": ["spec-id"]
}
```

Lightweight scan entries omit `gaps` array (no per-requirement analysis). They include only `scan_type`, `timestamp`, `overall_score` (from last deep scan), and a `status` string.

## Predictive Analysis

Runs as an OPTIONAL extension to deep scan. Requires `docs/self-architecture/request-history.json` with >= 10 entries.

### Phase Detection

Coordinator classifies current project phase from recent request history (Read + arithmetic — no subagent needed).

**Process:**
1. Coordinator reads `docs/self-architecture/request-history.json` (Read)
2. Extract `verb` and `phase_hint` from last 20 entries
3. Count verbs by phase category using verb mapping table
4. If >= 60% of entries map to one phase → that's the current phase. Otherwise → MIXED.

**Verb → Phase mapping:**

| Phase | Verbs (>= 60% threshold) |
|-------|-------------------------|
| DESIGN | plan, design, architect, research, define, analyze, review, explore, spec |
| IMPLEMENTATION | write, create, build, implement, add, code, develop, integrate, refactor |
| TESTING | test, verify, fix, debug, audit, check, validate, benchmark |
| DEPLOYMENT | deploy, configure, optimize, scale, monitor, setup, migrate, release |
| MIXED | no dominant pattern (default) |

### Domain Trajectory (Pathfinder)

During deep scan, pathfinder performs semantic trajectory analysis — this requires graph/reasoning:

1. **Neo4j:** Query domain-node connections related to recent request domains
2. **Qdrant:** Semantic similarity clustering of task summaries from request-history
3. Identify: dominant domain clusters, emerging domains, declining domains
4. Detect: phase transitions (e.g., DESIGN → IMPLEMENTATION shift over last 10 entries)

### Predicted Needs

Based on detected phase, anticipate capabilities for the NEXT phase:

| Current Phase | Predicted Next | Anticipated Capabilities |
|---------------|---------------|-------------------------|
| DESIGN | IMPLEMENTATION | engineer, data-architect, MCP tools for target stack |
| IMPLEMENTATION | TESTING | testing protocols, engineer (test-writing), CI/CD |
| TESTING | DEPLOYMENT | DevOps protocols, Docker/K8s, monitoring |
| DEPLOYMENT | MAINTENANCE | memory strengthening, documentation updates |
| MIXED | — | no prediction (insufficient signal) |

### Proactive Recommendations

When `predicted_needs` match a buffered build or available spec:
1. Coordinator checks `build-registry.json` and `spec-registry.json` (Read + keyword match)
2. If match found → include in gap analysis output: "Buffered build {id} / available spec {id} matches predicted need for {phase}."
3. Coordinator MAY suggest reactivation/activation to user proactively (**never auto-activate** — user decision)
4. Store prediction in memory: `python3 memory/scripts/memory_write.py` with `{type: "gap_analysis", subtype: "prediction"}`

### Predictive Output

Add to gap analysis log entry:

```json
{
  "predictive": {
    "current_phase": "IMPLEMENTATION",
    "phase_confidence": 0.73,
    "predicted_next_phase": "TESTING",
    "predicted_needs": [
      {"capability": "testing protocols", "type": "PROTOCOL", "urgency": "low"},
      {"capability": "CI/CD spec", "type": "SPEC", "urgency": "low"}
    ],
    "builds_matching_prediction": ["build-xyz"],
    "specs_matching_prediction": ["spec-protocol-testing"]
  }
}
```

### Predictive Rules

1. Predictions NEVER trigger build/spec creation — only recommend
2. Phase detection requires >= 10 entries in request-history.json
3. Phase confidence < 0.5 → phase = MIXED, no predictions
4. Predictions logged but NOT acted upon without user acknowledgment
5. Phase detection is coordinator arithmetic (no subagent). Domain trajectory is pathfinder analysis.

## Rules

1. Lightweight scan MUST NOT dispatch subagents — too expensive at session start
2. Deep scan dispatches pathfinder (self-explore mode) ONLY — no other subagents
3. Gap analysis results stored in memory: `{type: "gap_analysis"}` after every scan
4. If a buffered build matches the gap, recommend reactivation — never recommend build creation first
5. Never recommend build creation for KNOWLEDGE-only gaps — strengthen memory instead
6. Log entry appended after EVERY scan (lightweight or deep)
7. Coordinator presents gap findings to user before proceeding with build creation
8. `capability-map.md` missing = schedule deep scan, do NOT block session start

## Integration

| System | Integration point |
|--------|------------------|
| **Dispatcher** | Before T1–T5 classification, check if domain coverage is known low. If so, upgrade task tier or flag gap. |
| **Self Build-Up** | Deep gap analysis is Phase 2 of the self-build-up pipeline. |
| **Session Start** | Lightweight scan is step 5 of coordinator's session start flow (after memory load). |
| **Memory** | All gap analysis results stored with `{type: "gap_analysis"}` metadata. |
| **Protocol TTL** | Lightweight scan Step 2.5 checks Neo4j for stale protocols. Protocols update `last_triggered` on use. |
