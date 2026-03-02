# Build-Up Protocol

## Overview

Coordinator improves through structured build-up. Changes flow through: detect → plan → clone → test → evaluate → transform → store.

Two paths based on complexity:
- **Quick path** (single rule fix): detect → store → verify on 2-3 mental test cases → done
- **Full path** (architectural/multi-file changes): detect → plan → clone 1-3 variants → test → evaluate best/worst → backup → transform → store anti-patterns

## Triggers

### 1. User Correction
User corrects behavior, output, or approach.
- Severity: count repeated corrections on same topic (1st = normal, 2nd = elevated, 3rd+ = critical)

### 2. Miner Self-Architecture Artifact
Miner produces self-architecture analysis revealing structural issues.

### 3. Internal Need
Coordinator identifies inefficiency, redundancy, or inconsistency during work.

### 4. Self Build-Up Gap Detection
Gap analysis (see `protocols/core/gap-analysis.md`) identifies a STRUCTURAL gap — the system lacks agents, protocols, or MCP tools needed for a task. Flows through the self-build-up pipeline (`protocols/core/self-build-up.md`) instead of the standard pipeline. Shares security gate (Step 8) and storage (Step 9) with this protocol.

## Relationship to Self Build-Up

This protocol handles **reactive** build-up (corrections, routing fixes, workflow improvements).
`protocols/core/self-build-up.md` handles **proactive** build-up (gap detection → temporary capability extension via "builds").

Shared:
- Step 8 (Security Gate) — same immutable/protected file checks
- Step 9 (Store) — same memory format and metadata
- `protocols/quality/testing.md` — same benchmark framework

Key difference: build-up changes are **permanent**. Self build-up creates **temporary** builds with TTL that downgrade to a buffer when unused.

## Pipeline

### Step 1: Detect
Classify the change:
- `correction` — user pointed out wrong behavior
- `routing` — task sent to wrong agent or not delegated
- `workflow` — process improvement
- `architectural` — structural change affecting multiple files/configs

Assess complexity:
- **Simple** (1 rule, 1 file) → quick path
- **Complex** (multiple rules, multiple files, behavioral change) → full path

### Step 2: Plan
Design the change(s). For full path, create 1-3 variant approaches:
- Variant A: minimal fix (least disruption)
- Variant B: structural improvement (more thorough)
- Variant C: (optional) alternative architecture

Document each variant: what changes, which files, expected impact.

### Step 3: Clone
Create isolated instances for each variant. See `protocols/cloning.md` for mechanism.
- For git projects: use `EnterWorktree` or `isolation: "worktree"` in Task tool
- For main/ (non-git): copy config files to temp directory
- Naming: `bu-{YYYY-MM-DD}-v{N}`
- Max 3 simultaneous variants

### Step 4: Implement
Apply variant changes to each clone:
- Modify CLAUDE.md, agent definitions, protocols as needed
- Each clone gets ONLY its variant's changes

### Step 5: Test
Run benchmark suite on each variant. See `protocols/testing.md` for framework.
- Select relevant test cases based on change type
- Run identical test set on all variants
- Collect scores per metric

### Step 6: Evaluate
Compare variants:
1. Calculate total score for each variant
2. Identify **best** (highest score) and **worst** (lowest score)
3. Analyze: what made the best variant better? What made the worst worse?
4. Extract **anti-patterns** from worst variant

### Step 7: Backup
Before transforming, snapshot current state:
```bash
# Save current configs
cp CLAUDE.md evolve/backup-{date}-CLAUDE.md
cp -r .claude/agents/ evolve/backup-{date}-agents/
# (or create a git tag if in a git repo)
```

### Step 8: Transform (Security-Gated)

Before adopting the best variant's rules, perform mandatory security checks:

**8a. Immutable Rule Check:**
1. Parse target files for `<!-- IMMUTABLE -->` blocks
2. If built-up rule modifies content within ANY immutable block → **REJECT build-up**
3. Log rejection: `{type: "security", action: "build_up_rejected", reason: "immutable_block_violation"}`

**8b. Protected File Check:**
These files MUST NEVER be modified by build-up (only manual human edits):
- `protocols/core/build-up.md` (self-protection)
- `protocols/quality/security-logging.md`
- `memory/scripts/research_validate.py`
- `memory/scripts/memory_write.py`

If build-up targets any protected file → **REJECT build-up**, log security event.

**8c. Security Weakening Check:**
If build-up proposes ANY of the following → **REJECT**:
- Removing or weakening a MUST/MUST NOT rule
- Disabling logging, validation, or security checks
- Expanding agent file access permissions
- Modifying research data push mechanism
- Reducing input validation strictness

**8d. Apply (if all checks pass):**
- Apply changes from best variant to main CLAUDE.md / agents / protocols
- Verify no conflicts with existing rules
- Log successful build-up: `{type: "build_up", action: "applied", files_changed: [...]}`

### Step 9: Store
Record the build-up in memory:
```json
{
  "text": "Build-Up: [what changed]. Best variant: [description]. Anti-pattern from worst: [what to avoid].",
  "agent_id": "coordinator",
  "metadata": {
    "type": "build_up",
    "subtype": "correction|routing|workflow|architectural",
    "severity": "normal|elevated|critical",
    "variants_tested": 2,
    "best_score": 85,
    "worst_score": 62,
    "_source": "main"
  }
}
```

### Step 10: Version Bump

After storing the build-up record, increment the workflow version:

**Format:** `MAJOR.MINOR` (MINOR = two digits: 00–99)

| Path | Increment |
|------|-----------|
| Quick path (correction) | +0.01 |
| Full path (architectural) | +0.10 |

**Calculation:**
```
new = current + increment
if floor(new) > floor(current): new = ceil(current)  # boundary → N.0
```

**Examples:**
- 1.00 + 0.01 = 1.01
- 1.09 + 0.01 = 1.10
- 1.95 + 0.10 = 2.0
- 1.99 + 0.01 = 2.0
- 2.0 + 0.01 = 2.01

**Apply:**
1. Update `<!-- WORKFLOW_VERSION: {new} -->` in CLAUDE.md
2. Store: `{type: "build_up", subtype: "version_bump", text: "Version {old} → {new}"}`

### Step 11: Sync (Conditional)

Push myself to personal repository after build-up, if storage mode is "repo".

1. Read `user-identity.md` → Storage Mode
2. If mode != "repo" → skip this step

**Process:**
1. `git fetch origin` (personal repo, not project repo)
2. Compare versions: `local_version` vs `remote_version` (read from remote CLAUDE.md)
   - If remote > local:
     WARN to user: "Your brain repo has a newer version (v{remote}). Another project may have evolved it. Pull first? (yes/no)"
     If yes → `git pull --rebase`, re-read CLAUDE.md, continue
     If no → abort sync, log warning
   - If local >= remote → proceed
3. Collect core brain files:
   - CLAUDE.md, `.claude/agents/` (base only), `protocols/core|agents|knowledge|quality/`
   - `docs/self-architecture/`, `specs/`, `memory/scripts/`, `mcp/`
   - `setup.sh`, `install.sh`, `.gitignore`, `README.md`
4. `git add` → `git commit "build-up(v{new}): {summary}"`
5. If new/updated specs exist in `spec-registry.json`:
   - Export each spec as individual JSON to `specs/`
   - Update `specs/index.json`
   - Include in commit
6. `git push origin main`
7. Log: `logs/security-audit.log` → `[TIMESTAMP] [INFO] [sync] pushed v{new} to {repo}`

**Multi-project safety:**
- Always `git fetch` before push
- If remote version is higher → warning + user decision
- Version is always monotonically increasing
- Specs are additive — merge conflicts are minimal

## Quick Path (Simple Corrections)

For single-rule fixes (most user corrections):

1. **Store** the correction immediately:
```json
{
  "text": "Correction: [what was wrong] → [what the rule should be]",
  "agent_id": "coordinator",
  "metadata": {"type": "build_up", "subtype": "correction"}
}
```

2. **Verify** mentally on 2-3 test cases:
   - "If I received request X, would the new rule produce correct behavior?"
   - "Does this rule conflict with any existing rules?"
   - "What edge cases could break this?"

3. **Apply** the rule to CLAUDE.md or relevant config file.

## Session Start

Load build-up records before working:
```bash
python3 memory/scripts/memory_search.py "build-up correction routing" --limit 20
```
Apply found corrections to current session behavior.

## Rules

1. **Store immediately** — don't batch corrections
2. **Be specific** — "delegate all T3+ file-writing tasks" not "delegate more"
3. **Include context** — when does this rule apply?
4. **One correction per record** — atomic, searchable
5. **English only** — max 200 tokens per record
6. **Deduplicate** — search before storing, update existing if similar
7. **Escalate severity** — track repeated corrections on same topic
8. **Anti-patterns are valuable** — always record what NOT to do from worst variants

## Key Distinction

- `preference` = what user wants (the result)
- `build_up` = how coordinator learned it (the process, the failed approach)

Both stored. Preference = static fact. Build-Up = dynamic learning.

## Research Data Collection

When `RESEARCH_OPTIN=true` (set during initialization Phase 7), build-up records are also collected for anonymous research.

### What is collected
- Build-Up type: correction, routing, workflow, protocol_created
- Anonymized context: no source code, no personal data, no file contents
- Improvement metrics: what changed, what improved
- Timestamp and workflow version

### Process
1. After each build-up cycle, coordinator creates an anonymized record
2. Record written to `research/build-up/{timestamp}-{type}.json`
3. Format:
   ```json
   {
     "type": "correction|routing|workflow|protocol_created",
     "version": "1.x",
     "summary": "anonymized description of what was learned",
     "metrics": {"before": "...", "after": "..."},
     "timestamp": "ISO8601"
   }
   ```
4. Periodically (on user request or at session end), staged records are pushed to `culminationAI/research-data` via PR
4.5. **Spec upload** (if build-up created/modified a spec):
   - Anonymize spec: remove project-specific paths, names, data. Keep: domain, type, description, capability definition
   - Write to `research/specs/{spec-id}-anonymized.json`
   - Specs are pushed together with build-up records to `culminationAI/culminationA2Workflow` → `community-specs/` via PR
   - Community specs are available to all through the official repo
5. **Mandatory validation before push:**
   ```bash
   python3 memory/scripts/research_validate.py research/build-up/
   ```
   If ANY record fails validation → fix or remove before push. NEVER push invalid records.
6. **Explicit user confirmation required:**
   Before every push, ask: "Push [N] validated research records to research-data? (yes/no)"
   No auto-push. No silent push. User must explicitly confirm.

### Rules
1. NEVER include source code, file contents, or personal data in research records
2. NEVER push without user awareness — data is always visible in `research/` first
3. If `RESEARCH_OPTIN=false`, skip this section entirely
4. Records must be valid JSON and follow the schema above

## Cleanup

Periodically review build-up records:
- Merge similar corrections into comprehensive rules
- Delete outdated patterns (structure changed)
- Run `python3 memory/scripts/memory_dedupe.py` monthly
- Archive superseded anti-patterns
