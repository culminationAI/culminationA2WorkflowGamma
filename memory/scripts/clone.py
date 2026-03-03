#!/usr/bin/env python3
"""Clone the coordinator instance to a new repository or directory.

Creates a blank-but-self-aware copy: full evolved instance (protocols, agents,
memory scripts) but requires fresh initialization (onboarding).

Usage:
    python3 memory/scripts/clone.py owner/repo-name
    python3 memory/scripts/clone.py /path/to/local/dir
    python3 memory/scripts/clone.py target --dry-run
    python3 memory/scripts/clone.py /path/to/dir --init-git
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Source root detection
# ---------------------------------------------------------------------------

def get_source_root() -> Path:
    """Return the workspace root (3 levels up from memory/scripts/clone.py)."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Target type detection
# ---------------------------------------------------------------------------

def is_github_target(target: str) -> bool:
    """Return True if target looks like owner/repo (contains / but not a filesystem path)."""
    return "/" in target and not target.startswith("/") and not target.startswith(".")


# ---------------------------------------------------------------------------
# Instance manifest
# ---------------------------------------------------------------------------

def get_instance_manifest(source_root: Path) -> list[Path]:
    """Return list of relative Paths to include in the clone.

    Walks INCLUDE patterns, then filters out EXCLUDE patterns.
    All returned paths are relative to source_root.
    """

    # Patterns that must NEVER appear in the output, regardless of include rules
    EXCLUDE_EXACT: set[str] = {
        "user-identity.md",
        "secrets/.env",
        "mcp/mcp.json",
        "docs/self-architecture/meditation-log.md",
        "docs/self-architecture/gap-analysis-log.md",
        "docs/exploration-report.md",
        ".session_lock",
    }

    EXCLUDE_PREFIX: list[str] = [
        "infra/neo4j_data/",
        "infra/qdrant_storage/",
        "infra/ollama_models/",
        "protocols/project/",
        "docs/research/",
        "docs/specs/",
        "logs/",
        "evolve/",
        "research/",
    ]

    EXCLUDE_SUFFIX: list[str] = [
        ".pyc",
    ]

    EXCLUDE_PART: list[str] = [
        "__pycache__",
    ]

    # Path component names that exclude the file if any part matches exactly
    EXCLUDE_COMPONENT: set[str] = {".git"}

    def is_excluded(rel: Path) -> bool:
        rel_str = rel.as_posix()
        if rel_str in EXCLUDE_EXACT:
            return True
        for prefix in EXCLUDE_PREFIX:
            if rel_str.startswith(prefix):
                return True
        for suffix in EXCLUDE_SUFFIX:
            if rel_str.endswith(suffix):
                return True
        for part in EXCLUDE_PART:
            if part in rel_str:
                return True
        # Exclude files that live inside .git directories (nested repos, submodules)
        if any(component in EXCLUDE_COMPONENT for component in rel.parts):
            return True
        return False

    collected: list[Path] = []

    def add_file(rel: Path) -> None:
        """Add file if it exists and is not excluded."""
        if is_excluded(rel):
            return
        full = source_root / rel
        if full.is_file():
            collected.append(rel)

    def add_dir_recursive(dir_rel: str, glob_pattern: str = "*") -> None:
        """Recursively add all matching files from a directory."""
        full_dir = source_root / dir_rel
        if not full_dir.is_dir():
            return
        for full_path in sorted(full_dir.rglob(glob_pattern)):
            if not full_path.is_file():
                continue
            rel = full_path.relative_to(source_root)
            if not is_excluded(rel):
                collected.append(rel)

    # --- Explicit single files ---
    for filename in ["CLAUDE.md", "setup.sh", "install.sh", ".gitignore", "README.md"]:
        add_file(Path(filename))

    # --- .claude/agents (base agents only) ---
    for agent in ["pathfinder.md", "engineer.md", "protocol-manager.md", "llm-engineer.md"]:
        add_file(Path(".claude/agents") / agent)

    # --- protocols/ entire directory ---
    add_dir_recursive("protocols")

    # --- memory/scripts/ entire directory ---
    add_dir_recursive("memory/scripts")

    # --- mcp/ specific files ---
    for mcp_file in ["mcp-full.json", "mcp_configure.py", "ollama_qdrant_server.py", "with-env.sh"]:
        add_file(Path("mcp") / mcp_file)

    # --- infra/docker-compose.yml ---
    add_file(Path("infra/docker-compose.yml"))

    # --- infra/exchange-shared/ entire directory ---
    add_dir_recursive("infra/exchange-shared")

    # --- infra/responder/ entire directory ---
    add_dir_recursive("infra/responder")

    # --- docs/self-architecture/ selected files ---
    for sa_file in ["capability-map.md", "build-registry.json", "spec-registry.json"]:
        add_file(Path("docs/self-architecture") / sa_file)

    # --- secrets/.env.template ---
    add_file(Path("secrets/.env.template"))

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[Path] = []
    for p in collected:
        key = p.as_posix()
        if key not in seen:
            seen.add(key)
            result.append(p)

    return result


# ---------------------------------------------------------------------------
# Version extraction
# ---------------------------------------------------------------------------

def get_source_version(source_root: Path) -> str:
    """Read WORKFLOW_VERSION from CLAUDE.md header."""
    claude_md = source_root / "CLAUDE.md"
    if not claude_md.exists():
        return "unknown"
    content = claude_md.read_text(encoding="utf-8")
    match = re.search(r"<!--\s*WORKFLOW_VERSION:\s*([\d.]+)\s*-->", content)
    return match.group(1) if match else "unknown"


# ---------------------------------------------------------------------------
# Content transforms
# ---------------------------------------------------------------------------

def transform_claude_md(content: str) -> str:
    """Insert _WORKFLOW_NEEDS_INIT marker before ## Role if not already present."""
    marker = "<!-- _WORKFLOW_NEEDS_INIT -->"
    if marker in content:
        # Already has the actual HTML comment marker — leave as-is
        return content
    # Insert the marker on the line immediately before "## Role"
    return re.sub(
        r"(## Role)",
        f"{marker}\n\\1",
        content,
        count=1,
    )


def transform_build_registry(source_version: str) -> str:
    """Return a minimal build-registry stub for a fresh clone."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stub = {
        "builds": [
            {
                "id": "build-init-001",
                "type": "initialization",
                "from_version": "0.2",
                "to_version": "1.0",
                "timestamp": now,
                "changes": [
                    f"Instance imported from coordinator v{source_version}",
                    "Fresh initialization required",
                ],
                "status": "pending",
            }
        ]
    }
    return json.dumps(stub, indent=2)


def transform_accord(content: str) -> str:
    """Strip FalkVelt/OkiAra identifiers and mark the accord as a template."""
    # Replace ACTIVE status line
    content = re.sub(
        r"\*\*Status:\*\*\s*ACTIVE\s*\(ratified[^)]*\)",
        "**Status:** TEMPLATE — Not yet ratified",
        content,
    )
    # Replace parties line
    content = re.sub(
        r"\*\*Parties:\*\*\s*FalkVelt\s*\(_follower_\),\s*OkiAra\s*\(_primal_\)",
        "**Parties:** {new_coordinator} (TBD), {partner} (TBD)",
        content,
    )
    # Append template disclaimer at the end
    disclaimer = (
        "\n---\n"
        "**This is a TEMPLATE. This instance has not entered any bilateral accord.**\n"
        "**To ratify a new accord, follow the ratification process in §7.1.**\n"
        "---\n"
    )
    content = content.rstrip() + disclaimer
    return content


# ---------------------------------------------------------------------------
# Core copy + transform logic
# ---------------------------------------------------------------------------

TRANSFORMS: dict[str, str] = {
    "CLAUDE.md": "claude_md",
    "docs/self-architecture/build-registry.json": "build_registry",
    "protocols/agents/knowledge-exchange-accord.md": "accord",
}


def apply_transform(rel_posix: str, content: str, source_version: str) -> tuple[str, bool]:
    """Apply transform for a known path. Returns (transformed_content, was_transformed)."""
    transform_key = TRANSFORMS.get(rel_posix)
    if transform_key == "claude_md":
        return transform_claude_md(content), True
    if transform_key == "build_registry":
        return transform_build_registry(source_version), True
    if transform_key == "accord":
        return transform_accord(content), True
    return content, False


def copy_with_transforms(
    source_root: Path,
    target_dir: Path,
    manifest: list[Path],
    dry_run: bool,
    source_version: str,
) -> int:
    """Copy all manifest files to target_dir, applying transforms where needed.

    Returns count of files processed.
    """
    count = 0

    for rel in manifest:
        rel_posix = rel.as_posix()
        source_path = source_root / rel
        target_path = target_dir / rel

        try:
            raw_content = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file — copy as bytes, no transform
            if dry_run:
                print(f"  [BINARY]    {rel_posix}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes())
            count += 1
            continue

        final_content, was_transformed = apply_transform(rel_posix, raw_content, source_version)

        if dry_run:
            tag = "[TRANSFORM] " if was_transformed else "            "
            print(f"  {tag}{rel_posix}")
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(final_content, encoding="utf-8")

        count += 1

    # Always create empty protocols/project/ dir with .gitkeep
    project_dir = target_dir / "protocols" / "project"
    gitkeep = project_dir / ".gitkeep"
    if dry_run:
        print(f"  [CREATE]    protocols/project/.gitkeep")
    else:
        project_dir.mkdir(parents=True, exist_ok=True)
        gitkeep.touch()

    # Ensure docs/self-architecture/ dir exists for files created during init
    sa_dir = target_dir / "docs" / "self-architecture"
    if not dry_run:
        sa_dir.mkdir(parents=True, exist_ok=True)

    return count


# ---------------------------------------------------------------------------
# Clone to GitHub
# ---------------------------------------------------------------------------

def clone_to_github(
    target: str,
    source_root: Path,
    manifest: list[Path],
    dry_run: bool,
    source_version: str,
) -> None:
    """Clone instance to a new private GitHub repository."""
    if not shutil.which("gh"):
        print("[ERROR] GitHub CLI (gh) not found. Install it: https://cli.github.com/", file=sys.stderr)
        sys.exit(1)

    print(f"Target:  {target} (GitHub)")
    print(f"Version: {source_version}")
    print(f"Files:   {len(manifest)} in manifest")
    print()

    with tempfile.TemporaryDirectory(prefix="instance-clone-") as tmp:
        tmp_path = Path(tmp)

        if dry_run:
            print("[DRY RUN] Files that would be copied:")
            copy_with_transforms(source_root, tmp_path, manifest, dry_run=True, source_version=source_version)
            print()
            print(f"[DRY RUN] Would create GitHub repo: {target} (private)")
            print(f"[DRY RUN] Would push with commit: chore: initial instance import from coordinator v{source_version}")
            return

        print("Copying files...")
        count = copy_with_transforms(source_root, tmp_path, manifest, dry_run=False, source_version=source_version)
        print(f"  {count} files written to temp dir")

        print("Initializing git...")
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: initial instance import from coordinator v{source_version}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )

        print(f"Creating GitHub repo: {target} ...")
        subprocess.run(
            ["gh", "repo", "create", target, "--private", "--source", str(tmp_path), "--push"],
            check=True,
            text=True,
        )

        print()
        print(f"[OK] Clone pushed to https://github.com/{target}")


# ---------------------------------------------------------------------------
# Clone to local directory
# ---------------------------------------------------------------------------

def clone_to_local(
    target: str,
    source_root: Path,
    manifest: list[Path],
    dry_run: bool,
    init_git: bool,
    source_version: str,
) -> None:
    """Clone instance to a local directory."""
    target_dir = Path(target).expanduser().resolve()

    print(f"Target:  {target_dir} (local)")
    print(f"Version: {source_version}")
    print(f"Files:   {len(manifest)} in manifest")
    print()

    if not dry_run and target_dir.exists():
        print(f"[ERROR] Target directory already exists: {target_dir}", file=sys.stderr)
        print("        Remove it first or choose a different path.", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print("[DRY RUN] Files that would be copied:")
        copy_with_transforms(source_root, target_dir, manifest, dry_run=True, source_version=source_version)
        print()
        if init_git:
            print(f"[DRY RUN] Would run: git init && git commit in {target_dir}")
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    print("Copying files...")
    count = copy_with_transforms(source_root, target_dir, manifest, dry_run=False, source_version=source_version)
    print(f"  {count} files written")

    if init_git:
        print("Initializing git...")
        subprocess.run(["git", "init"], cwd=target_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=target_dir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore: initial instance import from coordinator v{source_version}"],
            cwd=target_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        print("  git init + initial commit done")

    print()
    print(f"[OK] Clone written to {target_dir}")


# ---------------------------------------------------------------------------
# Post-clone verification
# ---------------------------------------------------------------------------

def verify_clone(target_dir: Path) -> list[str]:
    """Verify the clone is structurally correct. Returns list of error strings."""
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    # CLAUDE.md exists and contains the init marker (HTML comment, not text references)
    marker = "<!-- _WORKFLOW_NEEDS_INIT -->"
    claude_md = target_dir / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        check(marker in content, "CLAUDE.md missing <!-- _WORKFLOW_NEEDS_INIT --> marker")
        check(
            content.count(marker) == 1,
            "CLAUDE.md contains <!-- _WORKFLOW_NEEDS_INIT --> more than once",
        )
    else:
        errors.append("CLAUDE.md does not exist")

    # mcp/mcp-full.json must exist and contain __WORKSPACE_ROOT__ placeholder
    mcp_full = target_dir / "mcp" / "mcp-full.json"
    if mcp_full.exists():
        mcp_content = mcp_full.read_text(encoding="utf-8")
        check("__WORKSPACE_ROOT__" in mcp_content, "mcp/mcp-full.json missing __WORKSPACE_ROOT__ placeholder")
    else:
        errors.append("mcp/mcp-full.json does not exist")

    # mcp/mcp.json must NOT exist
    check(not (target_dir / "mcp" / "mcp.json").exists(), "mcp/mcp.json must not exist in clone")

    # secrets/.env must NOT exist
    check(not (target_dir / "secrets" / ".env").exists(), "secrets/.env must not exist in clone")

    # user-identity.md must NOT exist
    check(not (target_dir / "user-identity.md").exists(), "user-identity.md must not exist in clone")

    # knowledge-exchange-accord.md must contain TEMPLATE
    accord = target_dir / "protocols" / "agents" / "knowledge-exchange-accord.md"
    if accord.exists():
        check("TEMPLATE" in accord.read_text(encoding="utf-8"), "knowledge-exchange-accord.md missing TEMPLATE marker")
    else:
        errors.append("protocols/agents/knowledge-exchange-accord.md does not exist")

    # build-registry.json must exist and have exactly 1 entry
    registry = target_dir / "docs" / "self-architecture" / "build-registry.json"
    if registry.exists():
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
            builds = data.get("builds", [])
            check(len(builds) == 1, f"build-registry.json must have exactly 1 entry (found {len(builds)})")
        except json.JSONDecodeError as exc:
            errors.append(f"build-registry.json is not valid JSON: {exc}")
    else:
        errors.append("docs/self-architecture/build-registry.json does not exist")

    return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone coordinator instance to a new GitHub repo or local directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/clone.py owner/repo-name\n"
            "  python3 memory/scripts/clone.py /path/to/local/dir\n"
            "  python3 memory/scripts/clone.py owner/repo-name --dry-run\n"
            "  python3 memory/scripts/clone.py /path/to/dir --init-git\n"
        ),
    )
    parser.add_argument(
        "target",
        help="Destination: 'owner/repo' for GitHub, '/path/to/dir' for local.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without actually doing it.",
    )
    parser.add_argument(
        "--init-git",
        action="store_true",
        help="Initialize a git repo in the local target directory (local clone only).",
    )
    args = parser.parse_args()

    source_root = get_source_root()
    source_version = get_source_version(source_root)
    manifest = get_instance_manifest(source_root)

    github_target = is_github_target(args.target)

    if github_target:
        if args.init_git:
            print("[WARN] --init-git is ignored for GitHub targets (git is always initialized).")
        try:
            clone_to_github(
                target=args.target,
                source_root=source_root,
                manifest=manifest,
                dry_run=args.dry_run,
                source_version=source_version,
            )
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] Command failed: {exc.cmd}", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
            sys.exit(1)
    else:
        try:
            clone_to_local(
                target=args.target,
                source_root=source_root,
                manifest=manifest,
                dry_run=args.dry_run,
                init_git=args.init_git,
                source_version=source_version,
            )
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] Command failed: {exc.cmd}", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
            sys.exit(1)
        except PermissionError as exc:
            print(f"[ERROR] Permission denied: {exc}", file=sys.stderr)
            sys.exit(1)

    # Verification (skip in dry-run mode)
    if args.dry_run:
        return

    if github_target:
        print("[INFO] Skipping local verify for GitHub clone (repo is remote).")
        return

    target_dir = Path(args.target).expanduser().resolve()
    print("Verifying clone...")
    errors = verify_clone(target_dir)
    if errors:
        print(f"[WARN] Verification found {len(errors)} issue(s):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("[OK] Verification passed.")

    print()
    print("Summary:")
    print(f"  Files copied:   {len(manifest) + 1}")  # +1 for protocols/project/.gitkeep
    print(f"  Source version: {source_version}")
    print(f"  Target:         {args.target}")
    print(f"  Verification:   {'PASS' if not errors else f'WARN ({len(errors)} issues)'}")
    print()
    print("Next step: run initialization inside the new workspace.")


if __name__ == "__main__":
    main()
