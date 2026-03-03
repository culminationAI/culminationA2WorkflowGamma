"""
watcher.py — FalkVelt exchange live responder.

Dual-mode: SSE (preferred) with polling fallback.
Processes messages from OkiAra and auto-responds via `claude -p`.

Usage:
    python3 infra/responder/watcher.py
    python3 infra/responder/watcher.py --exchange-url http://localhost:8888 --poll-interval 3
    python3 infra/responder/watcher.py --workspace /path/to/workspace
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Bootstrap: resolve workspace and add it to sys.path so context.py imports
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent

# Allow running from any cwd
sys.path.insert(0, str(_SCRIPT_DIR))
import context as ctx_module  # noqa: E402  (after path manipulation)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_running = True
_processed_ids: set[str] = set()
_start_time: float = time.time()  # used for uptime_seconds in status_request responses


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------
def _handle_signal(sig: int, frame) -> None:  # type: ignore[type-arg]
    global _running
    _log("INFO", f"Received signal {sig}, shutting down...")
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(level: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Session lock check
# ---------------------------------------------------------------------------
SESSION_LOCK_MAX_AGE = 4 * 3600  # 4 hours in seconds


def _session_locked(workspace: str) -> bool:
    """Return True if a fresh (< 4h) .session_lock file exists."""
    lock_path = Path(workspace) / ".session_lock"
    if not lock_path.exists():
        return False
    age = time.time() - lock_path.stat().st_mtime
    if age < SESSION_LOCK_MAX_AGE:
        _log("INFO", f"Session lock active (age={int(age)}s), skipping claude -p")
        return True
    # Stale lock — ignore
    return False


# ---------------------------------------------------------------------------
# Heartbeat / presence
# ---------------------------------------------------------------------------
_heartbeat_warned = False  # emit WARNING at most once for non-404 errors


def _heartbeat_loop(exchange_url: str) -> None:
    """Send a presence heartbeat every 30 seconds while the watcher is running."""
    global _heartbeat_warned

    while _running:
        try:
            resp = requests.post(
                f"{exchange_url}/presence/falkvelt",
                json={"state": "online"},
                timeout=5,
            )
            if resp.status_code == 404:
                # Endpoint not yet implemented server-side — skip silently
                pass
            else:
                resp.raise_for_status()
        except requests.exceptions.HTTPError:
            # raise_for_status() on a non-404 HTTP error
            if not _heartbeat_warned:
                _log("WARNING", "Heartbeat: unexpected HTTP error from presence endpoint")
                _heartbeat_warned = True
        except Exception as exc:
            if not _heartbeat_warned:
                _log("WARNING", f"Heartbeat: failed to reach exchange ({exc})")
                _heartbeat_warned = True

        # Sleep in 1-second ticks so shutdown is responsive
        for _ in range(30):
            if not _running:
                return
            time.sleep(1)


# ---------------------------------------------------------------------------
# Exchange API helpers
# ---------------------------------------------------------------------------
def _patch_status(exchange_url: str, msg_id: str, status: str) -> None:
    """Update a message status on the exchange server."""
    try:
        resp = requests.patch(
            f"{exchange_url}/messages/{msg_id}",
            json={"status": status},
            timeout=10,
        )
        resp.raise_for_status()
        _log("INFO", f"Patched message {msg_id} -> {status}")
    except Exception as exc:
        _log("ERROR", f"Failed to patch message {msg_id}: {exc}")


def _post_response(exchange_url: str, original: dict, body: str) -> None:
    """Send a response message back via the exchange server."""
    payload = {
        "from_agent": "falkvelt",
        "to_agent": original.get("from_agent", "okiara"),
        "type": "response",
        "priority": "normal",
        "subject": f"Re: {original.get('subject', '')}",
        "body": body,
        "in_reply_to": original.get("id"),
    }
    try:
        resp = requests.post(
            f"{exchange_url}/messages",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        _log("INFO", f"Posted response to {payload['to_agent']} re: {original.get('id')}")
    except Exception as exc:
        _log("ERROR", f"Failed to post response: {exc}")


def _handle_knowledge_import(message: dict, exchange_url: str) -> None:
    """Handle incoming knowledge messages — store to memory without claude -p."""
    msg_id = message.get("id", "unknown")
    subject = message.get("subject", "")
    body_raw = message.get("body", "")
    from_agent = message.get("from_agent", "unknown")

    # Parse body as JSON digest(s)
    digests = []
    try:
        parsed = json.loads(body_raw)
        if isinstance(parsed, list):
            digests = parsed
        elif isinstance(parsed, dict):
            digests = [parsed]
        else:
            _log("WARNING", f"Knowledge message {msg_id}: body is not JSON object or array")
            _patch_status(exchange_url, msg_id, "read")
            return
    except (json.JSONDecodeError, TypeError):
        _log("WARNING", f"Knowledge message {msg_id}: body is not valid JSON, treating as text")
        # Fallback: store raw text as knowledge
        digests = [{
            "correction_id": msg_id,
            "summary": subject,
            "full_text": body_raw,
            "type": "knowledge",
            "severity": "normal",
            "source_agent": from_agent,
            "applicability": "universal"
        }]

    stored_count = 0
    for digest in digests:
        correction_id = digest.get("correction_id", msg_id)
        summary = digest.get("summary", subject)
        full_text = digest.get("full_text", "")
        severity = digest.get("severity", "normal")

        # Store to memory via memory_write.py
        record = json.dumps([{
            "text": f"Knowledge import from {from_agent}: {summary}. Full: {full_text}",
            "user_id": "user",
            "agent_id": "coordinator",
            "metadata": {
                "type": "knowledge_import",
                "status": "pending_review",
                "correction_id": correction_id,
                "from_agent": from_agent,
                "severity": severity
            }
        }])

        try:
            result = subprocess.run(
                ["python3", "memory/scripts/memory_write.py", record],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                stored_count += 1
                _log("INFO", f"Knowledge imported: {summary} — pending review")
            else:
                _log("ERROR", f"Failed to store knowledge: {result.stderr[:200]}")
        except Exception as exc:
            _log("ERROR", f"Error storing knowledge: {exc}")

    _patch_status(exchange_url, msg_id, "read")
    _log("INFO", f"Knowledge message {msg_id}: stored {stored_count}/{len(digests)} digests")


def _fetch_pending(exchange_url: str) -> list:
    """Fetch pending messages addressed to falkvelt."""
    try:
        resp = requests.get(
            f"{exchange_url}/messages",
            params={"to": "falkvelt", "status": "pending"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _log("ERROR", f"Failed to fetch pending messages: {exc}")
        return []


# ---------------------------------------------------------------------------
# claude -p invocation
# ---------------------------------------------------------------------------
def _run_claude(prompt: str) -> Optional[str]:
    """Run `claude -p <prompt>` and return stdout, or None on error."""
    # Build a clean environment: strip CLAUDECODE to avoid nested-session errors
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            env=clean_env,
            timeout=120,  # 2-minute hard limit per response
        )
        if result.returncode != 0:
            _log("ERROR", f"claude -p exited with code {result.returncode}: {result.stderr[:300]}")
            return None
        output = result.stdout.strip()
        if not output:
            _log("WARNING", "claude -p returned empty output")
            return None
        return output
    except FileNotFoundError:
        _log("ERROR", "claude binary not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        _log("ERROR", "claude -p timed out after 120s")
        return None
    except Exception as exc:
        _log("ERROR", f"Unexpected error running claude -p: {exc}")
        return None


# ---------------------------------------------------------------------------
# Core message processing
# ---------------------------------------------------------------------------
def _handle_message(message: dict, exchange_url: str, workspace: str) -> None:
    """Process a single incoming message."""
    msg_id = message.get("id", "unknown")
    msg_type = message.get("type", "")
    subject = message.get("subject", "")
    from_agent = message.get("from_agent", "")

    _log("INFO", f"Handling message {msg_id} type={msg_type} from={from_agent} subject={subject!r}")

    # Knowledge messages: store to memory without claude -p
    if msg_type == "knowledge":
        _handle_knowledge_import(message, exchange_url)
        _processed_ids.add(msg_id)
        return

    # Notifications and responses: just mark read, no reply needed
    if msg_type in ("notification", "response"):
        _patch_status(exchange_url, msg_id, "read")
        _processed_ids.add(msg_id)
        return

    # For all other types: mark read first, then check session lock
    _patch_status(exchange_url, msg_id, "read")

    # ------------------------------------------------------------------
    # Structured payload fast-path: handle known actions without claude -p
    # ------------------------------------------------------------------
    raw_payload = message.get("payload")
    payload: Optional[dict] = None

    if isinstance(raw_payload, dict):
        payload = raw_payload
    elif isinstance(raw_payload, str):
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            pass  # not valid JSON — treat as no payload

    if payload is not None:
        action = payload.get("action")
        if action == "ping":
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            response_body = json.dumps({"action": "pong", "timestamp": ts})
            _log("INFO", f"Payload action=ping — responding with pong (msg {msg_id})")
            _post_response(exchange_url, message, f"[AUTO/PAYLOAD] {response_body}")
            _patch_status(exchange_url, msg_id, "processed")
            _processed_ids.add(msg_id)
            return
        elif action == "status_request":
            uptime = int(time.time() - _start_time)
            response_body = json.dumps({
                "action": "status_response",
                "agent": "falkvelt",
                "state": "online",
                "uptime_seconds": uptime,
            })
            _log("INFO", f"Payload action=status_request — responding with status (msg {msg_id})")
            _post_response(exchange_url, message, f"[AUTO/PAYLOAD] {response_body}")
            _patch_status(exchange_url, msg_id, "processed")
            _processed_ids.add(msg_id)
            return
        # Unknown action — fall through to claude -p below

    if _session_locked(workspace):
        # Don't invoke claude -p while a live session is active
        _processed_ids.add(msg_id)
        return

    # Build prompt and call claude -p
    prompt = ctx_module.build_prompt(message, workspace)
    _log("INFO", f"Calling claude -p for message {msg_id}...")
    reply_text = _run_claude(prompt)

    if reply_text:
        prefixed = f"[AUTO] {reply_text}"
        _post_response(exchange_url, message, prefixed)
        _patch_status(exchange_url, msg_id, "processed")
    else:
        _log("WARNING", f"No reply generated for message {msg_id}")

    _processed_ids.add(msg_id)


# ---------------------------------------------------------------------------
# SSE mode
# ---------------------------------------------------------------------------
def _run_sse_mode(exchange_url: str, workspace: str, poll_interval: int) -> None:
    """Try SSE stream; on failure fall back to polling."""
    try:
        import sseclient  # noqa: F401 — presence check only
    except ImportError:
        _log("WARNING", "sseclient-py not installed, falling back to polling")
        _run_polling_mode(exchange_url, workspace, poll_interval)
        return

    import sseclient

    backoff = 1
    max_backoff = 30

    while _running:
        stream_url = f"{exchange_url}/stream?agent=falkvelt"
        _log("INFO", f"Connecting to SSE stream: {stream_url}")
        try:
            response = requests.get(stream_url, stream=True, timeout=60)
            if response.status_code == 404:
                _log("INFO", "SSE endpoint returned 404, switching to polling mode")
                _run_polling_mode(exchange_url, workspace, poll_interval)
                return

            response.raise_for_status()
            client = sseclient.SSEClient(response)
            backoff = 1  # reset on successful connect
            _log("INFO", "SSE connected")

            for event in client.events():
                if not _running:
                    break
                if not event.data or event.data.strip() == "":
                    continue
                try:
                    message = json.loads(event.data)
                except json.JSONDecodeError as exc:
                    _log("WARNING", f"SSE: failed to parse event data: {exc}")
                    continue

                msg_id = message.get("id")
                if msg_id and msg_id in _processed_ids:
                    continue

                _handle_message(message, exchange_url, workspace)

        except requests.exceptions.ConnectionError as exc:
            _log("WARNING", f"SSE connection failed: {exc}, retrying in {backoff}s")
        except requests.exceptions.HTTPError as exc:
            _log("WARNING", f"SSE HTTP error: {exc}, retrying in {backoff}s")
        except Exception as exc:
            _log("ERROR", f"SSE unexpected error: {exc}, retrying in {backoff}s")

        if _running:
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)


# ---------------------------------------------------------------------------
# Polling mode
# ---------------------------------------------------------------------------
def _run_polling_mode(exchange_url: str, workspace: str, poll_interval: int) -> None:
    """Fallback: poll /messages every poll_interval seconds."""
    _log("INFO", f"Starting polling mode (interval={poll_interval}s)")

    while _running:
        messages = _fetch_pending(exchange_url)
        for message in messages:
            if not _running:
                break
            msg_id = message.get("id")
            if msg_id in _processed_ids:
                continue
            _handle_message(message, exchange_url, workspace)

        # Sleep in small increments so SIGINT is responsive
        for _ in range(poll_interval * 10):
            if not _running:
                break
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    default_workspace = str(_SCRIPT_DIR.parent.parent)

    parser = argparse.ArgumentParser(
        description="FalkVelt exchange live responder — dual-mode SSE/polling watcher"
    )
    parser.add_argument(
        "--workspace",
        default=default_workspace,
        help=f"Workspace root directory (default: {default_workspace})",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=3,
        help="Polling interval in seconds when SSE is unavailable (default: 3)",
    )
    parser.add_argument(
        "--exchange-url",
        default="http://localhost:8888",
        help="Exchange server base URL (default: http://localhost:8888)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    workspace = str(Path(args.workspace).resolve())
    exchange_url = args.exchange_url.rstrip("/")
    poll_interval = args.poll_interval

    _log("INFO", f"FalkVelt responder starting")
    _log("INFO", f"  workspace   : {workspace}")
    _log("INFO", f"  exchange_url: {exchange_url}")
    _log("INFO", f"  poll_interval: {poll_interval}s")

    # Start heartbeat background thread (daemon — won't block shutdown)
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(exchange_url,),
        daemon=True,
        name="falkvelt-heartbeat",
    )
    hb_thread.start()
    _log("INFO", "Heartbeat thread started (interval=30s)")

    # Try SSE first; it will fall back to polling internally if needed
    _run_sse_mode(exchange_url, workspace, poll_interval)

    _log("INFO", "FalkVelt responder stopped")


if __name__ == "__main__":
    main()
