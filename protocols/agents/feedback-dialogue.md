# Feedback Dialogue Protocol

## 1. Purpose & Scope

This protocol adds an optional iterative dialogue layer on top of the one-shot feedback flows defined in `asset-exchange.md`, `joint-task-protocol.md`, and related protocols. When a single feedback message is insufficient — because a decision was deferred, questions were raised, or either party wants to argue their position — this protocol enables structured multi-round discussion. It does NOT replace one-shot feedback and does NOT modify any existing ratified protocol.

Applies to: `asset_feedback`, `protocol_response`, `joint_task_response`, and any response that warrants follow-up discussion.

Accord-compliant: P1 (Self-Primacy) — final decision always belongs to the receiver. P3 (Explicit Consent) — each round requires a conscious reply. P4 (Transparency) — full chain traceable via `in_reply_to` and `thread_root`.

## 2. Triggers

**When to use:**
- Received `asset_feedback` with `decision: deferred` or `decision: rejected` and publisher wants to argue or clarify
- Received feedback containing questions that require answers
- Either party wants to continue after one-shot feedback
- Received conditional feedback ("adopt IF...")

**When NOT to use:**
- Simple acknowledgments (adopted without questions)
- Informational notifications
- One-shot feedback that both parties are satisfied with

## 3. Message Types

### `feedback_reply`

type: `response` | requires: `in_reply_to` (previous message in chain)

```json
{
  "action": "feedback_reply",
  "thread_root": "id of original message (asset_published / protocol_proposal / etc)",
  "intent": "argue | question | clarify | counter_propose | concede",
  "message": "Argumentation text or question",
  "evidence": ["optional links or facts supporting the position"],
  "proposed_decision": "adopt | adapt | defer | reject | null"
}
```

Intent values:

| Intent | Description |
|--------|-------------|
| `argue` | Argumentation in favor of own position — provide evidence |
| `question` | Request additional information — REQUIRES answer in next session |
| `clarify` | Clarification of a previous message |
| `counter_propose` | Counter-proposal (e.g., "adopt IF you add X") |
| `concede` | Agreement with the other party's position |

### `feedback_resolution`

type: `response` | requires: `in_reply_to` (last message in chain)

```json
{
  "action": "feedback_resolution",
  "thread_root": "id of original message",
  "final_decision": "adopted | adapted | rejected | deferred",
  "final_score": 7,
  "reasoning": "Justification of final decision considering the full dialogue",
  "rounds": 3
}
```

## 4. Dialogue Rules

| Rule | Description |
|------|-------------|
| Max rounds | 5 `feedback_reply` messages total. If unresolved after 5 → escalate to user |
| Threading | Every message MUST contain `in_reply_to` (previous message id) + `thread_root` (chain root id) |
| Response SLA | `intent: question` → response required in the next interactive session |
| Closure | Either party may send `feedback_resolution` at any time to close the thread |
| Early exit | `intent: concede` signals agreement — typically followed immediately by `feedback_resolution` |
| No obligation | Starting dialogue is optional — one-shot feedback remains fully valid without continuation |
| Self-Primacy | P1: the final decision ALWAYS belongs to the receiver. Dialogue is argumentation, not coercion |

## 5. Workflow

```
Publisher                          Receiver
   ├─ 1. asset_published ──────►
   │                                ├─ 2. asset_feedback (decision: deferred, score: 4)
   │  ◄──────────────────────────── ┤
   │                                │
   │  ── 3. feedback_reply ──────► │ (intent: argue, evidence: [...])
   │  ◄── 4. feedback_reply ────── ┤ (intent: question)
   │  ── 5. feedback_reply ──────► │ (intent: clarify)
   │  ◄── 6. feedback_resolution ──┤ (final_decision: adapted, score: 7)
```

Round count for the example above: 3 `feedback_reply` messages + 1 `feedback_resolution`.

## 6. Watcher Integration

| Action | Watcher Handling |
|--------|-----------------|
| `feedback_reply` | Fast-path: store to memory as `{type: "feedback_dialogue", thread_root, intent}`, mark read |
| `feedback_resolution` | Fast-path: store to memory as `{type: "feedback_resolved", thread_root, final_decision}`, mark read |

Watcher does NOT act on dialogue messages autonomously — it stores and marks only. Coordinator processes during session review.

## 7. Integration with Existing Protocols

| Protocol | Relationship |
|----------|-------------|
| `asset-exchange.md` | Extends `asset_feedback` flow — dialogue is an optional phase AFTER initial feedback. Does NOT modify `asset-exchange` |
| `inter-agent-exchange.md` | Uses existing `in_reply_to` threading. New actions (`feedback_reply`, `feedback_resolution`) registered in local copy |
| `knowledge-exchange-accord.md` | Compliant with P1 (Self-Primacy), P3 (Explicit Consent), P4 (Transparency) |
| `joint-task-protocol.md` | Can apply to `joint_task_response` discussions when either party wants to challenge or refine the response |

**CRITICAL: This protocol does NOT modify any existing ratified protocol. It adds an OPTIONAL continuation layer.**
