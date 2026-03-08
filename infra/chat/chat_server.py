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

# Commands from moderator UI → orchestrator (per-chat queues)
_command_queues: dict[str, asyncio.Queue] = {}

def _get_cmd_queue(chat_id: str) -> asyncio.Queue:
    """Get or create a per-chat command queue."""
    if chat_id not in _command_queues:
        _command_queues[chat_id] = asyncio.Queue()
    return _command_queues[chat_id]

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
        # Merge live_chats data (max_turns may have been set before subprocess started)
        if safe_id in live_chats:
            lc = live_chats[safe_id]
            if not chat.get("max_turns") and lc.get("max_turns"):
                chat["max_turns"] = lc["max_turns"]
        return JSONResponse(content=chat)

    # Second: try live_chats (for empty/waiting chats with no events yet)
    if safe_id in live_chats:
        lc = live_chats[safe_id]
        return JSONResponse(content={
            "chat_id": safe_id,
            "topic": lc.get("topic", ""),
            "agents": lc.get("agents", {}),
            "turns": lc.get("turns", []),
            "facts": [],
            "started_at": lc.get("started_at", ""),
            "ended_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "state": lc.get("state", "waiting"),
            "max_turns": lc.get("max_turns", 5),
            "_live": True,
        })

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
        cid = body.get("chat_id", "")
        if cid:
            q = _get_cmd_queue(cid)
            while not q.empty():
                try:
                    q.get_nowait()
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
async def get_commands(chat_id: str = "") -> JSONResponse:
    """Return pending moderator commands from the per-chat queue (drains it)."""
    if not chat_id:
        return JSONResponse(content=[])
    q = _get_cmd_queue(chat_id)
    commands: list[dict] = []
    while not q.empty():
        try:
            commands.append(q.get_nowait())
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

    # Drain stale commands + cleanup queue
    q = _get_cmd_queue(safe_id)
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break
    _command_queues.pop(safe_id, None)

    # Kill subprocess if running
    if safe_id in _chat_pids:
        pid = _chat_pids.pop(safe_id)
        try:
            os.kill(pid, 9)
            log.info("Killed subprocess pid=%d for chat %s", pid, safe_id)
        except OSError:
            pass

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
    Create and (optionally) spawn a new chat session.

    Body: {topic, agents?: [names], max_turns?, budget?}
    If agents are provided: writes a temp config to /tmp, spawns stream_chat.py.
    If agents list is empty or omitted: creates an empty chat (no subprocess).
    Agents can be added later via POST /api/chats/{chat_id}/add-agent.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    topic = body.get("topic", "").strip()
    agent_names = body.get("agents", [])
    max_turns = int(body.get("max_turns", 5))
    cli_budget = float(body.get("budget", 5.0))

    if not topic:
        return JSONResponse(content={"error": "topic is required"}, status_code=400)

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

    # Always insert into live_chats so the chat appears in the sidebar immediately
    now_iso = datetime.now(timezone.utc).isoformat()
    live_chats[chat_id] = {
        "chat_id": chat_id,
        "topic": topic,
        "agents": {},
        "turns": [],
        "_live": True,
        "state": "waiting",
        "started_at": now_iso,
        "_last_event_ts": datetime.now(timezone.utc),
        "max_turns": max_turns,
    }

    if agents_config:
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
        live_chats[chat_id]["state"] = "paused"
        log.info("Spawned chat %s (pid=%d, agents=%s)", chat_id, proc.pid, agent_names)
        return JSONResponse(content={"ok": True, "chat_id": chat_id, "pid": proc.pid}, status_code=201)
    else:
        # Empty chat — no subprocess, user will add agents later
        log.info("Created empty chat %s (no agents yet)", chat_id)
        return JSONResponse(content={"ok": True, "chat_id": chat_id, "pid": None}, status_code=201)


@app.post("/api/chats/{chat_id}/add-agent")
async def add_agent_to_chat(chat_id: str, request: Request) -> JSONResponse:
    """
    Add an agent to an existing chat by name.

    Body: {name, max_turns?, budget?}
    If the chat has no running subprocess yet, spawning happens here
    using a fresh config that includes all currently registered agents plus the new one.
    If a subprocess is already running, only the in-memory sidebar entry is updated
    (the live orchestrator cannot hot-add agents mid-session).
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

    max_turns = int(body.get("max_turns", 5))
    cli_budget = float(body.get("budget", 5.0))

    # Validate agent is in the registry
    registry = _load_agents()
    registry_map = {a["name"]: a for a in registry}
    if agent_name not in registry_map:
        return JSONResponse(
            content={"error": f"Agent '{agent_name}' not registered"},
            status_code=400,
        )

    reg = registry_map[agent_name]
    new_agent_cfg = {
        "name": agent_name,
        "workspace": reg["workspace"],
        "role": reg.get("role", ""),
        "budget": cli_budget,
        "permission_mode": reg.get("permission_mode", "bypassPermissions"),
    }

    # Update in-memory sidebar entry
    chat_info = live_chats[safe_id]
    agents_dict = chat_info.setdefault("agents", {})
    next_key = str(len(agents_dict))
    agents_dict[next_key] = {"name": agent_name}
    chat_info["_last_event_ts"] = datetime.now(timezone.utc)

    # If no subprocess is running yet, spawn one now
    if safe_id not in _chat_pids:
        # Collect all agents already in live_chats plus the new one
        existing_agents = [
            info for info in agents_dict.values()
            if info.get("name") and info["name"] != agent_name
        ]
        agents_config = [
            {
                "name": a["name"],
                "workspace": registry_map[a["name"]]["workspace"],
                "role": registry_map[a["name"]].get("role", ""),
                "budget": cli_budget,
                "permission_mode": registry_map[a["name"]].get("permission_mode", "bypassPermissions"),
            }
            for a in existing_agents
            if a["name"] in registry_map
        ]
        agents_config.append(new_agent_cfg)

        topic = chat_info.get("topic", "")
        effective_max_turns = chat_info.get("max_turns", max_turns)
        config = {
            "chat_id": safe_id,
            "topic": topic,
            "agents": agents_config,
            "project_cwd": str(Path(__file__).parent.parent.parent),
            "project_name": Path(__file__).parent.parent.parent.name,
            "max_turns": effective_max_turns,
            "max_tokens": 0,
            "ws_port": 8877,
            "start_paused": True,
        }

        config_path = f"/tmp/chat_config_{safe_id}.json"
        Path(config_path).write_text(json.dumps(config, indent=2), encoding="utf-8")

        stream_chat_path = str(BASE_DIR / "stream_chat.py")
        proc = subprocess.Popen(
            [sys.executable, stream_chat_path, "--config", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _chat_pids[safe_id] = proc.pid
        chat_info["state"] = "paused"
        agent_names_list = [a["name"] for a in agents_config]
        log.info(
            "Spawned chat %s (pid=%d, agents=%s) after add-agent",
            safe_id, proc.pid, agent_names_list,
        )
        return JSONResponse(content={"ok": True, "chat_id": safe_id, "pid": proc.pid, "spawned": True})

    log.info("Added agent %s to live chat %s (no respawn — subprocess running)", agent_name, safe_id)
    return JSONResponse(content={"ok": True, "chat_id": safe_id, "pid": _chat_pids[safe_id], "spawned": False})


@app.delete("/api/chats/{chat_id}/agents/{agent_name}")
async def remove_agent_from_chat(chat_id: str, agent_name: str) -> JSONResponse:
    """Remove an agent from a waiting chat (no running subprocess)."""
    import signal

    safe_id = Path(chat_id).name
    if safe_id not in live_chats:
        return JSONResponse(content={"error": "Chat not found"}, status_code=404)

    chat_info = live_chats[safe_id]

    # Cannot hot-remove from running subprocess
    if safe_id in _chat_pids:
        return JSONResponse(
            content={"error": "Stop the chat first to remove agents"},
            status_code=409,
        )

    agents_dict = chat_info.get("agents", {})
    key_to_remove = None
    for key, agent in agents_dict.items():
        if agent.get("name") == agent_name:
            key_to_remove = key
            break

    if key_to_remove is None:
        return JSONResponse(
            content={"error": f"Agent '{agent_name}' not in this chat"},
            status_code=404,
        )

    del agents_dict[key_to_remove]

    # Re-key remaining agents to sequential numeric keys
    remaining = list(agents_dict.values())
    agents_dict.clear()
    for i, a in enumerate(remaining):
        agents_dict[str(i)] = a

    chat_info["_last_event_ts"] = datetime.now(timezone.utc)
    log.info("Removed agent %s from chat %s", agent_name, safe_id)
    return JSONResponse(content={"ok": True, "chat_id": safe_id})


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
    safe_id = Path(chat_id).name

    # Always update live_chats so the UI reflects the change immediately
    if safe_id in live_chats:
        old_max = live_chats[safe_id].get("max_turns", 0)
        live_chats[safe_id]["max_turns"] = old_max + count

    # If subprocess is running, also forward to orchestrator
    if safe_id in _chat_pids:
        await _get_cmd_queue(safe_id).put({"cmd": "/turns", "arg": f"+{count}"})

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
            chat_id = msg.get("chat_id", "").strip()
            if not cmd:
                continue

            log.info("Moderator command [%s]: %s %r", chat_id or "?", cmd, arg)
            if chat_id:
                await _get_cmd_queue(chat_id).put({"cmd": cmd, "arg": arg})
            else:
                # Fallback: put into all active chat queues
                for cid in list(_chat_pids.keys()):
                    await _get_cmd_queue(cid).put({"cmd": cmd, "arg": arg})

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
