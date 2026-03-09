#!/usr/bin/env python3
"""
infra/chat/chat_server.py — FastAPI server for the chat viewer + moderator UI.

Architecture (v3 — Direct Router, no subprocess):
  chat_server calls `claude -p` directly via asyncio for each agent.
  No stream_chat.py orchestrator subprocess.

  Browser --WebSocket /ws/moderate--> command handling --> asyncio chat loop
  asyncio chat loop --SSE--> browser

Endpoints:
  GET  /                          — Serve chat viewer HTML
  GET  /api/chats                 — List all chat summaries
  GET  /api/chats/{chat_id}       — Full chat state (journal → live_chats fallback)
  POST /api/events                — Receive external events (kept for compatibility)
  GET  /events/stream             — SSE stream with Last-Event-ID replay
  WS   /ws/moderate               — Commands: /say, /pause, /resume, /end

Run:
  python3 chat_server.py              # port 8877
  python3 chat_server.py --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import asyncio.subprocess as aiosubprocess
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Coroutine, List, Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("chat_server")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"
TEMPLATES_DIR = BASE_DIR / "templates"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
AGENTS_FILE = BASE_DIR / "agents.json"

# ---------------------------------------------------------------------------
# Agent registry helpers
# ---------------------------------------------------------------------------

def _load_agents() -> list[dict]:
    """Load agent registry from agents.json. Returns empty list if file absent."""
    if AGENTS_FILE.exists():
        return json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
    return []


def _save_agents(agents: list[dict]) -> None:
    """Persist agent registry to agents.json (pretty-printed, UTF-8)."""
    AGENTS_FILE.write_text(json.dumps(agents, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Event Journal — single source of truth
# ---------------------------------------------------------------------------
_global_seq: int = 0
_events: list[dict] = []  # Global ordered event list (in-memory, backed by JSONL)
_sse_queues: list[asyncio.Queue] = []  # SSE subscriber queues

# Live chat summaries (for sidebar listing, derived from events)
live_chats: dict[str, dict[str, Any]] = {}

# Background asyncio tasks per chat
_chat_tasks: dict[str, asyncio.Task] = {}


def _create_chat_task(chat_id: str) -> asyncio.Task:
    """Create a chat loop task with exception logging."""
    task = asyncio.create_task(run_chat_loop(chat_id))
    def _on_done(t: asyncio.Task) -> None:
        exc = t.exception() if not t.cancelled() else None
        if exc:
            log.error("Chat loop %s crashed: %s", chat_id, exc, exc_info=exc)
    task.add_done_callback(_on_done)
    return task


def _journal_path(chat_id: str) -> Path:
    """Return path to per-chat JSONL event journal."""
    safe = Path(chat_id).name
    return LOGS_DIR / f"events_{safe}.jsonl"


def _append_event(event: dict) -> int:
    """Append event to global list + per-chat JSONL file. Returns seq."""
    global _global_seq
    _global_seq += 1

    record = {
        "seq": _global_seq,
        **event,
        "_ts": datetime.now(timezone.utc).isoformat(),
    }
    _events.append(record)

    # Persist to per-chat JSONL
    chat_id = event.get("chat_id", "")
    if chat_id:
        path = _journal_path(chat_id)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning("Failed to write journal %s: %s", path.name, exc)

    return _global_seq


def _load_journals() -> None:
    """Load existing JSONL journals into memory on server start."""
    global _global_seq

    all_events: list[dict] = []
    for path in LOGS_DIR.glob("events_*.jsonl"):
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            for line in text.split("\n"):
                if line.strip():
                    all_events.append(json.loads(line))
        except Exception as exc:
            log.warning("Could not load journal %s: %s", path.name, exc)

    # Sort by seq and rebuild global state
    all_events.sort(key=lambda e: e.get("seq", 0))
    _events.clear()
    _events.extend(all_events)
    _global_seq = all_events[-1]["seq"] if all_events else 0

    # Rebuild live_chats from events
    live_chats.clear()
    for ev in all_events:
        _update_live_chats(ev)

    log.info(
        "Loaded %d events from journals (seq up to %d, %d chats)",
        len(all_events), _global_seq, len(live_chats),
    )


def _update_live_chats(event: dict) -> None:
    """Update live_chats summary dict from an event."""
    etype = event.get("type", "")
    chat_id = event.get("chat_id", "")
    if not chat_id:
        return

    now = datetime.now(timezone.utc)

    if etype == "chat_started":
        existing = live_chats.get(chat_id, {})
        live_chats[chat_id] = {
            "chat_id": chat_id,
            "topic": event.get("topic", existing.get("topic", "Live chat")),
            "agents": event.get("agents", existing.get("agents", {})),
            "started_at": event.get("_ts", existing.get("started_at", "")),
            "ended_at": None,
            "turn_count": 0,
            "total_tokens": 0,
            "facts_count": 0,
            "state": event.get("state", existing.get("state", "running")),
            "max_turns": existing.get("max_turns") or event.get("max_turns", 0),
            "_live": True,
            "_last_event_ts": now,
        }
    elif etype == "status" and chat_id in live_chats:
        if event.get("state"):
            live_chats[chat_id]["state"] = event["state"]
        if event.get("max_turns"):
            live_chats[chat_id]["max_turns"] = event["max_turns"]
        live_chats[chat_id]["_last_event_ts"] = now
    elif etype == "turn" and chat_id in live_chats:
        td = event.get("turn_data", {})
        live_chats[chat_id]["turn_count"] = td.get(
            "turn", live_chats[chat_id]["turn_count"]
        )
        live_chats[chat_id]["total_tokens"] = event.get(
            "total_tokens", live_chats[chat_id]["total_tokens"]
        )
        live_chats[chat_id]["_last_event_ts"] = now
    elif etype == "chat_ended" and chat_id in live_chats:
        live_chats[chat_id]["ended_at"] = event.get("_ts", "")
        live_chats[chat_id]["state"] = "ended"
        live_chats[chat_id]["_live"] = False
    elif etype == "agent_joined" and chat_id in live_chats:
        # Add the new agent to the chat's agents dict
        agent_name = event.get("agent_name", "")
        if agent_name:
            agents = live_chats[chat_id].setdefault("agents", {})
            # Use next available integer key as string
            next_key = str(len(agents))
            agents[next_key] = {"name": agent_name}
        live_chats[chat_id]["_last_event_ts"] = now
    elif etype == "turns_extended" and chat_id in live_chats:
        new_max = event.get("new_max")
        if new_max is not None:
            live_chats[chat_id]["max_turns"] = new_max
        live_chats[chat_id]["_last_event_ts"] = now
    elif etype == "phase_change" and chat_id in live_chats:
        phase = event.get("phase")
        if phase:
            live_chats[chat_id]["phase"] = phase
        live_chats[chat_id]["_last_event_ts"] = now


def _build_chat_from_events(chat_id: str) -> dict | None:
    """Reconstruct full chat state from event journal."""
    chat_events = [e for e in _events if e.get("chat_id") == chat_id]
    if not chat_events:
        return None

    chat: dict[str, Any] = {
        "chat_id": chat_id,
        "topic": "",
        "agents": {},
        "turns": [],
        "facts": [],
        "started_at": "",
        "ended_at": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "state": "running",
    }

    for ev in chat_events:
        etype = ev.get("type", "")
        if etype == "chat_started":
            chat["topic"] = ev.get("topic", "")
            chat["agents"] = ev.get("agents", {})
            chat["started_at"] = ev.get("_ts", "")
            chat["state"] = ev.get("state", "running")
            chat["max_turns"] = ev.get("max_turns", 0)
            chat["max_context"] = ev.get("max_context", 200000)
            chat["permission_mode"] = ev.get("permission_mode", "bypassPermissions")
        elif etype == "turn":
            td = ev.get("turn_data", {})
            if td:
                chat["turns"].append(td)
                chat["total_input_tokens"] += td.get("input_tokens", 0)
                chat["total_output_tokens"] += td.get("output_tokens", 0)
        elif etype == "fact":
            chat["facts"].append(ev.get("fact", ""))
        elif etype == "chat_ended":
            chat["ended_at"] = ev.get("_ts", "")
            chat["state"] = "ended"
        elif etype == "status":
            if ev.get("state"):
                chat["state"] = ev["state"]
            if ev.get("max_turns"):
                chat["max_turns"] = ev["max_turns"]
            if ev.get("max_context"):
                chat["max_context"] = ev["max_context"]
            if ev.get("permission_mode"):
                chat["permission_mode"] = ev["permission_mode"]

    return chat


async def _notify_sse(event: dict) -> None:
    """Push event to all SSE subscriber queues."""
    dead: list[asyncio.Queue] = []
    for q in list(_sse_queues):
        try:
            q.put_nowait(event)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _sse_queues.remove(q)
        except ValueError:
            pass


def _broadcast_event(event: dict) -> None:
    """Synchronous wrapper: journal + notify SSE (fire-and-forget)."""
    chat_id = event.get("chat_id", "")
    ev_type = event.get("type", "")

    # Ephemeral events: SSE only, no journal
    ephemeral = {"stream_start", "stream_chunk", "stream_end", "msg_status",
                 "tool_call", "agent_msg", "sync_status", "shared_update"}
    if ev_type in ephemeral:
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.ensure_future(_notify_sse(event))
        )
        return

    # Journal + update live summary + notify SSE
    seq = _append_event(event)
    _update_live_chats(event)
    asyncio.ensure_future(_notify_sse({**event, "seq": seq}))


# ---------------------------------------------------------------------------
# Log parsing helpers (for completed chats with stream_*.json logs)
# ---------------------------------------------------------------------------
def _parse_log_file(path: Path) -> dict[str, Any] | None:
    """Parse a stream_*.json log and return a summary dict, or None on error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not parse %s: %s", path.name, exc)
        return None

    turns = data.get("turns", [])
    agent_turns = [t for t in turns if t.get("speaker") != "moderator"]
    facts = data.get("facts", [])

    total_tokens = (
        data.get("total_input_tokens", 0) + data.get("total_output_tokens", 0)
    )

    return {
        "chat_id": data.get("chat_id", path.stem),
        "topic": data.get("topic", ""),
        "agents": data.get("agents", {}),
        "started_at": data.get("started_at", ""),
        "ended_at": data.get("ended_at", ""),
        "turn_count": len(agent_turns),
        "total_tokens": total_tokens,
        "facts_count": len(facts),
    }


def _scan_logs() -> list[dict[str, Any]]:
    """Scan LOGS_DIR for stream_*.json files, return summaries sorted by date desc."""
    summaries = []
    for path in sorted(LOGS_DIR.glob("stream_*.json"), reverse=True):
        summary = _parse_log_file(path)
        if summary:
            summaries.append(summary)
    return summaries


# ---------------------------------------------------------------------------
# Capsule path helper
# ---------------------------------------------------------------------------

def _get_capsule_path(agent_name: str, workspace: str) -> Optional[str]:
    """Find identity capsule for agent — capsule file first, then CLAUDE.md."""
    ws = Path(workspace)
    capsule = ws / ".claude" / f"capsule_{agent_name}.md"
    if capsule.exists():
        return str(capsule)
    claude_md = ws / "CLAUDE.md"
    if claude_md.exists():
        return str(claude_md)
    return None


# ---------------------------------------------------------------------------
# Direct agent invocation via `claude -p`
# ---------------------------------------------------------------------------

async def invoke_agent_async(agent: dict, prompt: str, chat_id: str) -> tuple[str, dict]:
    """Call `claude -p` asynchronously, stream chunks via SSE. Returns (full_text, meta)."""
    cmd = [
        "claude", "-p",
        "--verbose",
        "--output-format", "stream-json",
        "--permission-mode", agent.get("permission_mode", "bypassPermissions"),
    ]
    if agent.get("budget"):
        cmd.extend(["--max-budget-usd", str(agent["budget"])])
    if agent.get("capsule_path"):
        cmd.extend(["--append-system-prompt", agent["capsule_path"]])
    if agent.get("session_id"):
        cmd.extend(["--resume", agent["session_id"]])

    # Strip CLAUDECODE / CLAUDE_CODE_ENTRYPOINT to allow nested claude -p
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=agent.get("workspace"),
        env=clean_env,
    )

    assert proc.stdin is not None
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    # Use a list to accumulate text chunks — avoids linter confusion over str += str
    chunks: list[str] = []
    final_from_result: str = ""

    # Broadcast stream start
    await _notify_sse({"type": "stream_start", "chat_id": chat_id, "speaker": agent["name"]})

    assert proc.stdout is not None
    async for raw_line in proc.stdout:
        line = raw_line.decode().strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        ctype: str = str(chunk.get("type", ""))
        text: str = ""

        if ctype == "assistant":
            # Non-streaming format: full message in one shot
            for block in chunk.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text = str(block.get("text", ""))
        elif ctype == "content_block_delta":
            delta = chunk.get("delta", {})
            text = str(delta.get("text", ""))
        elif ctype == "result":
            # Final result chunk — capture session_id and fallback full text
            sid = chunk.get("session_id")
            if sid:
                agent["session_id"] = sid
            final_from_result = str(chunk.get("result", ""))
            continue

        if text:
            chunks.append(text)
            await _notify_sse({
                "type": "stream_chunk",
                "chat_id": chat_id,
                "speaker": agent["name"],
                "chunk": text,
            })

    await proc.wait()

    # Log stderr if any (helps debug claude -p failures)
    stderr_text = ""
    _stderr = proc.stderr
    if _stderr is not None:
        stderr_text = (await _stderr.read()).decode(errors="replace")
    if stderr_text:
        log.warning("Agent %s stderr: %.500s", agent["name"], stderr_text)
    if proc.returncode and proc.returncode != 0:
        log.error("Agent %s exited with code %d", agent["name"], proc.returncode)

    # Broadcast stream end
    await _notify_sse({"type": "stream_end", "chat_id": chat_id, "speaker": agent["name"]})

    # Prefer streamed chunks; fall back to result field if nothing was streamed
    full_text: str = "".join(chunks) if chunks else final_from_result
    return full_text, {"session_id": agent.get("session_id")}


# ---------------------------------------------------------------------------
# Background chat loop
# ---------------------------------------------------------------------------

async def run_chat_loop(chat_id: str) -> None:
    """Background task: run rounds until convergence, max_rounds, or chat ended."""
    chat = live_chats[chat_id]
    max_rounds: int = int(chat.get("max_turns") or 20)
    # Use a list to hold the counter so rebinding never confuses the linter
    _rounds: List[int] = [0]

    while _rounds[0] < max_rounds and not chat.get("ended"):
        # Wait for pending messages to appear (or chat to end/pause)
        while not chat.get("pending_messages") and not chat.get("ended"):
            if chat.get("paused"):
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(0.3)

        if chat.get("ended"):
            break
        if chat.get("paused"):
            # Re-enter wait loop
            continue

        # Snapshot and clear pending messages atomically
        messages: list[dict] = chat["pending_messages"][:]
        chat["pending_messages"] = []

        # Build per-agent invocations: each agent sees only messages from OTHERS
        # Respect _target field for directed messages
        agent_tasks: list[tuple[dict, Any]] = []
        for agent in chat.get("agents_list", []):
            others = [
                m for m in messages
                if m["speaker"] != agent["name"]
                and (not m.get("_target") or m["_target"] == agent["name"])
            ]
            if not others:
                continue
            prompt = "\n\n".join(f"[{m['speaker']}]: {m['text']}" for m in others)
            agent_tasks.append((agent, invoke_agent_async(agent, prompt, chat_id)))

        if not agent_tasks:
            # No agent has anything to respond to — wait for more input
            continue

        _rounds[0] = _rounds[0] + 1
        current_round = _rounds[0]
        seq = _append_event({
            "type": "status",
            "chat_id": chat_id,
            "state": "running",
            "turn": current_round,
            "max_turns": max_rounds,
        })
        _update_live_chats({"type": "status", "chat_id": chat_id, "state": "running"})
        await _notify_sse({"type": "status", "chat_id": chat_id, "state": "running",
                           "turn": current_round, "max_turns": max_rounds, "seq": seq})

        # Run all agent coroutines in parallel
        results = await asyncio.gather(
            *[t[1] for t in agent_tasks],
            return_exceptions=True,
        )

        any_response = False
        for (agent, _), result in zip(agent_tasks, results):
            if isinstance(result, Exception):
                log.error("Agent %s error in chat %s: %s", agent["name"], chat_id, result)
                continue
            text, _meta = result
            if not text or not text.strip():
                continue

            any_response = True
            turn_num = len(chat.setdefault("turns", [])) + 1
            turn_record: dict[str, Any] = {
                "turn": turn_num,
                "speaker": agent["name"],
                "text": text.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "input_tokens": 0,
                "output_tokens": 0,
            }
            chat["turns"].append(turn_record)
            # Queue this agent's response for others to receive next round
            chat["pending_messages"].append({
                "speaker": agent["name"],
                "text": text.strip(),
            })

            seq = _append_event({
                "type": "turn",
                "chat_id": chat_id,
                "turn_data": turn_record,
                "total_tokens": 0,
            })
            _update_live_chats({"type": "turn", "chat_id": chat_id,
                                 "turn_data": turn_record, "total_tokens": 0})
            await _notify_sse({
                "type": "turn",
                "chat_id": chat_id,
                "turn_data": turn_record,
                "total_tokens": 0,
                "seq": seq,
            })

        if not any_response:
            log.info("Chat %s: no agent responded — convergence after %d rounds", chat_id, _rounds[0])
            break

    # End the chat
    if not chat.get("ended"):
        chat["ended"] = True
        chat["state"] = "ended"
        seq = _append_event({"type": "chat_ended", "chat_id": chat_id})
        _update_live_chats({"type": "chat_ended", "chat_id": chat_id})
        await _notify_sse({"type": "chat_ended", "chat_id": chat_id, "seq": seq})
        log.info("Chat %s ended after %d rounds", chat_id, _rounds[0])


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Chat Server", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.get("/api/chats")
async def list_chats() -> JSONResponse:
    """Return all chat summaries (live from journal + completed from log files)."""
    summaries = _scan_logs()
    log_ids = {s["chat_id"] for s in summaries}

    # Add live chats that don't have log files yet
    for cid, info in live_chats.items():
        if cid not in log_ids:
            clean = {k: v for k, v in info.items() if not k.startswith("_last_")}
            summaries.append(clean)

    # Sort: live chats first (by date DESC), then ended (by date DESC)
    live = [s for s in summaries if s.get("_live")]
    ended = [s for s in summaries if not s.get("_live")]
    live.sort(key=lambda s: s.get("started_at", ""), reverse=True)
    ended.sort(key=lambda s: s.get("started_at", ""), reverse=True)

    return JSONResponse(content=live + ended)


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str) -> JSONResponse:
    """Return full chat state — from live_chats (live) or event journal or log file (completed)."""
    safe_id = Path(chat_id).name

    # First: try live_chats for active/recent chats
    if safe_id in live_chats:
        lc = live_chats[safe_id]
        return JSONResponse(content={
            "chat_id": safe_id,
            "topic": lc.get("topic", ""),
            "agents": lc.get("agents", {}),
            "turns": lc.get("turns", []),
            "facts": [],
            "started_at": lc.get("started_at", str(lc.get("_last_event_ts", ""))),
            "ended_at": lc.get("ended_at"),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "state": "ended" if lc.get("ended") else ("paused" if lc.get("paused") else lc.get("state", "active")),
            "max_turns": lc.get("max_turns", 20),
            "_live": lc.get("_live", True),
        })

    # Second: try event journal (for chats evicted from live_chats)
    chat = _build_chat_from_events(safe_id)
    if chat:
        return JSONResponse(content=chat)

    # Third: try log files (for completed chats)
    candidates = [
        LOGS_DIR / f"stream_{safe_id}.json",
        LOGS_DIR / f"{safe_id}.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return JSONResponse(content=data)
            except Exception as exc:
                log.error("Error reading %s: %s", path, exc)
                return JSONResponse(
                    content={"error": "Could not parse log file"},
                    status_code=500,
                )

    return JSONResponse(content={"error": "Chat not found"}, status_code=404)


@app.post("/api/events")
async def post_event(request: Request) -> JSONResponse:
    """Receive event from external sources → journal + SSE broadcast (compatibility endpoint)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    ev_type = body.get("type", "")

    # Ephemeral events: broadcast only, don't journal
    if ev_type in ("stream_start", "stream_chunk", "stream_end", "msg_status",
                   "tool_call", "agent_msg", "sync_status", "shared_update"):
        await _notify_sse(body)
        return JSONResponse(content={"ok": True, "seq": 0})

    # All other events: journal + broadcast
    seq = _append_event(body)
    _update_live_chats(body)

    event_with_seq = {**body, "seq": seq}
    await _notify_sse(event_with_seq)

    return JSONResponse(content={"ok": True, "seq": seq})


@app.post("/api/chats/{chat_id}/end")
async def force_end_chat(chat_id: str) -> JSONResponse:
    """Force-end a live chat from the UI."""
    safe_id = Path(chat_id).name
    if safe_id not in live_chats:
        return JSONResponse(content={"error": "Chat not found"}, status_code=404)
    if not live_chats[safe_id].get("_live"):
        return JSONResponse(content={"error": "Chat already ended"}, status_code=400)

    # Signal the background task to exit
    live_chats[safe_id]["ended"] = True
    live_chats[safe_id]["paused"] = False

    event = {"type": "chat_ended", "chat_id": safe_id}
    seq = _append_event(event)
    _update_live_chats(event)
    await _notify_sse({**event, "seq": seq})

    log.info("Force-ended chat: %s", safe_id)
    return JSONResponse(content={"ok": True, "seq": seq})


# ---------------------------------------------------------------------------
# Agent registry endpoints
# ---------------------------------------------------------------------------

@app.get("/api/agents")
async def list_agents() -> JSONResponse:
    """Return all registered agents from agents.json."""
    return JSONResponse(content=_load_agents())


@app.post("/api/agents")
async def register_agent(request: Request) -> JSONResponse:
    """Register a new agent. Body: {name, workspace, role?, default_budget?, permission_mode?}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    name = body.get("name", "").strip()
    workspace = body.get("workspace", "").strip()
    if not name or not workspace:
        return JSONResponse(content={"error": "name and workspace are required"}, status_code=400)

    agents = _load_agents()

    # Prevent duplicate registration
    if any(a["name"] == name for a in agents):
        return JSONResponse(content={"error": f"Agent '{name}' is already registered"}, status_code=409)

    new_agent = {
        "name": name,
        "workspace": workspace,
        "role": body.get("role", ""),
        "default_budget": float(body.get("default_budget", 5.0)),
        "permission_mode": body.get("permission_mode", "bypassPermissions"),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    agents.append(new_agent)
    _save_agents(agents)

    log.info("Registered agent: %s (workspace=%s)", name, workspace)
    return JSONResponse(content={"ok": True, "agent": new_agent}, status_code=201)


@app.delete("/api/agents/{name}")
async def delete_agent(name: str) -> JSONResponse:
    """Remove an agent from the registry by name."""
    agents = _load_agents()
    filtered = [a for a in agents if a["name"] != name]

    if len(filtered) == len(agents):
        return JSONResponse(content={"error": f"Agent '{name}' not found"}, status_code=404)

    _save_agents(filtered)
    log.info("Removed agent: %s", name)
    return JSONResponse(content={"ok": True})


# ---------------------------------------------------------------------------
# Chat CRUD endpoints
# ---------------------------------------------------------------------------

@app.post("/api/chats")
async def create_chat(request: Request) -> JSONResponse:
    """
    Create a new chat session.

    Body: {topic, agents?: [names], max_turns?, budget?}
    Chat starts immediately as 'active' with empty agents_list.
    Agents can be added via POST /api/chats/{chat_id}/add-agent.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    topic = body.get("topic", "").strip()
    agent_names = body.get("agents", [])
    max_turns = int(body.get("max_turns", 20))
    cli_budget = float(body.get("budget", 5.0))

    if not topic:
        return JSONResponse(content={"error": "topic is required"}, status_code=400)

    # Generate unique chat_id
    _uid_suffix = f"{uuid4().int % 0x1_0000_0000:08x}"
    chat_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + _uid_suffix
    now_iso = datetime.now(timezone.utc).isoformat()

    live_chats[chat_id] = {
        "chat_id": chat_id,
        "topic": topic,
        "state": "active",
        "agents": {},
        "agents_list": [],
        "turns": [],
        "pending_messages": [],
        "paused": False,
        "ended": False,
        "max_turns": max_turns,
        "turn_count": 0,
        "total_tokens": 0,
        "facts_count": 0,
        "_live": True,
        "started_at": now_iso,
        "_last_event_ts": datetime.now(timezone.utc),
    }

    # If agent names were provided upfront, register them
    if agent_names:
        registry = _load_agents()
        registry_map = {a["name"]: a for a in registry}
        for name in agent_names:
            if name not in registry_map:
                return JSONResponse(
                    content={"error": f"Agent '{name}' not registered"},
                    status_code=400,
                )
            reg = registry_map[name]
            agent_config = {
                "name": name,
                "workspace": reg["workspace"],
                "session_id": None,
                "capsule_path": _get_capsule_path(name, reg["workspace"]),
                "budget": cli_budget,
                "permission_mode": reg.get("permission_mode", "bypassPermissions"),
            }
            live_chats[chat_id]["agents_list"].append(agent_config)
            agents_dict = live_chats[chat_id]["agents"]
            agents_dict[str(len(agents_dict))] = {"name": name, "color": "#569cd6"}

        log.info("Created chat %s with agents=%s", chat_id, agent_names)
    else:
        log.info("Created empty chat %s (no agents yet)", chat_id)

    return JSONResponse(content={"ok": True, "chat_id": chat_id, "pid": None}, status_code=201)


@app.post("/api/chats/{chat_id}/add-agent")
async def add_agent_to_chat(chat_id: str, request: Request) -> JSONResponse:
    """
    Add an agent to an existing chat by name.

    Body: {name, budget?}
    Starts the background chat loop if not already running.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    safe_id = Path(chat_id).name
    if safe_id not in live_chats:
        return JSONResponse(content={"error": "Chat not found"}, status_code=404)

    agent_name = body.get("name", "").strip()
    if not agent_name:
        return JSONResponse(content={"error": "name is required"}, status_code=400)

    chat = live_chats[safe_id]
    agents_list: list[dict] = chat.setdefault("agents_list", [])

    # Enforce 4-agent maximum
    if len(agents_list) >= 4:
        return JSONResponse(content={"error": "Maximum 4 agents per chat"}, status_code=400)

    # Check if agent already in chat
    if any(a["name"] == agent_name for a in agents_list):
        return JSONResponse(content={"error": f"Agent '{agent_name}' already in chat"}, status_code=400)

    # Validate agent is in the registry
    registry = _load_agents()
    registry_map = {a["name"]: a for a in registry}
    if agent_name not in registry_map:
        return JSONResponse(
            content={"error": f"Agent '{agent_name}' not registered"},
            status_code=400,
        )

    reg = registry_map[agent_name]
    cli_budget = float(body.get("budget", reg.get("default_budget", 5.0)))

    agent_config = {
        "name": agent_name,
        "workspace": reg["workspace"],
        "session_id": None,
        "capsule_path": _get_capsule_path(agent_name, reg["workspace"]),
        "budget": cli_budget,
        "permission_mode": reg.get("permission_mode", "bypassPermissions"),
    }
    agents_list.append(agent_config)

    # Keep UI agents dict in sync
    agents_dict = chat.setdefault("agents", {})
    agents_dict[str(len(agents_dict))] = {"name": agent_name, "color": "#569cd6"}
    chat["_last_event_ts"] = datetime.now(timezone.utc)

    # Broadcast agent_joined event
    seq = _append_event({"type": "agent_joined", "chat_id": safe_id, "agent_name": agent_name})
    _update_live_chats({"type": "agent_joined", "chat_id": safe_id, "agent_name": agent_name})
    await _notify_sse({"type": "agent_joined", "chat_id": safe_id, "agent_name": agent_name, "seq": seq})

    # Start chat loop if not already running
    if safe_id not in _chat_tasks or _chat_tasks[safe_id].done():
        _chat_tasks[safe_id] = _create_chat_task(safe_id)
        log.info("Started chat loop for %s (agents=%s)", safe_id,
                 [a["name"] for a in agents_list])

    log.info("Added agent %s to chat %s", agent_name, safe_id)
    return JSONResponse(content={"ok": True, "chat_id": safe_id})


@app.delete("/api/chats/{chat_id}/agents/{agent_name}")
async def remove_agent_from_chat(chat_id: str, agent_name: str) -> JSONResponse:
    """Remove an agent from a chat (only when no active round is running)."""
    safe_id = Path(chat_id).name
    if safe_id not in live_chats:
        return JSONResponse(content={"error": "Chat not found"}, status_code=404)

    chat_info = live_chats[safe_id]

    # Remove from agents_list
    agents_list: list[dict] = chat_info.get("agents_list", [])
    original_len = len(agents_list)
    chat_info["agents_list"] = [a for a in agents_list if a["name"] != agent_name]

    if len(chat_info["agents_list"]) == original_len:
        return JSONResponse(
            content={"error": f"Agent '{agent_name}' not in this chat"},
            status_code=404,
        )

    # Keep UI agents dict in sync
    agents_dict = chat_info.get("agents", {})
    key_to_remove = None
    for key, agent in agents_dict.items():
        if agent.get("name") == agent_name:
            key_to_remove = key
            break
    if key_to_remove is not None:
        del agents_dict[key_to_remove]
        remaining = list(agents_dict.values())
        agents_dict.clear()
        for i, a in enumerate(remaining):
            agents_dict[str(i)] = a

    chat_info["_last_event_ts"] = datetime.now(timezone.utc)
    log.info("Removed agent %s from chat %s", agent_name, safe_id)
    return JSONResponse(content={"ok": True, "chat_id": safe_id})


@app.get("/api/commands")
async def get_commands_stub(chat_id: str = "") -> JSONResponse:
    """Stub for legacy polling — always returns empty."""
    return JSONResponse(content=[])


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str) -> JSONResponse:
    """Delete a chat: cancel background task, remove from live_chats, delete log files."""
    safe_id = Path(chat_id).name

    # Cancel background task if running
    if safe_id in _chat_tasks and not _chat_tasks[safe_id].done():
        _chat_tasks[safe_id].cancel()
        _chat_tasks.pop(safe_id, None)

    # Signal ended + synthesize event if still live
    if safe_id in live_chats and live_chats[safe_id].get("_live"):
        live_chats[safe_id]["ended"] = True
        event = {"type": "chat_ended", "chat_id": safe_id}
        seq = _append_event(event)
        _update_live_chats(event)
        await _notify_sse({**event, "seq": seq})
        log.info("Synthesized chat_ended for deleted chat: %s", safe_id)

    live_chats.pop(safe_id, None)

    # Delete log file(s) for this chat
    journal_path = _journal_path(safe_id)
    journal_path.unlink(missing_ok=True)

    for f in LOGS_DIR.glob(f"stream_{safe_id}*.json"):
        f.unlink(missing_ok=True)

    journals_dir = BASE_DIR / "journals"
    if journals_dir.exists():
        for f in journals_dir.glob(f"{safe_id}*.jsonl"):
            f.unlink(missing_ok=True)

    log.info("Deleted chat: %s", safe_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/chats/{chat_id}/add-turns")
async def add_turns(chat_id: str, request: Request) -> JSONResponse:
    """
    Extend the turn limit for a live chat.

    Body: {count?}  (default 5)
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    count = int(body.get("count", 5))
    safe_id = Path(chat_id).name

    if safe_id in live_chats:
        old_max = live_chats[safe_id].get("max_turns", 0)
        live_chats[safe_id]["max_turns"] = old_max + count

    new_max = live_chats.get(safe_id, {}).get("max_turns", count)
    log.info("Added %d turns for chat %s → max_turns=%d", count, safe_id, new_max)
    return JSONResponse(content={"ok": True, "added": count, "max_turns": new_max})


@app.get("/")
async def serve_ui() -> FileResponse:
    """Serve the chat viewer HTML."""
    html_path = TEMPLATES_DIR / "chat.html"
    if not html_path.exists():
        return FileResponse(
            path=BASE_DIR / "chat_server.py",
            media_type="text/html",
            status_code=503,
            headers={"X-Error": "templates/chat.html not found"},
        )
    return FileResponse(
        path=html_path,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ---------------------------------------------------------------------------
# SSE endpoint — live event streaming with Last-Event-ID replay
# ---------------------------------------------------------------------------
@app.get("/events/stream")
async def sse_stream(request: Request):
    """
    Server-Sent Events stream.

    On connect: replays all events after Last-Event-ID (or last_id query param).
    Then streams new events in real-time.
    Sends periodic pings to keep connection alive.
    Browser's EventSource auto-reconnects and sends Last-Event-ID on reconnect.
    """
    last_id = int(
        request.headers.get(
            "Last-Event-ID",
            request.query_params.get("last_id", "0"),
        )
    )

    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues.append(queue)

    async def generate():
        try:
            # Phase 1: Replay missed events
            for ev in _events:
                if ev.get("seq", 0) > last_id:
                    yield {
                        "id": str(ev["seq"]),
                        "event": ev.get("type", "message"),
                        "data": json.dumps(ev, ensure_ascii=False),
                    }

            # Phase 2: Stream live events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "id": str(ev.get("seq", 0)),
                        "event": ev.get("type", "message"),
                        "data": json.dumps(ev, ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield {"event": "ping", "data": ""}
        finally:
            try:
                _sse_queues.remove(queue)
            except ValueError:
                pass

    return EventSourceResponse(generate())


# ---------------------------------------------------------------------------
# WebSocket — moderator commands (client → server → chat loop)
# ---------------------------------------------------------------------------
@app.websocket("/ws/moderate")
async def ws_moderate(websocket: WebSocket) -> None:
    """
    WebSocket for sending commands from browser to the chat loop.
    Handles: /say, /pause, /resume, /end
    Events are delivered via SSE, not WebSocket.
    """
    await websocket.accept()
    log.info("WebSocket command client connected.")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Non-JSON WebSocket message: %r", raw[:120])
                continue

            if msg.get("type") != "command":
                continue

            cmd = msg.get("cmd", "").strip()
            arg = msg.get("arg", "").strip()
            chat_id = msg.get("chat_id", "").strip()
            if not cmd or not chat_id:
                continue

            safe_chat_id = Path(chat_id).name
            log.info("Moderator command [%s]: %s %r", safe_chat_id, cmd, arg)

            if safe_chat_id not in live_chats:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "cmd": cmd,
                    "error": "Chat not found",
                }))
                continue

            chat = live_chats[safe_chat_id]

            if cmd == "/say":
                # Parse optional @mention for targeted delivery
                target: Optional[str] = None
                text = arg
                m_match = re.match(r'^@(\S+)\s+([\s\S]*)', arg)
                if m_match:
                    target = m_match.group(1)
                    text = m_match.group(2).strip()

                # Record moderator turn
                turn_record: dict[str, Any] = {
                    "turn": len(chat.get("turns", [])) + 1,
                    "speaker": "moderator",
                    "text": arg,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                chat.setdefault("turns", []).append(turn_record)
                seq = _append_event({
                    "type": "turn",
                    "chat_id": safe_chat_id,
                    "turn_data": turn_record,
                    "total_tokens": 0,
                })
                await _notify_sse({
                    "type": "turn",
                    "chat_id": safe_chat_id,
                    "turn_data": turn_record,
                    "total_tokens": 0,
                    "seq": seq,
                })

                # Add to pending messages for the chat loop to pick up
                pending_msg: dict[str, Any] = {"speaker": "moderator", "text": text}
                if target:
                    pending_msg["_target"] = target
                chat.setdefault("pending_messages", []).append(pending_msg)

                # If chat loop isn't running, start it
                if safe_chat_id not in _chat_tasks or _chat_tasks[safe_chat_id].done():
                    if chat.get("agents_list"):
                        _chat_tasks[safe_chat_id] = _create_chat_task(safe_chat_id)

            elif cmd == "/pause":
                chat["paused"] = True
                seq = _append_event({"type": "status", "chat_id": safe_chat_id, "state": "paused"})
                _update_live_chats({"type": "status", "chat_id": safe_chat_id, "state": "paused"})
                await _notify_sse({"type": "status", "chat_id": safe_chat_id, "state": "paused", "seq": seq})

            elif cmd == "/resume":
                chat["paused"] = False
                seq = _append_event({"type": "status", "chat_id": safe_chat_id, "state": "running"})
                _update_live_chats({"type": "status", "chat_id": safe_chat_id, "state": "running"})
                await _notify_sse({"type": "status", "chat_id": safe_chat_id, "state": "running", "seq": seq})

            elif cmd == "/end":
                chat["ended"] = True
                chat["paused"] = False
                chat["state"] = "ended"
                # The run_chat_loop will detect chat["ended"] and exit cleanly

            else:
                log.warning("Unknown command: %s", cmd)

            # Acknowledge
            await websocket.send_text(json.dumps({
                "type": "ack",
                "cmd": cmd,
                "arg": arg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))

    except WebSocketDisconnect:
        log.info("WebSocket command client disconnected.")
    except Exception as exc:
        log.error("WebSocket error: %s", exc)


# ---------------------------------------------------------------------------
# File watcher — notify clients when log files change
# ---------------------------------------------------------------------------
async def _watch_logs_dir(poll_interval: float = 1.5) -> None:
    """Poll LOGS_DIR for new/modified stream_*.json files."""
    log.info("File watcher started on: %s (poll %.1fs)", LOGS_DIR, poll_interval)

    seen: dict[str, float] = {}
    for path in LOGS_DIR.glob("stream_*.json"):
        try:
            seen[path.name] = os.stat(path).st_mtime
        except OSError:
            pass

    try:
        while True:
            await asyncio.sleep(poll_interval)

            current: dict[str, float] = {}
            for path in LOGS_DIR.glob("stream_*.json"):
                try:
                    mtime = os.stat(path).st_mtime
                    current[path.name] = mtime
                    if seen.get(path.name) != mtime:
                        chat_id = path.stem.removeprefix("stream_")
                        log.debug("Log updated: %s", path.name)
                        await _notify_sse({
                            "type": "log_updated",
                            "chat_id": chat_id,
                            "seq": 0,
                        })
                except OSError:
                    pass

            seen = current

    except asyncio.CancelledError:
        log.info("File watcher stopped.")
    except Exception as exc:
        log.error("File watcher error: %s", exc)


@app.on_event("startup")
async def startup_event() -> None:
    """Load journals and start file watcher on server startup."""
    _load_journals()
    asyncio.create_task(_watch_logs_dir())
    log.info(
        "Chat server v3 started (direct router). Logs: %s | Templates: %s",
        LOGS_DIR, TEMPLATES_DIR,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat viewer + moderator FastAPI server (port 8877 by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--port", type=int, default=8877,
        help="Port to listen on (default: 8877)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--reload", action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--log-level", default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    log.info(
        "Starting chat server on http://%s:%d — logs: %s",
        args.host, args.port, LOGS_DIR,
    )
    uvicorn.run(
        "chat_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        app_dir=str(BASE_DIR),
    )


if __name__ == "__main__":
    main()
