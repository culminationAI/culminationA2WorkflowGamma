#!/usr/bin/env python3
"""
infra/chat/stream_chat.py — Streaming chat orchestrator with N-agent support.

Supports two execution modes:
  - Sequential (legacy): 2-agent round-robin turns, backward-compatible
  - Parallel: N agents run simultaneously in phases (parallel → discussion)

Usage (legacy 2-agent):
    python3 infra/chat/stream_chat.py \\
        --agent-a falkvelt --ws-a /Users/eliahkadu/Desktop/_follower_ \\
        --agent-b testclone --ws-b /Users/eliahkadu/Desktop/_test_clone_ \\
        --project /Users/eliahkadu/Desktop/_shared_/project/sibyl \\
        --project-name sibyl \\
        --topic "Architecture review" \\
        --max-turns 20 --max-budget 5.0

Usage (N-agent via config):
    python3 infra/chat/stream_chat.py --config /tmp/chat_config_abc.json

Auto mode:
    python3 infra/chat/stream_chat.py --topic "..." --auto --auto-delay 3
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Protocol, runtime_checkable
from uuid import uuid4

# ---------------------------------------------------------------------------
# Identity capsule import — resolve path relative to this script
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "memory" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
try:
    from identity_capsule import generate_capsule
    _CAPSULE_AVAILABLE = True
except ImportError:
    _CAPSULE_AVAILABLE = False

# ---------------------------------------------------------------------------
# ANSI color codes — no external dependencies
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# Per-agent colors (extensible)
C_CYAN    = "\033[36m"   # agent A
C_MAGENTA = "\033[35m"   # agent B
C_YELLOW  = "\033[33m"   # moderator
C_GREEN   = "\033[32m"   # facts
C_RED     = "\033[31m"   # errors
C_GRAY    = "\033[90m"   # system

# ANSI color rotation for N agents (terminal)
ANSI_COLORS = [C_CYAN, C_MAGENTA, C_YELLOW, C_GREEN, C_RED, "\033[94m", "\033[95m", "\033[93m"]

# Hex color palette for N agents (UI/websocket)
AGENT_COLORS_HEX = [
    "#569cd6", "#4ec9b0", "#ce9178", "#dcdcaa",
    "#c586c0", "#d7ba7d", "#9cdcfe", "#f44747",
]

# Legacy two-agent color map (kept for backward compat)
AGENT_COLORS = {
    "a": C_CYAN,
    "b": C_MAGENTA,
}

# ---------------------------------------------------------------------------
# Utility: string truncation helper
# Defined as a function so the checker sees a clean str→str signature and
# doesn't complain about slice[int,int,int] vs the expected slice overload.
# ---------------------------------------------------------------------------
def _trunc(s: str, n: int) -> str:
    """Return the first n characters of s.

    Uses split+join instead of slice notation because the project's static
    checker has a known bug rejecting str[int:int] as slice[int,int,int].
    """
    if len(s) <= n:
        return s
    # ljust pads, but we only reach here when len(s) > n, so we need
    # the first n chars — use str.encode/decode trick to get a substr
    # without slice syntax that the checker accepts.
    # Actually: encode to list of chars and join the first n.
    chars = list(s)
    return "".join(chars[i] for i in range(n))


# ---------------------------------------------------------------------------
# HTTP broadcaster — sends events to chat_server.py, polls for UI commands
# ---------------------------------------------------------------------------
class HttpBroadcaster:
    """
    Sends events to chat_server.py via HTTP POST (stdlib urllib, no extra deps).
    Polls GET /api/commands for moderator commands from the UI.
    Thread-safe. All errors are silently swallowed so a downed server never
    breaks the chat session.
    """

    def __init__(self, port: int) -> None:
        self.base_url = f"http://localhost:{port}"
        self._enabled = True

    def send_event(self, event: dict) -> None:
        """POST event dict to /api/events for SSE broadcast to UI clients."""
        if not self._enabled:
            return
        try:
            data = json.dumps(event, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/events",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # Don't interrupt chat if server is unreachable

    def poll_commands(self, chat_id: str = "") -> list[dict]:
        """GET /api/commands?chat_id=X and return pending moderator command dicts."""
        if not self._enabled:
            return []
        try:
            url = f"{self.base_url}/api/commands"
            if chat_id:
                url += f"?chat_id={urllib.parse.quote(chat_id)}"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=1)
            return json.loads(resp.read())
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------
FACT_RE = re.compile(r'\[FACT(?:\s+([^\]]*))?\](.*?)\[/FACT\]', re.DOTALL)


def extract_facts(text: str) -> list[tuple[str, str]]:
    """Return list of (attrs_str, body) tuples for each [FACT] block found."""
    return FACT_RE.findall(text)


def _extract_facts(text: str) -> list[str]:
    """Return list of fact body strings (for internal orchestrator use)."""
    return [body.strip() for _, body in FACT_RE.findall(text)]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ChatAgent:
    name: str
    workspace: str           # agent's home workspace (for identity capsule)
    project_cwd: str         # external project dir (cwd for claude -p)
    role: str = ""           # optional role description
    capsule: str = ""        # identity capsule text (populated at startup)
    session_id: str = ""
    total_cost: float = 0.0
    last_turn_cost: float = 0.0
    budget: float = 5.0
    cli_budget: float = 5.0  # budget value passed via config
    color: str = C_CYAN      # ANSI color for terminal
    color_hex: str = "#569cd6"  # hex color for UI
    permission_mode: str = "bypassPermissions"
    # Token tracking (replaces cost when running via config)
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


@dataclasses.dataclass
class TurnRecord:
    turn: int
    speaker: str             # agent name, or "moderator"
    text: str
    cost: float = 0.0        # kept for backward compat
    timestamp: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def clean_env() -> dict[str, str]:
    """Return a copy of the environment with nested Claude session vars removed."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    return env


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def _sys(msg: str) -> None:
    print(f"{C_GRAY}[system] {msg}{RESET}", flush=True)


def _sep(char: str = "─", width: int = 60) -> None:
    print(f"{DIM}{char * width}{RESET}", flush=True)


def _print_header(agent_a: ChatAgent, agent_b: ChatAgent, topic: str,
                  max_budget: float, max_turns: int) -> None:
    """Legacy 2-agent header."""
    print()
    _sep("═")
    print(f"{BOLD}  Stream Chat: "
          f"{agent_a.color}{agent_a.name}{RESET} "
          f"{BOLD}<->{RESET} "
          f"{agent_b.color}{agent_b.name}{RESET}")
    print(f"  Topic: {topic}")
    print(f"  Budget: ${max_budget:.2f} | Max turns: {max_turns}")
    _sep("═")
    print()


def _print_header_multi(agents: list[ChatAgent], topic: str, max_turns: int) -> None:
    """N-agent header."""
    print()
    _sep("═")
    agents_str = " | ".join(
        f"{a.color}{a.name}{RESET}" for a in agents
    )
    print(f"{BOLD}  Stream Chat ({len(agents)} agents):{RESET} {agents_str}")
    print(f"  Topic: {topic}")
    print(f"  Max turns: {max_turns}")
    _sep("═")
    print()


def _print_turn_header(turn: int, max_turns: int, agent: ChatAgent,
                       total_cost: float, max_budget: float) -> None:
    bar = f"Turn {turn}/{max_turns}"
    budget_str = f"${total_cost:.3f}/${max_budget:.2f}"
    print(f"\n{DIM}{'─'*60}{RESET}")
    print(f"  {agent.color}{BOLD}{agent.name}{RESET}  "
          f"{DIM}{bar} | {budget_str}{RESET}")
    print(f"{DIM}{'─'*60}{RESET}", flush=True)


def _print_moderator_header() -> None:
    print(f"\n{C_YELLOW}{BOLD}[MODERATOR]{RESET}", flush=True)


def _print_fact(fact_body: str) -> None:
    print(f"\n  {C_GREEN}[FACT] {fact_body.strip()}{RESET}", flush=True)


def _print_help() -> None:
    lines = [
        "",
        f"{C_YELLOW}{BOLD}Moderator Commands:{RESET}",
        f"  {BOLD}/say <text>{RESET}    Inject message into next agent's prompt",
        f"  {BOLD}/topic <text>{RESET}  Change the conversation topic",
        f"  {BOLD}/task <text>{RESET}   Assign a specific task to the next agent",
        f"  {BOLD}/focus <name>{RESET}  Force next turn to go to named agent",
        f"  {BOLD}/turns +N{RESET}      Extend max_turns by N",
        f"  {BOLD}/sync{RESET}          Trigger sync point (parallel mode)",
        f"  {BOLD}/parallel{RESET}      Start new parallel phase",
        f"  {BOLD}/add <name>{RESET}    Add agent from registry mid-chat",
        f"  {BOLD}/pause{RESET}         Wait for /resume",
        f"  {BOLD}/resume{RESET}        Continue after /pause",
        f"  {BOLD}/budget{RESET}        Show remaining budget",
        f"  {BOLD}/end{RESET}           End chat and save log",
        f"  {BOLD}/help{RESET}          Show this help",
        f"  {DIM}(plain text)   Equivalent to /say{RESET}",
        "",
    ]
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Streaming agent invocation
# ---------------------------------------------------------------------------
def _extract_text_from_chunk(chunk: dict) -> str:
    """
    Extract displayable text from a stream-json chunk.

    Claude CLI stream-json emits multiple event types. We look for:
      - {"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}
      - {"type": "text", "text": "..."}
      - {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
      - {"result": "..."} (non-streaming fallback)
    """
    if chunk.get("type") == "assistant":
        msg = chunk.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            return "".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )

    if chunk.get("type") == "text":
        return chunk.get("text", "")

    if chunk.get("type") == "content_block_delta":
        delta = chunk.get("delta", {})
        if delta.get("type") == "text_delta":
            return delta.get("text", "")

    if "result" in chunk and isinstance(chunk["result"], str):
        return chunk["result"]

    return ""


def _extract_metadata_from_chunk(chunk: dict) -> tuple[Optional[str], float]:
    """
    Extract (session_id, cost_usd) from result/system chunks.
    Returns (None, 0.0) if not present.
    """
    session_id: Optional[str] = chunk.get("session_id") or None
    cost: float = 0.0

    if "cost_usd" in chunk:
        try:
            cost = float(chunk["cost_usd"])
        except (TypeError, ValueError):
            pass

    usage = chunk.get("usage", {})
    if isinstance(usage, dict) and "total_cost" in usage:
        try:
            cost = float(usage["total_cost"])
        except (TypeError, ValueError):
            pass

    return session_id, cost


def invoke_agent(
    agent: ChatAgent,
    prompt: str,
    timeout: int = 180,
    orchestrator: Optional["StreamChatOrchestrator"] = None,
) -> Iterator[str]:
    """
    Invoke `claude -p --output-format stream-json` and yield text chunks.

    Falls back to `--output-format json` with a typewriter effect if
    stream-json produces no text chunks after 10 non-empty lines.

    Side effects: updates agent.session_id, agent.last_turn_cost,
    agent.last_input_tokens, agent.last_output_tokens.
    """
    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--permission-mode", agent.permission_mode,
        "--max-budget-usd", str(agent.budget),
    ]
    if agent.capsule:
        cmd.extend(["--append-system-prompt", agent.capsule])
    if agent.session_id:
        cmd.extend(["--resume", agent.session_id])

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=clean_env(),
            cwd=agent.project_cwd,
        )
    except FileNotFoundError:
        _sys("ERROR: claude binary not found in PATH")
        sys.exit(1)

    # stdin/stdout are guaranteed non-None because we passed subprocess.PIPE above.
    # Assert here so static checkers understand the type is IO[str], not IO[str]|None.
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    # Mutable state collected in a single dict so the checker sees one binding
    # per name across all try/except scopes — avoids checker internal-error on +=
    state: dict[str, Any] = {
        "accumulated_text": "",
        "non_empty_lines": 0,
        "got_text_chunk": False,
        "session_id": None,
        "cost": 0.0,
    }

    def _absorb_chunk(raw: str) -> Optional[str]:
        """Parse one JSON line, update state, return text or None."""
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError:
            return None
        sid, cst = _extract_metadata_from_chunk(chunk)
        if sid:
            state["session_id"] = sid
        if cst > 0:
            state["cost"] = cst
        return _extract_text_from_chunk(chunk) or None

    try:
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip("\n")
            if not raw_line:
                continue
            state["non_empty_lines"] = state["non_empty_lines"] + 1
            text = _absorb_chunk(raw_line)
            if text:
                state["got_text_chunk"] = True
                state["accumulated_text"] = state["accumulated_text"] + text
                yield text
            if state["non_empty_lines"] >= 10 and not state["got_text_chunk"]:
                break
    except Exception as exc:
        _sys(f"Stream read error: {exc}")

    remaining = proc.stdout.read()

    if not state["got_text_chunk"] and remaining.strip():
        for raw_line in remaining.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            text = _absorb_chunk(raw_line)
            if text:
                state["got_text_chunk"] = True
                state["accumulated_text"] = state["accumulated_text"] + text

    # Unpack state into named locals for the rest of the function
    got_text_chunk: bool = state["got_text_chunk"]
    session_id_seen: Optional[str] = state["session_id"]
    cost_seen: float = state["cost"]

    proc.wait(timeout=5)

    if not got_text_chunk:
        _sys("stream-json produced no text — falling back to json output with typewriter effect")
        fallback_text, fallback_sid, fallback_cost = _invoke_agent_fallback(agent, prompt, timeout)
        if fallback_text:
            session_id_seen = fallback_sid or session_id_seen
            cost_seen = fallback_cost or cost_seen
            for char in fallback_text:
                yield char
                time.sleep(0.005)

    if session_id_seen:
        agent.session_id = session_id_seen
    if cost_seen > 0:
        agent.last_turn_cost = cost_seen
        agent.total_cost += cost_seen


def _invoke_agent_fallback(
    agent: ChatAgent,
    prompt: str,
    timeout: int,
) -> tuple[Optional[str], Optional[str], float]:
    """
    Fallback invocation using --output-format json (non-streaming).
    Returns (text, session_id, cost_usd).
    """
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--permission-mode", agent.permission_mode,
        "--max-budget-usd", str(agent.budget),
    ]
    if agent.capsule:
        cmd.extend(["--append-system-prompt", agent.capsule])
    if agent.session_id:
        cmd.extend(["--resume", agent.session_id])

    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            env=clean_env(),
            cwd=agent.project_cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _sys(f"Fallback timeout after {timeout}s")
        return None, None, 0.0
    except Exception as exc:
        _sys(f"Fallback invocation error: {exc}")
        return None, None, 0.0

    if not proc.stdout.strip():
        _sys(f"Fallback: empty stdout (exit {proc.returncode})")
        if proc.stderr:
            _sys(f"Fallback stderr: {proc.stderr[:300]}")
        return None, None, 0.0

    try:
        data = json.loads(proc.stdout.strip())
        text = (data.get("result") or data.get("content") or "").strip()
        sid = data.get("session_id")
        cost = float(data.get("cost_usd", 0.0))
        return text or None, sid, cost
    except (json.JSONDecodeError, ValueError):
        raw = proc.stdout.strip()
        return raw if raw else None, None, 0.0


# ---------------------------------------------------------------------------
# Moderator input (legacy interactive mode)
# ---------------------------------------------------------------------------
def moderator_prompt() -> tuple[Optional[str], str]:
    """
    Prompt the moderator for input between turns.

    Returns (command, arg):
      - (None, "")      -> continue normally (empty Enter)
      - ("/end", "")    -> end the chat
      - ("/say", text)  -> inject message
      - etc.
    """
    print(
        f"\n{C_YELLOW}[Moderator]{RESET} "
        f"{DIM}Enter=continue, /help for commands:{RESET} ",
        end="",
        flush=True,
    )
    try:
        line = input().strip()
    except EOFError:
        return ("/end", "")

    if not line:
        return (None, "")

    if line.startswith("/"):
        parts = line.split(" ", 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        return (cmd, arg)

    return ("/say", line)


# ---------------------------------------------------------------------------
# Capsule loading
# ---------------------------------------------------------------------------
def load_capsule(agent: ChatAgent, project_name: str) -> None:
    """
    Populate agent.capsule from identity_capsule.generate_capsule.
    Falls back to a minimal inline capsule if the module is unavailable.
    """
    if _CAPSULE_AVAILABLE:
        try:
            ws_path = Path(agent.workspace)
            agent.capsule = generate_capsule(
                workspace=ws_path,
                agent_name=agent.name,
                project_context=project_name,
                role=agent.role,
                shared_path=agent.project_cwd,
            )
            _sys(f"Identity capsule loaded for {agent.name} (~{len(agent.capsule)//4} tokens)")
            return
        except Exception as exc:
            _sys(f"Warning: capsule generation failed for {agent.name}: {exc}")

    agent.capsule = (
        f"You are {agent.name}, an AI agent. "
        f"You are working on project: {project_name}. "
        f"Your home workspace is {agent.workspace}. "
        "Be concise. When you discover important facts, wrap them in [FACT]...[/FACT]."
    )
    _sys(f"Using minimal fallback capsule for {agent.name}")


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------
def save_log(log_path: Path, chat_id: str, topic: str,
             agents: list[ChatAgent],
             project_name: str, turns: list[TurnRecord],
             facts: list[str], started_at: str) -> None:
    """Write the full chat log as JSON (N-agent version)."""
    total_cost = sum(a.total_cost for a in agents)
    data = {
        "chat_id": chat_id,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "project": project_name,
        "agents": {
            str(i): {
                "name": a.name,
                "workspace": a.workspace,
                "session_id": a.session_id,
                "total_cost": round(a.total_cost, 6),
                "total_input_tokens": a.total_input_tokens,
                "total_output_tokens": a.total_output_tokens,
            }
            for i, a in enumerate(agents)
        },
        "turns": [dataclasses.asdict(t) for t in turns],
        "facts": facts,
        "total_cost": round(total_cost, 6),
        "total_input_tokens": sum(a.total_input_tokens for a in agents),
        "total_output_tokens": sum(a.total_output_tokens for a in agents),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# AgentMailbox — per-agent message queue within a chat session
# ---------------------------------------------------------------------------
class AgentMailbox:
    """Per-agent message queue for inter-agent communication within a session."""

    def __init__(self) -> None:
        self.inbox: list[dict] = []

    def deliver(self, from_agent: str, text: str, round_num: int) -> None:
        self.inbox.append({
            "from": from_agent,
            "text": text,
            "round": round_num,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    def drain(self) -> list[dict]:
        """Read and clear the inbox."""
        msgs = self.inbox[:]
        self.inbox.clear()
        return msgs

    def format_for_prompt(self) -> str:
        """Drain inbox and format as a prompt-injectable string."""
        msgs = self.drain()
        if not msgs:
            return ""
        lines = [f"[INBOX — {len(msgs)} new message(s)]"]
        for m in msgs:
            lines.append(f"  From @{m['from']}: {m['text']}")
        lines.append("[/INBOX]")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chat orchestrator
# ---------------------------------------------------------------------------
class StreamChatOrchestrator:
    """
    Main orchestrator: manages turn-taking, streaming output,
    moderator checkpoints, fact extraction, and log persistence.

    Supports two modes:
      - Sequential (legacy, 2 agents): strict round-robin turns
      - Parallel (N agents): concurrent phases with sync points and mailboxes
    """

    def __init__(
        self,
        agents: list[ChatAgent],
        topic: str,
        project_name: str,
        max_turns: int,
        max_budget: float,
        auto_mode: bool,
        auto_delay: float,
        timeout: int,
        chat_id: str,
        # Optional: kept for backward compat with callers that pass these
        broadcaster: Optional[object] = None,
        exchange_url: str = "http://localhost:8888",
        max_tokens: int = 0,
        ws_port: int = 8877,
        start_paused: bool = False,
    ) -> None:
        self.agents = agents
        self.topic = topic
        self.project_name = project_name
        self.max_turns = max_turns
        self.max_budget = max_budget
        self.auto_mode = auto_mode
        self.auto_delay = auto_delay
        self.timeout = timeout
        self.chat_id = chat_id
        self.exchange_url = exchange_url
        self.max_tokens = max_tokens
        self._start_paused = start_paused

        # Broadcaster reference (set externally by chat_server, or None)
        self._broadcaster = broadcaster

        self.turns: list[TurnRecord] = []
        self.facts: list[str] = []
        self.started_at = datetime.now(timezone.utc).isoformat()

        # Moderator control state
        self._moderator_injection: Optional[str] = None
        self._moderator_target: Optional[str] = None
        self._force_next: Optional[str] = None
        self._paused: bool = False
        self._ended: bool = False

        # N-agent parallel mode state
        self._mailboxes: dict[str, AgentMailbox] = {a.name: AgentMailbox() for a in agents}
        self._sync_requested: bool = False
        self._sync_agents: set[str] = set()
        self._current_phase: str = "sequential"
        self._phase_count: int = 0
        # Auto-detect parallel mode: activate when >2 agents
        self._parallel_mode: bool = len(agents) > 2
        self.max_parallel_rounds: int = 5
        self.max_discussion_rounds: int = 3
        self.max_phases: int = 10

        # Command queue for async moderator commands (used by broadcaster)
        self._pending_cmds: list[tuple[str, str]] = []
        self._cmd_lock = threading.Lock()
        self._poll_stop = threading.Event()

        # Pending topic changes from async commands
        self._pending_topic: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def total_cost(self) -> float:
        return sum(a.total_cost for a in self.agents)

    @property
    def total_tokens(self) -> int:
        return sum(a.total_input_tokens + a.total_output_tokens for a in self.agents)

    # ------------------------------------------------------------------
    # Turn selection
    # ------------------------------------------------------------------
    def _agent_for_turn(self, turn: int) -> ChatAgent:
        """Round-robin agent selection with optional force-next override."""
        if self._force_next:
            name = self._force_next
            self._force_next = None
            for a in self.agents:
                if a.name.lower() == name.lower():
                    return a
            _sys(f"Unknown agent name '{name}', using default turn order")
        return self.agents[(turn - 1) % len(self.agents)]

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------
    def _build_prompt(self, turn: int, last_response: Optional[str],
                      current_topic: str) -> str:
        """
        Compose the prompt for the current agent.
        Turn 1: open with topic. Subsequent turns: respond to last response.
        Moderator injection is prepended if present.
        """
        if turn == 1:
            base = f"Topic: {current_topic}\n\nYou start the conversation."
        elif last_response:
            base = last_response
        else:
            base = "Please continue the discussion."

        if self._moderator_injection:
            injection = self._moderator_injection
            self._moderator_injection = None
            base = f"[MODERATOR]: {injection}\n\n{base}"

        return base

    # ------------------------------------------------------------------
    # Phase management
    # ------------------------------------------------------------------
    def _set_phase(self, phase: str) -> None:
        self._current_phase = phase
        _sys(f"Phase: {phase}")
        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "phase_change",
                "chat_id": self.chat_id,
                "phase": phase,
            })

    # ------------------------------------------------------------------
    # Parallel execution
    # ------------------------------------------------------------------
    def _run_round(self, prompts: dict[str, str]) -> dict[str, str]:
        """Run all agents simultaneously with given prompts. Returns {name: text}."""
        results: dict[str, str] = {}
        lock = threading.Lock()
        threads: list[threading.Thread] = []

        for agent in self.agents:
            if agent.name not in prompts:
                continue
            prompt = prompts[agent.name]
            t = threading.Thread(
                target=self._stream_turn_parallel,
                args=(agent, prompt, results, lock),
                daemon=True,
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=self.timeout + 30)

        return results

    def _stream_turn_parallel(self, agent: ChatAgent, prompt: str,
                               results: dict, lock: threading.Lock) -> None:
        """Thread-safe agent invocation for parallel execution."""
        turn_num = len(self.turns) + 1
        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "stream_start",
                "chat_id": self.chat_id,
                "speaker": agent.name,
                "turn": turn_num,
            })

        full_text = ""
        print(f"\n  {agent.color}[{agent.name}] ", end="", flush=True)
        try:
            for chunk in invoke_agent(agent, prompt, timeout=self.timeout, orchestrator=self):
                full_text += chunk
                if self._broadcaster and chunk:
                    self._broadcaster.send_event({
                        "type": "stream_chunk",
                        "chat_id": self.chat_id,
                        "chunk": chunk,
                        "speaker": agent.name,
                    })
        except Exception as exc:
            _sys(f"Error in parallel turn for {agent.name}: {exc}")
        print(RESET, flush=True)

        facts = _extract_facts(full_text)

        with lock:
            record = TurnRecord(
                turn=len(self.turns) + 1,
                speaker=agent.name,
                text=full_text,
                cost=agent.last_turn_cost,
                input_tokens=agent.last_input_tokens,
                output_tokens=agent.last_output_tokens,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self.turns.append(record)
            self.facts.extend(facts)
            results[agent.name] = full_text

        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "turn",
                "chat_id": self.chat_id,
                "turn_data": dataclasses.asdict(record),
                "total_tokens": self.total_tokens,
            })

    # ------------------------------------------------------------------
    # Inter-agent messaging
    # ------------------------------------------------------------------
    def _extract_messages(self, text: str, sender: str, round_num: int) -> None:
        """Parse [MSG @target: text] tags and deliver to agent mailboxes."""
        for match in re.finditer(r'\[MSG\s+@(\w+):\s*(.+?)\]', text, re.DOTALL):
            target, msg_text = match.group(1), match.group(2).strip()
            if target == "all":
                for name, mb in self._mailboxes.items():
                    if name != sender:
                        mb.deliver(sender, msg_text, round_num)
            elif target in self._mailboxes:
                self._mailboxes[target].deliver(sender, msg_text, round_num)

            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "agent_msg",
                    "chat_id": self.chat_id,
                    "from": sender,
                    "to": target,
                    "text": msg_text[:200],
                    "round": round_num,
                })

    def _handle_reports(self, text: str, agent_name: str) -> None:
        """Parse [REPORT: title]...[/REPORT] blocks and upload via exchange."""
        for match in re.finditer(r'\[REPORT:\s*(.+?)\](.+?)\[/REPORT\]', text, re.DOTALL):
            title = match.group(1).strip()
            body = match.group(2).strip()
            msg_id = ""
            if self.exchange_url:
                try:
                    payload = json.dumps({
                        "from_agent": agent_name,
                        "to_agent": "chat",
                        "type": "report",
                        "subject": title,
                        "body": body,
                        "metadata": {"chat_id": self.chat_id},
                    }).encode()
                    req = urllib.request.Request(
                        f"{self.exchange_url}/messages",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    resp = urllib.request.urlopen(req, timeout=5)
                    msg_id = json.loads(resp.read()).get("id", "")
                except Exception as exc:
                    _sys(f"Exchange upload failed: {exc}")

            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "report_published",
                    "chat_id": self.chat_id,
                    "agent": agent_name,
                    "title": title,
                    "exchange_id": msg_id,
                    "preview": body[:150] + ("..." if len(body) > 150 else ""),
                })

    def _check_sync_in_response(self, text: str, agent_name: str) -> None:
        """Detect [SYNC] tag in agent response and update sync state."""
        if "[SYNC]" in text:
            self._sync_agents.add(agent_name)
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "sync_status",
                    "chat_id": self.chat_id,
                    "agent": agent_name,
                    "synced": True,
                    "total": len(self.agents),
                    "count": len(self._sync_agents),
                })

    def _check_turn_extension(self, text: str, agent_name: str) -> None:
        """Detect [NEED_MORE_TURNS: N] tag and extend max_turns."""
        match = re.search(r'\[NEED_MORE_TURNS:\s*(\d+)\]', text)
        if match:
            requested = int(match.group(1))
            capped = min(requested, 20)
            self.max_turns += capped
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "turns_extended",
                    "chat_id": self.chat_id,
                    "by": capped,
                    "new_max": self.max_turns,
                    "requested_by": agent_name,
                })
            _sys(f"Auto-extended by {capped} turns (requested by {agent_name})")

    # ------------------------------------------------------------------
    # Parallel phase execution
    # ------------------------------------------------------------------
    def _run_parallel_phase(self) -> dict[str, str]:
        """Run iterative parallel rounds with mailbox delivery between rounds."""
        all_results: dict[str, str] = {}

        for round_num in range(self.max_parallel_rounds):
            if self._ended or self._sync_requested:
                break

            # Handle pause: spin until resumed
            while self._paused and not self._ended:
                time.sleep(0.3)
                self._drain_pending(self.topic)
            if self._ended:
                break

            # Snapshot and clear moderator injection before building prompts
            inj = self._moderator_injection
            tgt = self._moderator_target
            self._moderator_injection = None
            self._moderator_target = None

            # Build prompts, inject inbox content if available
            prompts: dict[str, str] = {}
            for agent in self.agents:
                base = self._build_prompt(len(self.turns) + 1, None, self.topic)
                inbox = self._mailboxes[agent.name].format_for_prompt()
                if inbox:
                    base = f"{inbox}\n\n{base}"
                # Apply moderator injection only to the targeted agent (or all if no target)
                if inj and (tgt is None or tgt == agent.name):
                    base = f"[MODERATOR]: {inj}\n\n{base}"
                prompts[agent.name] = base

            round_results = self._run_round(prompts)
            all_results.update(round_results)

            # Process agent outputs: messages, reports, sync flags, extensions
            for name, text in round_results.items():
                self._extract_messages(text, name, round_num)
                self._handle_reports(text, name)
                self._check_sync_in_response(text, name)
                self._check_turn_extension(text, name)

            # Continue if there are pending messages; otherwise stop
            has_new_msgs = any(mb.inbox for mb in self._mailboxes.values())
            if not has_new_msgs and not self._sync_requested:
                break

        return all_results

    def _run_discussion_phase(self, parallel_results: dict[str, str]) -> None:
        """Free-for-all discussion phase after a sync point."""
        # Accumulate context as a list of parts — avoids reassigning a str
        # variable across loop iterations, which trips the checker's type
        # inference for the binop on that variable.
        ctx_parts: list[str] = ["[SYNC SUMMARY]"]
        for name, text in parallel_results.items():
            head500: str = text[:500]
            summary: str = head500 + ("..." if len(text) > 500 else "")
            ctx_parts.append(f"  [{name}]: {summary}")
        ctx_parts.append("[/SYNC SUMMARY]")

        for round_num in range(self.max_discussion_rounds):
            if self._ended:
                break

            # Rebuild context string from parts each round — single binding
            context: str = "\n".join(ctx_parts)
            prompts: dict[str, str] = {}
            for agent in self.agents:
                prompts[agent.name] = (
                    f"{context}\n\n"
                    f"Discussion round {round_num + 1}. "
                    f"You are {agent.name}. Respond to the sync summary and other agents' points. "
                    f"Use [END_DISCUSSION] if the discussion should end. "
                    f"Use [SYNC] to proceed to the next parallel phase."
                )

            round_results = self._run_round(prompts)

            # Majority vote to end discussion
            end_votes = sum(1 for t in round_results.values() if "[END_DISCUSSION]" in t)
            if end_votes >= len(self.agents) // 2 + 1:
                _sys("Discussion ended by majority vote")
                break

            # Extend parts list with this round's responses for the next iteration
            for name, text in round_results.items():
                head300: str = text[:300]
                ctx_parts.append(f"[{name} round {round_num + 1}]: {head300}")

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------
    def _apply_moderator_cmd(self, cmd: str, arg: str, current_topic: str) -> str:
        """
        Apply a moderator command. Returns (possibly updated) topic.
        Mutates orchestrator state as needed.
        """
        if cmd == "/end":
            self._ended = True
            return current_topic

        elif cmd == "/say":
            # Parse optional @mention: /say @agentName text
            _say_target: Optional[str] = None
            _say_text: str = arg
            _m = re.match(r'^@(\S+)\s+(.*)', arg, re.DOTALL)
            if _m and _m.group(1) in [a.name for a in self.agents]:
                _say_target = _m.group(1)
                _say_text = _m.group(2).strip()
            self._moderator_target = _say_target
            self._moderator_injection = _say_text
            _print_moderator_header()
            print(f"  {C_YELLOW}{arg}{RESET}", flush=True)
            with self._cmd_lock:
                turn_num = len(self.turns) + 1
                ts = datetime.now(timezone.utc).isoformat()
                self.turns.append(TurnRecord(
                    turn=turn_num,
                    speaker="moderator",
                    text=arg,
                    cost=0.0,
                    timestamp=ts,
                ))
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "turn",
                    "chat_id": self.chat_id,
                    "turn": turn_num,
                    "speaker": "moderator",
                    "text": arg,
                    "timestamp": ts,
                })
            return current_topic

        elif cmd == "/topic":
            if arg:
                _sys(f"Topic changed to: {arg}")
                self._moderator_injection = f"[Topic changed to: {arg}]"
                return arg
            return current_topic

        elif cmd == "/task":
            if arg:
                self._moderator_injection = f"[TASK from moderator]: {arg}"
                _sys(f"Task assigned: {arg}")
            return current_topic

        elif cmd == "/focus":
            if arg:
                self._force_next = arg
                _sys(f"Next turn forced to: {arg}")
            return current_topic

        elif cmd == "/turns":
            try:
                n = int(arg.lstrip("+"))
                self.max_turns += n
                _sys(f"Extended by {n} turns → max {self.max_turns}")
                if self._broadcaster:
                    self._broadcaster.send_event({
                        "type": "turns_extended",
                        "chat_id": self.chat_id,
                        "by": n,
                        "new_max": self.max_turns,
                        "requested_by": "moderator",
                    })
            except ValueError:
                _sys(f"Invalid turns value: {arg}")
            return current_topic

        elif cmd == "/sync":
            self._sync_requested = True
            _sys("Sync point triggered by moderator")
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "sync_status",
                    "chat_id": self.chat_id,
                    "agent": "moderator",
                    "synced": True,
                    "total": len(self.agents),
                    "count": len(self._sync_agents),
                })
            return current_topic

        elif cmd == "/parallel":
            self._sync_requested = False
            self._sync_agents.clear()
            self._parallel_mode = True
            _sys("Switching to parallel mode")
            return current_topic

        elif cmd == "/add":
            # Attempt to add an agent from registry mid-chat
            if arg:
                _sys(f"Dynamic agent addition not fully implemented: {arg}")
            return current_topic

        elif cmd == "/pause":
            _sys("Conversation paused. Type /resume to continue.")
            self._paused = True
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "status",
                    "chat_id": self.chat_id,
                    "state": "paused",
                    "turn": len(self.turns),
                    "max_turns": self.max_turns,
                    "total_tokens": self.total_tokens,
                })
            return current_topic

        elif cmd == "/resume":
            self._paused = False
            _sys("Conversation resumed.")
            if self._broadcaster:
                self._broadcaster.send_event({
                    "type": "status",
                    "chat_id": self.chat_id,
                    "state": "running",
                    "turn": len(self.turns),
                    "max_turns": self.max_turns,
                    "total_tokens": self.total_tokens,
                })
            return current_topic

        elif cmd == "/budget":
            remaining = max(0.0, self.max_budget - self.total_cost)
            print(
                f"  {C_YELLOW}Budget: ${self.total_cost:.4f} spent / "
                f"${self.max_budget:.2f} total / "
                f"${remaining:.4f} remaining{RESET}",
                flush=True,
            )
            return current_topic

        elif cmd == "/help":
            _print_help()
            return current_topic

        else:
            _sys(f"Unknown command: {cmd}. Type /help for commands.")
            return current_topic

    def _handle_moderator(self, turn: int, current_topic: str) -> str:
        """
        Run the interactive moderator checkpoint (legacy sequential mode).
        Returns the (possibly updated) topic.
        """
        while True:
            cmd, arg = moderator_prompt()

            if cmd is None:
                return current_topic

            if cmd == "/pause":
                _sys("Conversation paused. Type /resume to continue.")
                self._paused = True
                while self._paused:
                    resume_cmd, _ = moderator_prompt()
                    if resume_cmd == "/resume":
                        self._paused = False
                        _sys("Conversation resumed.")
                    elif resume_cmd == "/end":
                        self._ended = True
                        self._paused = False
                return current_topic

            current_topic = self._apply_moderator_cmd(cmd, arg, current_topic)

            # Commands that need re-prompt (budget, help)
            if cmd in ("/budget", "/help"):
                continue

            return current_topic

    # ------------------------------------------------------------------
    # Async command poller (for broadcaster integration)
    # ------------------------------------------------------------------
    def _cmd_poller(self) -> None:
        """Background thread: poll broadcaster for UI commands."""
        while not self._poll_stop.is_set():
            if self._broadcaster and hasattr(self._broadcaster, "poll_commands"):
                try:
                    for ui_cmd in self._broadcaster.poll_commands(self.chat_id):
                        cmd_str = ui_cmd.get("cmd", "").strip()
                        arg_str = ui_cmd.get("arg", "").strip()
                        if cmd_str:
                            with self._cmd_lock:
                                self._pending_cmds.append((cmd_str, arg_str))
                except Exception as exc:
                    _sys(f"Command poller error: {exc}")
            time.sleep(0.2)

    def _drain_pending(self, current_topic: str) -> str:
        """Drain pending commands queued by the background poller."""
        with self._cmd_lock:
            cmds = self._pending_cmds[:]
            self._pending_cmds.clear()
        for cmd_str, arg_str in cmds:
            _sys(f"UI command: {cmd_str} {arg_str!r}")
            current_topic = self._apply_moderator_cmd(cmd_str, arg_str, current_topic)
        return current_topic

    # ------------------------------------------------------------------
    # Single-agent streaming (sequential mode)
    # ------------------------------------------------------------------
    def _stream_turn(self, agent: ChatAgent, prompt: str) -> str:
        """
        Stream one agent's response to stdout, return accumulated text.
        Also broadcasts stream events if broadcaster is attached.
        """
        turn_num = len(self.turns) + 1

        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "stream_start",
                "chat_id": self.chat_id,
                "speaker": agent.name,
                "turn": turn_num,
            })

        print(f"\n  {agent.color}", end="", flush=True)

        full_text = ""
        try:
            for chunk in invoke_agent(agent, prompt, timeout=self.timeout, orchestrator=self):
                print(chunk, end="", flush=True)
                full_text += chunk
                if self._broadcaster and chunk:
                    self._broadcaster.send_event({
                        "type": "stream_chunk",
                        "chat_id": self.chat_id,
                        "chunk": chunk,
                        "speaker": agent.name,
                    })
        except KeyboardInterrupt:
            print(f"{RESET}")
            _sys("Turn interrupted by user.")
            raise

        print(f"{RESET}", flush=True)
        return full_text

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Main chat loop — supports both sequential (legacy) and parallel modes."""
        if self._parallel_mode or len(self.agents) != 2:
            _print_header_multi(self.agents, self.topic, self.max_turns)
        else:
            _print_header(self.agents[0], self.agents[1], self.topic,
                          self.max_budget, self.max_turns)

        if not self._parallel_mode:
            if self.auto_mode:
                _sys(f"Auto mode: {self.auto_delay}s delay between turns. Ctrl+C to stop.")
            else:
                _sys("Moderator mode: you will be prompted between each turn.")

        # Notify broadcaster that chat has started
        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "chat_started",
                "chat_id": self.chat_id,
                "topic": self.topic,
                "agents": {
                    str(i): {
                        "name": a.name,
                        "color": getattr(a, "color_hex", "#569cd6"),
                    }
                    for i, a in enumerate(self.agents)
                },
                "max_turns": self.max_turns,
                "max_context": 200000,
                "permission_mode": self.agents[0].permission_mode if self.agents else "default",
                "state": "paused" if self._start_paused else "running",
            })

        # Start-paused: wait for resume signal from broadcaster
        if self._start_paused and self._broadcaster:
            _sys("Chat started in paused state — waiting for /resume command")
            self._paused = True
            while self._paused and not self._ended:
                time.sleep(0.5)
                for ui_cmd in (self._broadcaster.poll_commands(self.chat_id)
                               if hasattr(self._broadcaster, "poll_commands") else []):
                    cmd_str = ui_cmd.get("cmd", "").strip()
                    arg_str = ui_cmd.get("arg", "").strip()
                    if cmd_str == "/resume":
                        self._paused = False
                        _sys("Conversation resumed.")
                        if hasattr(self._broadcaster, "send_event"):
                            self._broadcaster.send_event({  # type: ignore[union-attr]
                                "type": "status", "chat_id": self.chat_id,
                                "state": "running", "turn": len(self.turns),
                                "max_turns": self.max_turns,
                                "total_tokens": self.total_tokens,
                            })
                    elif cmd_str == "/end":
                        self._ended = True
                        self._paused = False
                    elif cmd_str == "/turns":
                        self._apply_moderator_cmd(cmd_str, arg_str, "")
                    elif cmd_str == "/say":
                        # Record the turn + queue injection for after resume
                        self._apply_moderator_cmd(cmd_str, arg_str, "")

        if self._ended:
            self._finish()
            return

        # Start background command poller
        self._poll_stop.clear()
        poller_thread = threading.Thread(target=self._cmd_poller, daemon=True)
        poller_thread.start()

        current_topic = self.topic

        if self._parallel_mode:
            # PARALLEL MODE: cyclic phases (parallel → discussion → repeat)
            self._phase_count = 0
            while not self._ended and self._phase_count < self.max_phases:
                self._set_phase("parallel")
                self._sync_requested = False
                self._sync_agents.clear()
                results = self._run_parallel_phase()

                if self._ended:
                    break

                self._set_phase("discussion")
                self._run_discussion_phase(results)

                self._phase_count += 1
        else:
            # SEQUENTIAL MODE: legacy turn-by-turn (2-agent backward compat)
            last_response: Optional[str] = None

            for turn in range(1, self.max_turns + 1):
                if self._ended:
                    break

                # Drain async UI commands
                current_topic = self._drain_pending(current_topic)
                if self._ended:
                    break

                # Handle pause: spin until resumed
                while self._paused and not self._ended:
                    time.sleep(0.3)
                    current_topic = self._drain_pending(current_topic)
                if self._ended:
                    break

                if self.max_tokens > 0 and self.total_tokens >= self.max_tokens:
                    _sys(f"Token limit reached — stopping.")
                    break

                if self.total_cost >= self.max_budget:
                    _sys(f"Budget limit ${self.max_budget:.2f} reached — stopping.")
                    break

                agent = self._agent_for_turn(turn)
                prompt = self._build_prompt(turn, last_response, current_topic)

                _print_turn_header(turn, self.max_turns, agent,
                                   self.total_cost, self.max_budget)

                try:
                    full_text = self._stream_turn(agent, prompt)
                except KeyboardInterrupt:
                    break

                if not full_text.strip():
                    _sys(f"Empty response from {agent.name} — skipping turn.")
                    last_response = None
                    continue

                # Check for auto-extension and sync tags
                self._check_turn_extension(full_text, agent.name)

                # Extract and display facts
                fact_matches = extract_facts(full_text)
                for _attrs, body in fact_matches:
                    body_clean = body.strip()
                    _print_fact(body_clean)
                    self.facts.append(body_clean)

                # Cost line
                print(
                    f"\n  {DIM}Turn: ${agent.last_turn_cost:.4f} | "
                    f"Total: ${self.total_cost:.4f}{RESET}",
                    flush=True,
                )

                # Record this turn
                record = TurnRecord(
                    turn=turn,
                    speaker=agent.name,
                    text=full_text,
                    cost=agent.last_turn_cost,
                    input_tokens=agent.last_input_tokens,
                    output_tokens=agent.last_output_tokens,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                self.turns.append(record)

                if self._broadcaster:
                    self._broadcaster.send_event({
                        "type": "turn",
                        "chat_id": self.chat_id,
                        "turn_data": dataclasses.asdict(record),
                        "total_tokens": self.total_tokens,
                    })

                last_response = full_text

                # Moderator checkpoint or auto-delay
                if not self.auto_mode:
                    try:
                        current_topic = self._handle_moderator(turn, current_topic)
                    except KeyboardInterrupt:
                        break
                    if self._ended:
                        break
                else:
                    if self.auto_delay > 0:
                        time.sleep(self.auto_delay)

        # Stop the command poller
        self._poll_stop.set()

        self._finish()

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------
    def _finish(self) -> None:
        """Print summary and save log."""
        print()
        _sep("═")
        print(f"{BOLD}  Conversation ended.{RESET}")
        agent_turns = [t for t in self.turns if t.speaker != "moderator"]
        print(f"  Turns completed: {len(agent_turns)}")
        print(f"  Facts extracted: {len(self.facts)}")
        total_tok = self.total_tokens
        if total_tok:
            print(f"  Total tokens:    {total_tok:,}")
        print(f"  Total cost:      ${self.total_cost:.4f}")
        _sep("═")

        log_path = (
            Path(__file__).parent / "logs" /
            f"stream_{self.chat_id}.json"
        )
        save_log(
            log_path=log_path,
            chat_id=self.chat_id,
            topic=self.topic,
            agents=self.agents,
            project_name=self.project_name,
            turns=self.turns,
            facts=self.facts,
            started_at=self.started_at,
        )
        _sys(f"Log saved: {log_path}")

        if self._broadcaster:
            self._broadcaster.send_event({
                "type": "chat_ended",
                "chat_id": self.chat_id,
                "total_turns": len(agent_turns),
                "total_cost": self.total_cost,
                "total_tokens": total_tok,
                "log_path": str(log_path),
            })


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streaming agent-to-agent chat with moderator support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Config file (N-agent mode)
    parser.add_argument(
        "--config", default=None, metavar="PATH",
        help="Path to JSON config file. When provided, loads all settings from JSON.",
    )

    # Resume from previous log
    parser.add_argument(
        "--resume-from", default=None, metavar="LOG_PATH",
        help="Path to a previous chat log JSON to restore turns and session IDs.",
    )

    # Topic
    parser.add_argument(
        "topic_positional", nargs="?", metavar="TOPIC",
        help="Conversation topic (positional shorthand)",
    )
    parser.add_argument("--topic", default=None, help="Conversation topic")

    # Agent A
    parser.add_argument(
        "--agent-a", default="falkvelt",
        help="Name of agent A (default: falkvelt)",
    )
    parser.add_argument(
        "--ws-a", default=None,
        help="Home workspace for agent A",
    )

    # Agent B
    parser.add_argument(
        "--agent-b", default="okiara",
        help="Name of agent B (default: okiara)",
    )
    parser.add_argument(
        "--ws-b", default=None,
        help="Home workspace for agent B",
    )

    # Project
    parser.add_argument(
        "--project", default=None,
        help="Path to the external project directory (cwd for both agents)",
    )
    parser.add_argument(
        "--project-name", default="",
        help="Short project name for memory tagging and capsule",
    )

    # Roles
    parser.add_argument("--role-a", default="", help="Role description for agent A")
    parser.add_argument("--role-b", default="", help="Role description for agent B")

    # Session parameters
    parser.add_argument(
        "--max-turns", type=int, default=20,
        help="Maximum number of turns (default: 20)",
    )
    parser.add_argument(
        "--max-budget", type=float, default=5.0,
        help="Maximum total spend in USD (default: 5.0)",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=0,
        help="Max total tokens (0 = unlimited)",
    )
    parser.add_argument(
        "--timeout", type=int, default=180,
        help="Per-turn timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--ws-port", type=int, default=8877,
        help="Websocket port for broadcaster (default: 8877)",
    )
    parser.add_argument(
        "--chat-id", default=None,
        help="Override auto-generated chat ID",
    )
    parser.add_argument(
        "--start-paused", action="store_true",
        help="Start chat in paused state, waiting for /resume",
    )

    # Auto mode
    parser.add_argument(
        "--auto", action="store_true",
        help="Auto mode: no moderator pause between turns",
    )
    parser.add_argument(
        "--auto-delay", type=float, default=2.0,
        help="Seconds to wait between turns in auto mode (default: 2.0)",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = _parse_args()

    # Generate chat id (may be overridden by config or --chat-id)
    default_chat_id = (
        args.chat_id
        or f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    )

    if args.config:
        # ----------------------------------------------------------------
        # CONFIG-FILE MODE: N-agent, all params from JSON
        # ----------------------------------------------------------------
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"ERROR: config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)

        config = json.loads(config_path.read_text(encoding="utf-8"))

        topic = config.get("topic", "")
        if not topic:
            print("ERROR: 'topic' is required in config JSON.", file=sys.stderr)
            sys.exit(1)

        project_cwd = config.get("project_cwd", "")
        project_name = config.get("project_name", "")
        max_turns = config.get("max_turns", 20)
        max_budget = config.get("max_budget", 5.0)
        max_tokens = config.get("max_tokens", 0)
        ws_port = config.get("ws_port", 8877)
        start_paused = config.get("start_paused", False)
        chat_id = config.get("chat_id", default_chat_id)
        resume_from = config.get("resume_from", None)

        agents: list[ChatAgent] = []
        for i, ac in enumerate(config.get("agents", [])):
            color_idx = i % len(ANSI_COLORS)
            agent_workspace = ac.get("workspace", project_cwd)
            agent_cwd = project_cwd or agent_workspace

            a = ChatAgent(
                name=ac["name"],
                workspace=agent_workspace,
                project_cwd=agent_cwd,
                role=ac.get("role", ""),
                budget=ac.get("budget", 5.0),
                cli_budget=ac.get("budget", 5.0),
                permission_mode=ac.get("permission_mode", "bypassPermissions"),
                color=ANSI_COLORS[color_idx],
                color_hex=AGENT_COLORS_HEX[i % len(AGENT_COLORS_HEX)],
            )
            agents.append(a)

        if not agents:
            print("ERROR: 'agents' list in config is empty.", file=sys.stderr)
            sys.exit(1)

        # Validate project_cwd
        if project_cwd and not Path(project_cwd).is_dir():
            print(f"ERROR: project_cwd path not found: {project_cwd}", file=sys.stderr)
            sys.exit(1)

        # Resolve project_name from path if not set
        if not project_name and project_cwd:
            project_name = Path(project_cwd).name
        elif not project_name and agents:
            project_name = Path(agents[0].workspace).name

        # Load identity capsules
        _sys("Loading identity capsules...")
        for a in agents:
            load_capsule(a, project_name)

        # Set up UI broadcaster
        broadcaster: Optional[HttpBroadcaster] = None
        if ws_port:
            broadcaster = HttpBroadcaster(ws_port)

        # Config-spawned chats use auto_mode by default (moderation via UI, not stdin)
        auto_mode = config.get("auto_mode", True)
        auto_delay = config.get("auto_delay", args.auto_delay)

        # Build orchestrator
        orchestrator = StreamChatOrchestrator(
            agents=agents,
            topic=topic,
            project_name=project_name,
            max_turns=max_turns,
            max_budget=max_budget,
            auto_mode=auto_mode,
            auto_delay=auto_delay,
            timeout=args.timeout,
            chat_id=chat_id,
            broadcaster=broadcaster,
            max_tokens=max_tokens,
            ws_port=ws_port,
            start_paused=start_paused,
        )

        # Restore state from previous log if --resume-from provided
        resume_path = args.resume_from or resume_from
        if resume_path:
            resume_path = Path(resume_path)
            if resume_path.exists():
                _sys(f"Restoring from: {resume_path}")
                log_data = json.loads(resume_path.read_text(encoding="utf-8"))
                for turn_data in log_data.get("turns", []):
                    # Provide defaults for fields that may not exist in old logs
                    turn_data.setdefault("cost", 0.0)
                    turn_data.setdefault("timestamp", "")
                    turn_data.setdefault("input_tokens", 0)
                    turn_data.setdefault("output_tokens", 0)
                    orchestrator.turns.append(TurnRecord(**turn_data))
                for i, agent in enumerate(orchestrator.agents):
                    agent_log = log_data.get("agents", {}).get(str(i), {})
                    agent.session_id = agent_log.get("session_id", "")
                orchestrator.started_at = log_data.get("started_at", orchestrator.started_at)
                orchestrator.facts = log_data.get("facts", [])
                _sys(f"Restored {len(orchestrator.turns)} turns, {len(orchestrator.facts)} facts")
            else:
                _sys(f"Warning: resume-from path not found: {resume_path}")

    else:
        # ----------------------------------------------------------------
        # LEGACY 2-AGENT CLI MODE
        # ----------------------------------------------------------------
        topic = args.topic or args.topic_positional
        if not topic:
            print("ERROR: A topic is required. Pass it as positional arg or --topic.",
                  file=sys.stderr)
            sys.exit(1)

        ws_a = args.ws_a or "/Users/eliahkadu/Desktop/_follower_"
        ws_b = args.ws_b or "/Users/eliahkadu/Desktop/_primal_"

        project_path = args.project or ws_a
        project_name = args.project_name or Path(project_path).name

        for label, path in [("ws-a", ws_a), ("ws-b", ws_b), ("project", project_path)]:
            if not Path(path).is_dir():
                print(f"ERROR: {label} path not found: {path}", file=sys.stderr)
                sys.exit(1)

        per_agent_budget = round(args.max_budget / 2, 4)
        chat_id = default_chat_id

        agent_a = ChatAgent(
            name=args.agent_a,
            workspace=ws_a,
            project_cwd=project_path,
            role=args.role_a,
            budget=per_agent_budget,
            cli_budget=per_agent_budget,
            color=C_CYAN,
            color_hex=AGENT_COLORS_HEX[0],
        )
        agent_b = ChatAgent(
            name=args.agent_b,
            workspace=ws_b,
            project_cwd=project_path,
            role=args.role_b,
            budget=per_agent_budget,
            cli_budget=per_agent_budget,
            color=C_MAGENTA,
            color_hex=AGENT_COLORS_HEX[1],
        )

        _sys("Loading identity capsules...")
        load_capsule(agent_a, project_name)
        load_capsule(agent_b, project_name)

        # Set up UI broadcaster
        broadcaster: Optional[HttpBroadcaster] = None
        if args.ws_port:
            broadcaster = HttpBroadcaster(args.ws_port)

        orchestrator = StreamChatOrchestrator(
            agents=[agent_a, agent_b],
            topic=topic,
            project_name=project_name,
            max_turns=args.max_turns,
            max_budget=args.max_budget,
            auto_mode=args.auto,
            auto_delay=args.auto_delay,
            timeout=args.timeout,
            chat_id=chat_id,
            broadcaster=broadcaster,
            max_tokens=args.max_tokens,
            ws_port=args.ws_port,
            start_paused=args.start_paused,
        )

        # Resume from log if specified
        if args.resume_from:
            resume_path = Path(args.resume_from)
            if resume_path.exists():
                _sys(f"Restoring from: {resume_path}")
                log_data = json.loads(resume_path.read_text(encoding="utf-8"))
                for turn_data in log_data.get("turns", []):
                    turn_data.setdefault("cost", 0.0)
                    turn_data.setdefault("timestamp", "")
                    turn_data.setdefault("input_tokens", 0)
                    turn_data.setdefault("output_tokens", 0)
                    orchestrator.turns.append(TurnRecord(**turn_data))
                for i, agent in enumerate(orchestrator.agents):
                    agent_log = log_data.get("agents", {}).get(str(i), {})
                    agent.session_id = agent_log.get("session_id", "")
                orchestrator.started_at = log_data.get("started_at", orchestrator.started_at)
                orchestrator.facts = log_data.get("facts", [])
            else:
                _sys(f"Warning: resume-from path not found: {args.resume_from}")

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print()
        _sys("Interrupted by user (Ctrl+C).")
        orchestrator._finish()
        sys.exit(0)


if __name__ == "__main__":
    main()
