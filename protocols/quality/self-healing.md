# Self-Healing Protocol

## Overview

Automated infrastructure repair pipeline. Collects findings from meditation and yoga, classifies them
by category, executes mechanical fixes, and verifies results. Implements evolution.md Hook 7 as a
structured, scriptable pipeline. Self-healing covers data, metadata, graph edges, and indexes only —
behavioral changes are always rejected and routed to build-up.

## Triggers

- `/heal` — explicit user command
- Retreat cycle (automated, invoked per cycle by `retreat.md`)
- Hook 7 delegation from `evolution.md`
- Session start: integrity score < 0.5 in the latest meditation entry

## Relationship to Other Protocols

| Protocol | Relationship |
|----------|-------------|
| `evolution.md` Hook 7 | This protocol IS Hook 7's implementation — structured pipeline |
| `build-up.md` | Behavioral items REJECTED here → routed to build-up |
| `meditation.md` | Primary input: recommendations from Phase 6 |
| `yoga.md` | Secondary input: tension points from PARTIAL/BLOCKED poses |

---

## Phase 1: Collect

1. Read `docs/self-architecture/meditation-log.md` — latest entry only.
   - Extract: `recommendations[]`, `hard_conflicts[]`, `soft_conflicts[]`
   - Record the `meditation_id` (used in memory write and dedup)
2. Read `docs/self-architecture/yoga-report.md` — latest session only.
   - Extract: tension points from poses classified PARTIAL or BLOCKED
3. Merge into a single candidate list. Each item has: description, source (`meditation` | `yoga`), priority (P0-P5 from meditation, or `unknown` for yoga items).
4. **Deduplicate within run:** Remove exact-match duplicates. For near-duplicates (word overlap > 80%), keep the higher-priority entry.
5. **Cross-session dedup:** Search memory for `{type: "repair"}` records:
   ```bash
   python3 memory/scripts/memory_search.py "repair self_healing" --limit 20
   ```
   Skip any item whose description closely matches an already-fixed item (overlap > 80%).

**Output:** Deduplicated candidate list with priority + source annotations.

---

## Phase 2: Classify

Keyword matching assigns each item to one of five categories:

| Category | Keywords | Executor |
|----------|----------|----------|
| `version_sync` | version, VERSION node, capability-map version, workflow_version | self_healing.py |
| `graph_repair` | edge, OWNS_SPEC, IMPLEMENTS, GOVERNS, phantom node, topology | self_healing.py |
| `memory_cleanup` | stale record, _source tag, untagged, supersede, type metadata | self_healing.py |
| `infra_repair` | missing file, missing directory, evolve/, request-history | self_healing.py |
| `index_repair` | CLAUDE.md index, README.md, spec-registry, ghost entries | protocol-manager |

**Behavioral filter (applied before classification):**
Items containing any of the following phrases → REJECT → route to build-up pipeline, do not process further:
- "MUST/MUST NOT rule change"
- "routing change"
- "dispatch behavioral"
- "priority rule"
- "ordering" or "precedence" (in the context of protocol rules)

**Security gate** (mirrors `build-up.md` Step 8):
- MUST NOT modify protected files: `build-up.md`, `security-logging.md`, `research_validate.py`, `memory_write.py`
- MUST NOT weaken any MUST/MUST NOT rule
- MUST NOT change behavioral rules — only data, metadata, graph edges, and indexes are in scope

**Priority scope:** Default run processes P0-P2 only. Use `--max-priority P5` to include P3-P5.

**Output:** Classified list with category + executor assigned. Rejected items logged separately.

---

## Phase 3: Execute

Items are sorted: P0 first, then P1, then P2. Within the same priority, batch by category.

### Path A — Automated (self_healing.py)

Handles: `version_sync`, `graph_repair`, `memory_cleanup`, `infra_repair`

```bash
python3 memory/scripts/self_healing.py
```

- Each repair is atomic: one Cypher query, one file write, one memory upsert
- Timeout: 10 seconds per item
- On timeout: log failure, skip item, continue

### Path B — Subagent

| Category | Subagent | Notes |
|----------|----------|-------|
| `index_repair` | protocol-manager | CLAUDE.md table + README.md updates |
| Failed auto-repairs | engineer | Items where Path A returned FAILED after timeout |

Timeout: 60 seconds for subagent repairs.

**Hard cap:** Max 20 items per healing session. Items beyond the cap are deferred to next run.

---

## Phase 4: Verify

Each fix is verified immediately after execution. Verification method by category:

| Category | Verification Method | Pass Condition |
|----------|---------------------|----------------|
| `version_sync` | Re-read Neo4j VERSION node + capability-map header | Values match |
| `graph_repair` | Re-run MATCH query for the specific edge/node | Relationship exists |
| `memory_cleanup` | Re-query Qdrant for the record | Payload updated |
| `infra_repair` | `os.path.exists()` on created path | Path present |
| `index_repair` | Read CLAUDE.md/README.md, confirm entry present | Entry visible |

**Outcome codes:** `VERIFIED` | `FAILED` | `PARTIAL`

Failed verifications are logged but NOT retried in the same session. They are flagged for manual review.

---

## Phase 5: Store

After all repairs, write a single memory record:

```json
{
  "text": "Self-healing run: {N} items fixed, {M} failed. Categories: {list}. Source: {meditation_id}",
  "agent_id": "coordinator",
  "metadata": {
    "type": "repair",
    "subtype": "self_healing",
    "items_fixed": N,
    "items_failed": M,
    "categories": ["version_sync", "graph_repair"],
    "source_meditation_id": "{meditation_id}",
    "_source": "_follower_"
  }
}
```

Update session variables:
```
_repairs_this_session += N
_repair_log.append({
  "timestamp": "ISO8601",
  "categories": [...],
  "items_fixed": N,
  "items_failed": M,
  "verified": true
})
```

**NOT a version bump** — self-healing restores consistency, it does not evolve behavior.

---

## Automation

```bash
# Full auto-heal (P0-P2, all categories)
python3 memory/scripts/self_healing.py

# Single category only
python3 memory/scripts/self_healing.py --category version_sync

# Preview without executing (dry run)
python3 memory/scripts/self_healing.py --dry-run

# Machine-readable JSON output
python3 memory/scripts/self_healing.py --json

# Extend scope to all priorities
python3 memory/scripts/self_healing.py --max-priority P5
```

---

## Rules

1. NON-BLOCKING — does not preempt Hook 1 corrections; may run between tasks
2. No concurrent execution with meditation or yoga (both are introspective; run sequentially)
3. No modifications to protected files (see security gate in Phase 2)
4. No behavioral changes — data, metadata, graph edges, and indexes ONLY
5. Verification is MANDATORY for every executed fix — no unverified repairs
6. Cross-session dedup (Phase 1, step 5) prevents duplicate repairs across runs
7. Items failing the behavioral filter → build-up pipeline, NOT self-healing
8. Max 20 items per healing session; extras deferred, not dropped
9. Failed verifications are logged; manual review required before retry
10. All runs stored to memory with `{type: "repair", subtype: "self_healing"}`

---

## Examples

### Example 1: Version sync after meditation detects mismatch

Meditation finds: "Neo4j VERSION node shows 2.40, capability-map header shows 2.45."

Phase 1 extracts recommendation. Phase 2 classifies as `version_sync` (keyword: "version"). Phase 3 runs `self_healing.py --category version_sync`. Cypher: `MATCH (v:VERSION) SET v.value = "2.45"`. Phase 4 re-reads Neo4j — values match → VERIFIED. Phase 5 stores repair record.

### Example 2: Missing graph edge flagged by yoga

Yoga reports PARTIAL on Pose 6: "Hook 7 invocation logic is missing — no IMPLEMENTS edge from repair_pipeline to evolution." Phase 2 classifies as `graph_repair`. Phase 3 runs Cypher:
`MATCH (a:Protocol {name:"self-healing"}), (b:Protocol {name:"evolution"}) CREATE (a)-[:IMPLEMENTS]->(b)`. Phase 4 confirms edge exists. VERIFIED.

---

## See Also

- `protocols/core/evolution.md` — Hook 7 (this protocol implements it)
- `protocols/core/meditation.md` — primary input source for repair candidates
- `protocols/quality/yoga.md` — secondary input source (tension points)
- `protocols/core/build-up.md` — destination for rejected behavioral items
- `protocols/quality/retreat.md` — orchestrates repeated heal cycles
