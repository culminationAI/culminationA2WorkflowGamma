#!/usr/bin/env python3
"""
ttl_check.py — TTL (Time-To-Live) checker for active builds in the build registry.

Increments sessions_since_last_use for each active build and reports expiry status.
Called from Session Start (CLAUDE.md step 6).

Usage:
    python3 memory/scripts/ttl_check.py              # increment + check + warn
    python3 memory/scripts/ttl_check.py --check      # read-only: report without incrementing
    python3 memory/scripts/ttl_check.py --json        # machine-readable JSON output
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Source root: 3 levels up from memory/scripts/ttl_check.py
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = SOURCE_ROOT / "docs" / "self-architecture" / "build-registry.json"

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
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

# ---------------------------------------------------------------------------
# TTL field helpers
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ) into a date."""
    if not value:
        return None
    try:
        # Handle full ISO datetime format
        if "T" in value:
            return datetime.fromisoformat(value.rstrip("Z")).date()
        return date.fromisoformat(value)
    except (ValueError, AttributeError):
        return None


def classify_status(
    sessions_used: int,
    ttl_sessions: int,
    days_elapsed: int,
    ttl_days: int,
) -> tuple[str, str]:
    """
    Return (status, reason_hint) where status is one of:
        "expired"  — hard limit exceeded on sessions or days
        "warning"  — within 2 sessions or 2 days of limit
        "ok"       — plenty of TTL remaining
    """
    sessions_remaining = ttl_sessions - sessions_used
    days_remaining = ttl_days - days_elapsed

    if sessions_used > ttl_sessions or days_elapsed > ttl_days:
        if sessions_used > ttl_sessions:
            return "expired", f"{sessions_used}/{ttl_sessions} sessions"
        return "expired", f"{days_elapsed}/{ttl_days} days"

    if sessions_remaining <= 2:
        return "warning", f"{sessions_remaining} session{'s' if sessions_remaining != 1 else ''} remaining"
    if days_remaining <= 2:
        return "warning", f"{days_remaining} day{'s' if days_remaining != 1 else ''} remaining"

    return "ok", ""

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def process_registry(read_only: bool) -> tuple[list[dict], bool]:
    """
    Read the build registry, optionally mutate active builds, and return
    (build_results, incremented).

    build_results: list of dicts with per-build TTL data
    incremented: True if sessions_since_last_use was incremented
    """
    if not REGISTRY_PATH.exists():
        print(f"[ERROR] Registry not found: {REGISTRY_PATH}", file=sys.stderr)
        sys.exit(1)

    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON in registry: {exc}", file=sys.stderr)
        sys.exit(1)

    builds = registry.get("builds", [])
    today = date.today()
    today_str = today.isoformat()
    incremented = False
    results: list[dict] = []

    for build in builds:
        build_id = build.get("id", "<unknown>")
        state = build.get("state")

        # Only process active builds; everything else is skipped gracefully
        if state != "active":
            results.append({"id": build_id, "skipped": True, "state": state or "n/a"})
            continue

        # Validate required TTL fields; skip if missing
        ttl_sessions = build.get("ttl_sessions")
        ttl_days = build.get("ttl_days")
        activated_at_raw = build.get("activated_at")

        if ttl_sessions is None or ttl_days is None or not activated_at_raw:
            results.append({
                "id": build_id,
                "skipped": True,
                "state": "active",
                "reason": "missing ttl fields",
            })
            continue

        activated_at = parse_date(activated_at_raw)
        if activated_at is None:
            results.append({
                "id": build_id,
                "skipped": True,
                "state": "active",
                "reason": f"unparseable activated_at: {activated_at_raw!r}",
            })
            continue

        # Increment sessions counter if not read-only
        sessions_used = build.get("sessions_since_last_use", 0)
        if not read_only:
            sessions_used += 1
            build["sessions_since_last_use"] = sessions_used
            build["last_used"] = today_str
            incremented = True

        days_elapsed = (today - activated_at).days
        status, hint = classify_status(sessions_used, ttl_sessions, days_elapsed, ttl_days)

        results.append({
            "id": build_id,
            "skipped": False,
            "state": "active",
            "sessions_used": sessions_used,
            "sessions_ttl": ttl_sessions,
            "days_elapsed": days_elapsed,
            "days_ttl": ttl_days,
            "status": status,
            "hint": hint,
        })

    # Atomic write if we mutated anything
    if not read_only and incremented:
        _atomic_write(registry)

    return results, incremented


def _atomic_write(data: dict) -> None:
    """Write registry data atomically using a temp file + os.replace."""
    registry_dir = REGISTRY_PATH.parent
    registry_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=registry_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, REGISTRY_PATH)
    except Exception:
        # Best-effort cleanup of temp file on error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render_human(results: list[dict], today_str: str) -> int:
    """
    Print the human-readable TTL report. Returns exit code:
      0 = all ok, 1 = any warnings, 2 = any expired
    """
    active = [r for r in results if not r.get("skipped")]
    total = len(results)

    print(BOLD(f"TTL Check") + DIM(f" — {today_str} — {total} build{'s' if total != 1 else ''} scanned"))

    exit_code = 0

    for r in results:
        build_id = r["id"]

        if r.get("skipped"):
            state_label = r.get("state", "n/a")
            reason = r.get("reason", "")
            detail = f" ({reason})" if reason else ""
            print(DIM(f"  {build_id}: {state_label} (skipped{detail})"))
            continue

        sessions_used = r["sessions_used"]
        sessions_ttl  = r["sessions_ttl"]
        days_elapsed  = r["days_elapsed"]
        days_ttl      = r["days_ttl"]
        status        = r["status"]
        hint          = r["hint"]

        sessions_part = f"{sessions_used}/{sessions_ttl} sessions"
        days_part     = f"{days_elapsed}/{days_ttl} days"
        progress      = f"{sessions_part}, {days_part}"

        if status == "ok":
            line = f"  {build_id}: {progress} {GREEN('— ok')}"
            print(GREEN("  [ok]") + f"  {build_id}: {progress}")

        elif status == "warning":
            print(YELLOW("  [!]") + f"   {build_id}: {progress} {YELLOW('— WARNING')} ({hint})")
            exit_code = max(exit_code, 1)

        else:  # expired
            print(RED("  [x]") + f"   {build_id}: {progress} {RED('— EXPIRED')} ({hint}). Suggest deactivation.")
            exit_code = max(exit_code, 2)

    return exit_code


def render_json(results: list[dict], incremented: bool) -> int:
    """Print machine-readable JSON and return exit code."""
    builds_out = []
    summary = {"ok": 0, "warning": 0, "expired": 0, "skipped": 0}

    for r in results:
        if r.get("skipped"):
            summary["skipped"] += 1
            builds_out.append({
                "id": r["id"],
                "state": r.get("state", "n/a"),
                "skipped": True,
                "reason": r.get("reason", ""),
            })
            continue

        status = r["status"]
        summary[status] = summary.get(status, 0) + 1

        builds_out.append({
            "id": r["id"],
            "sessions_used": r["sessions_used"],
            "sessions_ttl": r["sessions_ttl"],
            "days_elapsed": r["days_elapsed"],
            "days_ttl": r["days_ttl"],
            "status": status,
        })

    output = {
        "builds": builds_out,
        "summary": summary,
        "incremented": incremented,
    }
    print(json.dumps(output, indent=2))

    # Exit code mirrors human mode
    if summary.get("expired", 0) > 0:
        return 2
    if summary.get("warning", 0) > 0:
        return 1
    return 0

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description="TTL checker for active builds in the build registry.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/ttl_check.py              # increment + check + warn\n"
            "  python3 memory/scripts/ttl_check.py --check      # read-only report\n"
            "  python3 memory/scripts/ttl_check.py --json       # machine-readable JSON\n"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only mode: report status without incrementing sessions_since_last_use.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of terminal display.",
    )
    args = parser.parse_args()

    if args.json_output:
        USE_COLOR = False

    read_only = args.check
    results, incremented = process_registry(read_only=read_only)

    today_str = date.today().isoformat()

    if args.json_output:
        exit_code = render_json(results, incremented)
    else:
        exit_code = render_human(results, today_str)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
