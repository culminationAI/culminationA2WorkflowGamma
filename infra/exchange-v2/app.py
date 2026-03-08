"""
Exchange v2 — minimal agent-to-agent message hub.
FastAPI + SQLite. No blockchain, no activities, no approve mode.
"""

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

log = logging.getLogger("exchange-v2")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_PATH = "/data/exchange_v2.db" if Path("/data").exists() else "./exchange_v2.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    from_agent  TEXT NOT NULL,
    to_agent    TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'message',
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    in_reply_to TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_to_status ON messages(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_messages_thread    ON messages(thread_id);

CREATE TABLE IF NOT EXISTS presence (
    agent      TEXT PRIMARY KEY,
    state      TEXT NOT NULL DEFAULT 'offline',
    updated_at TEXT NOT NULL
);
"""

VALID_AGENT = re.compile(r"^[a-zA-Z0-9_]{1,50}$")
VALID_TYPES    = {"message", "knowledge", "task", "system"}
VALID_STATUSES = {"pending", "read", "processed"}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    log.info("DB initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(ws_keepalive())
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Exchange v2", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket registry: agent_name -> WebSocket
connected_clients: Dict[str, WebSocket] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MessageCreate(BaseModel):
    from_agent: str
    to_agent: str
    type: str = "message"
    subject: str = ""
    body: str
    in_reply_to: Optional[str] = None

    @field_validator("from_agent", "to_agent")
    @classmethod
    def validate_agent(cls, v: str) -> str:
        if not VALID_AGENT.match(v):
            raise ValueError("Agent name: alphanumeric + underscore, 1-50 chars")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {VALID_TYPES}")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str) -> str:
        if len(v) > 10_000:
            raise ValueError("body max 10 000 chars")
        return v


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v


class PresenceUpdate(BaseModel):
    state: str = "online"

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in {"online", "busy", "offline"}:
            raise ValueError("state must be online | busy | offline")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def resolve_thread_id(conn: sqlite3.Connection, msg: MessageCreate, new_id: str) -> str:
    """
    New message   → thread_id = its own id.
    Reply         → thread_id inherited from the parent message.
    """
    if msg.in_reply_to is None:
        return new_id

    parent = conn.execute(
        "SELECT thread_id FROM messages WHERE id = ?", (msg.in_reply_to,)
    ).fetchone()

    if parent is None:
        raise HTTPException(status_code=404, detail=f"Parent message {msg.in_reply_to} not found")

    return parent["thread_id"]


async def push_to_ws(agent: str, message: dict) -> None:
    """Push a message dict to a connected WebSocket client, if any."""
    ws = connected_clients.get(agent)
    if ws is None:
        return
    try:
        await ws.send_text(json.dumps(message))
    except Exception as exc:
        log.warning("WS push to %s failed: %s", agent, exc)
        connected_clients.pop(agent, None)


async def ws_keepalive() -> None:
    """Ping all connected WebSocket clients every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        dead: List[str] = []
        for agent, ws in connected_clients.items():
            try:
                await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                dead.append(agent)
        for agent in dead:
            connected_clients.pop(agent, None)


# ---------------------------------------------------------------------------
# Routes — Messages
# ---------------------------------------------------------------------------

@app.post("/messages", status_code=201)
async def create_message(payload: MessageCreate) -> dict:
    msg_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        thread_id = resolve_thread_id(conn, payload, msg_id)

        conn.execute(
            """
            INSERT INTO messages
                (id, thread_id, from_agent, to_agent, type, subject, body,
                 in_reply_to, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                msg_id, thread_id,
                payload.from_agent, payload.to_agent,
                payload.type, payload.subject, payload.body,
                payload.in_reply_to, now,
            ),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        msg = row_to_dict(row)

    # Real-time delivery if target is connected
    await push_to_ws(payload.to_agent, msg)

    return msg


@app.get("/messages")
async def list_messages(
    to:     Optional[str] = Query(default=None),
    from_:  Optional[str] = Query(default=None, alias="from"),
    status: Optional[str] = Query(default=None),
    type:   Optional[str] = Query(default=None),
    limit:  int           = Query(default=50, ge=1, le=500),
) -> list:
    filters: list = []
    params:  list = []

    if to:
        filters.append("to_agent = ?")
        params.append(to)
    if from_:
        filters.append("from_agent = ?")
        params.append(from_)
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(422, f"status must be one of {VALID_STATUSES}")
        filters.append("status = ?")
        params.append(status)
    if type:
        if type not in VALID_TYPES:
            raise HTTPException(422, f"type must be one of {VALID_TYPES}")
        filters.append("type = ?")
        params.append(type)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM messages {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()

    return [row_to_dict(r) for r in rows]


@app.patch("/messages/{msg_id}")
async def update_message_status(msg_id: str, payload: StatusUpdate) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM messages WHERE id = ?", (msg_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Message not found")

        conn.execute(
            "UPDATE messages SET status = ? WHERE id = ?",
            (payload.status, msg_id),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()

    return row_to_dict(row)


# ---------------------------------------------------------------------------
# Routes — Threads
# ---------------------------------------------------------------------------

@app.get("/threads/{thread_id}")
async def get_thread(thread_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Thread not found")

    return [row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Routes — Presence
# ---------------------------------------------------------------------------

@app.post("/presence/{agent}")
async def update_presence(agent: str, body: PresenceUpdate = PresenceUpdate()) -> dict:
    if not VALID_AGENT.match(agent):
        raise HTTPException(422, "Invalid agent name")

    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO presence (agent, state, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(agent) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at
            """,
            (agent, body.state, now),
        )
        conn.commit()

    return {"agent": agent, "state": body.state, "updated_at": now}


@app.get("/presence")
async def get_all_presence() -> list:
    now = datetime.now(timezone.utc)

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM presence").fetchall()

    result = []
    for row in rows:
        entry = row_to_dict(row)
        updated = datetime.fromisoformat(entry["updated_at"])
        age_seconds = (now - updated).total_seconds()
        if age_seconds > 90:
            entry["state"] = "offline"
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/{agent}")
async def websocket_endpoint(websocket: WebSocket, agent: str) -> None:
    if not VALID_AGENT.match(agent):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    connected_clients[agent] = websocket
    log.info("WS connected: %s", agent)

    try:
        while True:
            # Keep the connection open; client sends nothing (or pong responses)
            await websocket.receive_text()
    except WebSocketDisconnect:
        log.info("WS disconnected: %s", agent)
    except Exception as exc:
        log.warning("WS error for %s: %s", agent, exc)
    finally:
        connected_clients.pop(agent, None)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    return {
        "status": "ok",
        "messages": count,
        "connected_agents": list(connected_clients.keys()),
    }
