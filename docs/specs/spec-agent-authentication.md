# Spec: Agent Identity & Authentication + CORS + Approve-Mode

**Status:** PROPOSED
**Domain:** Exchange Security — Agent Authentication
**Created:** 2026-03-03
**Related files:** `infra/exchange-shared/app.py`, `infra/responder/watcher.py`, `secrets/.env`

---

## Problem Statement

### 1. No Agent Identity Verification

Any process that can reach port 8888 can POST a message claiming to be any agent. The `from_agent` field (lines 141–155 in `app.py`) is validated only by a regex:

```python
VALID_AGENT_RE = re.compile(r"^[a-zA-Z0-9_]{1,50}$")
```

This confirms format but not identity. A message with `from_agent: "okiara"` is accepted from any caller — local or network.

### 2. Wildcard CORS

`app.py` line 131–135:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    ...
)
```
This allows browser-originated cross-origin requests from any domain to the exchange API, widening the attack surface unnecessarily for a system that only has two known local clients.

### 3. Approve-Mode Has No Auth

`PATCH /settings/approve-mode` (lines 578–585 in `app.py`) modifies the in-memory `approve_mode_store` with no authentication or authorization check. Any process that can reach port 8888 can enable or disable approve-mode for any agent — including enabling auto-approval for all `approval`-type messages.

---

## Current State

### `infra/exchange-shared/app.py` — key lines

**Line 54:** `VALID_AGENT_RE = re.compile(r"^[a-zA-Z0-9_]{1,50}$")` — only format validation, no secret.

**Lines 130–135:** `CORSMiddleware` with `allow_origins=["*"]` — wildcard.

**Lines 141–191:** `MessageCreate` schema. `from_agent` is caller-supplied string, validated regex-only (lines 151–155). No HMAC header extraction.

**Lines 272–325:** `create_message` — inserts message directly after Pydantic validation. No signature verification call anywhere in the handler or as middleware.

**Lines 379–401:** `update_message_status` (PATCH `/messages/{id}`) — no auth check; any caller can mark any message as read/processed/approved.

**Lines 578–585:** `update_approve_mode` (PATCH `/settings/approve-mode`) — no auth check; any caller can toggle approve-mode for any agent with any duration.

### `infra/responder/watcher.py` — key lines

**Lines 141–161:** `_post_response()` — constructs POST payload and calls `requests.post(f"{exchange_url}/messages", json=payload, timeout=10)`. No `X-Agent-Sig` header. No `X-Timestamp` header. No `X-Agent-Name` header.

**Lines 127–138:** `_patch_status()` — calls `requests.patch(f"{exchange_url}/messages/{msg_id}", json={"status": status})`. No auth headers.

**Lines 91–121:** `_heartbeat_loop()` — calls `requests.post(f"{exchange_url}/presence/falkvelt", json={"state": "online"})`. No auth headers.

**Lines 217–228:** `_handle_knowledge_import()` — uses `subprocess.run` to call `memory_write.py`. Outgoing exchange calls are `_patch_status` only (line 232), also unsigned.

### `secrets/.env` — current state

Contains infrastructure credentials (Qdrant, Neo4j ports/URLs/passwords) but no exchange-specific secrets:

```
QDRANT_PORT=6333
NEO4J_PASSWORD=workflow
# ... no EXCHANGE_HMAC_SECRET
# ... no EXCHANGE_INTERNAL_TOKEN
```

---

## Pre-Decision: HMAC-SHA256 Shared Secret

Ed25519 asymmetric key pairs were considered but rejected for this use case:
- Two known, fixed agents on the same machine
- No need for third-party verification
- No key distribution problem
- Implementation: ~10 lines of Python vs ~50+ for asymmetric

**Decision:** HMAC-SHA256 with a shared secret stored in `secrets/.env`. Both `app.py` (verifier) and `watcher.py` (signer) read the same file.

---

## Proposed Solution

### 1. Key Storage

Add two variables to `secrets/.env`:

```bash
# Exchange HMAC authentication (64-byte hex random secret)
EXCHANGE_HMAC_SECRET=<generated: python3 -c "import secrets; print(secrets.token_hex(32))">

# Internal token for approve-mode endpoint (32-byte hex)
EXCHANGE_INTERNAL_TOKEN=<generated: python3 -c "import secrets; print(secrets.token_hex(16))">
```

**Generation:** both values generated once at deployment time using Python's `secrets.token_hex()` (CSPRNG-backed). Not committed to git (`.env` is already gitignored).

**Rotation strategy:** manual. Run the generator, update `.env`, restart both `app.py` (via Docker container restart) and `watcher.py`. No grace period needed — both processes restart simultaneously since they run locally. Rotation recommended: every 90 days or on suspected compromise.

### 2. Header Format Specification

Every POST and PATCH request sent to the exchange must include three headers:

| Header | Value | Example |
|---|---|---|
| `X-Agent-Name` | Sender agent identifier | `falkvelt` |
| `X-Timestamp` | ISO 8601 UTC timestamp at signing time | `2026-03-03T14:22:01Z` |
| `X-Agent-Sig` | HMAC-SHA256 hex digest of the canonical signing string | `a3f9...` |

**Canonical signing string:**

```
{X-Timestamp}|{X-Agent-Name}|{body_sha256_hex}
```

Where `body_sha256_hex` is the SHA-256 hex digest of the raw request body bytes. For requests with no body (e.g. some GETs), use SHA-256 of empty bytes: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

**Why include body hash in the signing string:**
- Prevents replay of a valid signature with a substituted body.
- Ties the signature to the exact bytes on the wire.
- Same pattern used by AWS Signature Version 4 and other production HMAC API authentication schemes.

**HMAC computation:**
```python
import hashlib, hmac
signing_string = f"{timestamp}|{agent_name}|{body_hash_hex}"
sig = hmac.new(secret.encode(), signing_string.encode(), hashlib.sha256).hexdigest()
```

### 3. FastAPI Middleware (app.py)

A new `HMACAuthMiddleware` class inserted before request handlers:

**Protected methods:** POST, PATCH, DELETE.
**Excluded paths:** GET-only endpoints (`/`, `/messages`, `/chain/*`, `/activities`, `/stream*`, `/presence GET`) need no protection since they are read-only. The `/presence/{agent}` POST is authenticated (watcher signs its heartbeat).

**Verification logic:**

1. Extract `X-Agent-Name`, `X-Timestamp`, `X-Agent-Sig` from request headers.
2. If any header is missing: return `401 Unauthorized` with body `{"detail": "Missing auth headers"}`.
3. Parse `X-Timestamp`. If the timestamp is more than **60 seconds** in the past or future: return `401` with `{"detail": "Timestamp expired"}`. This is the replay-attack window.
4. Read raw request body bytes (without consuming the stream — FastAPI requires body to be re-injected or buffered).
5. Compute `body_hash_hex = hashlib.sha256(body_bytes).hexdigest()`.
6. Rebuild canonical signing string: `f"{x_timestamp}|{x_agent_name}|{body_hash_hex}"`.
7. Compute expected HMAC: `hmac.new(EXCHANGE_HMAC_SECRET.encode(), signing_string.encode(), sha256).hexdigest()`.
8. Compare using `hmac.compare_digest(expected, x_agent_sig)` — constant-time comparison prevents timing attacks.
9. If mismatch: return `401` with `{"detail": "Invalid signature"}`.
10. If valid: pass request to handler.

**Error logging:** log all 401s with agent name, path, and reason — feeds into future anomaly detection.

### 4. Watcher Signing (watcher.py)

Modify three outbound call sites to add HMAC headers.

**Helper function** (add to watcher.py):
```python
def _make_auth_headers(agent_name: str, body_bytes: bytes, secret: str) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    signing_string = f"{ts}|{agent_name}|{body_hash}"
    sig = hmac.new(secret.encode(), signing_string.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Agent-Name": agent_name,
        "X-Timestamp": ts,
        "X-Agent-Sig": sig,
    }
```

Secret loaded once at startup from `secrets/.env` via `os.environ.get("EXCHANGE_HMAC_SECRET")`. If absent, watcher logs a WARNING and falls back to unsigned mode (for backward compat during rollout).

**Call sites to update:**

- `_post_response()` (line 153): add `headers=_make_auth_headers("falkvelt", json.dumps(payload).encode(), secret)` to `requests.post(...)`.
- `_patch_status()` (line 130): serialize patch body to bytes, compute headers, add to `requests.patch(...)`.
- `_heartbeat_loop()` (line 97): serialize presence body to bytes, compute headers, add to `requests.post(...)`.

### 5. CORS Fix

Replace wildcard with explicit localhost origins. The exchange UI is accessed via browser on the same machine, and both agents are local processes — no cross-origin browser access from external domains is needed.

**Replace lines 130–135 in app.py:**

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8888",
        "http://127.0.0.1:8888",
        "http://localhost:3000",   # dev tooling / future UI on separate port
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Agent-Name", "X-Timestamp", "X-Agent-Sig",
                   "X-Internal-Token"],
    allow_credentials=False,
)
```

`allow_credentials=False` is correct here — no browser cookies are used. Explicit method list is also preferred over wildcard for least-privilege.

### 6. Approve-Mode Protection

`PATCH /settings/approve-mode` controls auto-approval behavior — it must be limited to trusted local calls only.

**Mechanism:** require an `X-Internal-Token` header matching `EXCHANGE_INTERNAL_TOKEN` from `.env`. This is separate from the HMAC signature because approve-mode is a privileged admin operation, not a standard agent message, and the token check is simpler and more explicit.

**In app.py**, the `update_approve_mode` handler gains a dependency:

```python
from fastapi import Header

async def update_approve_mode(
    body: ApproveModeUpdate,
    x_internal_token: Optional[str] = Header(default=None),
) -> dict:
    expected = os.environ.get("EXCHANGE_INTERNAL_TOKEN", "")
    if not expected or not hmac.compare_digest(x_internal_token or "", expected):
        raise HTTPException(status_code=403, detail="Forbidden")
    ...
```

**`GET /settings/approve-mode`** remains unauthenticated (read-only, no state change).

---

## Key Storage and Rotation Strategy Summary

| Secret | Variable | Length | Rotation |
|---|---|---|---|
| HMAC signing key | `EXCHANGE_HMAC_SECRET` | 64 hex chars (32 bytes) | Every 90 days or on compromise |
| Approve-mode token | `EXCHANGE_INTERNAL_TOKEN` | 32 hex chars (16 bytes) | On compromise only |

Both secrets are:
- Read from environment at startup (not hardcoded).
- Never returned by any API endpoint.
- Stored only in `secrets/.env` — which is gitignored.

---

## Security Properties After Implementation

| Threat | Before | After |
|---|---|---|
| Spoofed `from_agent` | Undetected — regex only | Blocked — HMAC verifies sender identity |
| Replay attack (reused signature) | N/A | Blocked — 60s timestamp window |
| Body substitution with valid headers | N/A | Blocked — body hash is part of signing string |
| Cross-origin browser request | Allowed from any domain | Restricted to localhost origins only |
| Unauthorized approve-mode toggle | Any caller | Requires `X-Internal-Token` |
| Timing attack on token comparison | Potentially vulnerable | `hmac.compare_digest()` prevents it |

---

## Impact on Files

| File | Change |
|---|---|
| `infra/exchange-shared/app.py` | Add `HMACAuthMiddleware` class. Tighten CORS origins list and allowed methods/headers. Add `X-Internal-Token` check to `update_approve_mode` handler. Load `EXCHANGE_HMAC_SECRET` and `EXCHANGE_INTERNAL_TOKEN` from environment. |
| `infra/responder/watcher.py` | Add `_make_auth_headers()` helper. Load `EXCHANGE_HMAC_SECRET` at startup. Apply headers to `_post_response()`, `_patch_status()`, and `_heartbeat_loop()`. |
| `secrets/.env` | Add `EXCHANGE_HMAC_SECRET` and `EXCHANGE_INTERNAL_TOKEN` with generated values. |

---

## References

- [Securing APIs with HMAC Signing in Python (2026)](https://oneuptime.com/blog/post/2026-01-22-hmac-signing-python-api/view)
- [FastAPI CORS official docs](https://fastapi.tiangolo.com/tutorial/cors/)
- [FastAPI HMAC middleware example](https://github.com/vaasugambhir/hmac-fastapi)
- [Secure API with HMAC — implementation patterns](https://www.linkedin.com/pulse/secure-api-hmac-lei-niu-uq9ae)
