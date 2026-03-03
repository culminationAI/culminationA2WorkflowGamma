# Yoga Protocol — End-to-End Pipeline Health Checking

## Overview

The system is a body. Protocols are joints. Scripts are muscles. Pipelines are energy channels.

Static analysis tells you whether a joint exists. Yoga tells you whether energy flows through it.

A yoga session executes each pipeline with a real test payload and observes where flow stops. Unlike gap-analysis (static capability scoring), meditation (structural introspection), or testing (build-up QA), yoga is dynamic: it runs the actual path from input to output and classifies each pipeline as flowing, partial, blocked, or stub.

If a pose flows end-to-end — the channel is open. If it stops — yoga locates the exact tension point.

---

## Vocabulary

| Term | Technical Meaning |
|------|------------------|
| Pose (asana) | Single pipeline test — one end-to-end execution trace |
| Flow | Data/control successfully traverses the full pipeline |
| Blockage | Pipeline stops at a specific step — step exists but fails |
| Stub | Step exists only on paper — protocol describes it, no code implements it |
| Tension point | Exact file + line or step where flow interrupts |
| Flexibility score | Percentage of pipelines FLOWING (FLOWING / total) |
| Yoga session | One complete run of all poses |

---

## Triggers

- `/yoga` — full session (all poses)
- `/yoga [pose-name]` — single pose
- After major system changes — recommended
- Session start if last yoga > 5 sessions ago — coordinator suggests

---

## Execution Model

Each pose follows four steps:

1. **Intention** — state the pipeline being tested
2. **Execution** — run each step in sequence
3. **Observation** — record what actually happened at each step
4. **Finding** — classify the pose

Finding classifications:

| Classification | Meaning |
|---------------|---------|
| FLOWING | All steps completed successfully |
| PARTIAL | Some steps passed, pipeline degraded but not dead |
| BLOCKED | Pipeline stops at a specific step (code exists, fails at runtime) |
| STUB | A step is design-only — protocol mentions it, no implementation exists |

---

## Poses

### Pose 1: Pranayama (Memory Breath)
**Pipeline:** Memory Write → Embed → Qdrant Store → Search → Retrieve

1. Generate test record: `{"text": "_yoga_test_ memory breath {timestamp}", "user_id": "yoga", "agent_id": "coordinator"}`
2. Run: `python3 memory/scripts/memory_write.py '<record>'`
3. Observe: Qdrant upsert confirmed in output
4. Run: `python3 memory/scripts/memory_search.py "_yoga_test_ memory breath" --limit 1`
5. Observe: test record returned with score > 0.7
6. Run: `python3 memory/scripts/memory_search.py "_yoga_test_" --graph`
7. Observe: graph search returns results or falls back gracefully
8. Cleanup: delete test record from Qdrant

**Tension points:** Ollama embedding service reachable, Qdrant collection config + named vectors, Neo4j fulltext index, graph search fallback behavior

---

### Pose 2: Tadasana (Standing — Session Start)
**Pipeline:** Session Start sequence (CLAUDE.md Steps 1–9.5)

1. Check `_WORKFLOW_NEEDS_INIT` absent in CLAUDE.md
2. Run `python3 memory/scripts/workflow_update.py --check`
3. Run `python3 memory/scripts/memory_search.py "active tasks blockers" --limit 5`
4. Check `docs/self-architecture/capability-map.md` exists and has a freshness timestamp
5. Check `docs/self-architecture/build-registry.json` TTL fields are present and parseable
6. Test session lock creation: `touch .session_lock && ls -la .session_lock`
7. Ping exchange: `curl -s http://localhost:8888/`
8. Check pending messages: `curl -s 'http://localhost:8888/messages?to=falkvelt&status=pending'`
9. Check `docs/self-architecture/meditation-log.md` for unresolved P0-P2 items
10. Cleanup: `rm -f .session_lock`

**Tension points:** workflow_update.py completeness, TTL parsing logic, session lock write permissions, exchange container running

---

### Pose 3: Virabhadrasana (Warrior — Correction Pipeline)
**Pipeline:** Correction → Build-up quick path (protocols/core/build-up.md)

1. Simulate synthetic correction: "User said X, system did Y instead"
2. Classify: type=correction, complexity=simple → quick path
3. Dedup check: `python3 memory/scripts/memory_search.py "synthetic correction yoga test" --limit 3`
4. Write test correction: `python3 memory/scripts/memory_write.py '[{"text": "_yoga_test_ correction record", "user_id": "yoga", "agent_id": "coordinator"}]'`
5. Verify retrievable: `python3 memory/scripts/memory_search.py "_yoga_test_ correction" --limit 1`
6. Identify STUB steps: clone (step 3), automated test (step 5), security gate (step 8), version bump (step 10), repo sync (step 11)
7. Cleanup test record

**Tension points:** No auto-detection logic for corrections, clone references missing `evolve/` directory, testing framework absent, version bump requires manual CLAUDE.md edit

---

### Pose 4: Natarajasana (Dancer — Agent Dispatch)
**Pipeline:** T-level classification → Route → Execute → Integrate

1. Take test request: "Write a utility script"
2. Classify: verb "write" → T3
3. Identify target agent: engineer
4. Check `.claude/agents/engineer.md` exists and is readable
5. Check `protocols/core/dispatcher.md` routing rules cover this case
6. Check if any programmatic dispatch exists (search for subagent invocation code in workspace)
7. Check if post-dispatch verification is automated or manual

**Tension points:** No dispatcher code — routing is protocol-only (design), T2+ routing is coordinator-manual with no invocation framework, no automated result integration

---

### Pose 5: Savasana (Corpse — Exchange Pipeline)
**Pipeline:** Message → Watcher → Process → Response

1. Ping exchange health: `curl -s http://localhost:8888/`
2. POST test message: `curl -s -X POST 'http://localhost:8888/messages' -H 'Content-Type: application/json' -d '{"from_agent":"yoga","to_agent":"falkvelt","type":"task","subject":"yoga test","body":"_yoga_test_ exchange pipeline"}'`
3. Verify HTTP 200 + message ID in response
4. GET pending: `curl -s 'http://localhost:8888/messages?to=falkvelt&status=pending'` — test message visible?
5. Check watcher process running: `ps aux | grep watcher`
6. Check session lock handling in watcher: does watcher pause when `.session_lock` exists?
7. Cleanup: `curl -s -X PATCH 'http://localhost:8888/messages/{id}' -d '{"status":"read"}'`

**Tension points:** Exchange container status (workflow-exchange), watcher process may not be running, session_lock dependency creates race condition

---

### Pose 6: Surya Namaskar (Sun Salutation — Evolution Cycle)
**Pipeline:** Correction → Session-End Review → Meditation → Repair

1. Check session variables concept: is there any persistence mechanism beyond in-prompt tracking?
2. Check Hook 1 enforcement code: does any script enforce correction capture before proceeding?
3. Check Hook 2 session-end: is there an implementation of the session-end review step?
4. Check `docs/self-architecture/meditation-log.md` — entries present with recommendations?
5. Extract P0-P2 items from latest meditation entry
6. Check `/repair` handler: is it defined in dispatcher.md?
7. Check Hook 7 invocation logic: is repair queue processing automated or manual?

**Tension points:** Session variables are in-memory only (lost on context reset), no auto-detection for corrections, Hook 2 not implemented as code, `/repair` is coordinator-manual only

---

## Output Format

Report saved to: `docs/self-architecture/yoga-report.md`

```markdown
# Yoga Session Report
Session ID: yoga-{timestamp}
Date: {date}
Flexibility Score: {n}/{total} ({pct}%) FLOWING

## Summary Table
| Pose | Pipeline | Result | Tension Point |
|------|----------|--------|--------------|
| Pranayama | Memory Breath | FLOWING | — |
| Tadasana | Session Start | PARTIAL | TTL logic |
| ... | ... | ... | ... |

## Detailed Findings
[Per pose: steps executed, observations, exact tension point if not FLOWING]

## Comparison with Previous Session
[Delta in flexibility score, new blockages, resolved blockages]

## Priority Repair List
[Ordered by severity: BLOCKED > STUB > PARTIAL]
```

JSON record stored to memory:
```json
{
  "type": "yoga",
  "subtype": "session_complete",
  "session_id": "yoga-{timestamp}",
  "flexibility_score": 0.67,
  "results": {"pranayama": "FLOWING", "tadasana": "PARTIAL", ...}
}
```

---

## Automation

Script: `memory/scripts/yoga.py`

Automates poses that are infrastructure-testable:
- **Pose 1 (Pranayama)** — fully automatable: write, embed, search, cleanup
- **Pose 2 (Tadasana)** — partially automatable: file checks, lock test, exchange ping
- **Pose 5 (Savasana)** — fully automatable: HTTP calls, message lifecycle

Poses 3, 4, 6 require coordinator judgment — protocol describes them for manual execution.

---

## Integration

| Output | Destination |
|--------|------------|
| Tension points per pose | Feeds meditation Phase 2 (concrete diagnostic data) |
| Repair list | Feeds evolution Hook 7 (repair queue) |
| Flexibility score | Written to `docs/self-architecture/capability-map.md` |
| Score < 30% | Coordinator warns user and suggests `/repair` |

---

## Rules

1. Cleanup ALL `_yoga_test_` data after each pose — no test pollution in memory
2. Diagnostic only — yoga does NOT modify system state, config, or protocols
3. Not concurrent with meditation — both are introspective, run sequentially
4. Recommended cadence: weekly, or after any major system change
5. Partial runs are valid — poses are independent, run any subset
6. Flexibility score = FLOWING count / total poses
7. No version bumps — yoga is diagnostic, not evolutionary
8. Results stored with `{type: "yoga", subtype: "session_complete"}`
9. Score < 30% → explicitly suggest `/repair` before next work session
10. Any pose may be interrupted — record the interruption point as a tension point

---

## Anti-patterns

- Running yoga every session — weekly cadence is sufficient; daily runs waste time
- Treating yoga as a fix tool — it diagnoses, does not repair; use `/repair` for fixes
- Skipping cleanup — `_yoga_test_` records pollute memory and skew future searches
- Running during active work — resource contention; run between tasks or at session start

---

## See Also

- `protocols/core/gap-analysis.md` — static capability scoring (can we do X?)
- `protocols/core/meditation.md` — structural introspection (is it connected?)
- `protocols/quality/testing.md` — build-up variant testing (does this variant work?)
- `memory/scripts/yoga.py` — automation companion for infrastructure poses
