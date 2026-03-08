#!/usr/bin/env python3
"""
infra/chat/stream_chat.py — Streaming chat orchestrator with moderator support.

Two Claude Code agents converse while a human moderator watches in real-time
and can intervene between turns. Agent responses stream character-by-character.
Facts are auto-extracted and logged. Chat log is saved to infra/chat/logs/.

Usage:
    python3 infra/chat/stream_chat.py \\
        --agent-a falkvelt --ws-a /Users/eliahkadu/Desktop/_follower_ \\
        --agent-b testclone --ws-b /Users/eliahkadu/Desktop/_test_clone_ \\
        --project /Users/eliahkadu/Desktop/_shared_/project/sibyl \\
        --project-name sibyl \\
        --topic "Architecture review" \\
        --max-turns 20 \\
        --max-budget 5.0

    # Auto mode (no moderator pause between turns):
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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterator, Optional
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

# Per-agent colors (extensible via AGENT_COLORS fallback below)
C_CYAN    = "\033[36m"   # agent A
C_MAGENTA = "\033[35m"   # agent B
C_YELLOW  = "\033[33m"   # moderator
C_GREEN   = "\033[32m"   # facts
C_RED     = "\033[31m"   # errors
C_GRAY    = "\033[90m"   # system

AGENT_COLORS = {
    "a": C_CYAN,
    "b": C_MAGENTA,
}

# ---------------------------------------------------------------------------
# Fact extraction — reuse pattern from chat.py
# ---------------------------------------------------------------------------
FACT_RE = re.compile(r'\[FACT(?:\s+([^\]]*))?\](.*?)\[/FACT\]', re.DOTALL)


def extract_facts(text: str) -> list[tuple[str, str]]:
    """Return list of (attrs_str, body) tuples for each [FACT] block found."""
    return FACT_RE.findall(text)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ChatAgent:
    name: str
    workspace: str          # agent's home workspace (for identity capsule)
    project_cwd: str        # external project dir (cwd for claude -p)
    role: str = ""          # optional role description
    capsule: str = ""       # identity capsule text (populated at startup)
    session_id: str = ""
    total_cost: float = 0.0
    last_turn_cost: float = 0.0
    budget: float = 5.0
    color: str = C_CYAN


@dataclasses.dataclass
class TurnRecord:
    turn: int
    speaker: str            # agent name, or "moderator"
    text: str
    cost: float
    timestamp: str


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


def _print_turn_header(turn: int, max_turns: int, agent: ChatAgent,
                       total_cost: float, max_budget: float) -> None:
    bar = f"Turn {turn}/{max_turns}"
    budget_str = f"${total_cost:.3f}/${max_budget:.2f}"
    print(f"\n{_sep.__module__ and ''}"
          f"{DIM}{'─'*60}{RESET}")
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
    # Standard streaming assistant message
    if chunk.get("type") == "assistant":
        msg = chunk.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            return "".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )

    # Direct text chunk
    if chunk.get("type") == "text":
        return chunk.get("text", "")

    # Content block delta (Anthropic streaming format)
    if chunk.get("type") == "content_block_delta":
        delta = chunk.get("delta", {})
        if delta.get("type") == "text_delta":
            return delta.get("text", "")

    # Non-streaming json output fallback
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

    # Top-level cost_usd (stream-json result event)
    if "cost_usd" in chunk:
        try:
            cost = float(chunk["cost_usd"])
        except (TypeError, ValueError):
            pass

    # Nested usage in result event: {"usage": {"total_cost": ...}}
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
) -> Iterator[str]:
    """
    Invoke `claude -p --output-format stream-json` and yield text chunks.

    Falls back to `--output-format json` with a typewriter effect if
    stream-json produces no text chunks after 5 non-empty lines.

    The generator also updates agent.session_id and agent.last_turn_cost
    as side effects (they are populated from result chunks before the
    generator is exhausted).
    """
    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--permission-mode", "bypassPermissions",
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

    # Write prompt and close stdin so claude knows input is done
    proc.stdin.write(prompt)
    proc.stdin.close()

    accumulated_text = ""
    non_empty_lines = 0
    got_text_chunk = False
    session_id_seen: Optional[str] = None
    cost_seen: float = 0.0

    try:
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip("\n")
            if not raw_line:
                continue

            non_empty_lines += 1

            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                # Non-JSON line — could be a debug message, skip silently
                continue

            # Extract metadata from every chunk
            sid, cost = _extract_metadata_from_chunk(chunk)
            if sid:
                session_id_seen = sid
            if cost > 0:
                cost_seen = cost

            # Extract and yield text
            text = _extract_text_from_chunk(chunk)
            if text:
                got_text_chunk = True
                accumulated_text += text
                yield text

            # After 10 non-empty non-text lines, assume stream-json isn't
            # delivering incremental text — switch to typewriter fallback below
            if non_empty_lines >= 10 and not got_text_chunk:
                break

    except Exception as exc:
        _sys(f"Stream read error: {exc}")

    # Drain remaining stdout to unblock the process
    remaining = proc.stdout.read()

    # Try to parse remaining output for metadata / full result
    if not got_text_chunk and remaining.strip():
        for raw_line in remaining.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                chunk = json.loads(raw_line)
                sid, cost = _extract_metadata_from_chunk(chunk)
                if sid:
                    session_id_seen = sid
                if cost > 0:
                    cost_seen = cost
                text = _extract_text_from_chunk(chunk)
                if text:
                    got_text_chunk = True
                    accumulated_text += text
            except json.JSONDecodeError:
                continue

    proc.wait(timeout=5)

    # Typewriter fallback: if stream-json gave no text, try json output format
    if not got_text_chunk:
        _sys("stream-json produced no text — falling back to json output with typewriter effect")
        fallback_text, fallback_sid, fallback_cost = _invoke_agent_fallback(agent, prompt, timeout)
        if fallback_text:
            session_id_seen = fallback_sid or session_id_seen
            cost_seen = fallback_cost or cost_seen
            for char in fallback_text:
                yield char
                time.sleep(0.005)  # typewriter delay: ~200 chars/sec

    # Update agent metadata after streaming completes
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
        "--permission-mode", "bypassPermissions",
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
        # Raw text fallback
        raw = proc.stdout.strip()
        return raw if raw else None, None, 0.0


# ---------------------------------------------------------------------------
# Moderator input
# ---------------------------------------------------------------------------
def moderator_prompt() -> tuple[Optional[str], str]:
    """
    Prompt the moderator for input between turns.

    Returns (command, arg):
      - (None, "")      -> continue normally (empty Enter)
      - ("/end", "")    -> end the chat
      - ("/say", text)  -> inject message
      - ("/topic", text)
      - ("/task", text)
      - ("/focus", name)
      - ("/pause", "")
      - ("/resume", "")
      - ("/budget", "")
      - ("/help", "")
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

    # Plain text => inject as /say
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

    # Minimal fallback capsule
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
             agent_a: ChatAgent, agent_b: ChatAgent,
             project_name: str, turns: list[TurnRecord],
             facts: list[str], started_at: str) -> None:
    """Write the full chat log as JSON."""
    total_cost = agent_a.total_cost + agent_b.total_cost
    data = {
        "chat_id": chat_id,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "project": project_name,
        "agents": {
            "a": {"name": agent_a.name, "workspace": agent_a.workspace},
            "b": {"name": agent_b.name, "workspace": agent_b.workspace},
        },
        "turns": [dataclasses.asdict(t) for t in turns],
        "facts": facts,
        "total_cost": round(total_cost, 6),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Chat orchestrator
# ---------------------------------------------------------------------------
class StreamChatOrchestrator:
    """
    Main orchestrator: manages turn-taking, streaming output,
    moderator checkpoints, fact extraction, and log persistence.
    """

    def __init__(
        self,
        agent_a: ChatAgent,
        agent_b: ChatAgent,
        topic: str,
        project_name: str,
        max_turns: int,
        max_budget: float,
        auto_mode: bool,
        auto_delay: float,
        timeout: int,
        chat_id: str,
    ) -> None:
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.topic = topic
        self.project_name = project_name
        self.max_turns = max_turns
        self.max_budget = max_budget
        self.auto_mode = auto_mode
        self.auto_delay = auto_delay
        self.timeout = timeout
        self.chat_id = chat_id

        self.turns: list[TurnRecord] = []
        self.facts: list[str] = []
        self.started_at = datetime.now(timezone.utc).isoformat()

        # State for moderator control
        self._moderator_injection: Optional[str] = None  # text to prepend next turn
        self._force_next: Optional[str] = None           # force next turn to this agent name
        self._paused: bool = False
        self._ended: bool = False

    @property
    def total_cost(self) -> float:
        return self.agent_a.total_cost + self.agent_b.total_cost

    def _agent_for_turn(self, turn: int) -> ChatAgent:
        """Determine which agent speaks on this turn (or use forced agent)."""
        if self._force_next:
            name = self._force_next
            self._force_next = None
            if name.lower() == self.agent_a.name.lower():
                return self.agent_a
            if name.lower() == self.agent_b.name.lower():
                return self.agent_b
            _sys(f"Unknown agent name '{name}', using default turn order")
        return self.agent_a if (turn % 2 == 1) else self.agent_b

    def _build_prompt(self, turn: int, last_response: Optional[str],
                      current_topic: str) -> str:
        """
        Compose the prompt for the current agent.
        Turn 1: open with topic. Subsequent turns: respond to last response.
        Moderator injection is appended if present.
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

    def _handle_moderator(self, current_topic: str) -> str:
        """
        Run the moderator checkpoint. Returns the (possibly updated) topic.
        Mutates self._moderator_injection, self._force_next, self._ended, self._paused.
        """
        while True:  # loop for /pause
            cmd, arg = moderator_prompt()

            if cmd is None:
                # Plain Enter — continue
                return current_topic

            if cmd == "/end":
                self._ended = True
                return current_topic

            elif cmd == "/say":
                self._moderator_injection = arg
                _print_moderator_header()
                print(f"  {C_YELLOW}{arg}{RESET}", flush=True)
                self.turns.append(TurnRecord(
                    turn=len(self.turns) + 1,
                    speaker="moderator",
                    text=arg,
                    cost=0.0,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
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

            elif cmd == "/pause":
                _sys("Conversation paused. Type /resume to continue.")
                self._paused = True
                # Stay in loop until /resume
                while self._paused:
                    resume_cmd, _ = moderator_prompt()
                    if resume_cmd == "/resume":
                        self._paused = False
                        _sys("Conversation resumed.")
                    elif resume_cmd == "/end":
                        self._ended = True
                        self._paused = False
                return current_topic

            elif cmd == "/resume":
                # Already running — no-op
                return current_topic

            elif cmd == "/budget":
                remaining = max(0.0, self.max_budget - self.total_cost)
                print(
                    f"  {C_YELLOW}Budget: ${self.total_cost:.4f} spent / "
                    f"${self.max_budget:.2f} total / "
                    f"${remaining:.4f} remaining{RESET}",
                    flush=True,
                )
                # Show prompt again after budget info
                continue

            elif cmd == "/help":
                _print_help()
                continue  # Show prompt again

            else:
                _sys(f"Unknown command: {cmd}. Type /help for commands.")
                continue

    def _stream_turn(self, agent: ChatAgent, prompt: str) -> str:
        """
        Stream one agent's response to stdout, return the full accumulated text.
        Also handles fact extraction and display inline.
        """
        print(f"\n  {agent.color}", end="", flush=True)

        full_text = ""
        try:
            for chunk in invoke_agent(agent, prompt, timeout=self.timeout):
                print(chunk, end="", flush=True)
                full_text += chunk
        except KeyboardInterrupt:
            # User hit Ctrl+C during streaming — stop this turn gracefully
            print(f"{RESET}")
            _sys("Turn interrupted by user.")
            raise

        print(f"{RESET}", flush=True)
        return full_text

    def run(self) -> None:
        """Main chat loop."""
        _print_header(self.agent_a, self.agent_b, self.topic,
                      self.max_budget, self.max_turns)

        if self.auto_mode:
            _sys(f"Auto mode: {self.auto_delay}s delay between turns. Ctrl+C to stop.")
        else:
            _sys("Moderator mode: you will be prompted between each turn.")

        current_topic = self.topic
        last_response: Optional[str] = None

        for turn in range(1, self.max_turns + 1):
            if self._ended:
                break

            if self.total_cost >= self.max_budget:
                _sys(f"Budget limit ${self.max_budget:.2f} reached — stopping.")
                break

            agent = self._agent_for_turn(turn)
            prompt = self._build_prompt(turn, last_response, current_topic)

            # Print turn header
            _print_turn_header(turn, self.max_turns, agent,
                               self.total_cost, self.max_budget)

            # Stream the response
            try:
                full_text = self._stream_turn(agent, prompt)
            except KeyboardInterrupt:
                break

            if not full_text.strip():
                _sys(f"Empty response from {agent.name} — skipping turn.")
                last_response = None
                continue

            # Extract and display facts inline
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
            self.turns.append(TurnRecord(
                turn=turn,
                speaker=agent.name,
                text=full_text,
                cost=agent.last_turn_cost,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

            last_response = full_text

            # Moderator checkpoint or auto-delay
            if not self.auto_mode:
                try:
                    current_topic = self._handle_moderator(current_topic)
                except KeyboardInterrupt:
                    break
                if self._ended:
                    break
            else:
                if self.auto_delay > 0:
                    time.sleep(self.auto_delay)

        self._finish()

    def _finish(self) -> None:
        """Print summary and save log."""
        print()
        _sep("═")
        print(f"{BOLD}  Conversation ended.{RESET}")
        print(f"  Turns completed: {len([t for t in self.turns if t.speaker != 'moderator'])}")
        print(f"  Facts extracted: {len(self.facts)}")
        print(f"  Total cost:      ${self.total_cost:.4f}")
        _sep("═")

        # Save log
        log_path = (
            Path(__file__).parent / "logs" /
            f"stream_{self.chat_id}.json"
        )
        save_log(
            log_path=log_path,
            chat_id=self.chat_id,
            topic=self.topic,
            agent_a=self.agent_a,
            agent_b=self.agent_b,
            project_name=self.project_name,
            turns=self.turns,
            facts=self.facts,
            started_at=self.started_at,
        )
        _sys(f"Log saved: {log_path}")


# ---------------------------------------------------------------------------
# CLI argument parsing and entry point
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streaming agent-to-agent chat with moderator support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
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
        help="Home workspace for agent A (default: /Users/eliahkadu/Desktop/_follower_)",
    )

    # Agent B
    parser.add_argument(
        "--agent-b", default="okiara",
        help="Name of agent B (default: okiara)",
    )
    parser.add_argument(
        "--ws-b", default=None,
        help="Home workspace for agent B (default: /Users/eliahkadu/Desktop/_primal_)",
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
        "--timeout", type=int, default=180,
        help="Per-turn timeout in seconds (default: 180)",
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


def main() -> None:
    args = _parse_args()

    # Resolve topic
    topic = args.topic or args.topic_positional
    if not topic:
        print("ERROR: A topic is required. Pass it as positional arg or --topic.", file=sys.stderr)
        sys.exit(1)

    # Resolve workspaces
    ws_a = args.ws_a or "/Users/eliahkadu/Desktop/_follower_"
    ws_b = args.ws_b or "/Users/eliahkadu/Desktop/_primal_"

    # Resolve project directory (where claude runs)
    # If --project not provided, fall back to agent A's workspace
    project_path = args.project or ws_a
    project_name = args.project_name or Path(project_path).name

    # Validate paths
    for label, path in [("ws-a", ws_a), ("ws-b", ws_b), ("project", project_path)]:
        if not Path(path).is_dir():
            print(f"ERROR: {label} path not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Per-agent budget: each agent gets half of the total
    per_agent_budget = round(args.max_budget / 2, 4)

    # Generate chat id
    chat_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"

    # Build agent objects
    agent_a = ChatAgent(
        name=args.agent_a,
        workspace=ws_a,
        project_cwd=project_path,
        role=args.role_a,
        budget=per_agent_budget,
        color=C_CYAN,
    )
    agent_b = ChatAgent(
        name=args.agent_b,
        workspace=ws_b,
        project_cwd=project_path,
        role=args.role_b,
        budget=per_agent_budget,
        color=C_MAGENTA,
    )

    # Load identity capsules
    _sys(f"Loading identity capsules...")
    load_capsule(agent_a, project_name)
    load_capsule(agent_b, project_name)

    # Build and run orchestrator
    orchestrator = StreamChatOrchestrator(
        agent_a=agent_a,
        agent_b=agent_b,
        topic=topic,
        project_name=project_name,
        max_turns=args.max_turns,
        max_budget=args.max_budget,
        auto_mode=args.auto,
        auto_delay=args.auto_delay,
        timeout=args.timeout,
        chat_id=chat_id,
    )

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print()
        _sys("Interrupted by user (Ctrl+C).")
        orchestrator._finish()
        sys.exit(0)


if __name__ == "__main__":
    main()
