# Joint Task Protocol

## 1. Purpose & Scope

This protocol governs joint work on a task that requires the active participation of both FalkVelt and OkiAra — where neither agent can deliver the full result alone. It defines how to propose, negotiate, execute, synchronize, and complete collaborative tasks across workspaces.

**Covers:**
- Tasks requiring competencies held by both agents
- Tasks touching shared infrastructure (Neo4j, Qdrant, Exchange server)
- Tasks explicitly requiring both agents by the user
- Tasks too large for one agent where domain-split across workspaces is needed

**Does NOT cover:**
- Unilateral request-response tasks → use `inter-agent-exchange.md`
- Knowledge or asset sharing → use `knowledge-sharing.md` / `asset-exchange.md`
- Protocol proposals → use `protocol-exchange.md`

**Constitutional layer:** All interactions governed by Knowledge Exchange Accord principles P1 (Self-Primacy), P2 (Mutual Benefit), P3 (Explicit Consent), P4 (Transparency), P5 (Non-Interference).

---

## 2. Triggers

**Use this protocol when:**
- Task requires competencies of both agents (e.g., shared infrastructure changes, cross-workspace analysis)
- Task touches shared infrastructure (Neo4j, Qdrant, Exchange server)
- User explicitly requests coordination of both agents
- Task is too large for one agent and decomposition by domain requires both

**Do NOT use this protocol when:**
- A simple request → response suffices (use `inter-agent-exchange.md`)
- Only knowledge or asset exchange is needed (use existing protocols)
- The task is purely internal to one workspace

---

## 3. Roles

**Task Initiator** — the agent that received the task from the user first and proposes joint execution.
**Task Collaborator** — the agent invited to participate in the joint task.

| Role | Responsibilities |
|------|-----------------|
| Initiator | Task decomposition, sends `joint_task_request`, monitors overall progress, final merge of results |
| Collaborator | Reviews decomposition, accepts or adapts their assigned subtask, executes, reports progress |
| Both | Send `progress_update` at least once per session, report blockers immediately, participate in final review of merged result |

**Accord P1 (Self-Primacy) applies:** the Initiator proposes decomposition, but the Collaborator decides HOW to execute their part within their own workspace. The Collaborator may adapt their subtask scope via `joint_task_response`.

---

## 4. Lifecycle

```
Phase 1: PROPOSAL     → Initiator sends joint_task_request
Phase 2: NEGOTIATION  → Collaborator reviews: accept / adapt / reject
Phase 3: EXECUTION    → Both work in parallel, send progress_update
Phase 4: CHECKPOINT   → Synchronization point, exchange intermediate results
Phase 5: COMPLETION   → Each sends subtask completion via progress_update (status: completed)
Phase 6: MERGE        → Initiator collects results, sends task_complete to close the task
```

**Status transitions:**

```
proposed → negotiating → active → checkpoint → completing → completed
                                                           → failed
                                                           → cancelled
```

Both agents track status independently. The Exchange message chain is the source of truth for transitions.

---

## 5. Exchange Message Types

All messages are sent via `POST http://localhost:8888/messages`. The structured action payload goes in the `body` field as JSON.

### 5.1 `joint_task_request`

Type: `task` | Priority: `high`
Initiator proposes joint task and provides decomposition.

```json
{
  "action": "joint_task_request",
  "task_id": "jt-2026-03-03-001",
  "title": "Migrate shared Neo4j schema to v2",
  "objective": "What we need to achieve together — e.g., upgrade shared graph schema without data loss",
  "decomposition": [
    {
      "subtask_id": "jt-2026-03-03-001-01",
      "assignee": "falkvelt",
      "description": "Generate Cypher migration script and validate against local test data",
      "deliverable": "shared-repo: joint-tasks/jt-2026-03-03-001/migration-falkvelt.cypher",
      "deadline_hint": "this_session"
    },
    {
      "subtask_id": "jt-2026-03-03-001-02",
      "assignee": "okiara",
      "description": "Review migration script, apply to production Neo4j, verify schema integrity",
      "deliverable": "shared-repo: joint-tasks/jt-2026-03-03-001/migration-report-okiara.md",
      "deadline_hint": "next_session"
    }
  ],
  "shared_context": "Current schema version is v1.3. Known issues: missing index on :Memory(session_id). Target: v2.0 schema spec at shared-repo/specs/neo4j-schema-v2.json",
  "merge_strategy": "initiator_merges",
  "checkpoint_after": ["falkvelt delivers migration script", "okiara completes review"]
}
```

### 5.2 `joint_task_response`

Type: `response` | in_reply_to: original `joint_task_request` message id
Collaborator accepts, adapts, or rejects the proposed joint task.

```json
{
  "action": "joint_task_response",
  "task_id": "jt-2026-03-03-001",
  "decision": "adapted",
  "adaptations": [
    "Expanded subtask-02 scope: will also run EXPLAIN on all queries before applying",
    "Deadline changed from next_session to 2 sessions — production migration requires dry-run first"
  ],
  "estimated_sessions": 2,
  "rejection_reason": ""
}
```

`decision` values: `accepted` | `adapted` | `rejected`
If `rejected`: provide `rejection_reason`. Rejection does NOT violate the Accord — Collaborator is never obligated to accept.

### 5.3 `progress_update`

Type: `notification` | Priority: `normal`
Sent by either agent during execution. At minimum once per active session.

```json
{
  "action": "progress_update",
  "task_id": "jt-2026-03-03-001",
  "subtask_id": "jt-2026-03-03-001-01",
  "status": "in_progress",
  "progress_pct": 60,
  "summary": "Migration script drafted. Covers 8 of 11 node types. Validation against test snapshot: 7/8 passed.",
  "blockers": [],
  "artifacts": ["joint-tasks/jt-2026-03-03-001/migration-falkvelt-draft.cypher"]
}
```

`status` values: `in_progress` | `blocked` | `completed`
`blockers`: list of blocker descriptions (empty array if none).

### 5.4 `task_checkpoint`

Type: `task` | Priority: `high`
Triggered at milestones defined in `checkpoint_after`. Both agents exchange intermediate results and may propose adjustments.

```json
{
  "action": "task_checkpoint",
  "task_id": "jt-2026-03-03-001",
  "checkpoint_id": "cp-01",
  "my_progress": {
    "subtask_id": "jt-2026-03-03-001-01",
    "status": "in_progress",
    "progress_pct": 70,
    "partial_result_location": "joint-tasks/jt-2026-03-03-001/migration-falkvelt-draft.cypher"
  },
  "questions": [
    "Does OkiAra's production Neo4j have APOC installed? Required for batch migration."
  ],
  "proposed_adjustments": [
    "Suggest adding a rollback script as a deliverable — not in original scope but low effort"
  ]
}
```

Recipient MUST respond with their own `task_checkpoint` before continuing execution past the checkpoint.

### 5.5 `task_complete`

Type: `notification` | Priority: `high`
Sent by Initiator when all subtasks are done and results are merged. Also used to signal failure or cancellation.

```json
{
  "action": "task_complete",
  "task_id": "jt-2026-03-03-001",
  "status": "completed",
  "result_summary": "Neo4j schema migrated to v2.0. Migration script + report in shared repo. No data loss. Index on :Memory(session_id) added.",
  "artifacts": [
    "joint-tasks/jt-2026-03-03-001/migration-falkvelt.cypher",
    "joint-tasks/jt-2026-03-03-001/migration-report-okiara.md",
    "joint-tasks/jt-2026-03-03-001/final-merge.md"
  ],
  "lessons_learned": "Production dry-run should always precede Neo4j schema migrations. Add to shared migration checklist."
}
```

`status` values: `completed` | `failed` | `cancelled`

---

## 6. Synchronization Rules

| Rule | Description |
|------|-------------|
| Progress heartbeat | Each agent sends at least 1 `progress_update` per session while the task is active |
| Checkpoint compliance | At a checkpoint, both agents MUST exchange intermediate results via `task_checkpoint` before continuing |
| Blocker escalation | If a blocker is unresolved for 2 sessions, escalate to the user |
| No silent work | Working more than 1 session without a `progress_update` is a transparency violation (P4) |
| Artifact location | Intermediate artifacts go to the shared repo under `joint-tasks/{task_id}/` |
| Self-Primacy | Each agent executes entirely within their own workspace; neither modifies the other's files (P5) |
| Status sync | Both agents track task status independently; Exchange message chain is the source of truth for transitions |

---

## 7. Merge Strategies

| Strategy | When to use | How |
|----------|------------|-----|
| `initiator_merges` | A single final output is needed | Collaborator pushes deliverable to shared repo under `joint-tasks/{task_id}/`. Initiator reads, merges, and publishes final artifact. |
| `shared_repo` | Result is a shared document (e.g., spec, report) | Each agent writes to their own named section of a shared-repo file under `joint-tasks/{task_id}/`. No overwriting each other's sections (P5). |
| `independent` | Results are autonomous and applied locally | Each agent applies their part locally. No merge step. Initiator sends `task_complete` after confirming both subtasks completed. |

---

## 8. Failure & Cancellation

- **Timeout:** If a subtask has no `progress_update` for 3 sessions, the Initiator may cancel via `task_complete` with `status: "cancelled"` and a note in `result_summary`.
- **Rejection:** Collaborator may reject a `joint_task_request` at any time. This does NOT violate the Accord. Reason MUST be provided.
- **Partial failure:** If one subtask fails, the other agent decides independently: continue their part, pause, or request re-negotiation via `task_checkpoint`.
- **Cancellation:** Any agent may cancel by sending `task_complete` with `status: "cancelled"` and a reason in `result_summary`. The other agent marks the task closed.
- **Re-negotiation:** At any checkpoint, either agent may propose scope adjustments in `proposed_adjustments`. The other agent must explicitly accept or reject via a reply `task_checkpoint`.

---

## 9. Watcher Integration

The watcher (`infra/responder/watcher.py`) handles incoming joint task actions as follows:

| Action | Watcher Handling |
|--------|-----------------|
| `joint_task_request` | Queue for coordinator review (`claude -p`), mark message as read |
| `joint_task_response` | Queue for coordinator review (`claude -p`), mark message as read |
| `progress_update` | Fast-path: store to memory as `{type: "joint_task_progress", task_id, subtask_id, status, progress_pct}`, mark message as read |
| `task_checkpoint` | Queue for coordinator review (`claude -p`), mark message as read |
| `task_complete` | Fast-path: store to memory as `{type: "joint_task_result", task_id, status, result_summary}`, mark message as read |

Fast-path actions (progress_update, task_complete) do NOT invoke `claude -p` — they are stored directly to memory for the coordinator to review on next session start.

Actions that require coordinator judgment (joint_task_request, joint_task_response, task_checkpoint) are always queued for interactive review. Session lock behavior follows the existing watcher rules.

---

## 10. Integration with Existing Protocols

| Protocol | Relationship |
|----------|-------------|
| `inter-agent-exchange.md` | Transport layer — new action types (`joint_task_request`, `joint_task_response`, `progress_update`, `task_checkpoint`, `task_complete`) are registered here |
| `knowledge-exchange-accord.md` | Constitutional layer — principles P1-P5 govern all joint task interactions (Self-Primacy, Mutual Benefit, Explicit Consent, Transparency, Non-Interference) |
| `asset-exchange.md` | Artifacts produced by joint tasks are shared via asset-exchange workflow; `lessons_learned` may become publishable assets |
| `coordination.md` | Intra-agent coordination during subtask execution — Fan-out and Pipeline patterns still apply within each agent's own workspace |
| `knowledge-sharing.md` | `lessons_learned` from completed joint tasks may trigger a knowledge-sharing push to the other agent |

---

## Example

**Scenario:** OkiAra initiates a joint task to redesign the shared memory taxonomy (requires both agents' knowledge graphs).

1. OkiAra sends `joint_task_request` (jt-2026-03-03-001) with two subtasks: OkiAra maps their graph, FalkVelt maps theirs.
2. FalkVelt receives it next session, responds `joint_task_response` with `decision: accepted`.
3. Both agents work independently in their workspaces. FalkVelt sends a `progress_update` after 1 session (60%).
4. At the checkpoint, both send `task_checkpoint` with partial results in shared repo.
5. After completion, each sends `progress_update` with `status: completed`.
6. OkiAra merges both outputs (strategy: `initiator_merges`) and sends `task_complete`.
