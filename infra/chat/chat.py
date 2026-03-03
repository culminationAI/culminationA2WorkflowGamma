#!/usr/bin/env python3
"""
infra/chat/chat.py — CLI-based agent-to-agent chat orchestrator.

Two Claude Code agents chat in real-time. Each has full tool access in its
own workspace. This orchestrator manages turn-taking, display, logging, and
fact extraction to the exchange server.

Usage:
    python3 infra/chat/chat.py "Discuss your architecture"
    python3 infra/chat/chat.py --topic "Compare memory implementations" \
        --agent-a falkvelt --dir-a /path/to/follower \
        --agent-b clone --dir-b /path/to/clone \
        --max-turns 20 --max-budget 2.0 --timeout 180
"""

import argparse
import dataclasses
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

COLORS = {
    "falkvelt": "\033[36m",   # cyan
    "clone":    "\033[35m",   # magenta
    "human":    "\033[33m",   # yellow
    "system":   "\033[90m",   # dark gray
    "error":    "\033[31m",   # red
    "fact":     "\033[32m",   # green
}

# Fact tag regex: [FACT attr="val" ...] body [/FACT]
FACT_RE = re.compile(r'\[FACT(?:\s+([^\]]*))?\](.*?)\[/FACT\]', re.DOTALL)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ChatAgent:
    name: str
    workspace: str
    color: str
    system_prompt: str = ""
    session_id: Optional[str] = None
    turn_count: int = 0
    total_cost: float = 0.0


@dataclasses.dataclass
class TurnRecord:
    turn: int
    agent: str
    prompt: str
    response: str
    cost_usd: float
    session_id: str
    timestamp: str
    facts_extracted: int = 0


# ---------------------------------------------------------------------------
# Fact extraction and exchange routing
# ---------------------------------------------------------------------------
def extract_and_route_facts(
    text: str,
    from_agent: str,
    to_agent: str,
    turn: int,
    chat_id: str,
    exchange_url: str,
) -> tuple[str, int]:
    """
    Parse [FACT] blocks from text, POST each to exchange server.
    Returns (cleaned_text, fact_count).
    """
    facts = FACT_RE.findall(text)
    count = 0

    for attrs_str, body in facts:
        subject_m = re.search(r'subject="([^"]*)"', attrs_str)
        priority_m = re.search(r'priority="([^"]*)"', attrs_str)

        subject = subject_m.group(1) if subject_m else "fact"
        priority = priority_m.group(1) if priority_m else "P2"

        msg = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "type": "fact",
            "subject": subject,
            "body": body.strip(),
            "metadata": json.dumps({
                "priority": priority,
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
            count += 1
        except Exception as exc:
            _print_system(f"Warning: exchange POST failed: {exc}")

    # Replace each [FACT]...[/FACT] block with a compact marker
    cleaned = FACT_RE.sub(
        f"{COLORS['fact']}→ fact sent to exchange{RESET}", text
    )
    return cleaned, count


# ---------------------------------------------------------------------------
# Terminal display helpers
# ---------------------------------------------------------------------------
def _color(name: str, text: str) -> str:
    c = COLORS.get(name.lower(), "")
    return f"{c}{text}{RESET}" if c else text


def _print_system(msg: str) -> None:
    print(f"{COLORS['system']}[system] {msg}{RESET}", flush=True)


def _print_separator(char: str = "─", width: int = 60) -> None:
    print(f"{DIM}{char * width}{RESET}", flush=True)


def _print_header(agent_a: str, agent_b: str, topic: str, budget: float, max_turns: int) -> None:
    print()
    _print_separator("═")
    print(f"{BOLD}  Agent Chat: {_color(agent_a, agent_a)} ↔ {_color(agent_b, agent_b)}{RESET}")
    print(f"  Topic: {topic}")
    print(f"  Budget: ${budget:.2f} | Max turns: {max_turns}")
    _print_separator("═")
    print()


def _print_turn_header(turn: int, agent_name: str, cost: float, color: str) -> None:
    cost_str = f"${cost:.4f}" if cost > 0 else ""
    label = f"[Turn {turn}] {agent_name}"
    suffix = f" ({cost_str})" if cost_str else ""
    print(f"\n{color}{BOLD}{label}{suffix}{RESET}", flush=True)
    _print_separator()


def _print_human_injection(sender: str, message: str) -> None:
    print(f"\n{COLORS['human']}{BOLD}[HUMAN] {sender}: {message}{RESET}", flush=True)
    _print_separator()


def _print_response(text: str, color: str) -> None:
    # Indent each line for visual separation
    for line in text.splitlines():
        print(f"  {color}{line}{RESET}", flush=True)


# ---------------------------------------------------------------------------
# Claude subprocess invocation
# ---------------------------------------------------------------------------
def _run_claude(
    agent: ChatAgent,
    message: str,
    timeout: int,
    max_budget: float,
    last_turns_context: Optional[list[TurnRecord]] = None,
) -> tuple[Optional[str], Optional[str], float]:
    """
    Invoke `claude -p` for the given agent.
    Returns (response_text, new_session_id, cost_usd).
    On error returns (None, None, 0.0).

    If agent.session_id is set and --resume fails, falls back to fresh
    session with last 3 turns injected as context.
    """
    # Strip CLAUDECODE env to avoid nested-session errors (pattern from watcher.py)
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    def _build_cmd(session_id: Optional[str], prompt: str) -> tuple[list[str], str]:
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--append-system-prompt", agent.system_prompt,
            "--permission-mode", "bypassPermissions",
            "--max-budget-usd", str(max_budget),
        ]
        if session_id:
            cmd.extend(["--resume", session_id])
        return cmd, prompt

    def _execute(cmd: list[str], prompt: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            env=clean_env,
            cwd=agent.workspace,
            timeout=timeout,
        )

    def _parse_result(proc: subprocess.CompletedProcess) -> tuple[Optional[str], Optional[str], float]:
        """Parse JSON output; fall back to raw stdout on parse failure."""
        stdout = proc.stdout.strip()
        if not stdout:
            return None, None, 0.0

        try:
            data = json.loads(stdout)
            result_text = data.get("result", "") or data.get("content", "") or ""
            session_id = data.get("session_id")
            cost = float(data.get("cost_usd", 0.0))
            return result_text.strip() or None, session_id, cost
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat raw stdout as response text
            return stdout if stdout else None, None, 0.0

    # Attempt with --resume if we have a session
    cmd, prompt = _build_cmd(agent.session_id if agent.turn_count > 0 else None, message)

    try:
        proc = _execute(cmd, prompt)
        if proc.returncode == 0:
            return _parse_result(proc)

        # Non-zero exit — if we tried --resume, retry fresh with context injection
        if agent.session_id and agent.turn_count > 0:
            _print_system(f"--resume failed (code {proc.returncode}), retrying fresh session")
            context_prompt = _build_context_prompt(message, last_turns_context or [])
            cmd_fresh, _ = _build_cmd(None, context_prompt)
            proc2 = _execute(cmd_fresh, context_prompt)
            if proc2.returncode == 0:
                return _parse_result(proc2)
            _print_system(f"Fresh session also failed: {proc2.stderr[:200]}")
            return None, None, 0.0

        _print_system(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
        return None, None, 0.0

    except subprocess.TimeoutExpired:
        return None, None, 0.0  # caller handles timeout retry
    except FileNotFoundError:
        _print_system("ERROR: claude binary not found in PATH")
        sys.exit(1)
    except Exception as exc:
        _print_system(f"Unexpected error running claude: {exc}")
        return None, None, 0.0


def _build_context_prompt(message: str, last_turns: list[TurnRecord]) -> str:
    """Inject last N turns as context when --resume is unavailable."""
    if not last_turns:
        return message
    ctx_lines = ["[Context from previous turns:]"]
    for t in last_turns[-3:]:
        ctx_lines.append(f"[Turn {t.turn} - {t.agent}]: {t.response[:400]}")
    ctx_lines.append(f"\n[Current message]: {message}")
    return "\n".join(ctx_lines)


def _run_claude_with_retry(
    agent: ChatAgent,
    message: str,
    timeout: int,
    max_budget: float,
    last_turns: list[TurnRecord],
) -> tuple[Optional[str], Optional[str], float]:
    """
    Wrap _run_claude with:
    - Timeout retry (once with "Please continue")
    - Empty response retry with nudge (max 2 attempts)
    """
    for attempt in range(3):
        try:
            text, sid, cost = _run_claude(agent, message, timeout, max_budget, last_turns)
        except subprocess.TimeoutExpired:
            if attempt == 0:
                _print_system(f"Timeout on attempt {attempt + 1}, retrying with nudge...")
                message = "Please continue."
                continue
            _print_system("Timeout on retry — skipping turn")
            return None, None, 0.0

        if text:
            return text, sid, cost

        if attempt < 2:
            nudge = "Please continue." if attempt == 0 else "Please provide your response."
            _print_system(f"Empty response (attempt {attempt + 1}), retrying with: {nudge!r}")
            message = nudge
        else:
            _print_system("Max retries reached, skipping turn")

    return None, None, 0.0


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------
def _build_system_prompt(
    my_name: str,
    my_workspace: str,
    other_name: str,
    topic: str,
) -> str:
    return f"""You are {my_name}, an AI agent working in {my_workspace}.
You are having a real-time conversation with {other_name}, another AI agent.
Topic: {topic}

Rules:
- Respond directly and conversationally. You can reference your workspace files.
- Use tools (Read, Bash, Grep, etc.) when you need to look up actual data.
- Keep responses focused — 2-4 paragraphs unless detail is genuinely needed.
- Build on what {other_name} says; advance the discussion.

Persisting facts to exchange:
When you discover a fact, insight, or artifact worth preserving beyond this
conversation, wrap it in [FACT] tags:

[FACT subject="Memory architecture" priority="P1"]
Your fact content here.
[/FACT]

Available priority levels: P0 (critical), P1 (important), P2 (general).
Use [FACT] only for knowledge worth persisting — not every statement.
The orchestrator will route facts to the exchange server automatically.
"""


# ---------------------------------------------------------------------------
# Conversation log
# ---------------------------------------------------------------------------
def _save_log(log_path: Path, records: list[TurnRecord], meta: dict) -> None:
    data = {
        "meta": meta,
        "turns": [dataclasses.asdict(r) for r in records],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# User input thread
# ---------------------------------------------------------------------------
class UserInputThread(threading.Thread):
    """Background thread that reads user input and posts to a queue."""

    def __init__(self, input_queue: queue.Queue) -> None:
        super().__init__(daemon=True)
        self.input_queue = input_queue
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                line = input()
                self.input_queue.put(line)
            except EOFError:
                break


# ---------------------------------------------------------------------------
# Chat orchestrator
# ---------------------------------------------------------------------------
class ChatOrchestrator:
    def __init__(
        self,
        agent_a: ChatAgent,
        agent_b: ChatAgent,
        topic: str,
        max_turns: int,
        max_budget: float,
        timeout: int,
        exchange_url: str,
        chat_id: str,
    ) -> None:
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.topic = topic
        self.max_turns = max_turns
        self.max_budget = max_budget
        self.timeout = timeout
        self.exchange_url = exchange_url
        self.chat_id = chat_id

        self.records: list[TurnRecord] = []
        self.total_cost: float = 0.0
        self.paused: bool = False
        self._input_queue: queue.Queue = queue.Queue()
        self._pending_injection: Optional[str] = None
        self._should_quit: bool = False
        self._input_thread = UserInputThread(self._input_queue)

    def _agents(self) -> list[ChatAgent]:
        return [self.agent_a, self.agent_b]

    def _current_agent(self, turn: int) -> ChatAgent:
        return self.agent_a if turn % 2 == 1 else self.agent_b

    def _other_agent(self, turn: int) -> ChatAgent:
        return self.agent_b if turn % 2 == 1 else self.agent_a

    def _check_user_input(self) -> None:
        """Drain input queue, handle commands."""
        while not self._input_queue.empty():
            line = self._input_queue.get_nowait()
            cmd = line.strip().lower()
            if cmd == "q":
                _print_system("Quit requested — finishing after this turn.")
                self._should_quit = True
            elif cmd == "p":
                self.paused = not self.paused
                state = "paused" if self.paused else "resumed"
                _print_system(f"Conversation {state}. Press p to toggle, q to quit.")
            elif line.strip():
                self._pending_injection = line.strip()
                _print_human_injection("user", line.strip())
            # Empty enter: prompt user for a message
            else:
                _print_system("Type a message (Enter), 'p' to pause, 'q' to quit.")

    def _wait_while_paused(self) -> None:
        while self.paused and not self._should_quit:
            self._check_user_input()
            time.sleep(0.3)

    def _build_next_message(self, prev_response: Optional[str], turn: int) -> str:
        """Compose the next message to send to the current agent."""
        if turn == 1:
            # First turn: send the topic as the opening message
            base = self.topic
        elif prev_response:
            base = prev_response
        else:
            base = "Please continue the discussion."

        # Inject user message if pending
        if self._pending_injection:
            injection = self._pending_injection
            self._pending_injection = None
            # Prepend user injection so the agent responds to it
            base = f"[Message from user]: {injection}\n\n{base}"

        return base

    def run(self) -> None:
        _print_header(
            self.agent_a.name,
            self.agent_b.name,
            self.topic,
            self.max_budget,
            self.max_turns,
        )
        _print_system("Starting conversation. Press Enter to inject a message, 'p' to pause, 'q' to quit.")
        print()

        self._input_thread.start()

        prev_response: Optional[str] = None

        for turn in range(1, self.max_turns + 1):
            self._wait_while_paused()
            self._check_user_input()

            if self._should_quit:
                break

            if self.total_cost >= self.max_budget:
                _print_system(f"Budget ${self.max_budget:.2f} reached — stopping.")
                break

            agent = self._current_agent(turn)
            other = self._other_agent(turn)
            message = self._build_next_message(prev_response, turn)

            _print_turn_header(turn, agent.name, 0.0, agent.color)
            _print_system("Thinking...")

            remaining_budget = max(0.10, self.max_budget - self.total_cost)
            text, sid, cost = _run_claude_with_retry(
                agent, message, self.timeout, remaining_budget, self.records
            )

            if text is None:
                _print_system(f"No response from {agent.name} — skipping turn.")
                prev_response = None
                continue

            # Update session id (always — in case --resume fell back to fresh session)
            if sid:
                agent.session_id = sid
            agent.turn_count += 1
            agent.total_cost += cost
            self.total_cost += cost

            # Extract and route [FACT] blocks
            clean_text, fact_count = extract_and_route_facts(
                text, agent.name, other.name, turn, self.chat_id, self.exchange_url
            )

            # Reprint turn header with cost now known
            _print_turn_header(turn, agent.name, cost, agent.color)
            _print_response(clean_text, agent.color)

            if fact_count > 0:
                print(f"\n  {COLORS['fact']}[{fact_count} fact(s) sent to exchange]{RESET}")

            # Record turn
            record = TurnRecord(
                turn=turn,
                agent=agent.name,
                prompt=message,
                response=clean_text,
                cost_usd=cost,
                session_id=agent.session_id or "",
                timestamp=datetime.utcnow().isoformat(),
                facts_extracted=fact_count,
            )
            self.records.append(record)

            # Running cost display
            print(
                f"\n  {DIM}Turn cost: ${cost:.4f} | "
                f"Session total: ${self.total_cost:.4f} / ${self.max_budget:.2f}{RESET}"
            )

            prev_response = clean_text

        self._input_thread.stop()
        self._finish()

    def _finish(self) -> None:
        print()
        _print_separator("═")
        print(f"{BOLD}  Conversation ended.{RESET}")
        print(f"  Turns completed: {len(self.records)}")
        print(f"  Total cost: ${self.total_cost:.4f}")
        _print_separator("═")

        # Save log
        log_path = Path(__file__).parent / "logs" / f"{self.chat_id}.json"
        meta = {
            "chat_id": self.chat_id,
            "agent_a": self.agent_a.name,
            "agent_b": self.agent_b.name,
            "dir_a": self.agent_a.workspace,
            "dir_b": self.agent_b.workspace,
            "topic": self.topic,
            "total_cost_usd": self.total_cost,
            "turns_completed": len(self.records),
            "started_at": self.chat_id,
        }
        _save_log(log_path, self.records, meta)
        _print_system(f"Log saved: {log_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _auto_detect_clone_dir() -> Optional[str]:
    """Try common sibling locations for the clone workspace."""
    candidates = [
        Path.home() / "Desktop" / "_clone_",
        Path.cwd().parent / "_clone_",
        Path("/tmp/_clone_"),
    ]
    for p in candidates:
        if p.is_dir():
            return str(p)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI-based agent-to-agent chat orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "topic_positional",
        nargs="?",
        metavar="TOPIC",
        help="Conversation topic (positional shorthand)",
    )
    parser.add_argument("--topic", default=None, help="Conversation topic")
    parser.add_argument("--agent-a", default="falkvelt", help="Name of agent A (default: falkvelt)")
    parser.add_argument("--dir-a", default=None, help="Workspace directory for agent A (default: cwd)")
    parser.add_argument("--agent-b", default="clone", help="Name of agent B (default: clone)")
    parser.add_argument("--dir-b", default=None, help="Workspace directory for agent B (required if not auto-detected)")
    parser.add_argument("--max-turns", type=int, default=20, help="Maximum turns (default: 20)")
    parser.add_argument("--max-budget", type=float, default=2.0, help="Max total spend in USD (default: 2.0)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-turn timeout in seconds (default: 180)")
    parser.add_argument("--exchange-url", default="http://localhost:8888", help="Exchange server URL")

    args = parser.parse_args()

    # Resolve topic
    topic = args.topic or args.topic_positional
    if not topic:
        parser.error("A topic is required. Pass it as positional arg or --topic.")

    # Resolve workspace dirs
    dir_a = args.dir_a or str(Path.cwd())
    dir_b = args.dir_b or _auto_detect_clone_dir()
    if not dir_b:
        parser.error(
            "--dir-b is required (could not auto-detect clone workspace). "
            "Pass --dir-b /path/to/clone"
        )

    if not Path(dir_a).is_dir():
        parser.error(f"Agent A workspace not found: {dir_a}")
    if not Path(dir_b).is_dir():
        parser.error(f"Agent B workspace not found: {dir_b}")

    # Per-turn budget cap: allocate half of total to each turn as a soft guard
    # The full max_budget is passed; claude --max-budget-usd enforces per-invocation
    per_turn_budget = round(args.max_budget / max(args.max_turns, 1) * 4, 4)

    chat_id = f"chat_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    color_a = COLORS.get(args.agent_a.lower(), "\033[36m")
    color_b = COLORS.get(args.agent_b.lower(), "\033[35m")

    agent_a = ChatAgent(
        name=args.agent_a,
        workspace=dir_a,
        color=color_a,
        system_prompt=_build_system_prompt(args.agent_a, dir_a, args.agent_b, topic),
    )
    agent_b = ChatAgent(
        name=args.agent_b,
        workspace=dir_b,
        color=color_b,
        system_prompt=_build_system_prompt(args.agent_b, dir_b, args.agent_a, topic),
    )

    orchestrator = ChatOrchestrator(
        agent_a=agent_a,
        agent_b=agent_b,
        topic=topic,
        max_turns=args.max_turns,
        max_budget=args.max_budget,
        timeout=args.timeout,
        exchange_url=args.exchange_url,
        chat_id=chat_id,
    )

    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print()
        _print_system("Interrupted by user.")
        orchestrator._finish()
        sys.exit(0)


if __name__ == "__main__":
    main()
