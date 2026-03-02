# Self Build-Up Protocol

## Overview

Meta-cognitive extension to the build-up protocol. Enables the coordinator to detect capability gaps proactively, create temporary architectural enhancements ("builds"), and manage their lifecycle.

Key distinction:
- `protocols/core/build-up.md` handles **REACTIVE** build-up — corrections, routing fixes, rule refinement
- This protocol handles **PROACTIVE** build-up — gap detection, capability extension, build lifecycle

Both share the security gate from `build-up.md` Step 8.

## Triggers

| Trigger | Action |
|---------|--------|
| Complex task arrives where coordinator detects insufficient capability | Deep gap analysis → decision fork |
| Pathfinder self-explore reveals capability gap | Phase 2 (Gap Analysis) |
| 2+ consecutive T4+ task failures in same domain | Deep gap analysis |
| User requests `/evolve` | Full pipeline from Phase 1 |
| Session-start lightweight gap scan finds unresolved gaps | Phase 2 (Gap Analysis) |

## Pipeline

### Phase 1: Explore (Self-Scan)

Two-step process: coordinator collects raw data, pathfinder analyzes.

**Step 1 — Coordinator collects (direct tools):**
1. Glob `.claude/agents/*.md` → Read each → extract YAML frontmatter (name, model, tools, MCP) → agent inventory
2. Glob `protocols/**/*.md` → Read each → extract purpose (first H2) → protocol inventory
3. Read `mcp/mcp.json` + `mcp/mcp-full.json` → active vs available servers
4. Bash `python3 memory/scripts/memory_verify.py --quick` → memory health
5. Read CLAUDE.md → version, rules count, protocol index
6. Package as structured context for pathfinder dispatch

**Step 2 — Pathfinder analyzes:**
1. Receives pre-collected inventories from coordinator
2. **Neo4j:** Cross-reference agents ↔ dispatcher routing entries
3. **Neo4j:** Cross-reference protocols ↔ CLAUDE.md index
4. **Qdrant:** Semantic coverage scoring per domain
5. Identify inconsistencies, gaps, orphaned components
6. Produce or refresh `docs/self-architecture/capability-map.md`

Output: structured capability map covering agents, protocols, MCP, memory state, cross-reference integrity.

### Phase 2: Gap Analysis

Run deep gap analysis (`protocols/core/gap-analysis.md` — Deep Scan):
1. Decompose the triggering task into required domain capabilities
2. Score each capability across 5 dimensions (AGENT, PROTOCOL, MEMORY, MCP, KNOWLEDGE)
3. Classify each gap: KNOWLEDGE vs STRUCTURAL
4. Output: gap report with severity and recommendations, appended to `docs/self-architecture/gap-analysis-log.md`

### Phase 3: Decision Fork

```
IF all gaps == KNOWLEDGE:
  → Strengthen memory path (no build needed)
    1. Dispatch researcher/pathfinder for knowledge acquisition
    2. Store findings: {type: "build_up", subtype: "knowledge_acquisition"}
    3. Search memory to confirm gap closed (re-run lightweight scan)
    4. Proceed with original task

IF any gap == STRUCTURAL:
  → Build path
    1. Present gap analysis summary to user
    2. User approves build creation
    3. Proceed to Phase 4
```

KNOWLEDGE path is always preferred. Do not propose build creation unless a STRUCTURAL gap is confirmed.

### Phase 4: Build Creation

Design build manifest, register it, create component files.

**4a-pre. Spec Check:**
Before designing a new build manifest:
1. Coordinator reads `docs/self-architecture/spec-registry.json` (Read)
2. For each capability needed, coordinator checks if a matching spec exists (Grep spec descriptions)
3. If spec exists (state=AVAILABLE) → reference it by ID in build's `spec_refs`. Do NOT recreate.
4. If spec does NOT exist locally AND storage mode == "repo" (read from `user-identity.md`):
   a. `gh api repos/{repo}/contents/specs/index.json` → read remote spec index
   b. Find matching spec by domain + description
   c. If found → `gh api repos/{repo}/contents/specs/{spec-file}` → download spec
   d. Import into local `spec-registry.json`
   e. Reference by ID (cherry-pick from remote)
5. If spec not found anywhere → create new spec entry in `spec-registry.json`, then reference it.
6. New specs get state=AVAILABLE immediately upon creation.

**4a. Design manifest:**

```json
{
  "id": "build-{YYYY-MM-DD}-{short-descriptor}",
  "created": "ISO8601",
  "why": "Gap description — why this build is needed",
  "what_task": "The specific task that prompted creation",
  "gap_analysis_ref": "timestamp of the triggering gap analysis entry",
  "state": "draft",
  "ttl_sessions": 10,
  "ttl_days": 14,
  "sessions_since_last_use": 0,
  "last_used": null,
  "activated_at": null,
  "deactivated_at": null,
  "smoke_test_results": null,
  "cherry_picked_from": null,
  "spec_refs": [],
  "components": {
    // existing components block stays for backward compatibility
    // but is auto-derived from spec definitions at activation time
    "agents": [
      {"action": "create|modify", "path": ".claude/agents/{name}.md", "description": "..."}
    ],
    "protocols": [
      {"action": "create|modify", "path": "protocols/{dir}/{name}.md", "description": "..."}
    ],
    "claude_md_rules": [
      {
        "action": "add|modify",
        "section": "Subagents — Team",
        "rule_text": "| agent-name | description |",
        "original_text": null
      }
    ],
    "mcp_profile": {
      "action": "switch|add|none",
      "target_profile": null,
      "servers_to_add": []
    },
    "memory_records": [
      {
        "text": "...",
        "metadata": {"type": "build_up", "subtype": "build_context"}
      }
    ]
  },
  "rollback": {
    "agents_to_delete": [],
    "agents_to_restore": [{"path": "...", "backup_path": "..."}],
    "protocols_to_delete": [],
    "protocols_to_restore": [{"path": "...", "backup_path": "..."}],
    "claude_md_rules_to_remove": [],
    "claude_md_rules_to_restore": [{"section": "...", "original_text": "..."}],
    "mcp_profile_to_restore": null
  }
}
```

**4b. Register:** Append build manifest to `docs/self-architecture/build-registry.json`.

**4c. Create component files** (agent `.md`, protocol `.md`) in their normal locations. Set build state: `draft`.

**4d. Backup originals:** For modified files, save current content to `evolve/backup-{date}-{filename}` before any edits. Populate `rollback` fields.

### Phase 5: Build Activation (Security-Gated)

Security gate — imported from `build-up.md` Step 8. All three checks MUST pass:

**5a. Immutable Rule Check:**
Parse all target files for `<!-- IMMUTABLE -->` blocks. If any build component modifies content within an immutable block → **REJECT**. Log: `{type: "security", action: "build_rejected", reason: "immutable_block_violation", build_id: "..."}`.

**5b. Protected File Check:**
Build MUST NOT modify these files (only human edits allowed):
- `protocols/core/build-up.md`
- `protocols/quality/security-logging.md`
- `memory/scripts/research_validate.py`
- `memory/scripts/memory_write.py`

If build targets any protected file → **REJECT**. Log security event.

**5c. Security Weakening Check:**
If build proposes any of the following → **REJECT**:
- Removing or weakening a MUST/MUST NOT rule
- Disabling logging, validation, or security checks
- Expanding agent file access permissions
- Reducing input validation strictness

**5d. Apply (if all checks pass):**
1. Resolve spec references: read each spec's `definition` from `spec-registry.json`
2. For AGENT specs: write agent files to `.claude/agents/`
3. For PROTOCOL specs: write protocol files to `protocols/`
4. For MCP specs: switch/add MCP servers via `python3 mcp/mcp_configure.py`
5. For RULE specs: apply CLAUDE.md rule additions (Edit)
6. Apply inline_overrides (memory_records, additional rules)
7. Update spec states: IN_USE, add build_id to `used_by_builds`
8. Update build manifest: `state → active`, set `activated_at`

### Phase 6: Smoke Test

Run 2–3 targeted tests from `protocols/quality/testing.md` relevant to the build's domain.

**Pass threshold:** 2 of 3 tests must pass.

| Result | Action |
|--------|--------|
| Pass | Build remains active. Store: `{type: "build_up", subtype: "build_activated"}`. Update `smoke_test_results` in manifest. |
| Fail | Execute rollback (see Downgrade process). Build returns to `draft` or is deleted. |

### Phase 7: Lifecycle Management

**State machine:**
```
[DRAFT] --smoke pass--> [ACTIVE] --TTL / inactivity--> [BUFFERED] --30 days--> [ARCHIVED]
                            ^                                |
                            +------ reactivate on demand ----+
```

---

#### Downgrade (ACTIVE → BUFFERED)

**Triggers:**
- TTL expired: `sessions_since_last_use > ttl_sessions` OR `(now - last_used) > ttl_days`
- 5 consecutive sessions without using any build component
- User requests `/deactivate-build {id}`

**Process:**
1. Execute rollback: delete created agents/protocols; restore originals from backup
2. Remove CLAUDE.md entries (subagent table, protocol index)
3. Remove routing entries from `dispatcher.md`
4. Restore MCP profile if it was switched
5. Update manifest: `state → buffered`, set `deactivated_at`
6. Memory records remain (knowledge is permanent)
7. Store: `{type: "build_up", subtype: "build_deactivated", build_id: "..."}`

After rollback:
- For each spec in build's `spec_refs`:
  - Remove this build_id from spec's `used_by_builds`
  - If `used_by_builds` is now empty → set spec state to AVAILABLE
  - If spec is still used by another active build → keep state IN_USE

---

#### Reactivation (BUFFERED → ACTIVE)

**Triggers:**
- Gap analysis recommends `reactivate_build:{id}`
- User requests `/reactivate-build {id}`

**Process:**
1. Read manifest from `build-registry.json`
2. Verify component files exist; regenerate from manifest if missing
3. Re-apply all components (agents, protocols, CLAUDE.md, MCP, memory records)
4. Add routing entries to `dispatcher.md`
5. Reset TTL counters: `sessions_since_last_use → 0`, set new `activated_at`
6. Run smoke tests (Phase 6)
7. Store: `{type: "build_up", subtype: "build_reactivated", build_id: "..."}`

---

#### Archive (BUFFERED → ARCHIVED)

**Triggers:**
- 30 days in buffer without reactivation
- User explicitly archives the build

**Process:**
1. Delete component files (agents, protocols, backups)
2. Update manifest: `state → archived`
3. Keep manifest in `build-registry.json` — WHY/WHAT metadata preserved as institutional memory
4. Store: `{type: "build_up", subtype: "build_archived", build_id: "..."}`

---

#### Cherry-pick

With specs, cherry-pick is trivial:
1. Identify the needed spec ID from the source build's `spec_refs`
2. Create a new build with only that spec in its `spec_refs`
3. Set `cherry_picked_from: "{source-build-id}"` in new build manifest
4. No component duplication — spec is shared by reference
5. Source build remains in its current state (spec is not moved, only shared)

### Standalone Spec Activation

For lightweight build-up where a full build is overkill — activate a single spec without creating a build.

**When:** Gap analysis finds a single-dimension STRUCTURAL gap (e.g., only AGENT < 0.5, all others fine).

**Process:**
1. Find or create the needed spec in `spec-registry.json`
2. Apply spec directly (same as Phase 5d steps 2-5, but for one spec)
3. No build manifest needed — spec tracks its own state
4. Set spec state: IN_USE, `used_by_builds: ["standalone"]`
5. TTL managed on the spec itself: deactivate after 10 sessions without use

**Constraint:** Max 3 standalone specs active simultaneously (see `spec-registry.json` → `max_standalone_specs`).

**Deactivation:** Rollback the single spec's files, set state → AVAILABLE.

## TTL Tracking (Session Start)

At every session start, after the lightweight gap scan, coordinator checks `build-registry.json`:

```python
for build in builds where state == "active":
    if (now - build.last_used) > build.ttl_days:
        trigger downgrade(build.id)
    elif build.sessions_since_last_use > build.ttl_sessions:
        trigger downgrade(build.id)
    elif build.ttl_days - (now - build.last_used) <= 2:
        warn: f"Build {build.id} TTL expiring in ≤2 days"
```

If `build-registry.json` is missing, skip silently and create it on next build creation.

## Rules

1. Max **2 active builds** at once — prevents config explosion and context bloat
2. Security gate from `build-up.md` Step 8 applies to ALL build activations — no exceptions
3. Builds MUST NOT modify protected files (same list as `build-up.md`)
4. Every build MUST have complete rollback instructions before activation
5. KNOWLEDGE path is always preferred over STRUCTURAL when both could work
6. Builds buffered >30 days without reactivation are candidates for archival
7. Lightweight gap analysis at session start MUST complete in <30 seconds (no subagents)
8. Coordinator presents gap findings and build proposal to user before activation — never activate silently
9. Build manifest retains full WHY/WHAT even after archival
10. Memory records from builds persist even after build deactivation — knowledge is permanent

**Note:** Build activations and deactivations do NOT trigger version bumps. Only the reactive build-up protocol (corrections, routing, workflow, architectural changes) bumps the version via Step 10.

## Integration

| System | Integration point |
|--------|------------------|
| **build-up.md** | Shares security gate (Step 8), storage format (Step 9), and trigger #4 (`/evolve` command) |
| **gap-analysis.md** | Phases 1–3 of this protocol run gap analysis. Buffered build check in gap-analysis feeds Phase 3 decision fork. |
| **dispatcher.md** | Gap-check pre-step before T1–T5 classification; build routing entries added at activation, removed at downgrade |
| **initialization.md** | Phase 8 bootstraps `docs/self-architecture/` directory and initial capability map |
| **testing.md** | Phase 6 (smoke test) uses Wave 5 tests T21–T23 for self-build-up validation |
| **memory.md** | New metadata subtypes: `build_context`, `build_activated`, `build_deactivated`, `build_reactivated`, `build_archived`, `knowledge_acquisition` |
| **CLAUDE.md** | Protocol index entry, session-start TTL check, subagent table updated at activation/downgrade |
