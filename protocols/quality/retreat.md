# Retreat Protocol

## Overview

Meta-protocol for deep self-improvement cycles. Orchestrates repeated rounds of meditation → yoga →
self-healing to systematically identify and resolve infrastructure issues. Each cycle builds on the
previous, with escalating intensity and scope. Retreat is the highest-level introspective operation:
it runs multiple passes until the system reaches health thresholds or item count reaches zero.

## Triggers

- `/retreat [N]` — start N-cycle retreat (default: 10 cycles)
- `/retreat --resume` — resume a paused retreat from its last checkpoint

---

## Configuration

| Parameter | Default | Range |
|-----------|---------|-------|
| `cycles` | 10 | 1–20 |
| `meditation_intensity` | escalating | quick (cycles 1–7), deep (8–9), full (10) |
| `healing_scope` | escalating | P0-P2 (cycles 1–7), P0-P3 (cycles 8–9), P0-P5 (cycle 10) |
| `state_file` | `docs/self-architecture/retreat-state.json` | — |
| `report_file` | `docs/self-architecture/retreat-report.md` | — |

---

## Exit Conditions

Retreat ends early if ANY of the following conditions is met (checked after every cycle):

1. **Integrity threshold:** `integrity_score >= 0.80`
2. **Flexibility threshold:** `flexibility_score >= 80%`
3. **Diminishing returns:** fewer than 2 items resolved in 3 consecutive cycles
4. **Clean state:** `items_remaining == 0`
5. **Safety cap:** 20 cycles maximum, regardless of user request

When an exit condition is met: log exit reason → generate report → set `status: "completed"`.

---

## Cycle Structure

For each cycle `i = 1..N`:

### Step 1: Meditation

Intensity escalates with cycle number:
- Cycles 1–7 → `quick`
- Cycles 8–9 → `deep`
- Cycle 10 → `full`

Execute via `/meditate {intensity}`. Capture:
- `integrity_score` (overall)
- `findings_count` (total items found)
- `recommendations[]` (passed to self-healing in Step 3)

### Step 2: Yoga

```bash
python3 memory/scripts/yoga.py --json
```

Capture:
- `flexibility_score` (percentage of FLOWING poses)
- `tension_points[]` (PARTIAL/BLOCKED pose findings)
- Compare with previous cycle's score to detect improvement or regression

### Step 3: Self-Healing

Run `/heal` with scope escalating by cycle:
- Cycles 1–7: `--max-priority P2` (critical + high)
- Cycles 8–9: `--max-priority P3` (including medium)
- Cycle 10: `--max-priority P5` (all priorities)

Each cycle's self-healing processes ONLY findings from that cycle's meditation and yoga output.
It does NOT re-process items already repaired in prior cycles (cross-session dedup in self-healing Phase 1 handles this).

Capture:
- `items_resolved` (VERIFIED count)
- `items_remaining` (failed + deferred)
- `items_failed` (FAILED verification count)

### Step 4: Checkpoint

Write state to `docs/self-architecture/retreat-state.json` immediately after Step 3:

```json
{
  "status": "active",
  "cycle_current": 3,
  "cycle_total": 10,
  "started_at": "2026-03-03T20:00:00Z",
  "last_checkpoint": "2026-03-03T20:45:00Z",
  "exit_reason": null,
  "cycles": [
    {
      "cycle": 1,
      "meditation_intensity": "quick",
      "integrity_score": 0.60,
      "flexibility_score": 67,
      "items_resolved": 5,
      "items_remaining": 12,
      "items_failed": 1,
      "timestamp": "2026-03-03T20:15:00Z"
    }
  ]
}
```

### Step 5: Check Exit Conditions

Evaluate all five exit conditions. If any met:
1. Set `exit_reason` in state file
2. Set `status: "completed"`
3. Proceed directly to report generation

---

## Session Persistence

- State file is written after EVERY cycle checkpoint (Step 4). No cycle data is lost on interruption.
- **Status values:** `active` | `paused` | `completed` | `aborted`
- **Resume:** Read state file → continue from `cycle_current + 1`. All prior cycle data is preserved.
- **Session boundary:** If the coordinator session ends mid-retreat → state is set to `paused` before session lock is removed.
- **Session start detection:** If `retreat-state.json` exists with `status: "active"` or `status: "paused"`:
  - Inform user: "Retreat cycle {N}/{total} paused. Run `/retreat --resume` to continue."
  - Do NOT auto-resume — always wait for explicit user confirmation.

---

## Report

Generated at retreat completion (including early exit). Written to `docs/self-architecture/retreat-report.md`.

### Report Contents

**1. Header**
- Start/end timestamps
- Total cycles completed vs. planned
- Exit reason (threshold met | clean state | diminishing returns | safety cap | user abort)

**2. Trend table**

```
| Cycle | Meditation | Integrity | Flexibility | Resolved | Remaining |
|-------|-----------|-----------|-------------|----------|-----------|
| 1     | quick     | 0.60      | 67%         | 5        | 12        |
| 2     | quick     | 0.63      | 67%         | 3        | 9         |
| ...   |           |           |             |          |           |
```

**3. ASCII trend charts** (integrity and flexibility over cycles)

```
Integrity  0.60 ████████████░░░░░░░░ 0.80
           0.63 █████████████░░░░░░░ 0.80
           0.68 ██████████████░░░░░░ 0.80
```

Each bar fills proportionally from 0.0 to target threshold (0.80 integrity, 80% flexibility).

**4. Persistent issues**

Items that survived all cycles without being resolved. These require either:
- Manual intervention by the user
- A full `build-up.md` path (if they are behavioral, not mechanical)

**5. Evolution summary**

- Integrity delta: start → end
- Flexibility delta: start → end
- Total items resolved across all cycles
- Total items failed (unresolvable by automation)

---

## Rules

1. Max 1 retreat active at a time — if `retreat-state.json` has `status: "active"`, reject new `/retreat` command
2. Meditation, yoga, and self-healing run SEQUENTIALLY within each cycle — never parallel
3. Retreat does NOT bypass build-up for behavioral changes — behavioral findings go to Hook 1
4. State file is authoritative — `status: "paused"` means coordinator does not auto-resume
5. Retreat report is generated even on early exit (all exit conditions trigger report)
6. If meditation or yoga fails in a cycle → log the failure in the cycle record, skip self-healing for that cycle, proceed to next cycle
7. Safety cap: 20 cycles maximum regardless of user request (Rule 5 of exit conditions)
8. Each cycle's self-healing processes only NEW findings from that cycle's meditation + yoga output
9. Cycle data is never deleted — all cycles retained in state file for report generation
10. On aborted retreat (user cancels mid-cycle): complete current phase, then checkpoint with `status: "aborted"`

---

## Integration

| System | Integration Point |
|--------|------------------|
| `meditation.md` | Retreat calls meditation with escalating intensity (Step 1) |
| `yoga.md` | Retreat runs yoga between meditation and healing (Step 2) |
| `self-healing.md` | Retreat triggers healing with escalating scope (Step 3) |
| `evolution.md` | Behavioral findings routed to Hook 1, not self-healing |
| `CLAUDE.md` | Session start checks for paused retreat (Step 9.5 analog) |
| `dispatcher.md` | `/retreat` command routing (T4 — meta-orchestration task) |

---

## Examples

### Example 1: 3-cycle retreat reaches integrity threshold

User runs `/retreat 3`. Cycle 1: integrity 0.64, 5 items fixed. Cycle 2: integrity 0.75, 3 items fixed. Cycle 3: integrity 0.82 — exit condition 1 met. Retreat ends after cycle 3. Report generated with exit reason "integrity_threshold".

### Example 2: Resume after session boundary

User starts `/retreat 10`. After cycle 4 the session ends. State file shows `status: "paused"`, `cycle_current: 4`. Next session: coordinator informs user "Retreat cycle 4/10 paused. Run `/retreat --resume` to continue." User runs `/retreat --resume`. Coordinator reads state file, resumes from cycle 5.

---

## See Also

- `protocols/core/meditation.md` — introspection engine (Step 1 of each cycle)
- `protocols/quality/yoga.md` — pipeline health check (Step 2 of each cycle)
- `protocols/quality/self-healing.md` — repair executor (Step 3 of each cycle)
- `protocols/core/evolution.md` — behavioral change pipeline (for rejected items)
