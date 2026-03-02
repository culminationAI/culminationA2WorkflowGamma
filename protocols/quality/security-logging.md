# Security Logging Protocol

## Overview

Rules for input validation, audit trail, and sensitive data handling across the workflow. Applies to all phases of initialization, memory operations, and agent dispatch.

## Triggers

- Phase 3 (Learn): user preference input
- Memory write operations (memory_write.py)
- Agent dispatch: user-provided task descriptions
- Any external data entering the system

## Input Validation

### Identifiers (labels, relation types)

Whitelist: `^[a-zA-Z_][a-zA-Z0-9_]*$`, max 50 chars.
- Enforced by `sanitize_identifier()` in memory_write.py
- Invalid identifiers are blocked and logged

### Text Fields (names, descriptions, memory text)

- Max length: 255 chars (names), 2000 chars (memory text)
- Forbidden characters: backtick, semicolon, null byte
- Pattern detection — flag (do not block) inputs containing:
  - `<script` or `</script>` — potential XSS
  - `../` or `..\` — path traversal
  - Cypher keywords in unexpected context: `DETACH DELETE`, `DROP`, `CALL dbms`
  - SQL keywords in unexpected context: `DROP TABLE`, `DELETE FROM`, `UNION SELECT`

### Preference Fields (Phase 3)

- Style: allowlist `[formal, informal, brief, detailed, balanced]`
- Priorities: allowlist `[speed, quality, learning, exploration]`
- Language: allowlist or ISO 639-1 codes
- Name: max 50 chars, no forbidden characters

## Audit Trail

### Log Location

`logs/security-audit.log` (append-only, created on first write)

### Log Format

```
[TIMESTAMP] [LEVEL] [SOURCE] [TYPE] [ACTION] — DETAILS
```

Fields:
- **TIMESTAMP**: ISO 8601
- **LEVEL**: `INFO | WARN | BLOCK`
- **SOURCE**: phase name or script name (e.g., `phase3`, `memory_write`)
- **TYPE**: `identifier | text | preference | pattern`
- **ACTION**: `blocked | sanitized | flagged | passed`
- **DETAILS**: truncated input (max 100 chars, sensitive data redacted)

### Examples

```
[2026-03-02T14:30:00Z] [BLOCK] [memory_write] [identifier] [blocked] — Invalid entity type: "Person`} SET n.admin=true"
[2026-03-02T14:30:01Z] [WARN] [phase3] [pattern] [flagged] — XSS pattern in name field: "<script>aler..."
[2026-03-02T14:30:02Z] [INFO] [phase3] [preference] [sanitized] — Empty style → default "balanced"
```

## Escalation

| Condition | Action |
|-----------|--------|
| 1 flagged input | Log WARN, continue |
| 3+ flagged inputs in session | Log WARN, notify coordinator |
| Any blocked input | Log BLOCK, notify user with explanation |
| Repeated blocks from same source | Flag as potential adversarial — coordinator decides next step |
| Coordinator receives escalation warning | Review flagged inputs in audit log. If legitimate → clear flags and note in memory. If suspicious → ask user to re-enter input. If malicious pattern (3+ blocks in single session) → terminate input collection, apply all defaults, store security event in memory: `{type: "security", action: "defaults_applied"}` |

### Research Data Validation

| Event | Level | Action |
|-------|-------|--------|
| Record passes all checks | INFO | Log: record file, type, timestamp |
| Record fails schema/size check | BLOCK | Log violation details, reject record |
| PII detected in record | BLOCK | Log PII type (not the PII itself), reject record |
| Prompt injection detected | BLOCK | Log pattern type, reject record, flag for review |

### Build-Up Security

| Event | Level | Action |
|-------|-------|--------|
| Build-Up modifies immutable block | BLOCK | Reject build-up, log attempted modification target |
| Build-Up targets protected file | BLOCK | Reject build-up, log file path |
| Build-Up weakens security rule | BLOCK | Reject build-up, log rule being weakened |
| Build-Up passes all security checks | INFO | Log: build-up type, files changed |

## Sensitive Data Rules

**NEVER log:**
- API keys, passwords, tokens (match patterns: `sk-`, `ghp_`, `Bearer`, `password=`)
- Full file paths containing `secrets/` or `.env`
- User email addresses or phone numbers

**ALWAYS redact before logging:**
- Truncate to 100 chars max
- Replace matched sensitive patterns with `[REDACTED]`

## Integration Points

| Component | How Security Logging Applies |
|-----------|------------------------------|
| `memory_write.py` | `sanitize_identifier()` blocks invalid labels/relations, logs to audit trail |
| Phase 3 (initialization) | Validate preferences against allowlists, flag pattern matches |
| Agent dispatch | Flag task descriptions with suspicious patterns |
| Build-Up records | Validate before storage, redact sensitive data |

## Implementation Notes

- Security logging is advisory, not blocking (except for identifiers which MUST be blocked)
- The coordinator makes final decisions on flagged inputs
- This protocol works with the existing memory layer — no new infrastructure needed
- Log file rotation: coordinator should archive when `security-audit.log` exceeds 1MB
