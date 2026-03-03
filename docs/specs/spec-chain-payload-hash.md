# Spec: Chain Payload Hash Inclusion

**Status:** PROPOSED
**Domain:** Exchange Security — Chain Integrity
**Created:** 2026-03-03
**Related files:** `infra/exchange-shared/chain.py`, `infra/exchange-shared/app.py`

---

## Problem Statement

The exchange hash chain currently computes block hashes from message metadata and a hash of the `body` field (a plain-text string), but **excludes the `payload` field** entirely. `payload` is a structured JSON dict, up to 15KB, that carries typed inter-agent data (ping/pong, status_request, knowledge digests, and future action types).

Because `payload` is omitted from the block hash, an attacker with direct SQLite write access — or a compromised process — can modify `payload` in `messages.payload` without invalidating the chain. This defeats the tamper-evidence guarantee for the most semantically rich part of a message.

---

## Current State

### `infra/exchange-shared/chain.py` — key lines

**Lines 15–21** — `compute_block_hash`: builds a pipe-delimited string from nine fields; `payload` is absent.

```python
def compute_block_hash(
    prev_hash: str, block_number: int, timestamp: str,
    message_id: str, from_agent: str, to_agent: str,
    msg_type: str, subject: str, body_hash: str,
) -> str:
    payload = f"{prev_hash}|{block_number}|{timestamp}|{message_id}|{from_agent}|{to_agent}|{msg_type}|{subject}|{body_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

**Lines 34–81** — `append_block`: extracts `body_hash` from `message["body"]`, calls `compute_block_hash`, writes JSONL block record. `message["payload"]` is never read.

**Lines 84–122** — `verify_chain`: recomputes each block's expected hash using `compute_block_hash` with the same nine-argument signature. No payload field in the block dict, no payload verification possible.

### `infra/exchange-shared/app.py` — key lines

**Lines 90–94** — idempotent `ALTER TABLE` adds `payload TEXT` column to SQLite schema.

**Lines 141–191** — `MessageCreate` Pydantic model: `payload: Optional[dict]`. Validated: serialized size <= 15000 chars (line 188–190).

**Lines 272–325** — `create_message`: serializes `payload.payload` via `json.dumps()` (line 276) and inserts into DB. Immediately after insert, calls `append_block(conn, dict(row))` (line 303). The `dict(row)` at this point contains `payload` as a JSON string — but `append_block` ignores it.

**Exploit path:** After `create_message` returns, any process with SQLite write access executes:
```sql
UPDATE messages SET payload = '{"action":"malicious"}' WHERE id = '<uuid>';
```
`verify_chain()` reports `{"valid": true}` because `payload` was never hashed.

---

## Proposed Solution

### 1. Add `compute_payload_hash()` function

A new helper function in `chain.py`:

- **Input:** `payload` — either `None`, a `dict`, or a JSON string.
- **Canonical serialization:** convert to `dict` if string, then `json.dumps(payload_dict, sort_keys=True, separators=(',', ':'), ensure_ascii=False)`.
  - `sort_keys=True` guarantees key order is deterministic regardless of insertion order (confirmed standard by RFC 8785 / JCS and Python stdlib docs).
  - `separators=(',', ':')` removes all whitespace — produces compact, unambiguous bytes.
  - `ensure_ascii=False` preserves non-ASCII characters faithfully instead of escaping them.
- **If payload is None:** use the sentinel string `"null"` (the literal JSON null representation) as input to SHA-256, yielding a stable, predictable hash for empty payloads.
- **Output:** SHA-256 hex digest of the canonical bytes (UTF-8 encoded).

This matches the de-facto standard for JSON object signing (used by JWS, JOSE, and documented in RFC 8785). The `json.dumps(sort_keys=True)` approach is specifically recommended over libraries like `canonicaljson` for local systems where full JCS compliance is not required.

### 2. Extend `compute_block_hash()` signature

Add `payload_hash: str` as a tenth parameter:

```
compute_block_hash(prev_hash, block_number, timestamp, message_id,
                   from_agent, to_agent, msg_type, subject, body_hash,
                   payload_hash)
```

The pipe-delimited input string gains one additional segment:

```
"{prev_hash}|{block_number}|{timestamp}|{message_id}|{from_agent}|{to_agent}|{msg_type}|{subject}|{body_hash}|{payload_hash}"
```

**Why append rather than insert:** appending preserves the existing prefix for conceptual clarity during migration; ordering within the string is arbitrary for SHA-256 security, but consistency with prior format aids readability.

### 3. Extend block dict (JSONL record)

`append_block` must store `payload_hash` in the written JSONL block so `verify_chain` can re-verify it later:

```json
{
  "block_number": 42,
  "hash": "...",
  "prev_hash": "...",
  "timestamp": "...",
  "message_id": "...",
  "from_agent": "...",
  "to_agent": "...",
  "type": "...",
  "priority": "...",
  "subject": "...",
  "body_hash": "...",
  "body_length": 120,
  "payload_hash": "e3b0c44..."
}
```

### 4. Update `verify_chain()` logic

Two cases in the verification loop:

- **Block has `payload_hash` key:** use it in `compute_block_hash` call and also re-derive expected hash from stored `payload_hash` field value — if the stored field itself is corrupted, the outer block hash mismatch catches it.
- **Block does NOT have `payload_hash` key (legacy block):** call `compute_block_hash` with the nine-argument legacy signature (or pass a sentinel), skip payload-specific checks. Log a warning: `"Block N: legacy format, payload not covered"`.

This "skip if absent" logic preserves chain continuity across the migration boundary.

---

## Migration Plan

### Scope

Existing blocks in `chain.jsonl` were written without `payload_hash`. They cannot be retroactively re-hashed without breaking the prev_hash linkage (changing a block hash invalidates all subsequent blocks). The correct migration approach is **forward-only** with a one-time annotation pass.

### Step 1 — Annotation pass (run once, offline)

A migration script reads every block from `chain.jsonl` and every corresponding `messages` row from SQLite. For each block without `payload_hash`:

1. Read `messages.payload` from SQLite for the corresponding `message_id`.
2. Compute `payload_hash` using the new `compute_payload_hash()` function.
3. Rewrite the JSONL line with `payload_hash` appended.

**Critical:** the block's `hash` field is NOT recalculated. The `payload_hash` annotation is stored as metadata alongside the existing hash, not as part of it. `verify_chain` for legacy blocks validates only the original nine-field hash; the annotated `payload_hash` is informational only.

This means the annotation pass produces a "soft" tamper-evidence layer for existing messages — the payload hash is stored and checkable, but not chain-linked. Acceptable for a local 2-agent system where the chain primarily guards against future tampering.

### Step 2 — Post-migration: all new blocks use the new signature

From the moment the updated `chain.py` is deployed, all new `append_block` calls produce ten-field hashes including `payload_hash`. The chain is effectively versioned at the natural migration boundary.

### Step 3 — Chain meta versioning (optional but recommended)

Store `chain_version = "2"` in `chain_meta` table after migration. `verify_chain` can use this to determine whether to apply the nine-field or ten-field hash logic globally, rather than per-block key presence.

---

## Backward Compatibility Notes

| Scenario | Handling |
|---|---|
| Old block (no `payload_hash` in JSONL) | `verify_chain` calls nine-field `compute_block_hash`, skips payload check. Chain remains valid. |
| New block (has `payload_hash`) | `verify_chain` calls ten-field `compute_block_hash`. Both block hash and payload coverage verified. |
| `payload = null` in DB | `compute_payload_hash(None)` returns SHA-256 of `"null"`. Deterministic, stable. |
| `payload` is a dict with varying key order | `sort_keys=True` normalizes order. Same dict always produces same hash. |
| Payload contains non-ASCII | `ensure_ascii=False` preserves encoding; no double-escaping artifacts. |
| GitHub sync of JSONL | Annotation pass outputs valid JSON per line. GitHub push logic unchanged. |

---

## Impact on Files

| File | Change |
|---|---|
| `infra/exchange-shared/chain.py` | Add `compute_payload_hash()`. Extend `compute_block_hash()` signature (+1 param). Update `append_block()` to compute and store `payload_hash`. Update `verify_chain()` with legacy/new branch logic. |
| `infra/exchange-shared/app.py` | No logic change required. `dict(row)` passed to `append_block` already includes `payload` string from SQLite row. `append_block` reads it. |
| Migration script (new) | One-time `scripts/migrate_chain_payload_hash.py` — annotation pass on existing JSONL + chain_meta version bump. |

---

## References

- [RFC 8785: JSON Canonicalization Scheme (JCS)](https://www.rfc-editor.org/rfc/rfc8785)
- [Securing JSON objects with HMAC + canonical serialization](https://connect2id.com/blog/how-to-secure-json-objects-with-hmac)
- [Deterministic hashing of Python data objects](https://death.andgravity.com/stable-hashing)
