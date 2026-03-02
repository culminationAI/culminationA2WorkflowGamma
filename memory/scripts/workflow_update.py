#!/usr/bin/env python3
"""
workflow_update.py — Checks and applies workflow updates from GitHub.

Usage:
    python3 memory/scripts/workflow_update.py --check
    python3 memory/scripts/workflow_update.py --apply
    python3 memory/scripts/workflow_update.py --check --workspace /path/to/project
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = "culminationAI/culminationWorkFlow"
GITHUB_API = "https://api.github.com"
REPO_CLONE_URL = "https://github.com/culminationAI/culminationWorkFlow.git"

# Files that are NEVER overwritten during update
PROTECTED_FILES = {
    "protocols/core/build-up.md",
    "protocols/quality/security-logging.md",
    "memory/scripts/research_validate.py",
    "memory/scripts/memory_write.py",
}

# Path prefixes that are entirely skipped (user-customized or sensitive)
SKIP_PATHS = {
    "user-identity.md",
    "secrets/",
    "protocols/project/",
    ".git/",
    "research/",
    "logs/",
    "bot/",
}

# Files that receive special merge treatment (IMMUTABLE blocks preserved)
MERGE_FILES = {"CLAUDE.md"}


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_local_version(workspace: Path) -> Optional[str]:
    """
    Read CLAUDE.md from workspace root and extract the embedded workflow version.
    Looks for: <!-- WORKFLOW_VERSION: X.X -->
    Returns version string (e.g. "1.0") or None if marker not found.
    """
    claude_md = workspace / "CLAUDE.md"
    if not claude_md.exists():
        return None

    content = claude_md.read_text(encoding="utf-8")
    match = re.search(r"<!--\s*WORKFLOW_VERSION:\s*(\S+?)\s*-->", content)
    if match:
        return match.group(1)
    return None


def fetch_remote_version() -> Optional[str]:
    """
    Fetch the latest release tag from GitHub API.
    Returns version string (e.g. "0.2") or None on any error.
    Never raises — network failures are non-fatal at check time.
    """
    url = f"{GITHUB_API}/repos/{REPO}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "workflow-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        # Strip leading "v" so "v0.1" becomes "0.1"
        return tag.lstrip("v") if tag else None
    except urllib.error.URLError:
        return None
    except Exception:  # noqa: BLE001
        return None


def compare_versions(local: str, remote: str) -> int:
    """
    Compare two version strings split by ".".
    Returns: -1 if local < remote, 0 if equal, 1 if local > remote.
    Falls back to string comparison for non-numeric segments.
    """

    def _parts(v: str):
        parts = []
        for seg in v.split("."):
            try:
                parts.append(int(seg))
            except ValueError:
                parts.append(seg)
        return parts

    lparts = _parts(local)
    rparts = _parts(remote)

    # Pad shorter list with zeros (or empty strings)
    max_len = max(len(lparts), len(rparts))
    while len(lparts) < max_len:
        lparts.append(0)
    while len(rparts) < max_len:
        rparts.append(0)

    for lp, rp in zip(lparts, rparts):
        if lp < rp:
            return -1
        if lp > rp:
            return 1
    return 0


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

def classify_file(rel_path: str) -> str:
    """
    Classify how a file from the remote repo should be handled.

    Returns one of:
        "skip"      — leave the local file untouched
        "overwrite" — replace local file with remote version
        "merge"     — special merge logic (IMMUTABLE blocks preserved)
    """
    # Normalize to forward slashes for consistent matching
    normalized = rel_path.replace("\\", "/")

    if normalized in PROTECTED_FILES:
        return "skip"

    for prefix in SKIP_PATHS:
        if normalized == prefix or normalized.startswith(prefix):
            return "skip"

    if normalized in MERGE_FILES:
        return "merge"

    return "overwrite"


# ---------------------------------------------------------------------------
# CLAUDE.md merge
# ---------------------------------------------------------------------------

def merge_claude_md(local_path: Path, remote_path: Path) -> str:
    """
    Merge remote CLAUDE.md while preserving IMMUTABLE blocks from local.

    IMMUTABLE block syntax:
        <!-- IMMUTABLE -->
        ## Some Heading
        ...content...
        <!-- /IMMUTABLE -->

    Strategy:
    1. Extract all IMMUTABLE blocks from local, keyed by the heading
       immediately following the opening tag.
    2. In remote content, replace each IMMUTABLE block with the matching
       local block (matched by heading). If no match exists in local,
       the remote block is kept as-is.
    3. Preserve the absence of <!-- _WORKFLOW_NEEDS_INIT --> if it was
       already removed from local (don't re-introduce the init marker).
    """
    local_content = local_path.read_text(encoding="utf-8")
    remote_content = remote_path.read_text(encoding="utf-8")

    # --- Extract local IMMUTABLE blocks keyed by heading ---
    immutable_pattern = re.compile(
        r"(<!-- IMMUTABLE -->)(.*?)(<!-- /IMMUTABLE -->)",
        re.DOTALL,
    )

    local_blocks: dict[str, str] = {}
    for match in immutable_pattern.finditer(local_content):
        block_body = match.group(2)
        # The heading is the first non-empty line inside the block
        heading_match = re.search(r"^\s*(#{1,6}\s+.+)$", block_body, re.MULTILINE)
        if heading_match:
            key = heading_match.group(1).strip()
            # Store the full block (opening tag + body + closing tag)
            local_blocks[key] = match.group(0)

    # --- Replace IMMUTABLE blocks in remote with matching local blocks ---
    def replace_block(m: re.Match) -> str:
        block_body = m.group(2)
        heading_match = re.search(r"^\s*(#{1,6}\s+.+)$", block_body, re.MULTILINE)
        if heading_match:
            key = heading_match.group(1).strip()
            if key in local_blocks:
                return local_blocks[key]
        # No matching local block — keep remote version unchanged
        return m.group(0)

    merged = immutable_pattern.sub(replace_block, remote_content)

    # --- _WORKFLOW_NEEDS_INIT handling ---
    # If local already had the marker removed, don't re-introduce it
    init_marker = "<!-- _WORKFLOW_NEEDS_INIT -->"
    if init_marker not in local_content and init_marker in merged:
        merged = merged.replace(init_marker, "")

    return merged


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_current(workspace: Path, version: str) -> Path:
    """
    Back up the current workflow state before applying an update.
    Copies CLAUDE.md, protocols/, memory/scripts/, .claude/agents/ into
    .claude/backups/pre-update-{version}/.
    Returns the backup directory path.
    """
    backup_dir = workspace / ".claude" / "backups" / f"pre-update-{version}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    items_to_backup = [
        workspace / "CLAUDE.md",
        workspace / "protocols",
        workspace / "memory" / "scripts",
        workspace / ".claude" / "agents",
    ]

    for item in items_to_backup:
        if not item.exists():
            continue
        dest = backup_dir / item.relative_to(workspace)
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    return backup_dir


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def check_update(workspace: Path) -> None:
    """
    Read-only check for available updates.
    Prints a message only when an update is available or an error occurs.
    Completely silent when already up to date.
    """
    try:
        local_version = parse_local_version(workspace)
        remote_version = fetch_remote_version()

        if remote_version is None:
            print("[WARN] Could not check for updates (network error). Skipping.")
            return

        if local_version is None:
            # No version marker — cannot compare, stay silent
            return

        cmp = compare_versions(local_version, remote_version)
        if cmp < 0:
            print(f"[UPDATE] Workflow update available: {local_version} → {remote_version}")
            print(f"  Run: python3 memory/scripts/workflow_update.py --apply")
            print(f"  Release: https://github.com/{REPO}/releases/latest")
        # Equal or local > remote → silent

    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Could not check for updates: {exc}. Skipping.")


def apply_update(workspace: Path) -> None:
    """
    Clone the latest workflow repo and apply changes to the workspace.

    Steps:
    1. Fetch remote version, compare with local.
    2. If already up to date, exit.
    3. Clone repo to tempdir (shallow, depth=1).
    4. Backup current workspace state.
    5. Walk all files in the clone, classify and apply each.
    6. Update version marker in CLAUDE.md.
    7. Print summary and clean up.
    """
    local_version = parse_local_version(workspace)
    remote_version = fetch_remote_version()

    if remote_version is None:
        print("[ERROR] Could not fetch remote version. Cannot apply update.", file=sys.stderr)
        sys.exit(1)

    if local_version is not None:
        cmp = compare_versions(local_version, remote_version)
        if cmp >= 0:
            print("Already up to date.")
            return

    from_ver = local_version or "unknown"
    print(f"[UPDATE] Updating workflow: {from_ver} → {remote_version}")

    # Backup current state before touching anything
    backup_path = backup_current(workspace, from_ver)
    print(f"[BACKUP] Current state saved to {backup_path.relative_to(workspace)}/")

    # Clone to a temporary directory
    tmpdir = Path(tempfile.mkdtemp(prefix="workflow_update_"))
    try:
        _clone_repo(tmpdir)
        _apply_files(workspace, tmpdir)
        _update_version_marker(workspace, remote_version)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _clone_repo(tmpdir: Path) -> None:
    """Clone the workflow repo (shallow, depth 1) into tmpdir."""
    clone_target = tmpdir / "repo"
    result = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_CLONE_URL, str(clone_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[ERROR] git clone failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def _apply_files(workspace: Path, tmpdir: Path) -> None:
    """Walk cloned repo files, classify each, and apply the appropriate action."""
    repo_root = tmpdir / "repo"

    updated = 0
    merged = 0
    skipped = 0

    for src_path in repo_root.rglob("*"):
        if src_path.is_dir():
            continue

        rel_path = src_path.relative_to(repo_root)
        rel_str = str(rel_path).replace("\\", "/")

        action = classify_file(rel_str)
        dest_path = workspace / rel_path

        if action == "skip":
            reason = "protected" if rel_str in PROTECTED_FILES else "user data"
            print(f"[SKIPPED] {rel_str} ({reason})")
            skipped += 1

        elif action == "merge":
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.exists():
                merged_content = merge_claude_md(dest_path, src_path)
            else:
                # No local file to merge from — use remote as-is
                merged_content = src_path.read_text(encoding="utf-8")
            dest_path.write_text(merged_content, encoding="utf-8")
            print(f"[MERGED]  {rel_str} (immutable blocks preserved)")
            merged += 1

        else:  # overwrite
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)
            print(f"[UPDATED] {rel_str}")
            updated += 1

    print()
    print(f"Summary: {updated} updated, {merged} merged, {skipped} skipped")


def _update_version_marker(workspace: Path, new_version: str) -> None:
    """
    Replace <!-- WORKFLOW_VERSION: X.X --> in CLAUDE.md with the new version.
    Prints the final transition line.
    """
    claude_md = workspace / "CLAUDE.md"
    if not claude_md.exists():
        return

    content = claude_md.read_text(encoding="utf-8")

    old_version_match = re.search(r"<!--\s*WORKFLOW_VERSION:\s*(\S+?)\s*-->", content)
    old_version = old_version_match.group(1) if old_version_match else "unknown"

    updated = re.sub(
        r"<!--\s*WORKFLOW_VERSION:\s*\S+?\s*-->",
        f"<!-- WORKFLOW_VERSION: {new_version} -->",
        content,
    )

    if updated == content and old_version == "unknown":
        # Marker wasn't present — append it at the end
        updated = content.rstrip() + f"\n\n<!-- WORKFLOW_VERSION: {new_version} -->\n"

    claude_md.write_text(updated, encoding="utf-8")
    print(f"Workflow version: {old_version} → {new_version}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Workflow auto-updater")
    parser.add_argument("--check", action="store_true", help="Check for updates (read-only)")
    parser.add_argument("--apply", action="store_true", help="Apply available update")
    parser.add_argument("--workspace", "-w", default=".", help="Workspace root directory")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()

    if not (workspace / "CLAUDE.md").exists():
        print("Error: CLAUDE.md not found in workspace", file=sys.stderr)
        sys.exit(1)

    if args.apply:
        apply_update(workspace)
    elif args.check:
        check_update(workspace)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
