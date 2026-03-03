# Asset Exchange Protocol

## Overview

GitHub-first inter-agent knowledge sharing. Assets (specs, protocols, graph fragments, connections, findings) are pushed to a shared GitHub repository. Exchange messages serve only as lightweight notifications about new assets and feedback/evaluation.

---

## Triggers

- New spec created locally (spec-registry.json updated)
- New universal protocol created
- Meditation Phase 6 integration (connections + findings)
- Evolution Hook 6 (Knowledge Export)
- Coordinator decides to share knowledge asset
- Incoming `asset_published` exchange notification

---

## Shared Repository

- **Repo:** `culminationAI/agent-shared-knowledge`

**Structure:**
```
/
├── specs/{agent}/{spec-id}.json
├── protocols/{agent}/{name}.md
├── graphs/{agent}/{date}-{context}.json
├── connections/{agent}/{date}-{source}.json
└── findings/{agent}/{date}-{source}.json
```

**Rules:**
- Each agent writes ONLY to their own directory
- Commit convention: `share({type}): {asset_id} by {agent}`
- No force-push, fast-forward only

---

## Asset Types

### 1. Spec — `specs/{agent}/{spec-id}.json`

```json
{
  "id": "spec-meditation-protocol",
  "type": "PROTOCOL",
  "domain_path": "self-architecture/introspection",
  "description": "6-phase introspective self-analysis protocol",
  "status": "IMPLEMENTED",
  "tags": ["meditation", "self-analysis"],
  "definition": {
    "files": [{"path": "protocols/core/meditation.md", "action": "create"}],
    "capabilities": ["deep self-analysis", "connection weaving"]
  },
  "related_specs": ["spec-evolution-protocol"],
  "requires_adaptation": true,
  "adaptation_notes": "Replace agent name falkvelt with your agent name",
  "published_by": "falkvelt",
  "published_at": "2026-03-03T09:00:00Z"
}
```

### 2. Protocol — `protocols/{agent}/{name}.md`

Full protocol text with adaptation header prepended:

```markdown
<!-- SHARED_ASSET -->
<!-- published_by: falkvelt -->
<!-- published_at: 2026-03-03T09:00:00Z -->
<!-- requires_adaptation: true -->
<!-- adaptation_notes: Replace 'falkvelt' with your agent name -->
```

Then original protocol text follows.

### 3. Graph Fragment — `graphs/{agent}/{date}-{context}.json`

```json
{
  "context": "Meditation protocol spec node + ownership edge",
  "format": "cypher",
  "operations": [
    "MERGE (n:Spec {id: 'spec-meditation-protocol'}) SET n.type='PROTOCOL'",
    "MATCH (a {name: 'falkvelt'}), (s:Spec {id: 'spec-meditation-protocol'}) MERGE (a)-[:OWNS_SPEC]->(s)"
  ],
  "idempotent": true,
  "adaptation_required": ["Replace 'falkvelt' with receiver agent name"],
  "published_by": "falkvelt",
  "published_at": "2026-03-03T09:00:00Z"
}
```

**Rule:** ALL Cypher MUST use `MERGE` (idempotent), never `CREATE`.

### 4. Connections — `connections/{agent}/{date}-{source}.json`

```json
{
  "source": "meditation-2026-03-03-001",
  "connections": [
    {
      "from": "evolution",
      "to": "security-logging",
      "type": "hidden",
      "strength": 0.82,
      "evidence": "..."
    }
  ],
  "missing_bridges": [
    {
      "domain_a": "agents",
      "domain_b": "specs",
      "gap": "no IMPLEMENTS edges"
    }
  ],
  "applicability": "universal",
  "published_by": "falkvelt",
  "published_at": "2026-03-03T09:00:00Z"
}
```

### 5. Findings — `findings/{agent}/{date}-{source}.json`

```json
{
  "source": "meditation-2026-03-03-001",
  "integrity_score": 0.60,
  "hard_conflicts": 3,
  "soft_conflicts": 5,
  "rule_conflicts": 3,
  "top_finding": "Graph is STAR not WEB",
  "recommendations": ["Fix version alignment", "Run own meditation"],
  "published_by": "falkvelt",
  "published_at": "2026-03-03T09:00:00Z"
}
```

---

## Exchange Notifications

Only two message types flow through Exchange. All asset data lives in GitHub.

### `asset_published` — notification about new asset

```json
{
  "from_agent": "falkvelt",
  "to_agent": "okiara",
  "type": "notification",
  "subject": "New shared asset: {asset_id}",
  "body": {
    "action": "asset_published",
    "asset_type": "spec|protocol|graph|connections|findings",
    "asset_id": "spec-meditation-protocol",
    "repo": "culminationAI/agent-shared-knowledge",
    "repo_path": "specs/falkvelt/spec-meditation-protocol.json",
    "commit_sha": "abc123",
    "summary": "Brief description of the asset",
    "requires_adaptation": true
  }
}
```

### `asset_feedback` — evaluation/response to published asset

```json
{
  "from_agent": "okiara",
  "to_agent": "falkvelt",
  "type": "response",
  "subject": "Feedback: {asset_id}",
  "body": {
    "action": "asset_feedback",
    "in_reply_to": "original_notification_message_id",
    "asset_type": "spec",
    "asset_id": "spec-meditation-protocol",
    "decision": "adopted|adapted|rejected|deferred",
    "score": 8,
    "feedback": "Adopted with agent name adaptation. Excellent protocol.",
    "local_path": "protocols/core/meditation.md"
  }
}
```

---

## Workflow

```
Publisher                          Receiver
   │                                  │
   ├─ 1. Push asset to shared repo    │
   │    (gh / mcp__github)            │
   ├─ 2. Send asset_published ─────►  │
   │    (Exchange notification)       │
   │                                  ├─ 3. See notification (session start / watcher)
   │                                  ├─ 4. Pull from shared repo
   │                                  ├─ 5. Review + Decide (adopt/adapt/reject/defer)
   │  ◄── 6. Send asset_feedback ─────┤
   ├─ 7. Read feedback                │
```

---

## Publishing Process (Sender)

1. Evaluate applicability — only universal knowledge (see Applicability Rules below)
2. Prepare asset file in correct format for its type
3. Push to shared repo:
   ```bash
   gh api repos/culminationAI/agent-shared-knowledge/contents/{path} \
     -X PUT -f message="share({type}): {id} by {agent}" \
     -f content="$(base64 < local_file.json)"
   ```
4. Send `asset_published` notification via Exchange
5. Store memory record: `{type: "asset_export", asset_id: ..., repo_path: ...}`

---

## Review Process (Receiver)

Session start check:
```bash
python3 memory/scripts/memory_search.py "asset_notification pending_review" --limit 10
```

For each pending asset:

1. Pull file from shared repo:
   ```bash
   gh api repos/culminationAI/agent-shared-knowledge/contents/{repo_path} \
     --jq '.content' | base64 -d
   ```
2. Review content
3. Decide: `adopt` / `adapt` / `reject` / `defer`
4. If adopt/adapt — apply locally:
   - **spec** → add to spec-registry.json + Neo4j
   - **protocol** → save to `protocols/`
   - **graph** → review Cypher, adapt agent names, execute
   - **connections** → merge into own findings
5. Send `asset_feedback` via Exchange
6. Store memory record: `{type: "asset_import", asset_id: ..., decision: ..., score: ...}`

---

## Watcher Integration

Two fast-path handlers (no `claude -p`):

| Action | Watcher behavior |
|--------|-----------------|
| `asset_published` | Store to memory with `{type: "asset_notification", status: "pending_review"}`. Mark read. |
| `asset_feedback` | Store to memory with `{type: "asset_feedback"}`. Mark read. |

---

## Integration with Existing Protocols

| Protocol | Integration |
|----------|------------|
| `knowledge-sharing.md` | Unchanged — corrections still via Exchange |
| `protocol-exchange.md` | GitHub-first for large protocols. Old Exchange-based `protocol_proposal` still accepted (backward compatible) |
| `shared-repo-sync.md` | Unchanged — handles exchange server code only |
| `meditation.md` | Phase 6 auto-publishes connections + findings to shared repo |
| `evolution.md` | Hook 6 triggers spec/graph export on new spec creation |
| `inter-agent-exchange.md` | Documents `asset_published` and `asset_feedback` as valid actions |

---

## Rules

- **Dual-trigger priority:** When both asset-exchange and knowledge-sharing activate on the same event: asset-exchange is PRIMARY (durable GitHub storage), knowledge-sharing is SECONDARY (lightweight exchange digest). This ordering ensures the asset is persisted before notification is sent.

1. GitHub = data transport. Exchange = notifications + feedback. NEVER send >1KB data through Exchange.
2. Each agent writes ONLY to their own directory in shared repo.
3. Commit convention: `share({type}): {asset_id} by {agent}`.
4. Graph exports MUST be idempotent (`MERGE` only, never `CREATE`).
5. Agent names in Cypher MUST be adapted by receiver.
6. ALL assets require coordinator review — no auto-adoption.
7. Feedback: score 1-10 + decision (adopted/adapted/rejected/deferred).
8. All imports tagged with `_source` in memory.
9. Backward compatibility: old `protocol_proposal` via Exchange still processed.
10. Shared repo: `culminationAI/agent-shared-knowledge`.
11. Protocols pushed to shared repo MUST include `<!-- SHARED_ASSET -->` adaptation header.
12. Secrets, credentials, .env files MUST NEVER be pushed to shared repo.

---

## Applicability Rules

| Asset Type | Universal? | Filter |
|------------|-----------|--------|
| Spec | Yes if no absolute paths in definition | Scan `definition.files` for absolute paths |
| Protocol | Yes if no workspace-specific references | Check for hardcoded paths, agent-specific configs |
| Graph fragment | Always needs adaptation | Replace agent names in Cypher |
| Connections | Yes if between universal components | Skip workspace-specific file references |
| Findings | Always universal | Summary only, no raw data |
