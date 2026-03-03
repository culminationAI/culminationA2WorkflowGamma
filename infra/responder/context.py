"""
context.py — builds the system prompt for FalkVelt's claude -p calls.

Reads and caches workspace files (TTL 5 min) to avoid repeated disk reads.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# Cache: {path: (content, timestamp)}
_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 300  # 5 minutes


def get_workspace_root(script_path: str) -> str:
    """Resolve workspace root from script location.

    Assumes structure: {workspace}/infra/responder/context.py
    Two levels up from the script gives the workspace root.
    """
    return str(Path(script_path).resolve().parent.parent.parent)


def _read_cached(path: str) -> str:
    """Read a file with 5-minute TTL cache. Returns empty string if file not found."""
    now = time.time()
    cached = _cache.get(path)
    if cached is not None and (now - cached[1]) < CACHE_TTL:
        return cached[0]

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError):
        content = ""

    _cache[path] = (content, now)
    return content


def _summarize_capability_map(content: str) -> str:
    """Return first 60 lines of capability-map.md."""
    lines = content.splitlines()
    return "\n".join(lines[:60])


def build_prompt(message: dict, workspace: str) -> str:
    """Build the full prompt string to pass to `claude -p`.

    Args:
        message: the raw message dict from the exchange API.
        workspace: absolute path to the workspace root.

    Returns:
        Formatted prompt string ready for subprocess stdin / -p arg.
    """
    capability_map_path = os.path.join(
        workspace, "docs", "self-architecture", "capability-map.md"
    )
    user_identity_path = os.path.join(workspace, "user-identity.md")

    capability_map_raw = _read_cached(capability_map_path)
    capability_map_summary = _summarize_capability_map(capability_map_raw)
    user_identity = _read_cached(user_identity_path)

    from_agent = message.get("from_agent", "unknown")
    msg_type = message.get("type", "unknown")
    priority = message.get("priority", "normal")
    subject = message.get("subject", "(no subject)")
    body = message.get("body", "")

    prompt = f"""You are FalkVelt, secondary coordinator of the _follower_ workspace.
Role: follower to OkiAra (primary coordinator in _primal_).
Style: direct, factual, no emojis. Always respond in English.

Your capabilities:
{capability_map_summary}

Your identity:
{user_identity}

---

You received a message via the inter-agent exchange protocol.

From: {from_agent}
Type: {msg_type}
Priority: {priority}
Subject: {subject}

Message:
{body}

---

Respond appropriately. Be concise and actionable.

IMPORTANT: You are running in text-only mode (no tools, no shell, no file access). Your response text will be automatically posted back to the exchange by the watcher script. Just write your reply content directly — do NOT try to run commands, curl, or reference any tool execution. If the task requires running commands or accessing files, say so and the coordinator will handle it in an interactive session."""

    return prompt
