#!/usr/bin/env python3
"""
infra/chat/chat_server.py — FastAPI server for the chat viewer + moderator UI.

Architecture (v2 — Event Sourcing):
  stream_chat.py --POST /api/events--> chat_server --SSE--> browser
                                           |
                                      Event Journal
                                  (JSONL per chat in logs/)
                                           |
                             GET /api/chats/{id} = full replay

  Browser --WebSocket /ws/moderate--> command_queue --GET /api/commands--> stream_chat.py

Endpoints:
  GET  /                          — Serve chat viewer HTML
  GET  /api/chats                 — List all chat summaries
  GET  /api/chats/{chat_id}       — Full chat state (journal → log file fallback)
  POST /api/events                — Receive events from stream_chat.py
  GET  /api/commands              — Drain command queue (polled by orchestrator)
  GET  /events/stream             — SSE stream with Last-Event-ID replay
  WS   /ws/moderate               — Commands only (client → server)

Run:
  python3 chat_server.py              # port 8877
  python3 chat_server.py --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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
# Live-chat process tracking
# ---------------------------------------------------------------------------

# Maps chat_id → OS PID of the spawned stream_chat.py subprocess
_chat_pids: dict[str, int] = {}

# ---------------------------------------------------------------------------
# Event Journal — single source of truth
# ---------------------------------------------------------------------------
_global_seq: int = 0
_events: list[dict] = []  # Global ordered event list (in-memory, backed by JSONL)
_sse_queues: list[asyncio.Queue] = []  # SSE subscriber queues

# Commands from moderator UI → orchestrator
command_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

# Live chat summaries (for sidebar listing, derived from events)
live_chats: dict[str, dict[str, Any]] = {}


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
        live_chats[chat_id] = {
            "chat_id": chat_id,
            "topic": event.get("topic", "Live chat"),
            "agents": event.get("agents", {}),
            "started_at": event.get("_ts", ""),
            "ended_at": None,
            "turn_count": 0,
            "total_tokens": 0,
            "facts_count": 0,
            "state": event.get("state", "running"),
            "_live": True,
            "_last_event_ts": now,
        }
    elif etype == "status" and chat_id in live_chats:
        if event.get("state"):
            live_chats[chat_id]["state"] = event["state"]
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
            if ev.get("total_tokens"):
                pass  # total_tokens tracked via turns
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
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Chat Server", version="2.0.0")

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
    """Return full chat state — from event journal (live) or log file (completed)."""
    safe_id = Path(chat_id).name

    # First: try event journal (for live/recent chats)
    chat = _build_chat_from_events(safe_id)
    if chat:
        return JSONResponse(content=chat)

    # Second: try log files (for completed chats)
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
    """Receive event from stream_chat.py → journal + SSE broadcast."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    ev_type = body.get("type", "")

    # Ephemeral events: broadcast only, don't journal
    if ev_type in ("stream_start", "stream_chunk", "msg_status", "tool_call", "agent_msg", "sync_status", "shared_update"):
        await _notify_sse(body)
        return JSONResponse(content={"ok": True, "seq": 0})

    # New chat started: drain stale commands from previous session
    if ev_type == "chat_started":
        while not command_queue.empty():
            try:
                command_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    # All other events: journal + broadcast
    seq = _append_event(body)
    _update_live_chats(body)

    # Notify all SSE subscribers
    event_with_seq = {**body, "seq": seq}
    await _notify_sse(event_with_seq)

    return JSONResponse(content={"ok": True, "seq": seq})


@app.get("/api/commands")
async def get_commands() -> JSONResponse:
    """Return pending moderator commands from the queue (drains it)."""
    commands: list[dict] = []
    while not command_queue.empty():
        try:
            commands.append(command_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return JSONResponse(content=commands)


@app.post("/api/chats/{chat_id}/end")
async def force_end_chat(chat_id: str) -> JSONResponse:
    """Force-end a stale/zombie chat from the UI (server-side synthesized event)."""
    safe_id = Path(chat_id).name
    if safe_id not in live_chats:
        return JSONResponse(content={"error": "Chat not found"}, status_code=404)
    if not live_chats[safe_id].get("_live"):
        return JSONResponse(content={"error": "Chat already ended"}, status_code=400)

    event = {"type": "chat_ended", "chat_id": safe_id}
    seq = _append_event(event)
    _update_live_chats(event)
    await _notify_sse({**event, "seq": seq})

    # Drain stale commands
    while not command_queue.empty():
        try:
            command_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    log.info("Force-ended zombie chat: %s", safe_id)
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
    Create and spawn a new chat session.

    Body: {topic, agents: [names], max_turns?, budget?}
    Writes a temp config to /tmp, spawns stream_chat.py --config <path>.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    topic = body.get("topic", "").strip()
    agent_names = body.get("agents", [])
    max_turns = int(body.get("max_turns", 20))
    cli_budget = float(body.get("budget", 5.0))

    if not topic or not agent_names:
        return JSONResponse(content={"error": "topic and agents are required"}, status_code=400)

    # Lookup each agent name in the registry
    registry = _load_agents()
    registry_map = {a["name"]: a for a in registry}
    agents_config = []
    for name in agent_names:
        if name not in registry_map:
            return JSONResponse(
                content={"error": f"Agent '{name}' not registered"},
                status_code=400,
            )
        reg = registry_map[name]
        agents_config.append({
            "name": name,
            "workspace": reg["workspace"],
            "role": reg.get("role", ""),
            "budget": cli_budget,
            "permission_mode": reg.get("permission_mode", "bypassPermissions"),
        })

    # Generate a unique chat_id — 8-char hex suffix via modulo (avoids string slice)
    _uid_suffix = f"{uuid4().int % 0x1_0000_0000:08x}"
    chat_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + _uid_suffix

    config = {
        "chat_id": chat_id,
        "topic": topic,
        "agents": agents_config,
        "project_cwd": str(Path(__file__).parent.parent.parent),  # workspace root
        "project_name": Path(__file__).parent.parent.parent.name,
        "max_turns": max_turns,
        "max_tokens": 0,
        "ws_port": 8877,
        "start_paused": True,
    }

    config_path = f"/tmp/chat_config_{chat_id}.json"
    Path(config_path).write_text(json.dumps(config, indent=2), encoding="utf-8")

    stream_chat_path = str(BASE_DIR / "stream_chat.py")
    proc = subprocess.Popen(
        [sys.executable, stream_chat_path, "--config", config_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _chat_pids[chat_id] = proc.pid
    log.info("Spawned chat %s (pid=%d, agents=%s)", chat_id, proc.pid, agent_names)

    return JSONResponse(content={"ok": True, "chat_id": chat_id, "pid": proc.pid}, status_code=201)


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str) -> JSONResponse:
    """
    Delete a chat: kill subprocess (if live), remove from live_chats, delete log files.
    """
    import signal

    safe_id = Path(chat_id).name

    # Kill the subprocess if tracked
    if safe_id in _chat_pids:
        pid = _chat_pids.pop(safe_id)
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Sent SIGTERM to chat %s (pid=%d)", safe_id, pid)
        except (ProcessLookupError, OSError) as exc:
            log.debug("Could not kill pid %d: %s", pid, exc)

    # Synthesize a chat_ended event if still live in memory
    if safe_id in live_chats and live_chats[safe_id].get("_live"):
        event = {"type": "chat_ended", "chat_id": safe_id}
        seq = _append_event(event)
        _update_live_chats(event)
        await _notify_sse({**event, "seq": seq})
        log.info("Synthesized chat_ended for deleted chat: %s", safe_id)

    # Remove from live_chats
    live_chats.pop(safe_id, None)

    # Delete log file(s) for this chat
    journal_path = _journal_path(safe_id)
    journal_path.unlink(missing_ok=True)

    for f in LOGS_DIR.glob(f"stream_{safe_id}*.json"):
        f.unlink(missing_ok=True)

    # Delete any journal subdirectory files
    journals_dir = BASE_DIR / "journals"
    if journals_dir.exists():
        for f in journals_dir.glob(f"{safe_id}*.jsonl"):
            f.unlink(missing_ok=True)

    log.info("Deleted chat: %s", safe_id)
    return JSONResponse(content={"ok": True})


@app.post("/api/chats/{chat_id}/resurrect")
async def resurrect_chat(chat_id: str, request: Request) -> JSONResponse:
    """
    Resurrect an ended chat with additional turns.

    Reads the original log, builds a new config with resume_from, spawns a new session.
    Body: {additional_turns?}
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    safe_id = Path(chat_id).name
    additional_turns = int(body.get("additional_turns", 10))

    # Locate the original log file
    log_files = list(LOGS_DIR.glob(f"stream_*{safe_id}*.json"))
    if not log_files:
        # Also try exact match
        exact = LOGS_DIR / f"stream_{safe_id}.json"
        if exact.exists():
            log_files = [exact]

    if not log_files:
        return JSONResponse(content={"error": "Log file not found for this chat"}, status_code=404)

    log_path = log_files[0]
    try:
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return JSONResponse(content={"error": f"Could not parse log: {exc}"}, status_code=500)

    # Reconstruct agents config from the log
    agents_config = []
    for _key, agent_info in log_data.get("agents", {}).items():
        agents_config.append({
            "name": agent_info.get("name", ""),
            "workspace": agent_info.get("workspace", ""),
            "role": agent_info.get("role", ""),
            "budget": 5.0,
        })

    if not agents_config:
        return JSONResponse(content={"error": "No agents found in log"}, status_code=400)

    new_chat_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + f"{uuid4().int % 0x1_0000_0000:08x}"
    old_max_turns = log_data.get("max_turns", len(log_data.get("turns", [])))

    config = {
        "chat_id": new_chat_id,
        "topic": log_data.get("topic", ""),
        "agents": agents_config,
        "project_cwd": str(Path(__file__).parent.parent.parent),
        "project_name": log_data.get("project", Path(__file__).parent.parent.parent.name),
        "max_turns": old_max_turns + additional_turns,
        "max_tokens": 0,
        "ws_port": 8877,
        "start_paused": True,
        "resume_from": str(log_path),
    }

    config_path = f"/tmp/chat_config_{new_chat_id}.json"
    Path(config_path).write_text(json.dumps(config, indent=2), encoding="utf-8")

    stream_chat_path = str(BASE_DIR / "stream_chat.py")
    proc = subprocess.Popen(
        [sys.executable, stream_chat_path, "--config", config_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _chat_pids[new_chat_id] = proc.pid
    log.info(
        "Resurrected chat %s → %s (pid=%d, +%d turns)",
        safe_id, new_chat_id, proc.pid, additional_turns,
    )

    return JSONResponse(content={"ok": True, "chat_id": new_chat_id, "pid": proc.pid})


@app.post("/api/chats/{chat_id}/add-turns")
async def add_turns(chat_id: str, request: Request) -> JSONResponse:
    """
    Extend the turn limit for a live chat.

    Body: {count?}  (default 5)
    Sends a /turns +N command to the orchestrator via the command queue.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    count = int(body.get("count", 5))
    await command_queue.put({"cmd": "/turns", "arg": f"+{count}"})
    log.info("Queued /turns +%d for chat %s", count, Path(chat_id).name)
    return JSONResponse(content={"ok": True, "added": count})


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
    # Support both header (standard) and query param (fallback)
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
# WebSocket — commands only (client → server)
# ---------------------------------------------------------------------------
@app.websocket("/ws/moderate")
async def ws_moderate(websocket: WebSocket) -> None:
    """
    WebSocket for sending commands from browser to orchestrator.
    Only handles: {"type": "command", "cmd": "/pause"|"/resume"|"/end"|..., "arg": "..."}
    Responds with ACK.
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
            if not cmd:
                continue

            log.info("Moderator command: %s %r", cmd, arg)
            await command_queue.put({"cmd": cmd, "arg": arg})

            # Acknowledge back
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
async def _stale_chat_detector(interval: float = 30.0) -> None:
    """Detect zombie chats whose orchestrator stopped sending events."""
    STALE_THRESHOLD = 60  # seconds without any event → stale
    log.info("Stale chat detector started (interval=%.0fs, threshold=%ds)", interval, STALE_THRESHOLD)
    try:
        while True:
            await asyncio.sleep(interval)
            now = datetime.now(timezone.utc)
            for cid, info in list(live_chats.items()):
                if not info.get("_live") or info.get("state") in ("ended", "stale", "paused"):
                    continue
                last_ts = info.get("_last_event_ts")
                if not last_ts:
                    continue
                if isinstance(last_ts, str):
                    last_ts = datetime.fromisoformat(last_ts)
                elapsed = (now - last_ts).total_seconds()
                if elapsed > STALE_THRESHOLD:
                    info["state"] = "stale"
                    log.info("Chat %s marked stale (no events for %.0fs)", cid, elapsed)
                    await _notify_sse({
                        "type": "status",
                        "chat_id": cid,
                        "state": "stale",
                        "seq": 0,
                    })
    except asyncio.CancelledError:
        log.info("Stale chat detector stopped.")
    except Exception as exc:
        log.error("Stale chat detector error: %s", exc)


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
                        # Notify via SSE (not broadcast — that's gone)
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
    asyncio.create_task(_stale_chat_detector())
    log.info(
        "Chat server v2 started. Logs: %s | Templates: %s",
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
