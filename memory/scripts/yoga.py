#!/usr/bin/env python3
"""Yoga Protocol — Automated infrastructure health poses.

Automates 3 of 6 yoga poses (infrastructure health checks):
  1. Pranayama — Memory write → search → graph search cycle
  2. Tadasana  — Session start checks (files, exchange, lock)
  3. Savasana  — Exchange server ping → message → verify → cleanup

Poses 3 (Vrikshasana), 4 (Warrior), 6 (Lotus) are manual — coordinator reasoning required.

Usage:
    python3 memory/scripts/yoga.py                    # All 3 automatable poses
    python3 memory/scripts/yoga.py --pose pranayama
    python3 memory/scripts/yoga.py --pose tadasana
    python3 memory/scripts/yoga.py --pose savasana
    python3 memory/scripts/yoga.py --cleanup          # Remove leftover _yoga_test_ data
    python3 memory/scripts/yoga.py --json             # JSON output instead of terminal
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Source root: 3 levels up from memory/scripts/yoga.py
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# ANSI colors (disabled when --json or not a TTY)
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


GREEN  = lambda t: _c("32", t)
RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PoseResult:
    name: str
    pipeline: str
    status: str          # FLOWING / PARTIAL / BLOCKED / STUB
    steps: list[StepResult] = field(default_factory=list)
    tension_point: str = ""
    error: str = ""

    def add(self, name: str, passed: bool, detail: str = "") -> StepResult:
        sr = StepResult(name=name, passed=passed, detail=detail)
        self.steps.append(sr)
        return sr

    def finalize(self) -> None:
        """Set status based on step outcomes."""
        if self.error:
            self.status = "BLOCKED"
            return
        total = len(self.steps)
        if total == 0:
            self.status = "STUB"
            return
        passed = sum(1 for s in self.steps if s.passed)
        if passed == total:
            self.status = "FLOWING"
        elif passed == 0:
            self.status = "BLOCKED"
        else:
            self.status = "PARTIAL"
            failures = [s.name for s in self.steps if not s.passed]
            self.tension_point = ", ".join(failures)

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = 5) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:
        raise


def http_post(url: str, body: dict, timeout: int = 5) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def http_patch(url: str, body: dict, timeout: int = 5) -> int:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code

# ---------------------------------------------------------------------------
# Pose 1: Pranayama (Memory Breath)
# ---------------------------------------------------------------------------

def pose_pranayama() -> PoseResult:
    pose = PoseResult(name="Pranayama", pipeline="Memory Write → Vector Retrieve → Graph Search", status="FLOWING")
    timestamp = int(time.time())
    test_text = f"_yoga_test_ memory breath {timestamp}"

    # Step 1: Ollama / embedding service reachable
    try:
        status_code, _ = http_get("http://localhost:11434/api/tags", timeout=5)
        pose.add("Embedding service (Ollama) reachable", status_code < 300, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Embedding service (Ollama) reachable", False, str(e))

    # Step 2: Qdrant reachable
    try:
        status_code, body = http_get("http://localhost:6333/collections/workflow_memory", timeout=5)
        if status_code < 300:
            points = json.loads(body).get("result", {}).get("points_count", "?")
            pose.add("Qdrant reachable", True, f"HTTP {status_code}, {points} points")
        else:
            pose.add("Qdrant reachable", False, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Qdrant reachable", False, str(e))

    # Step 3: Write test record
    record = json.dumps([{
        "text": test_text,
        "user_id": "yoga",
        "agent_id": "coordinator",
        "metadata": {"type": "yoga_test", "_source": "_follower_"},
    }])
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/memory_write.py", record],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=30,
        )
        write_ok = result.returncode == 0
        detail = "ok" if write_ok else (result.stderr.strip()[:80] or result.stdout.strip()[:80])
        pose.add("Write test record", write_ok, detail)
    except Exception as e:
        pose.add("Write test record", False, str(e))
        pose.error = str(e)
        pose.finalize()
        return pose

    # Step 4: Vector search for test record
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/memory_search.py", "_yoga_test_ memory breath", "--limit", "3"],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=30,
        )
        search_ok = False
        if result.returncode == 0:
            try:
                hits = json.loads(result.stdout)
                search_ok = any("_yoga_test_" in h.get("memory", "") for h in hits)
            except json.JSONDecodeError:
                pass
        detail = "test record found" if search_ok else "test record not found in results"
        pose.add("Vector search retrieves test record", search_ok, detail)
    except Exception as e:
        pose.add("Vector search retrieves test record", False, str(e))

    # Step 5: Graph search (fallback is acceptable)
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/memory_search.py", "_yoga_test_", "--graph"],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=30,
        )
        graph_ok = result.returncode == 0
        detail = "graph search executed" if graph_ok else result.stderr.strip()[:80]
        pose.add("Graph search executes (fallback OK)", graph_ok, detail)
    except Exception as e:
        pose.add("Graph search executes (fallback OK)", False, str(e))

    # Step 6: Neo4j fulltext index exists
    try:
        status_code, response = http_post(
            "http://localhost:7474/db/neo4j/tx/commit",
            {"statements": [{"statement": "SHOW INDEXES YIELD name WHERE name = 'memory_fulltext' RETURN name"}]},
            timeout=8,
        )
        if status_code == 200:
            results = response.get("results", [])
            rows = results[0].get("data", []) if results else []
            index_ok = len(rows) > 0
            pose.add("Neo4j memory_fulltext index exists", index_ok,
                     "index present" if index_ok else "index missing (graph search uses fallback)")
        else:
            pose.add("Neo4j memory_fulltext index exists", False, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Neo4j memory_fulltext index exists", False, str(e))

    # Step 7: Cleanup yoga test records from Qdrant
    try:
        status_code, _ = http_post(
            "http://localhost:6333/collections/workflow_memory/points/delete",
            {"filter": {"must": [{"key": "user_id", "match": {"value": "yoga"}}]}},
            timeout=8,
        )
        cleanup_ok = status_code < 300
        pose.add("Cleanup test records from Qdrant", cleanup_ok, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Cleanup test records from Qdrant", False, str(e))

    pose.finalize()
    return pose

# ---------------------------------------------------------------------------
# Pose 2: Tadasana (Standing — Session Start)
# ---------------------------------------------------------------------------

def pose_tadasana() -> PoseResult:
    pose = PoseResult(name="Tadasana", pipeline="Session Start Checks", status="FLOWING")

    # Step 1: CLAUDE.md — check for actual _WORKFLOW_NEEDS_INIT HTML comment marker
    claude_md = SOURCE_ROOT / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        # The actual marker is <!-- _WORKFLOW_NEEDS_INIT --> (not text references in protocol docs)
        # We look specifically for the HTML comment form
        has_init_marker = bool(re.search(r"<!--\s*_WORKFLOW_NEEDS_INIT\s*-->", content))
        pose.add(
            "CLAUDE.md: no _WORKFLOW_NEEDS_INIT marker",
            not has_init_marker,
            "needs initialization" if has_init_marker else "initialized",
        )
    else:
        pose.add("CLAUDE.md exists", False, "file not found")

    # Step 2: workflow_update.py --check
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/workflow_update.py", "--check"],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=15,
        )
        update_ok = result.returncode == 0
        stdout_snippet = (result.stdout.strip().splitlines()[0] if result.stdout.strip() else "")[:80]
        pose.add("Workflow update check", update_ok, stdout_snippet or "ok")
    except Exception as e:
        pose.add("Workflow update check", False, str(e))

    # Step 3: Memory search "active tasks blockers"
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/memory_search.py", "active tasks blockers", "--limit", "5"],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=15,
        )
        search_ok = result.returncode == 0
        try:
            hits = json.loads(result.stdout)
            detail = f"{len(hits)} results"
        except Exception:
            detail = "executed" if search_ok else result.stderr.strip()[:60]
        pose.add("Memory search (active tasks blockers)", search_ok, detail)
    except Exception as e:
        pose.add("Memory search (active tasks blockers)", False, str(e))

    # Step 4: capability-map.md exists
    cap_map = SOURCE_ROOT / "docs" / "self-architecture" / "capability-map.md"
    cap_exists = cap_map.exists()
    if cap_exists:
        mtime = cap_map.stat().st_mtime
        age_days = (time.time() - mtime) / 86400
        detail = f"age {age_days:.1f}d"
        # Warn if older than 30 days but don't fail — freshness is a judgment call
        pose.add("capability-map.md exists", True, detail)
    else:
        pose.add("capability-map.md exists", False, "file not found")

    # Step 5: build-registry.json exists and is valid JSON
    registry_path = SOURCE_ROOT / "docs" / "self-architecture" / "build-registry.json"
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            builds = data.get("builds", [])
            pose.add("build-registry.json valid", True, f"{len(builds)} builds")
        except json.JSONDecodeError as e:
            pose.add("build-registry.json valid", False, f"JSON error: {e}")
    else:
        pose.add("build-registry.json valid", False, "file not found")

    # Step 6: Session lock create/delete cycle
    lock = SOURCE_ROOT / ".session_lock"
    try:
        lock.touch()
        lock.unlink()
        pose.add("Session lock create/delete", True, "ok")
    except Exception as e:
        pose.add("Session lock create/delete", False, str(e))

    # Step 7: Exchange server reachable
    try:
        status_code, _ = http_get("http://localhost:8888/", timeout=5)
        exchange_ok = status_code < 300
        pose.add("Exchange server reachable", exchange_ok, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Exchange server reachable", False, str(e))

    # Step 8: Check pending messages count
    try:
        status_code, body_bytes = http_get("http://localhost:8888/messages?to=falkvelt&status=pending", timeout=5)
        if status_code < 300:
            messages = json.loads(body_bytes)
            count = len(messages) if isinstance(messages, list) else 0
            pose.add("Exchange inbox accessible", True, f"{count} pending messages")
        else:
            pose.add("Exchange inbox accessible", False, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Exchange inbox accessible", False, str(e))

    # Step 9: meditation-log — check for unresolved P0-P2 recommendations
    med_log = SOURCE_ROOT / "docs" / "self-architecture" / "meditation-log.md"
    if med_log.exists():
        content = med_log.read_text(encoding="utf-8")
        # Look for unresolved P0/P1/P2 markers in repair/recommendation blocks
        unresolved_pattern = re.compile(r'"status":\s*"(pending|open|unresolved)".*?"priority":\s*"(P[012])"', re.DOTALL)
        unresolved = unresolved_pattern.findall(content)
        # Also check simpler pattern: "P0:" or "P1:" in recommendations not marked resolved
        p_counts = {"P0": 0, "P1": 0, "P2": 0}
        for line in content.splitlines():
            for p in ("P0", "P1", "P2"):
                if f'"{p}"' in line or f": {p}" in line or f"[{p}]" in line:
                    p_counts[p] += 1
        total_flagged = sum(p_counts.values())
        detail = f"P0:{p_counts['P0']} P1:{p_counts['P1']} P2:{p_counts['P2']}"
        # Not a failure — just informational. Pass if no P0s specifically.
        pose.add("Meditation log: no critical (P0) items", p_counts["P0"] == 0, detail)
    else:
        pose.add("Meditation log exists", False, "file not found")

    pose.finalize()
    return pose

# ---------------------------------------------------------------------------
# Pose 3 (renamed Savasana here — pose 5 in full protocol): Exchange Pipeline
# ---------------------------------------------------------------------------

def pose_savasana() -> PoseResult:
    pose = PoseResult(name="Savasana", pipeline="Exchange Server Pipeline", status="FLOWING")
    exchange_url = "http://localhost:8888"
    sent_message_id: Optional[str] = None

    # Step 1: Health check
    try:
        status_code, _ = http_get(exchange_url, timeout=5)
        health_ok = status_code < 300
        pose.add("Exchange health check", health_ok, f"HTTP {status_code}")
        if not health_ok:
            pose.error = f"Exchange unreachable (HTTP {status_code})"
            pose.finalize()
            return pose
    except Exception as e:
        pose.add("Exchange health check", False, str(e))
        pose.error = f"Exchange unreachable: {e}"
        pose.finalize()
        return pose

    # Step 2: Send test message
    msg = {
        "from_agent": "yoga_test",
        "to_agent": "falkvelt",
        "type": "notification",
        "subject": "_yoga_test_ exchange ping",
        "body": f"Yoga savasana test payload {int(time.time())}",
    }
    try:
        status_code, response = http_post(f"{exchange_url}/messages", msg, timeout=8)
        send_ok = status_code in (200, 201)
        sent_message_id = response.get("id") or response.get("message_id")
        pose.add("Send test message", send_ok, f"HTTP {status_code}, id={sent_message_id}")
    except Exception as e:
        pose.add("Send test message", False, str(e))
        pose.error = str(e)
        pose.finalize()
        return pose

    # Step 3: Verify message visible in inbox
    try:
        status_code, body_bytes = http_get(
            f"{exchange_url}/messages?to=falkvelt&status=pending", timeout=5
        )
        if status_code < 300:
            messages = json.loads(body_bytes) if isinstance(body_bytes, bytes) else []
            yoga_msgs = [m for m in messages if "_yoga_test_" in m.get("subject", "")]
            visible = len(yoga_msgs) > 0
            # Grab first yoga message id for cleanup if send didn't return one
            if not sent_message_id and yoga_msgs:
                sent_message_id = yoga_msgs[0].get("id")
            pose.add("Test message visible in inbox", visible,
                     f"{len(yoga_msgs)} yoga test message(s) found")
        else:
            pose.add("Test message visible in inbox", False, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Test message visible in inbox", False, str(e))

    # Step 4: watcher.py process running
    try:
        result = subprocess.run(
            ["pgrep", "-f", "watcher.py"],
            capture_output=True, text=True, timeout=5,
        )
        watcher_running = result.returncode == 0
        pids = result.stdout.strip().replace("\n", ",")
        pose.add("Watcher process running", watcher_running,
                 f"pid(s): {pids}" if watcher_running else "not running (live responder inactive)")
    except Exception as e:
        pose.add("Watcher process running", False, str(e))

    # Step 5: Cleanup — mark yoga test messages as read
    cleanup_ok = False
    try:
        # Re-fetch to get all yoga test message IDs
        status_code, body_bytes = http_get(
            f"{exchange_url}/messages?to=falkvelt&status=pending", timeout=5
        )
        if status_code < 300:
            messages = json.loads(body_bytes) if isinstance(body_bytes, bytes) else []
            yoga_ids = [m["id"] for m in messages if "_yoga_test_" in m.get("subject", "") and "id" in m]
            patched = 0
            for mid in yoga_ids:
                code = http_patch(f"{exchange_url}/messages/{mid}", {"status": "read"}, timeout=5)
                if code < 300:
                    patched += 1
            cleanup_ok = len(yoga_ids) == 0 or patched == len(yoga_ids)
            pose.add("Cleanup test messages", cleanup_ok,
                     f"marked {patched}/{len(yoga_ids)} message(s) as read")
        else:
            pose.add("Cleanup test messages", False, f"HTTP {status_code}")
    except Exception as e:
        pose.add("Cleanup test messages", False, str(e))

    pose.finalize()
    return pose

# ---------------------------------------------------------------------------
# Cleanup function
# ---------------------------------------------------------------------------

def cleanup() -> None:
    """Remove all _yoga_test_ data from Qdrant and exchange."""
    print(BOLD("Cleanup: removing all _yoga_test_ data"))

    # Qdrant: delete by user_id=yoga filter (all yoga test writes use this)
    try:
        status_code, _ = http_post(
            "http://localhost:6333/collections/workflow_memory/points/delete",
            {"filter": {"must": [{"key": "user_id", "match": {"value": "yoga"}}]}},
            timeout=10,
        )
        if status_code < 300:
            print(GREEN("  [OK]") + " Qdrant yoga test records deleted")
        else:
            print(YELLOW("  [WARN]") + f" Qdrant delete returned HTTP {status_code}")
    except Exception as e:
        print(RED("  [ERROR]") + f" Qdrant cleanup failed: {e}")

    # Exchange: mark _yoga_test_ messages as read
    try:
        status_code, body_bytes = http_get(
            "http://localhost:8888/messages?to=falkvelt&status=pending", timeout=5
        )
        if status_code < 300:
            messages = json.loads(body_bytes) if isinstance(body_bytes, bytes) else []
            yoga_ids = [m["id"] for m in messages if "_yoga_test_" in m.get("subject", "") and "id" in m]
            if yoga_ids:
                patched = 0
                for mid in yoga_ids:
                    code = http_patch(f"http://localhost:8888/messages/{mid}", {"status": "read"}, timeout=5)
                    if code < 300:
                        patched += 1
                print(GREEN("  [OK]") + f" Exchange: marked {patched}/{len(yoga_ids)} yoga messages as read")
            else:
                print(DIM("  [--]") + " Exchange: no pending yoga test messages found")
        else:
            print(YELLOW("  [WARN]") + f" Exchange inbox check returned HTTP {status_code}")
    except Exception as e:
        print(RED("  [ERROR]") + f" Exchange cleanup failed: {e}")

    print(DIM("  Done."))

# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[PoseResult], report_path: Path) -> None:
    """Write yoga-report.md with flexibility score and per-pose findings."""
    flowing = sum(1 for r in results if r.status == "FLOWING")
    partial = sum(1 for r in results if r.status == "PARTIAL")
    blocked = sum(1 for r in results if r.status == "BLOCKED")
    score = round(flowing / len(results) * 100) if results else 0

    # Load previous report for comparison
    prev_score: Optional[int] = None
    if report_path.exists():
        try:
            prev_content = report_path.read_text(encoding="utf-8")
            m = re.search(r"Flexibility Score[:\s]+(\d+)%", prev_content)
            if m:
                prev_score = int(m.group(1))
        except Exception:
            pass

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Yoga Report — {now_str}",
        "",
        f"**Flexibility Score:** {score}%"
        + (f" (prev: {prev_score}%, delta: {score - prev_score:+d}%)" if prev_score is not None else ""),
        f"**Poses:** {flowing} FLOWING / {partial} PARTIAL / {blocked} BLOCKED",
        "",
        "---",
        "",
    ]

    for r in results:
        status_icon = {"FLOWING": "FLOWING", "PARTIAL": "PARTIAL", "BLOCKED": "BLOCKED", "STUB": "STUB"}[r.status]
        lines += [
            f"## {r.name} — {status_icon}",
            f"**Pipeline:** {r.pipeline}",
        ]
        if r.tension_point:
            lines.append(f"**Tension point:** {r.tension_point}")
        if r.error:
            lines.append(f"**Error:** {r.error}")
        lines.append("")
        lines.append("| Step | Status | Detail |")
        lines.append("|------|--------|--------|")
        for s in r.steps:
            icon = "PASS" if s.passed else "FAIL"
            lines.append(f"| {s.name} | {icon} | {s.detail} |")
        lines.append("")

    lines += [
        "---",
        "",
        "**Manual poses** (require coordinator reasoning):",
        "- Vrikshasana (3) — Knowledge graph connectivity review",
        "- Warrior (4) — Protocol conflict analysis",
        "- Lotus (6) — Meditation reflection and integration",
        "",
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")

# ---------------------------------------------------------------------------
# Terminal rendering
# ---------------------------------------------------------------------------

def print_pose_result(r: PoseResult) -> None:
    status_fn = {"FLOWING": GREEN, "PARTIAL": YELLOW, "BLOCKED": RED, "STUB": DIM}.get(r.status, BOLD)
    print()
    print(BOLD(f"  {r.name}") + "  " + status_fn(f"[{r.status}]"))
    print(DIM(f"  {r.pipeline}"))
    for s in r.steps:
        icon = GREEN("  PASS") if s.passed else RED("  FAIL")
        detail = DIM(f"  {s.detail}") if s.detail else ""
        print(f"{icon}  {s.name}{('  ' + s.detail) if s.detail else ''}")
    if r.tension_point:
        print(YELLOW(f"  Tension: {r.tension_point}"))
    if r.error:
        print(RED(f"  Error: {r.error}"))


def print_summary(results: list[PoseResult]) -> None:
    flowing = sum(1 for r in results if r.status == "FLOWING")
    score = round(flowing / len(results) * 100) if results else 0
    score_fn = GREEN if score == 100 else (YELLOW if score >= 50 else RED)
    print()
    print(BOLD("  Summary"))
    print(f"  Flexibility score: {score_fn(str(score) + '%')}")
    for r in results:
        status_fn = {"FLOWING": GREEN, "PARTIAL": YELLOW, "BLOCKED": RED, "STUB": DIM}.get(r.status, BOLD)
        print(f"  {status_fn('*')} {r.name}: {status_fn(r.status)}")
    print()

# ---------------------------------------------------------------------------
# Pose dispatcher
# ---------------------------------------------------------------------------

POSE_MAP: dict[str, tuple[str, object]] = {
    "pranayama": ("Pranayama", pose_pranayama),
    "tadasana":  ("Tadasana",  pose_tadasana),
    "savasana":  ("Savasana",  pose_savasana),
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description="Yoga Protocol — automated infrastructure health poses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/yoga.py\n"
            "  python3 memory/scripts/yoga.py --pose pranayama\n"
            "  python3 memory/scripts/yoga.py --cleanup\n"
            "  python3 memory/scripts/yoga.py --json\n"
        ),
    )
    parser.add_argument(
        "--pose", "-p",
        choices=list(POSE_MAP.keys()),
        help="Run a single pose only.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove all _yoga_test_ data and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of terminal display.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing yoga-report.md.",
    )
    args = parser.parse_args()

    if args.json_output:
        USE_COLOR = False

    if args.cleanup:
        cleanup()
        return

    # Select poses to run
    if args.pose:
        selected = [(args.pose, POSE_MAP[args.pose][1])]
    else:
        selected = [(name, fn) for name, (_, fn) in POSE_MAP.items()]

    if not args.json_output:
        print()
        print(BOLD("  Yoga Protocol") + DIM("  — infrastructure health poses"))
        print(DIM(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}"))

    results: list[PoseResult] = []
    for pose_key, fn in selected:
        if not args.json_output:
            print()
            print(DIM(f"  Running {POSE_MAP[pose_key][0]}..."))
        r = fn()
        results.append(r)
        if not args.json_output:
            print_pose_result(r)

    if args.json_output:
        output = {
            "poses": [asdict(r) for r in results],
            "flexibility_score": round(sum(1 for r in results if r.status == "FLOWING") / len(results) * 100) if results else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(results)

    # Write report (unless --no-report or single pose)
    if not args.no_report and not args.pose:
        report_path = SOURCE_ROOT / "docs" / "self-architecture" / "yoga-report.md"
        try:
            generate_report(results, report_path)
            if not args.json_output:
                print(DIM(f"  Report: {report_path}"))
        except Exception as e:
            if not args.json_output:
                print(YELLOW(f"  [WARN] Could not write report: {e}"))

    # Exit code: 0 = all FLOWING, 1 = any issues
    all_flowing = all(r.status == "FLOWING" for r in results)
    sys.exit(0 if all_flowing else 1)


if __name__ == "__main__":
    main()
