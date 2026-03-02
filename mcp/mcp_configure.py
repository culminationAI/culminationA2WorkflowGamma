#!/usr/bin/env python3
"""MCP server profile switcher.

Usage:
    python3 mcp/mcp_configure.py --profile core
    python3 mcp/mcp_configure.py --add github
    python3 mcp/mcp_configure.py --remove semgrep
    python3 mcp/mcp_configure.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROFILES: Dict[str, List[str]] = {
    "core":     ["context7", "filesystem"],
    "db":       ["context7", "filesystem", "neo4j", "qdrant"],
    "web":      ["context7", "filesystem", "playwright", "github"],
    "research": ["context7", "filesystem", "youtube-transcript"],
    "full":     ["context7", "filesystem", "neo4j", "qdrant",
                 "github", "playwright", "semgrep", "youtube-transcript"],
}

# Servers that cannot be removed (always-on core)
PROTECTED_SERVERS = {"context7", "filesystem"}

# Approximate token cost per server in the system prompt
TOKENS_PER_SERVER = 2_000

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

MCP_DIR = Path(__file__).resolve().parent          # .../workflow/mcp/
PROJECT_ROOT = MCP_DIR.parent                       # .../workflow/
FULL_JSON = MCP_DIR / "mcp-full.json"
ACTIVE_JSON = MCP_DIR / "mcp.json"
PLACEHOLDER = "__WORKSPACE_ROOT__"


def resolve_root() -> str:
    """Return the absolute project root path (parent of mcp/)."""
    return str(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------

def load_full() -> Dict:
    """Load the immutable source-of-truth mcp-full.json."""
    if not FULL_JSON.exists():
        sys.exit(f"ERROR: {FULL_JSON} not found. Cannot proceed.")
    with FULL_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_active() -> Dict:
    """Load current mcp.json. Returns empty mcpServers dict if missing."""
    if not ACTIVE_JSON.exists():
        return {"mcpServers": {}}
    with ACTIVE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_active(config: Dict) -> None:
    """Serialise config to mcp.json with __WORKSPACE_ROOT__ replaced."""
    root = resolve_root()
    # Serialise to string first, then do a global text replacement —
    # this handles the placeholder wherever it appears (command, args, env).
    raw = json.dumps(config, indent=2, ensure_ascii=False)
    raw = raw.replace(PLACEHOLDER, root)
    ACTIVE_JSON.write_text(raw, encoding="utf-8")


def filter_servers(full: Dict, server_names: List[str]) -> Dict:
    """Return a new config dict containing only the requested servers."""
    all_servers: Dict = full.get("mcpServers", {})
    selected: Dict = {}
    for name in server_names:
        if name not in all_servers:
            print(f"WARNING: server '{name}' not found in mcp-full.json — skipping.")
            continue
        selected[name] = all_servers[name]
    return {"mcpServers": selected}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_profile(profile_name: str) -> None:
    """Switch to a named profile."""
    if profile_name not in PROFILES:
        available = ", ".join(PROFILES.keys())
        sys.exit(f"ERROR: unknown profile '{profile_name}'. Available: {available}")

    full = load_full()
    server_list = PROFILES[profile_name]
    config = filter_servers(full, server_list)

    # Collect actually-included names (after skipping missing ones)
    included = list(config["mcpServers"].keys())
    count = len(included)
    tokens = count * TOKENS_PER_SERVER

    save_active(config)

    print(f"Switched to profile '{profile_name}': {count} servers (~{tokens:,} tokens/message)")
    print(f"  + {', '.join(included)}")
    print("Restart Claude Code for changes to take effect.")


def cmd_add(server_name: str) -> None:
    """Add a single server from mcp-full.json to current mcp.json."""
    full = load_full()
    all_servers: Dict = full.get("mcpServers", {})

    if server_name not in all_servers:
        sys.exit(f"ERROR: server '{server_name}' not found in mcp-full.json.")

    active = load_active()
    servers: Dict = active.setdefault("mcpServers", {})

    if server_name in servers:
        print(f"Server '{server_name}' is already active — nothing changed.")
        return

    servers[server_name] = all_servers[server_name]
    save_active(active)

    count = len(servers)
    tokens = count * TOKENS_PER_SERVER
    print(f"Added '{server_name}'. Active servers ({count}): {', '.join(servers.keys())} (~{tokens:,} tokens/message)")
    print("Restart Claude Code for changes to take effect.")


def cmd_remove(server_name: str) -> None:
    """Remove a server from current mcp.json."""
    if server_name in PROTECTED_SERVERS:
        sys.exit(f"ERROR: '{server_name}' is a core server and cannot be removed.")

    active = load_active()
    servers: Dict = active.get("mcpServers", {})

    if server_name not in servers:
        print(f"Server '{server_name}' is not in the active config — nothing changed.")
        return

    del servers[server_name]
    save_active(active)

    count = len(servers)
    tokens = count * TOKENS_PER_SERVER
    remaining = ", ".join(servers.keys()) if servers else "(none)"
    print(f"Removed '{server_name}'. Active servers ({count}): {remaining} (~{tokens:,} tokens/message)")
    print("Restart Claude Code for changes to take effect.")


def cmd_status() -> None:
    """Print current profile status."""
    full = load_full()
    all_server_names: List[str] = list(full.get("mcpServers", {}).keys())

    active = load_active()
    active_names: List[str] = list(active.get("mcpServers", {}).keys())
    inactive_names: List[str] = [n for n in all_server_names if n not in active_names]

    active_count = len(active_names)
    inactive_count = len(inactive_names)
    tokens = active_count * TOKENS_PER_SERVER

    # Try to match a profile
    matched_profile: Optional[str] = None
    active_set = set(active_names)
    for pname, pservers in PROFILES.items():
        if set(pservers) == active_set:
            matched_profile = pname
            break

    print("MCP Profile Status")
    print("==================")
    active_str = ", ".join(active_names) if active_names else "(none)"
    inactive_str = ", ".join(inactive_names) if inactive_names else "(none)"
    print(f"Active servers ({active_count}): {active_str}")
    print(f"Inactive servers ({inactive_count}): {inactive_str}")
    print(f"Token overhead: ~{tokens:,} tokens/message")
    print()
    if matched_profile:
        print(f"Profile match: {matched_profile}")
    else:
        print("Profile match: (custom)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp_configure.py",
        description="Switch MCP server profiles for Claude Code.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--profile",
        metavar="NAME",
        help=f"Switch to a named profile. Available: {', '.join(PROFILES.keys())}",
    )
    group.add_argument(
        "--add",
        metavar="SERVER",
        help="Add a single server to the current config.",
    )
    group.add_argument(
        "--remove",
        metavar="SERVER",
        help="Remove a server from the current config.",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Show current active/inactive servers and token overhead.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.profile:
        cmd_profile(args.profile)
    elif args.add:
        cmd_add(args.add)
    elif args.remove:
        cmd_remove(args.remove)
    elif args.status:
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
