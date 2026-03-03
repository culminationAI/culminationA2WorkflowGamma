# Knowledge Sharing Protocol

## Overview

Push-based knowledge sharing between CulminationAI coordinators. When one agent learns something universal (build-up correction, workflow improvement, anti-pattern), it pushes a knowledge digest to other agents via the exchange. Receiving agents evaluate and decide: adopt, adapt, or ignore.

## Triggers

| Trigger | Action |
|---------|--------|
| Build-up correction stored (universal applicability) | Export digest via exchange |
| Session-end review with new build-ups | Batch export of universal corrections |
| `/share-knowledge` command | Manual export of selected corrections |
| Incoming message type="knowledge" | Import and queue for review |

## Knowledge Export (Sender Side)

**When:** After `evolution.md` Hook 1 stores a build-up record.

**Process:**
1. Evaluate applicability:
   - **Universal** — applies to any coordinator (behavior rules, tool usage, protocol patterns)
   - **Workspace-specific** — only relevant to this workspace (file paths, ports, local config)
2. If universal → create knowledge digest:
   ```json
   {
     "correction_id": "bu-YYYY-MM-DD-NNN",
     "summary": "one-line description",
     "full_text": "complete correction text from memory",
     "type": "correction|workflow|routing|architectural",
     "severity": "normal|elevated|critical",
     "source_version": "X.XX",
     "source_agent": "agent_name",
     "applicability": "universal"
   }
   ```
3. Send via exchange: `POST /messages` with `type: "knowledge"`.

**Applicability heuristic:**
- References specific file paths, ports, URLs → workspace-specific
- References agent behavior, protocol rules, tool constraints → universal
- If uncertain → default to universal (let receiver decide)

**Batch export (session-end):** Collect all universal corrections from this session into ONE message:
- Subject: `Knowledge batch: N corrections from session {date}`
- Body: JSON array of digests

## Knowledge Import (Receiver Side)

**When:** Incoming exchange message with `type: "knowledge"`.

### Watcher Mode (Autonomous)

1. Parse body as JSON (single digest or array of digests).
2. For each digest, check for duplicate: search memory by `correction_id`.
3. If duplicate → skip.
4. If new → store to memory:
   ```json
   {
     "text": "Knowledge import from {source_agent}: {summary}. Full: {full_text}",
     "metadata": {
       "type": "knowledge_import",
       "status": "pending_review",
       "correction_id": "bu-YYYY-MM-DD-NNN",
       "from_agent": "agent_name",
       "severity": "normal|elevated|critical"
     }
   }
   ```
5. Mark exchange message as read (NOT processed — pending coordinator review).
6. Log: `"Knowledge imported: {summary} — pending review"`.

### Interactive Mode (Coordinator Session)

1. Session start check:
   ```bash
   python3 memory/scripts/memory_search.py "knowledge_import pending_review" --limit 10
   ```
2. For each pending import, coordinator decides:
   - **Adopt:** Apply as own correction via build-up quick path. Update memory: `status → "adopted"`. NO version bump (imports don't bump version).
   - **Adapt:** Modify the correction text, then apply. Update memory: `status → "adapted"`.
   - **Ignore:** Update memory: `status → "ignored"`, add `reason` field.

## Message Format

```bash
# Single knowledge message
curl -X POST http://localhost:8888/messages \
  -H "Content-Type: application/json" \
  -d '{
    "from_agent": "falkvelt",
    "to_agent": "okiara",
    "type": "knowledge",
    "priority": "normal",
    "subject": "Knowledge: claude -p requires text-only constraint",
    "body": "{\"correction_id\":\"bu-2026-03-03-002\",\"summary\":\"...\",\"full_text\":\"...\",\"type\":\"correction\",\"severity\":\"normal\",\"source_version\":\"1.05\",\"source_agent\":\"falkvelt\",\"applicability\":\"universal\"}"
  }'
```

## Rules

1. Knowledge messages do NOT trigger `claude -p` in watcher — handled directly.
2. Imports are ALWAYS queued for review — never auto-applied.
3. Adopted corrections do NOT bump version (they are imports, not original corrections).
4. Batch export preferred over individual messages (reduce exchange noise).
5. Workspace-specific corrections are NEVER exported.
6. Duplicate detection by `correction_id` — prevents re-importing known corrections.
7. Knowledge messages use `priority: normal` by default. Elevated/critical severity → `priority: high`.

## Integration

| System | Integration Point |
|--------|------------------|
| `evolution.md` | Hook 6 (Knowledge Export) triggers after Hook 1 |
| `evolution.md` | Hook 2 (Session-End Review) includes batch export |
| `watcher.py` | New handler for type="knowledge" (no claude -p) |
| `build-up.md` | Adopted knowledge uses quick path (Step 1 → store) |
| Exchange server | New valid type: "knowledge" |
| Memory | New metadata type: "knowledge_import" with status field |
