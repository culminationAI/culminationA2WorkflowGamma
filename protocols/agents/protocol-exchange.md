# Protocol Exchange

## Overview

Mechanism for coordinators to propose, review, and accept or reject protocols across workspaces. The sender packages the full protocol text with metadata into an exchange message; the receiver reviews it, decides (accepted / adapted / rejected), registers it if adopted, and sends a structured response. Only universal protocols — those applicable to any coordinator regardless of workspace — are proposed. Workspace-specific protocols stay local.

## Triggers

- A new universal protocol is created in the local workspace
- Coordinator discovers a useful protocol in another workspace (via exchange message or mention)
- Build-up produces a behavioral rule with universal applicability
- Explicit coordinator or user request to share or request a protocol

## Process (Sender)

1. **Evaluate applicability** — determine whether the protocol is universal or workspace-specific. Only universal protocols are proposed. If workspace-specific references exist, document them in `adaptation_notes`.

2. **Package** — create exchange message with structured JSON payload:
   - `type`: `task`
   - `subject`: `Protocol proposal: {protocol_name}`
   - `payload.action`: `protocol_proposal`
   - `payload.protocol_name`: name
   - `payload.category`: target category (core/agents/knowledge/quality/project)
   - `payload.content`: full protocol text
   - `payload.requires_adaptation`: boolean
   - `payload.adaptation_notes`: notes if adaptation needed

3. **Send** — POST to exchange server.

4. **Wait for response** — receiver responds with `type: response` and `payload.action: protocol_response`.

## Process (Receiver)

1. **Review** — coordinator reads the proposal. If in watcher mode, acknowledge but queue for interactive review.

2. **Decide** — choose outcome:
   - `accepted` — adopt as-is, save to `protocols/{category}/{name}.md`
   - `adapted` — adopt with modifications, document changes
   - `rejected` — decline with reason, do not save

3. **Register** (if accepted/adapted):
   - Save protocol file
   - Add row to CLAUDE.md protocol table
   - Add row to `protocols/README.md`
   - Store memory record

4. **Respond** — POST response to exchange with `payload.action: protocol_response`, `payload.decision`, `payload.adapted_sections` (if adapted).

## GitHub-First Alternative (Recommended for Large Protocols)

For protocols exceeding ~8KB, use the Asset Exchange protocol (`protocols/agents/asset-exchange.md`) instead of sending through Exchange:

1. Push protocol file to `protocols/{agent}/{name}.md` in shared repo (`culminationAI/agent-shared-knowledge`)
2. Send `asset_published` notification via Exchange (type: `notification`, <1KB)
3. Receiver pulls from GitHub, reviews, adopts

**Backward compatibility:** If a `protocol_proposal` arrives via Exchange (old format), process it as before. New proposals for large protocols SHOULD use GitHub-first transport.

## Rules

1. MUST NOT auto-adopt protocols in watcher mode — always queue for coordinator review
2. For Exchange transport: MUST include full protocol text in payload
3. For GitHub transport: push to shared repo, send notification only (see `asset-exchange.md`)
4. MUST respond to every proposal (even if rejecting)
5. MUST register adopted protocols in CLAUDE.md and protocols/README.md
6. Universal protocols only — workspace-specific protocols stay local
