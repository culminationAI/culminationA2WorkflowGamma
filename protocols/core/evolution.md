# Evolution Protocol

## Overview

Orchestration layer for the coordinator's evolution system. Enforces correction capture, session-end review, adaptive build selection, predictive loop triggers, and post-task verification.

This protocol does NOT replace `build-up.md`, `self-build-up.md`, or `gap-analysis.md` — it enforces and coordinates them.

## Triggers

| Trigger | Hook | Action |
|---------|------|--------|
| User correction detected | Correction Interceptor | FORCE reactive build-up (quick or full path) |
| Session end (bye, context limit, `/review`) | Session-End Review | Audit corrections vs stored build-ups |
| STRUCTURAL gap detected by gap-analysis | Adaptive Orchestrator | Score options → reactivate / assemble / create |
| Every 10th T3+ task (request-history count % 10 == 0) | Predictive Loop | Run predictive analysis |
| Completed task (before closing todo) | Post-Task Hook | Verify correction capture + log gaps |
| Build-up stored (universal correction) | Knowledge Export | Send digest to other agents |
| Meditation repair recommendations (P0-P2) | Repair Pipeline | Collect → classify → execute → verify → store |

## Hook 1: Correction Interceptor (BLOCKING)

**When:** Coordinator recognizes it was wrong — user says "no", "that's wrong", corrects output, or provides the right answer.

**Process:**
1. STOP current work. Do not proceed to next task.
2. Classify correction per `build-up.md` Step 1:
   - `correction` — user pointed out wrong behavior
   - `routing` — task sent to wrong agent or not delegated
   - `workflow` — process improvement
   - `architectural` — structural change
3. Assess complexity: simple → quick path, complex → full path.
4. Execute the appropriate path from `build-up.md`:
   - **Quick path:** detect → store → verify on 2-3 mental test cases → apply rule
   - **Full path:** Steps 1-11 (detect → plan → clone → test → evaluate → transform → store → version bump → sync)
5. Confirm storage: `python3 memory/scripts/memory_search.py "build_up correction" --limit 1`
6. Update session state:
   ```
   _corrections_this_session += 1
   _correction_log.append({
     "timestamp": "ISO8601",
     "summary": "what was corrected",
     "stored": true,
     "build_up_type": "quick|full"
   })
   ```
7. Only THEN resume normal work.

**Enforcement:** If coordinator attempts to respond to a new user message while a correction is unprocessed → self-check MUST trigger this hook first.

## Hook 2: Session-End Review (MANDATORY)

**When:** User says goodbye, signals session end, types `/review`, or context approaches limit (>80%).

**Process:**
1. Count corrections this session: `len(_correction_log)`.
2. Search memory for build-up records created today:
   ```bash
   python3 memory/scripts/memory_search.py "build_up correction" --limit 20
   ```
3. Cross-reference: for each entry in `_correction_log`, verify a matching record exists.
4. Generate report:
   ```
   Session Review:
   - Corrections given: N
   - Build-ups stored: M
   - MISSED: [list of corrections not stored]
   - Gaps detected: K
   - T3+ tasks completed: P
   ```
5. If MISSED > 0: run quick-path build-up for each missed correction NOW.
6. Present report to user.

## Hook 3: Adaptive Evolution Orchestrator

**When:** `gap-analysis.md` deep scan returns a STRUCTURAL gap (any dimension < 0.5).

**Process:**

1. **Collect candidates:**
   - Buffered builds: `build-registry.json` where `state == "buffered"`
   - Available specs: `spec-registry.json` where `state == "AVAILABLE"`
   - New build: always available as fallback

2. **Score each candidate:**

   | Factor | Points | Condition |
   |--------|--------|-----------|
   | Base: Reactivation | +3 | Candidate is a buffered build |
   | Base: Spec assembly | +2 | Candidate uses existing specs |
   | Base: New build | +1 | No existing match |
   | Exact gap match | +2 | Keyword overlap ≥ 80% |
   | Partial gap match | +1 | Keyword overlap 40-79% |
   | Recency bonus | +1 | Buffered build deactivated < 7 days ago |
   | Multi-gap coverage | +1 | Covers 2+ gaps from same scan |

   Keyword extraction: lowercase, split on spaces/hyphens, remove stop words.
   Tie-break: fewer components = simpler = preferred.

3. **Execute selected path:**
   - **Reactivation:** `self-build-up.md` Phase 7 → Reactivation flow
   - **Spec assembly:** `self-build-up.md` Phase 4 (spec_refs pre-filled) → Phase 5 → Phase 6
   - **New build:** `self-build-up.md` Phase 4 (full design) → Phase 5 → Phase 6

4. All paths pass through `build-up.md` Step 8 security gate.
5. All paths end with Phase 6 smoke test.

## Hook 4: Predictive Loop

**When:** After appending to `request-history.json`, if `entries_count % 10 == 0` AND `entries_count >= 10`.

**Process:**
1. Run phase detection from `gap-analysis.md` §Predictive Analysis (coordinator arithmetic, no subagent).
2. If phase confidence ≥ 0.5 and current phase differs from last prediction:
   - Check buffered builds matching predicted next-phase needs.
   - Check available specs matching predicted needs.
   - Inform user: "Prediction: transitioning to {PHASE}. Build {id} / spec {id} may be useful."
3. Store: `{type: "gap_analysis", subtype: "prediction"}`.
4. Do NOT auto-activate. User decides.

## Hook 5: Post-Task Verification

**When:** After EVERY completed task, before marking todo as done.

**Process:**
1. **Correction check:** Was there a user correction during this task?
   - Yes + not in `_correction_log` with `stored: true` → STOP → run Hook 1.
2. **Gap check:** Did the task reveal a capability gap?
   - Yes → append to `_session_gaps`: `{domain, severity, task_id}`.
3. **Request history:** Append entry per `dispatcher.md` §Post-Dispatch Verification.
4. **Predictive trigger:** Check if Hook 4 condition is met.

## Hook 6: Knowledge Export

**When:** After Hook 1 (Correction Interceptor) stores a build-up record.

**Process:**
1. Evaluate applicability: universal or workspace-specific (see `knowledge-sharing.md` §Applicability heuristic).
2. If universal → create knowledge digest → send via exchange `type: "knowledge"` to all known agents.
3. If workspace-specific → skip export.
4. At session end (Hook 2), batch-export all unexported universal corrections as one message.

**Rule:** This hook runs AFTER the build-up is stored locally. Export failure does NOT block the coordinator.

## Hook 7: Repair Pipeline

**When:** Meditation findings contain unresolved P0-P2 infrastructure recommendations, user runs `/repair`, or session-start integrity check finds any dimension < 0.5 in latest meditation.

**Nature:** Infrastructure maintenance — deterministic fixes for version mismatches, missing graph edges, unindexed protocols, stale memory records. NOT behavioral changes. Does NOT route through `build-up.md`.

**Repair Categories:**

| Category | Description | Executor |
|----------|-------------|----------|
| `version_sync` | Synchronize version values across Neo4j, capability-map, memory | engineer |
| `graph_repair` | Fix missing edges, remove phantom nodes, add IMPLEMENTS/GOVERNS | engineer |
| `index_repair` | Update CLAUDE.md protocol index, README.md, spec-registry asymmetry | protocol-manager |
| `memory_cleanup` | Supersede stale records, add missing _source/type metadata | engineer |
| `infra_repair` | Create missing infrastructure files/directories (evolve/, request-history.json) | engineer |

**Process:**
1. **Collect:** Read `docs/self-architecture/meditation-log.md` → extract recommendations from latest session. Or accept manual list via `/repair`.
2. **Classify:** Assign repair category per table above. Verify each item is mechanical (data/metadata/graph/index), not behavioral. If behavioral → reject, route to Hook 1 or Hook 3.
3. **Prioritize:** P0 first, then P1, P2. Within same priority, batch by category for efficiency.
4. **Execute:** Dispatch appropriate subagent per category. Each repair item becomes a specific, atomic action (one Cypher query, one file edit, one memory write).
5. **Verify:** Re-check each repaired item — query Neo4j, re-read file, re-search memory. If verification fails → log failure, do not retry (flag for manual review).
6. **Store:** Record repair batch to memory:
   ```json
   {
     "text": "Repair run: {N} items fixed. Categories: {list}. Source: meditation {id}.",
     "agent_id": "coordinator",
     "metadata": {
       "type": "repair",
       "subtype": "{primary_category}",
       "meditation_id": "{source_meditation_id}",
       "items_fixed": N,
       "items_failed": M,
       "_source": "_follower_"
     }
   }
   ```

**Security Gate (adapted from build-up Step 8):**
- MUST NOT weaken any MUST/MUST NOT rule
- MUST NOT modify protected files (build-up.md, security-logging.md, research_validate.py, memory_write.py)
- MUST NOT change behavioral rules — only data, metadata, graph edges, and indexes
- All repairs logged to memory for traceability

**Key differences from build-up:**
- No variant testing (repairs are deterministic)
- No version bump (restoring consistency, not evolving behavior)
- Batch execution (multiple repairs per run)
- Own pipeline (does not route through build-up.md)

**Rule:** Repair is NON-BLOCKING — coordinator may continue with other tasks between repair items. Repairs do not preempt Hook 1 corrections.

## Session Variables

In-memory only, reset at session start. Not persisted to files.

```
_corrections_this_session: int = 0
_correction_log: list = []       # {timestamp, summary, stored, build_up_type}
_session_gaps: list = []          # {domain, severity, task_id}
_t3plus_count: int = 0
_exported_corrections: list = []  # correction_ids exported this session
_repair_queue: list = []              # {priority, category, description, source_meditation_id}
_repairs_this_session: int = 0
_repair_log: list = []                # {timestamp, category, items_fixed, verified}
```

## Rules

1. Hook 1 is BLOCKING — coordinator MUST NOT proceed until build-up is stored.
2. Hook 2 is MANDATORY — never close a session without review.
3. Hook 3 scoring uses coordinator arithmetic only — no subagent dispatch.
4. Hook 4 is ADVISORY — never auto-activate builds or specs.
5. Hook 5 runs after EVERY task, regardless of tier.
6. This protocol does NOT modify `build-up.md` (protected file) — it orchestrates it.
7. All session variables reset at session start.
8. Keyword matching uses simple word overlap: `|intersection| / |union|`.
9. Hook 6 is NON-BLOCKING — export failure does not stop the coordinator.
10. Hook 7 is NON-BLOCKING — repairs do not preempt Hook 1 corrections.

## Integration

| System | Integration Point |
|--------|------------------|
| `build-up.md` | Hook 1 enforces Steps 1-11; Hook 2 catches missed corrections |
| `self-build-up.md` | Hook 3 orchestrates Phases 4-7 with adaptive selection |
| `gap-analysis.md` | Hook 3 triggered by STRUCTURAL gaps; Hook 4 uses §Predictive |
| `dispatcher.md` | Hook 5 extends Post-Dispatch Verification with correction check |
| `CLAUDE.md` | Session Start initializes variables; Session End triggers Hook 2 |
| `knowledge-sharing.md` | Hook 6 triggers knowledge export; Hook 2 includes batch export |
| `meditation.md` | Hook 7 reads meditation-log.md recommendations as repair input |
