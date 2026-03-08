#!/usr/bin/env python3
"""Generate a compact identity capsule for agents working in external projects.

The capsule preserves agent identity (name, protocols, capabilities, memory rules)
when running `claude -p` with `cwd` set to an external project directory.

Usage:
    python3 memory/scripts/identity_capsule.py --workspace ~/Desktop/_follower_ --agent falkvelt --project sibyl
    python3 memory/scripts/identity_capsule.py --workspace ~/Desktop/_follower_ --agent falkvelt --project sibyl --role "memory isolation audit"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def load_protocol_index(workspace: Path) -> str:
    """Extract the Protocols table from CLAUDE.md, compressed to name+trigger only."""
    claude_md = workspace / "CLAUDE.md"
    if not claude_md.exists():
        return "(protocol index unavailable)"

    text = claude_md.read_text(encoding="utf-8")

    # Find the ## Protocols section
    match = re.search(r"^## Protocols\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return "(protocol index unavailable)"

    section = match.group(0)

    # Extract table rows: | Name | Trigger | File |
    # We want rows that have exactly 3 pipe-delimited columns (skipping header/separator)
    lines = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        # Skip header row and separator row
        if parts[0].lower() in ("protocol", "---", "-------"):
            continue
        if set(parts[0].replace("-", "")) == set():
            continue
        # parts[0] = protocol name, parts[1] = trigger
        name = parts[0]
        trigger = parts[1] if len(parts) > 1 else ""
        # Skip separator lines
        if re.match(r"^[-|: ]+$", name):
            continue
        lines.append(f"{name} | {trigger}")

    if not lines:
        return "(protocol index unavailable)"

    header = "Protocol | Trigger"
    return header + "\n" + "\n".join(lines)


def load_capability_summary(workspace: Path) -> str:
    """Extract a compact summary from capability-map.md (overview section or first 500 chars)."""
    cap_map = workspace / "docs" / "self-architecture" / "capability-map.md"
    if not cap_map.exists():
        return "(capability map unavailable)"

    text = cap_map.read_text(encoding="utf-8")

    # Try to extract the header block (version, coordinator, role lines)
    header_lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or line.startswith("**"):
            header_lines.append(line)
        if len(header_lines) >= 6:
            break

    # Also grab the agents table (## 1. Agents section)
    agents_match = re.search(
        r"^## 1\. Agents\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    agents_section = ""
    if agents_match:
        # Keep first 400 chars of agents section
        agents_section = agents_match.group(0)[:400].strip()

    summary_parts = []
    if header_lines:
        summary_parts.append("\n".join(header_lines))
    if agents_section:
        summary_parts.append(agents_section)

    result = "\n\n".join(summary_parts)
    # Hard cap at 600 chars to stay compact
    if len(result) > 600:
        result = result[:600] + "..."

    return result if result else text[:500]


def load_agent_identity(workspace: Path) -> str:
    """Extract agent name and key traits from user-identity.md. Returns empty if not found."""
    identity_file = workspace / "user-identity.md"
    if not identity_file.exists():
        return ""

    text = identity_file.read_text(encoding="utf-8")

    # Extract Coordinator section
    coord_match = re.search(
        r"^## Coordinator\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not coord_match:
        return text[:300]

    return coord_match.group(0).strip()


def generate_capsule(
    workspace: Path,
    agent_name: str,
    project_context: str,
    role: str = "",
    shared_path: str = "",
) -> str:
    """Assemble the full identity capsule string."""
    capability_summary = load_capability_summary(workspace)
    protocol_index = load_protocol_index(workspace)
    agent_identity = load_agent_identity(workspace)

    # Build identity block — include identity traits if available
    identity_block = f"You are {agent_name}, a coordinator agent from workspace {workspace.name}."
    if agent_identity:
        # Append style/role if parseable
        style_match = re.search(r"\*\*Style:\*\*\s*(.+)", agent_identity)
        role_match = re.search(r"\*\*Role:\*\*\s*(.+)", agent_identity)
        traits = []
        if style_match:
            traits.append(f"style: {style_match.group(1).strip()}")
        if role_match:
            traits.append(f"role: {role_match.group(1).strip()}")
        if traits:
            identity_block += f" ({', '.join(traits)})"

    role_line = f"Your role: {role}" if role else ""
    shared_line = f"Shared workspace: {shared_path}" if shared_path else ""
    context_extras = "\n".join(line for line in [role_line, shared_line] if line)

    capsule = f"""\
## Your Identity
{identity_block}
Your full protocols and architecture live at {workspace}.
You are currently working on an EXTERNAL PROJECT.
File operations target THIS project's codebase.
Your identity and memory belong to your home workspace.

## Memory Rules (CRITICAL)
- When writing memories about THIS PROJECT:
  python3 {workspace}/memory/scripts/memory_write.py '[{{"text": "...", "metadata": {{"_project_concern": "{project_context}"}}, "agent_id": "{agent_name}"}}]'
- When searching THIS PROJECT's memories:
  python3 {workspace}/memory/scripts/memory_search.py "query" --project-concern {project_context}
- When searching YOUR OWN memories:
  python3 {workspace}/memory/scripts/memory_search.py "query"

## Chat Rules
- Be concise — this is a conversation, not a monologue
- When you discover something important, wrap it in [FACT]...[/FACT]
- Respond to [MODERATOR] messages immediately
- Stay focused on the current topic

## Your Capabilities
{capability_summary}

## Your Protocols (reference only)
{protocol_index}

## Current Project Context
Project: {project_context}
{context_extras}""".rstrip()

    return capsule


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a compact identity capsule for external project sessions."
    )
    parser.add_argument("--workspace", required=True, help="Path to agent's home workspace")
    parser.add_argument("--agent", required=True, help="Agent name (e.g., falkvelt)")
    parser.add_argument("--project", required=True, help="Project context name (e.g., sibyl)")
    parser.add_argument("--role", default="", help="Specific role in this project")
    parser.add_argument("--shared", default="", help="Shared workspace path")
    parser.add_argument("--output", default="", help="Write capsule to file instead of stdout")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.exists():
        print(f"[ERROR] Workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    capsule = generate_capsule(
        workspace=workspace,
        agent_name=args.agent,
        project_context=args.project,
        role=args.role,
        shared_path=args.shared,
    )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(capsule, encoding="utf-8")
        # Report token estimate to stderr so stdout stays clean for piping
        token_estimate = len(capsule) // 4
        print(f"[OK] Capsule written to {out_path} (~{token_estimate} tokens)", file=sys.stderr)
    else:
        print(capsule)


if __name__ == "__main__":
    main()
