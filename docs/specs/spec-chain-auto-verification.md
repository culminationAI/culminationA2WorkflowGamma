# Spec: Chain Auto-Verification
**Domain:** Exchange Security — Domain 3 (P3 + P7)
**Date:** 2026-03-03
**Status:** Draft
**Author:** pathfinder (research mission)

---

## 1. Problem Statement

The blockchain hash chain in `infra/exchange-shared/chain.py` provides tamper-evidence for all inter-agent messages via a JSONL append-only log (`chain.jsonl`). However, `verify_chain()` is only exposed as an on-demand HTTP endpoint (`GET /chain/verify`) and is **never called automatically**.

This creates three concrete gaps:

1. **No startup verification** — a corrupted or tampered `chain.jsonl` can go undetected indefinitely if `GET /chain/verify` is never manually called.
2. **No periodic monitoring** — corruption introduced at runtime (e.g., storage error, external file write) would remain silent until the next manual call.
3. **No per-agent checkpoints** — there is no record of which block each agent last verified, making it impossible to audit "what was the chain state when agent X last checked it?".

---

## 2. Current State

### 2.1 Lifespan (app.py, lines 118–121)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
```

The lifespan does exactly one thing: `init_db()`. No chain verification is performed. No background tasks are spawned. The `yield` returns control immediately to FastAPI's server loop.

### 2.2 `verify_chain()` (chain.py, lines 84–122)

```python
def verify_chain() -> dict:
    """Read chain.jsonl and verify every block's hash + prev_hash linkage."""
    if not CHAIN_FILE.exists():
        return {"valid": True, "blocks": 0, "errors": []}

    errors = []
    prev_hash = GENESIS_HASH
    count = 0

    with open(CHAIN_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            ...
            count += 1
            if block["prev_hash"] != prev_hash:
                errors.append(...)
            expected = compute_block_hash(...)
            if block["hash"] != expected:
                errors.append(...)
            prev_hash = block["hash"]

    return {"valid": len(errors) == 0, "blocks": count, "errors": errors}
```

**Performance characteristics:**
- O(N) sequential scan of all blocks — reads and parses every line of `chain.jsonl`
- For each block: two SHA-256 hashes (`compute_body_hash` + `compute_block_hash`) — negligible per block
- Bottleneck: **disk I/O** and **JSON parsing**, not CPU
- Benchmark estimate:
  - 1,000 blocks ≈ ~50ms (fast SSD, small records)
  - 10,000 blocks ≈ ~400–600ms (acceptable for background task)
  - 50,000 blocks ≈ ~2–4s (acceptable on startup, background only)
  - 100,000+ blocks → **compaction threshold** (see Section 6)
- The function is **synchronous** — it must be wrapped with `asyncio.to_thread()` when called from async context to avoid blocking the event loop.

### 2.3 Chain endpoint (app.py, line 432–434)

```python
@app.get("/chain/verify")
async def verify_chain_endpoint() -> dict:
    return verify_chain()
```

Currently calls `verify_chain()` directly in the async handler — **this is already a blocking call** in the event loop, a pre-existing issue that the periodic task design should also fix.

### 2.4 `/chain/status` endpoint (app.py, lines 437–446)

Returns `last_block_number`, `last_block_hash`, and `github_synced` from `chain_meta`. Does **not** expose verification health. This endpoint will be extended to include verification state.

---

## 3. Proposed Solution

### 3.1 Startup Hook

In the `lifespan()` function, call `verify_chain()` immediately after `init_db()` using `asyncio.to_thread()` to avoid blocking the event loop during startup. Log the result. Set the global chain health flag.

**Implementation sketch:**

```python
# app.py — module-level state
_chain_health: dict = {"valid": None, "blocks": 0, "errors": [], "last_checked": None}

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Startup: verify chain integrity
    result = await asyncio.to_thread(verify_chain)
    _chain_health.update({
        "valid": result["valid"],
        "blocks": result["blocks"],
        "errors": result["errors"],
        "last_checked": datetime.now(timezone.utc).isoformat(),
    })
    log = logging.getLogger("exchange")
    if result["valid"]:
        log.info(f"Chain startup verify OK: {result['blocks']} blocks")
    else:
        log.error(f"Chain startup verify FAILED: {result['errors']}")

    # Launch periodic verification background task
    task = asyncio.create_task(_periodic_chain_verify())

    yield

    # Shutdown: cancel periodic task cleanly
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

Key points:
- `asyncio.to_thread()` — runs synchronous `verify_chain()` in a thread pool, non-blocking
- Task reference stored → cancelled on shutdown (prevents dangling task warning)
- Startup errors are **logged as ERROR** but do NOT crash the server (the exchange must remain reachable even if the chain file is absent or corrupt — agents should be able to alert via the API)

### 3.2 Periodic Background Task

```python
CHAIN_VERIFY_INTERVAL = 6 * 3600  # 6 hours in seconds

async def _periodic_chain_verify() -> None:
    """Background task: verify chain every 6 hours."""
    log = logging.getLogger("exchange")
    while True:
        await asyncio.sleep(CHAIN_VERIFY_INTERVAL)
        try:
            result = await asyncio.to_thread(verify_chain)
            _chain_health.update({
                "valid": result["valid"],
                "blocks": result["blocks"],
                "errors": result["errors"],
                "last_checked": datetime.now(timezone.utc).isoformat(),
            })
            if result["valid"]:
                log.info(f"Chain periodic verify OK: {result['blocks']} blocks")
            else:
                log.error(f"Chain periodic verify FAILED: {len(result['errors'])} errors")
        except Exception as exc:
            log.error(f"Chain periodic verify exception: {exc}")
```

Design decisions:
- `asyncio.create_task()` inside lifespan (not `BackgroundTasks`) — correct pattern for long-running loops that must outlive request handlers
- `while True: await asyncio.sleep(N)` — idiomatic Python asyncio periodic pattern; no external scheduler (no APScheduler, no Celery)
- Sleep-first design: startup verify already ran at `yield` time; first periodic check is at T+6h
- Exception-safe: `try/except` prevents the loop from dying on transient errors (e.g., file locked during GitHub sync)

### 3.3 Per-Agent Verification Checkpoints

After each verify (startup + periodic), write per-agent checkpoint records to `chain_meta`:

```
key: "{agent_name}_last_verified_block"
value: JSON string: {"block_number": N, "block_hash": "...", "timestamp": "ISO8601"}
```

**Why `chain_meta`?**
- Already exists in SQLite, already used for `last_block_number` and `last_block_hash`
- No schema migration needed — `chain_meta` is a free-form key/value store
- Accessible via existing DB connection, no new table

**Implementation:**

```python
async def _run_verify_and_checkpoint(agents: list[str]) -> dict:
    """Verify chain and write per-agent checkpoints to chain_meta."""
    result = await asyncio.to_thread(verify_chain)
    ts = datetime.now(timezone.utc).isoformat()

    if result["valid"] and result["blocks"] > 0:
        checkpoint = json.dumps({
            "block_number": result["blocks"],
            "block_hash": _chain_health.get("last_block_hash", ""),
            "timestamp": ts,
        })
        with get_conn() as conn:
            for agent in agents:
                conn.execute(
                    "INSERT OR REPLACE INTO chain_meta (key, value) VALUES (?, ?)",
                    (f"{agent}_last_verified_block", checkpoint),
                )
            conn.commit()
    return result
```

Agents to checkpoint: `["falkvelt", "okiara"]` — both participants. Hardcoded for this 2-agent system; extend if agents are added.

**Checkpoint accessible via:**

```
GET /chain/status  →  (extended to include per-agent checkpoints)
```

### 3.4 Alert Mechanism

The `_chain_health` dict (in-memory, reset on restart) acts as the alert state. The `/chain/status` endpoint is extended to expose it:

```python
@app.get("/chain/status")
async def chain_status() -> dict:
    with get_conn() as conn:
        meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM chain_meta").fetchall()}
    return {
        "last_block_number": int(meta.get("last_block_number", 0)),
        "last_block_hash": meta.get("last_block_hash", GENESIS_HASH)[:16] + "...",
        "github_synced": "github_file_sha" in meta,
        "github_file_sha": (meta.get("github_file_sha", "")[:12] + "...") if "github_file_sha" in meta else None,
        # NEW: verification health
        "chain_valid": _chain_health["valid"],
        "chain_blocks_verified": _chain_health["blocks"],
        "chain_last_checked": _chain_health["last_checked"],
        "chain_errors": _chain_health["errors"],  # empty list if valid
        # NEW: per-agent checkpoints
        "checkpoints": {
            agent: json.loads(meta[f"{agent}_last_verified_block"])
            for agent in ["falkvelt", "okiara"]
            if f"{agent}_last_verified_block" in meta
        },
    }
```

Alert escalation options (in order of implementation cost):
1. **Log-only (minimal):** Already covered — `log.error()` on failure. Ops/monitoring can tail logs.
2. **Status flag (implemented above):** `chain_valid: false` on `/chain/status` — watcher.py can poll this.
3. **Presence state update:** If chain invalid, update `presence_store["falkvelt"]["state"] = "busy"` with a `chain_error` detail field. This makes the failure visible to OkiAra via `/presence/falkvelt`.
4. **Exchange message (optional):** Post a notification message to the exchange from `falkvelt` to `okiara` with type `notification` and subject `"chain integrity failure"` — visible in the UI.

Recommended implementation order: 1 → 2 → 3. Option 4 creates a circularity risk (the chain itself is broken, should we trust the exchange to report it?).

---

## 4. Chain Compaction / Archival Recommendation

### 4.1 Performance Analysis

`verify_chain()` is O(N) with disk I/O dominant. At ~200–400 bytes per JSONL line (a typical block), storage and verification time scale linearly:

| Blocks | File size (est.) | Verify time (est.) | Action |
|--------|------------------|--------------------|--------|
| < 5,000 | < 2 MB | < 200ms | No action |
| 5,000–15,000 | 2–6 MB | 200ms–600ms | Monitor |
| 15,000–50,000 | 6–20 MB | 600ms–2s | Consider compaction |
| > 50,000 | > 20 MB | > 2s | **Archive** |

For a 2-agent system exchanging ~10–50 messages/day, reaching 50K blocks takes ~3–13 years. Compaction is a **low-priority future concern**, not immediate.

### 4.2 Archival Strategy (When Needed)

When `verify_chain()` returns `blocks > COMPACTION_THRESHOLD` (recommend `50_000`):

1. **Snapshot archival:** Copy current `chain.jsonl` → `chain-archive-{YYYYMMDD}.jsonl.gz` (gzip, ~10:1 compression)
2. **Anchor block:** Create a new genesis-like block in a fresh `chain.jsonl` containing the hash of the last block in the archived file. This preserves verifiable continuity.
3. **Index update:** Write to `chain_meta`: `archive_pointer = {"file": "chain-archive-20261201.jsonl.gz", "last_block": N, "last_hash": "..."}`
4. **Periodic verify scope:** After compaction, `verify_chain()` only verifies the active (non-archived) portion. Full historical verify can be done on demand.

Compaction should be operator-triggered (not automatic) to avoid data loss risk. Add a `POST /chain/compact` endpoint (admin-only) when needed.

---

## 5. Impact on Files

| File | Change | Details |
|------|--------|---------|
| `infra/exchange-shared/app.py` | Modified | Add `_chain_health` dict; extend `lifespan()` with startup verify + `asyncio.create_task()`; add `_periodic_chain_verify()` coroutine; extend `/chain/status` response; update `/chain/verify` endpoint to use `asyncio.to_thread()` |
| `infra/exchange-shared/chain.py` | None | `verify_chain()` is already correct. No changes needed. Optionally: add `verify_chain_from_offset(start_block)` for incremental verification (future optimization). |

---

## 6. Open Questions

1. **Incremental verification:** Should periodic verify re-verify ALL blocks, or only blocks since the last checkpoint? For a small chain (<10K blocks), full re-verify every 6h is fine. For large chains, incremental verify from `last_verified_block` would be more efficient. Design for full verify now; add incremental as optimization when compaction threshold is approached.
2. **Startup crash behavior:** If `verify_chain()` on startup returns `valid: False`, should the exchange refuse to accept new messages? Current design: log error, continue serving. This is the right default for a 2-agent local system.
3. **GitHub sync interaction:** The periodic verify and GitHub sync both run as background tasks. They both read `chain.jsonl`. No write conflicts (verify is read-only), but if GitHub sync is writing a new block simultaneously, the verify may see a partially-written line. Mitigation: `verify_chain()` already handles `json.JSONDecodeError` gracefully (line 101–102 in chain.py).
