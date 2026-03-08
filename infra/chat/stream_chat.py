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
        --max-tokens 200000

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


def _route_fact_to_exchange(
    body: str,
    from_agent: str,
    to_agent: str,
    turn: int,
    chat_id: str,
    exchange_url: str,
    attrs_str: str = "",
) -> bool:
    """POST a fact to the exchange server as type 'knowledge'. Returns True on success."""
    import urllib.request

    subject_m = re.search(r'subject="([^"]*)"', attrs_str)
    subject = subject_m.group(1) if subject_m else "chat_fact"

    msg = {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "type": "knowledge",
        "subject": subject,
        "body": json.dumps({
            "fact": body.strip(),
            "chat_turn": turn,
            "chat_id": chat_id,
        }),
    }
    req = urllib.request.Request(
        f"{exchange_url}/messages",
        data=json.dumps(msg).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as exc:
        _sys(f"Exchange POST failed: {exc}")
        return False


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
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    cli_budget: float = 5.0     # passed to claude -p --max-budget-usd (safety limit)
    color: str = C_CYAN


@dataclasses.dataclass
class TurnRecord:
    turn: int
    speaker: str            # agent name, or "moderator"
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = ""


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


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234 -> '1.2K', 12345 -> '12.3K', 123 -> '123'."""
    if n >= 1000:
        return f"{n/1000:.1f}K"
    return str(n)


def _print_header(agent_a: ChatAgent, agent_b: ChatAgent, topic: str,
                  max_turns: int) -> None:
    print()
    _sep("═")
    print(f"{BOLD}  Stream Chat: "
          f"{agent_a.color}{agent_a.name}{RESET} "
          f"{BOLD}<->{RESET} "
          f"{agent_b.color}{agent_b.name}{RESET}")
    print(f"  Topic: {topic}")
    print(f"  Max turns: {max_turns}")
    _sep("═")
    print()


def _print_turn_header(turn: int, max_turns: int, agent: ChatAgent,
                       total_tokens: int, max_tokens: int) -> None:
    bar = f"Turn {turn}/{max_turns}"
    tok_str = f"{_fmt_tokens(total_tokens)}"
    if max_tokens > 0:
        tok_str += f"/{_fmt_tokens(max_tokens)}"
    print(f"\n{DIM}{'─'*60}{RESET}")
    print(f"  {agent.color}{BOLD}{agent.name}{RESET}  "
          f"{DIM}{bar} | {tok_str} tokens{RESET}")
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
def _extract_text_from_chunk(chunk: dict, _streamed: list | None = None) -> str:
    """
    Extract displayable text from a stream-json chunk.

    Priority: content_block_delta (incremental streaming). The "assistant"
    and "result" events carry the FULL text and are only used as fallback
    when no deltas were received (to avoid duplication).
    """
    raw = chunk  # keep original for top-level checks

    # Unwrap stream_event envelope from Claude CLI stream-json
    if chunk.get("type") == "stream_event":
        chunk = chunk.get("event", {})

    # Content block delta — incremental streaming text (primary path)
    if chunk.get("type") == "content_block_delta":
        delta = chunk.get("delta", {})
        if delta.get("type") == "text_delta":
            return delta.get("text", "")

    # Skip "assistant" and "result" events — they contain the FULL text
    # which would duplicate what we already got from content_block_delta.
    # These are handled only in the fallback path (_invoke_agent_fallback).

    return ""


def _extract_metadata_from_chunk(raw_chunk: dict) -> tuple[Optional[str], int, int]:
    """
    Extract (session_id, input_tokens, output_tokens) from stream-json chunks.
    Returns (None, 0, 0) if not present.
    """
    session_id: Optional[str] = raw_chunk.get("session_id") or None
    input_tokens = 0
    output_tokens = 0

    # Unwrap to get event
    event = raw_chunk
    if raw_chunk.get("type") == "stream_event":
        event = raw_chunk.get("event", {})

    # message_start has input token count
    if event.get("type") == "message_start":
        msg_usage = event.get("message", {}).get("usage", {})
        input_tokens = msg_usage.get("input_tokens", 0)

    # message_delta has output token count
    if event.get("type") == "message_delta":
        usage = event.get("usage", {})
        output_tokens = usage.get("output_tokens", 0)

    # json format fallback — has usage block with both
    if "usage" in raw_chunk and isinstance(raw_chunk["usage"], dict):
        input_tokens = raw_chunk["usage"].get("input_tokens", 0) or input_tokens
        output_tokens = raw_chunk["usage"].get("output_tokens", 0) or output_tokens

    return session_id, input_tokens, output_tokens


def invoke_agent(
    agent: ChatAgent,
    prompt: str,
    timeout: int = 180,
) -> Iterator[str]:
    """
    Invoke `claude -p --output-format stream-json --include-partial-messages`
    and yield text chunks as they arrive.

    Falls back to `--output-format json` with a typewriter effect if
    stream-json produces no text at all (e.g. CLI version mismatch).

    Updates agent.session_id and token counters as side effects.
    """
    import threading

    cmd = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--permission-mode", "bypassPermissions",
        "--max-budget-usd", str(agent.cli_budget),
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
    session_id_seen: Optional[str] = None
    input_tokens_total = 0
    output_tokens_total = 0

    # Timeout watchdog — kill process if it exceeds the limit
    timed_out = False

    def _timeout_kill():
        nonlocal timed_out
        timed_out = True
        if proc.poll() is None:
            proc.kill()

    timer = threading.Timer(timeout, _timeout_kill)
    timer.start()

    try:
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip("\n")
            if not raw_line:
                continue

            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            # Extract metadata (session_id + tokens) from every chunk
            sid, in_tok, out_tok = _extract_metadata_from_chunk(chunk)
            if sid:
                session_id_seen = sid
            input_tokens_total += in_tok
            output_tokens_total += out_tok

            # Extract and yield text
            text = _extract_text_from_chunk(chunk)
            if text:
                accumulated_text += text
                yield text

    except Exception as exc:
        _sys(f"Stream read error: {exc}")

    finally:
        timer.cancel()
        # Always clean up the subprocess
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    if timed_out:
        _sys(f"Turn timed out after {timeout}s")

    # Typewriter fallback: if stream-json gave no text, try json output format
    if not accumulated_text:
        _sys("stream-json produced no text — falling back to json output with typewriter effect")
        fallback_text, fallback_sid, fb_in, fb_out = _invoke_agent_fallback(agent, prompt, timeout)
        if fallback_text:
            session_id_seen = fallback_sid or session_id_seen
            input_tokens_total += fb_in
            output_tokens_total += fb_out
            for char in fallback_text:
                yield char
                time.sleep(0.005)  # typewriter delay: ~200 chars/sec

    # Update agent metadata after streaming completes
    if session_id_seen:
        agent.session_id = session_id_seen
    agent.last_input_tokens = input_tokens_total
    agent.last_output_tokens = output_tokens_total
    agent.total_input_tokens += input_tokens_total
    agent.total_output_tokens += output_tokens_total


def _invoke_agent_fallback(
    agent: ChatAgent,
    prompt: str,
    timeout: int,
) -> tuple[Optional[str], Optional[str], int, int]:
    """
    Fallback invocation using --output-format json (non-streaming).
    Returns (text, session_id, input_tokens, output_tokens).
    """
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--max-budget-usd", str(agent.cli_budget),
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
        return None, None, 0, 0
    except Exception as exc:
        _sys(f"Fallback invocation error: {exc}")
        return None, None, 0, 0

    if not proc.stdout.strip():
        _sys(f"Fallback: empty stdout (exit {proc.returncode})")
        if proc.stderr:
            _sys(f"Fallback stderr: {proc.stderr[:300]}")
        return None, None, 0, 0

    try:
        data = json.loads(proc.stdout.strip())
        text = (data.get("result") or data.get("content") or "").strip()
        sid = data.get("session_id")
        usage = data.get("usage", {})
        in_tok = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        out_tok = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
        return text or None, sid, in_tok, out_tok
    except (json.JSONDecodeError, ValueError):
        raw = proc.stdout.strip()
        return raw if raw else None, None, 0, 0


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
        "total_input_tokens": agent_a.total_input_tokens + agent_b.total_input_tokens,
        "total_output_tokens": agent_a.total_output_tokens + agent_b.total_output_tokens,
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
        max_tokens: int,
        auto_mode: bool,
        auto_delay: float,
        timeout: int,
        chat_id: str,
        exchange_url: str = "",
    ) -> None:
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.topic = topic
        self.project_name = project_name
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.auto_mode = auto_mode
        self.auto_delay = auto_delay
        self.timeout = timeout
        self.chat_id = chat_id
        self.exchange_url = exchange_url

        self.turns: list[TurnRecord] = []
        self.facts: list[str] = []
        self.started_at = datetime.now(timezone.utc).isoformat()

        # State for moderator control
        self._moderator_injection: Optional[str] = None  # text to prepend next turn
        self._force_next: Optional[str] = None           # force next turn to this agent name
        self._paused: bool = False
        self._ended: bool = False

    @property
    def total_tokens(self) -> int:
        return (self.agent_a.total_input_tokens + self.agent_a.total_output_tokens +
                self.agent_b.total_input_tokens + self.agent_b.total_output_tokens)

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
        Turn 1: open with topic. Subsequent turns: respond with full context.
        Moderator injection is prepended if present.
        """
        if turn == 1:
            base = (
                f"Topic: {current_topic}\n\n"
                f"You are starting a conversation with another AI agent about this topic. "
                f"Share your analysis, insights, and questions. Be substantive — "
                f"aim for 2-4 paragraphs. Use [FACT]...[/FACT] tags for key discoveries."
            )
        elif last_response:
            # Build richer context for responding agent
            agent = self._agent_for_turn(turn)
            other = self.agent_b if agent == self.agent_a else self.agent_a

            # Include last 2-3 turns for context (not just the last one)
            recent_context = ""
            relevant_turns = [t for t in self.turns[-3:] if t.speaker != "moderator"]
            if len(relevant_turns) > 1:
                for t in relevant_turns[:-1]:
                    recent_context += f"[{t.speaker}]: {t.text[:500]}\n\n"

            base = f"Topic: {current_topic}\n\n"
            if recent_context:
                base += f"Earlier in the conversation:\n{recent_context}\n"

            base += (
                f"[{other.name}] just said:\n{last_response}\n\n"
                f"Respond substantively. Share your own analysis, build on their points, "
                f"raise new questions or perspectives. Aim for 2-4 paragraphs. "
                f"Use [FACT]...[/FACT] tags for key discoveries."
            )
        else:
            base = f"Topic: {current_topic}\n\nPlease continue the discussion."

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
                print(
                    f"  {C_YELLOW}Tokens: {_fmt_tokens(self.total_tokens)} used"
                    + (f" / {_fmt_tokens(self.max_tokens)} limit" if self.max_tokens > 0 else "")
                    + f"{RESET}",
                    flush=True,
                )
                # Show prompt again after token info
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
            print(f"{RESET}")
            _sys("Turn interrupted by user.")
            raise

        print(f"{RESET}", flush=True)

        # Session resume fallback: if empty response and agent had a session,
        # clear session_id and retry once with a fresh session
        if not full_text.strip() and agent.session_id:
            _sys(f"Empty response — retrying {agent.name} without --resume")
            stale_sid = agent.session_id
            agent.session_id = ""
            print(f"\n  {agent.color}", end="", flush=True)
            try:
                for chunk in invoke_agent(agent, prompt, timeout=self.timeout):
                    print(chunk, end="", flush=True)
                    full_text += chunk
            except KeyboardInterrupt:
                print(f"{RESET}")
                raise
            print(f"{RESET}", flush=True)

        return full_text

    def run(self) -> None:
        """Main chat loop."""
        _print_header(self.agent_a, self.agent_b, self.topic, self.max_turns)

        if self.auto_mode:
            _sys(f"Auto mode: {self.auto_delay}s delay between turns. Ctrl+C to stop.")
        else:
            _sys("Moderator mode: you will be prompted between each turn.")

        current_topic = self.topic
        last_response: Optional[str] = None

        for turn in range(1, self.max_turns + 1):
            if self._ended:
                break

            if self.max_tokens > 0 and self.total_tokens >= self.max_tokens:
                _sys(f"Token limit {_fmt_tokens(self.max_tokens)} reached — stopping.")
                break

            agent = self._agent_for_turn(turn)
            prompt = self._build_prompt(turn, last_response, current_topic)

            # Print turn header
            _print_turn_header(turn, self.max_turns, agent,
                               self.total_tokens, self.max_tokens)

            # Stream the response
            try:
                full_text = self._stream_turn(agent, prompt)
            except KeyboardInterrupt:
                break

            if not full_text.strip():
                _sys(f"Empty response from {agent.name} — skipping turn.")
                last_response = None
                continue

            # Extract and display facts inline; route to exchange if available
            other = self.agent_b if agent == self.agent_a else self.agent_a
            fact_matches = extract_facts(full_text)
            for attrs_str, body in fact_matches:
                body_clean = body.strip()
                _print_fact(body_clean)
                self.facts.append(body_clean)
                if self.exchange_url:
                    _route_fact_to_exchange(
                        body_clean, agent.name, other.name,
                        turn, self.chat_id, self.exchange_url,
                        attrs_str=attrs_str,
                    )

            # Token usage line
            print(
                f"\n  {DIM}Turn: {_fmt_tokens(agent.last_input_tokens)} in / "
                f"{_fmt_tokens(agent.last_output_tokens)} out | "
                f"Total: {_fmt_tokens(self.total_tokens)} tokens{RESET}",
                flush=True,
            )

            # Record this turn
            self.turns.append(TurnRecord(
                turn=turn,
                speaker=agent.name,
                text=full_text,
                input_tokens=agent.last_input_tokens,
                output_tokens=agent.last_output_tokens,
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
        print(f"  Total tokens:    {_fmt_tokens(self.total_tokens)}")
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
        "--max-tokens", type=int, default=0,
        help="Maximum total tokens (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--cli-budget", type=float, default=5.0,
        help="Per-agent safety budget for claude CLI in USD (default: 5.0)",
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

    # Exchange
    parser.add_argument(
        "--exchange-url", default="",
        help="Exchange server URL for fact routing (e.g. http://localhost:8889). Empty = no routing.",
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

    # Generate chat id
    chat_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"

    # Build agent objects — each gets the full cli_budget as a safety cap
    agent_a = ChatAgent(
        name=args.agent_a,
        workspace=ws_a,
        project_cwd=project_path,
        role=args.role_a,
        cli_budget=args.cli_budget,
        color=C_CYAN,
    )
    agent_b = ChatAgent(
        name=args.agent_b,
        workspace=ws_b,
        project_cwd=project_path,
        role=args.role_b,
        cli_budget=args.cli_budget,
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
        max_tokens=args.max_tokens,
        auto_mode=args.auto,
        auto_delay=args.auto_delay,
        timeout=args.timeout,
        chat_id=chat_id,
        exchange_url=args.exchange_url,
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
