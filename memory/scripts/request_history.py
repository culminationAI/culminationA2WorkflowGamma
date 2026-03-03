#!/usr/bin/env python3
"""
request_history.py — Atomically append entries to request-history.json.

Called by the coordinator after every T3+ subagent dispatch to track request
history. Automatically archives oldest 50 entries when total reaches 100.

Usage:
    python3 memory/scripts/request_history.py \\
        --tier T3 --verb write --domain infrastructure --agents engineer \\
        --summary "Created ttl_check.py for build TTL management" \\
        --outcome success

    python3 memory/scripts/request_history.py --stats
    python3 memory/scripts/request_history.py --stats --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Source root: 3 levels up from memory/scripts/request_history.py
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = SOURCE_ROOT / "docs" / "self-architecture" / "request-history.json"
ARCHIVE_PATH = SOURCE_ROOT / "docs" / "self-architecture" / "request-history-archive.json"

ARCHIVE_TRIGGER = 100   # archive when entries reach this count
ARCHIVE_KEEP    = 50    # keep newest N after archiving (move oldest N = TRIGGER - KEEP)

# ---------------------------------------------------------------------------
# ANSI colors (disabled when not a TTY or --json)
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
# Phase hint inference
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[str, str] = {
    "write":      "IMPLEMENTATION",
    "create":     "IMPLEMENTATION",
    "implement":  "IMPLEMENTATION",
    "build":      "IMPLEMENTATION",
    "code":       "IMPLEMENTATION",
    "design":     "DESIGN",
    "architect":  "DESIGN",
    "plan":       "DESIGN",
    "test":       "TESTING",
    "verify":     "TESTING",
    "benchmark":  "TESTING",
    "validate":   "TESTING",
    "deploy":     "DEPLOYMENT",
    "release":    "DEPLOYMENT",
    "publish":    "DEPLOYMENT",
    "push":       "DEPLOYMENT",
}


def infer_phase(verb: str) -> str | None:
    """Return DESIGN|IMPLEMENTATION|TESTING|DEPLOYMENT or None."""
    return _PHASE_MAP.get(verb.lower().strip())

# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_id(entries: list[dict], now: datetime) -> str:
    """
    Format: req-{YYYY-MM-DD}-{HHmm}-{NNN}
    NNN is 1-based count of existing entries sharing the same prefix.
    """
    prefix = f"req-{now.strftime('%Y-%m-%d-%H%M')}"
    existing = sum(1 for e in entries if e.get("id", "").startswith(prefix))
    return f"{prefix}-{existing + 1:03d}"

# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    """Load JSON from path, returning {"entries": []} if missing or empty."""
    if not path.exists():
        return {"entries": []}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {"entries": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _atomic_write(path: Path, data: dict) -> None:
    """Write data to path atomically via tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

# ---------------------------------------------------------------------------
# Archiving
# ---------------------------------------------------------------------------

def maybe_archive(entries: list[dict]) -> list[dict]:
    """
    If len(entries) >= ARCHIVE_TRIGGER after append, move oldest
    (ARCHIVE_TRIGGER - ARCHIVE_KEEP) entries to archive file.
    Returns the trimmed active list.
    """
    if len(entries) < ARCHIVE_TRIGGER:
        return entries

    split = len(entries) - ARCHIVE_KEEP  # number of entries to archive
    to_archive = entries[:split]
    to_keep    = entries[split:]

    archive_data = _load_json(ARCHIVE_PATH)
    archive_data.setdefault("entries", [])
    archive_data["entries"].extend(to_archive)
    _atomic_write(ARCHIVE_PATH, archive_data)

    print(
        DIM(f"  Archived {len(to_archive)} entries → {ARCHIVE_PATH.name}"),
        file=sys.stderr,
    )
    return to_keep

# ---------------------------------------------------------------------------
# Append logic
# ---------------------------------------------------------------------------

def append_entry(args: argparse.Namespace) -> int:
    """Build and append one entry. Returns exit code."""
    now = datetime.now(tz=timezone.utc)

    history = _load_json(HISTORY_PATH)
    history.setdefault("entries", [])
    entries: list[dict] = history["entries"]

    # Truncate summary to 100 chars
    summary = (args.summary or "")[:100]

    # Parse agents list
    agents: list[str] = [a.strip() for a in args.agents.split(",") if a.strip()]

    entry: dict = {
        "id":             generate_id(entries, now),
        "timestamp":      now.isoformat(),
        "tier":           args.tier,
        "verb":           args.verb,
        "domain":         args.domain,
        "subagents_used": agents,
        "task_summary":   summary,
        "gap_detected":   args.gap_detected,
        "gap_severity":   args.gap_severity,
        "build_used":     args.build_used,
        "outcome":        args.outcome,
        "phase_hint":     infer_phase(args.verb),
    }

    entries.append(entry)

    # Archive if needed, then persist
    entries = maybe_archive(entries)
    history["entries"] = entries
    _atomic_write(HISTORY_PATH, history)

    print(GREEN("  [ok]") + f"  Appended {BOLD(entry['id'])} — {entry['tier']} {entry['verb']} [{entry['domain']}]")
    return 0

# ---------------------------------------------------------------------------
# Stats logic
# ---------------------------------------------------------------------------

def _relative_time(iso: str) -> str:
    """Return a human-readable 'Xh ago' / 'Xm ago' / 'just now' string."""
    try:
        ts = datetime.fromisoformat(iso)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(tz=timezone.utc) - ts
        total_secs = int(delta.total_seconds())
        if total_secs < 60:
            return "just now"
        if total_secs < 3600:
            return f"{total_secs // 60}m ago"
        if total_secs < 86400:
            return f"{total_secs // 3600}h ago"
        return f"{total_secs // 86400}d ago"
    except (ValueError, TypeError):
        return "unknown"


def render_stats_human(entries: list[dict]) -> int:
    total = len(entries)
    if total == 0:
        print(BOLD("Request History:") + " 0 entries")
        return 0

    tier_counts    = Counter(e.get("tier", "?")     for e in entries)
    domain_counts  = Counter(e.get("domain", "?")   for e in entries)
    outcome_counts = Counter(e.get("outcome", "?")  for e in entries)

    last = entries[-1]
    last_id  = last.get("id", "?")
    last_ts  = last.get("timestamp", "")
    last_rel = _relative_time(last_ts)

    # Tier summary string: T3: 8 | T4: 5 | T5: 2
    tier_str = " | ".join(
        f"{k}: {v}" for k, v in sorted(tier_counts.items())
    )

    # Domain summary: top 5 by count, sorted desc
    domain_str = ", ".join(
        f"{k}({v})" for k, v in domain_counts.most_common(5)
    )

    # Outcome summary
    outcome_str = ", ".join(
        f"{k}({v})" for k, v in outcome_counts.most_common()
    )

    print(BOLD("Request History:") + f" {total} entries")
    print(f"  {DIM('Tiers:')}    {tier_str}")
    print(f"  {DIM('Domains:')}  {domain_str}")
    print(f"  {DIM('Outcomes:')} {outcome_str}")
    print(f"  {DIM('Last:')}     {last_id} ({last_rel})")

    return 0


def render_stats_json(entries: list[dict]) -> int:
    total = len(entries)
    tier_counts    = dict(Counter(e.get("tier", "?")    for e in entries))
    outcome_counts = dict(Counter(e.get("outcome", "?") for e in entries))
    domain_counts  = dict(Counter(e.get("domain", "?")  for e in entries))

    last_entry_id = entries[-1].get("id") if entries else None

    output = {
        "total":         total,
        "by_tier":       tier_counts,
        "by_outcome":    outcome_counts,
        "domains":       domain_counts,
        "last_entry_id": last_entry_id,
    }
    print(json.dumps(output, indent=2))
    return 0


def show_stats(json_output: bool) -> int:
    history = _load_json(HISTORY_PATH)
    entries: list[dict] = history.get("entries", [])

    if json_output:
        return render_stats_json(entries)
    return render_stats_human(entries)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description="Atomically append entries to request-history.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/request_history.py \\\n"
            "      --tier T3 --verb write --domain infrastructure \\\n"
            "      --agents engineer --summary 'Created ttl_check.py' \\\n"
            "      --outcome success\n"
            "\n"
            "  python3 memory/scripts/request_history.py \\\n"
            "      --tier T4 --verb design --domain evolution \\\n"
            "      --agents 'pathfinder,engineer' \\\n"
            "      --summary 'Designed retreat protocol' \\\n"
            "      --outcome success --gap-detected --gap-severity medium\n"
            "\n"
            "  python3 memory/scripts/request_history.py --stats\n"
            "  python3 memory/scripts/request_history.py --stats --json\n"
        ),
    )

    # --- stats mode ---
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Read-only: print summary statistics about request history.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="With --stats: output as JSON instead of human-readable text.",
    )

    # --- required append flags ---
    parser.add_argument(
        "--tier",
        choices=["T3", "T4", "T5"],
        help="Request tier (T3|T4|T5).",
    )
    parser.add_argument(
        "--verb",
        help="Action verb (e.g. write, design, deploy).",
    )
    parser.add_argument(
        "--domain",
        help="Domain label (e.g. infrastructure, evolution).",
    )
    parser.add_argument(
        "--agents",
        help="Comma-separated list of subagents used (e.g. 'engineer' or 'pathfinder,engineer').",
    )
    parser.add_argument(
        "--summary",
        help="Task summary (truncated to 100 chars).",
    )
    parser.add_argument(
        "--outcome",
        choices=["success", "partial", "failed"],
        help="Outcome of the request.",
    )

    # --- optional append flags ---
    parser.add_argument(
        "--gap-detected",
        action="store_true",
        default=False,
        help="Flag: a capability gap was detected during this request.",
    )
    parser.add_argument(
        "--gap-severity",
        choices=["low", "medium", "high", "critical"],
        default=None,
        help="Severity of the detected gap (requires --gap-detected).",
    )
    parser.add_argument(
        "--build-used",
        default=None,
        metavar="BUILD_ID",
        help="ID of the build that was active for this request.",
    )

    args = parser.parse_args()

    # Disable color for JSON stats output
    if args.json_output:
        USE_COLOR = False

    # --- stats mode ---
    if args.stats:
        sys.exit(show_stats(args.json_output))

    # --- append mode: validate required fields ---
    required = {"tier": args.tier, "verb": args.verb, "domain": args.domain,
                "agents": args.agents, "summary": args.summary, "outcome": args.outcome}
    missing = [k for k, v in required.items() if not v]
    if missing:
        parser.error(
            f"The following flags are required for append mode: "
            + ", ".join(f"--{m}" for m in missing)
        )

    sys.exit(append_entry(args))


if __name__ == "__main__":
    main()
