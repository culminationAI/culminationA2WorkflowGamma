#!/usr/bin/env python3
"""Crossbreed two coordinator instances into a hybrid offspring.

Creates a new workspace that inherits genes (protocols, agents, memory scripts,
infra, mcp configs) from two parent workspaces according to a fitness-evaluated
gene map.

Usage:
    # Scan both parents → generate gene-map.json
    python3 memory/scripts/crossbreed.py --scan /path/to/parent_a /path/to/parent_b

    # Create offspring (local)
    python3 memory/scripts/crossbreed.py /path/to/target --parent-a /path/to/parent_a --parent-b /path/to/parent_b

    # Create offspring (GitHub)
    python3 memory/scripts/crossbreed.py owner/repo --parent-a /path/to/parent_a --parent-b /path/to/parent_b

    # Dry run
    python3 memory/scripts/crossbreed.py /path/to/target --parent-a /path/to/parent_a --parent-b /path/to/parent_b --dry-run

    # With git init
    python3 memory/scripts/crossbreed.py /path/to/target --parent-a /path/to/parent_a --parent-b /path/to/parent_b --init-git

    # Using existing gene-map
    python3 memory/scripts/crossbreed.py /path/to/target --parent-a /path/to/parent_a --parent-b /path/to/parent_b --gene-map /path/to/gene-map.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PARENT_A = Path("/Users/eliahkadu/Desktop/_follower_")
DEFAULT_PARENT_B = Path("/Users/eliahkadu/Desktop/_primal_")

# Script workspace root (3 levels up from memory/scripts/crossbreed.py)
SCRIPT_ROOT = Path(__file__).resolve().parent.parent.parent

# Gene categories mapped to their relative path prefixes
GENE_CATEGORIES: dict[str, list[str]] = {
    "protocols": ["protocols/"],
    "agents": [".claude/agents/"],
    "blueprint": ["CLAUDE.md"],
    "infrastructure": ["memory/scripts/"],
    "tool": ["mcp/"],
    "substrate": ["infra/"],
    "knowledge": ["docs/self-architecture/spec-registry.json"],
    "identity": ["docs/self-architecture/capability-map.md"],
}

# Genes where fitness heuristics are overridden → always merged from parent_a base
FORCE_MERGE_GENES: set[str] = {
    "evolution.md",
    "build-up.md",
    "dispatcher.md",
}

# Patterns that must never appear in offspring (same as clone.py)
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

EXCLUDE_SUFFIX: list[str] = [".pyc"]
EXCLUDE_PART: list[str] = ["__pycache__"]
EXCLUDE_COMPONENT: set[str] = {".git"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GeneEntry:
    """Represents a single gene extracted from a workspace scan."""
    gene_id: str                   # e.g. gene-protocols-core-evolution
    category: str                  # protocols | agents | blueprint | infrastructure | tool | substrate | knowledge | identity
    rel_path: str                  # posix relative path from workspace root
    file_size: int                 # bytes
    mtime: float                   # unix timestamp
    parent: str                    # "parent_a" | "parent_b" | "both"
    selection: Optional[str] = None  # "parent_a" | "parent_b" | "merge" | null (pending evaluation)
    fitness_score_a: float = 0.0
    fitness_score_b: float = 0.0


# ---------------------------------------------------------------------------
# Exclusion helper
# ---------------------------------------------------------------------------

def is_excluded(rel: Path) -> bool:
    """Return True if this relative path should be excluded from genes."""
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
    if any(component in EXCLUDE_COMPONENT for component in rel.parts):
        return True
    return False


# ---------------------------------------------------------------------------
# Version extraction (mirrors clone.py)
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
# Target type detection (mirrors clone.py)
# ---------------------------------------------------------------------------

def is_github_target(target: str) -> bool:
    """Return True if target looks like owner/repo (not a filesystem path)."""
    return "/" in target and not target.startswith("/") and not target.startswith(".")


# ---------------------------------------------------------------------------
# Gene ID generation
# ---------------------------------------------------------------------------

def make_gene_id(category: str, rel_path: str) -> str:
    """Generate a stable gene ID from category and relative path.

    Examples:
        protocols/core/evolution.md    → gene-protocols-core-evolution
        .claude/agents/pathfinder.md  → gene-agents-pathfinder
        CLAUDE.md                     → gene-blueprint-claude
        mcp/mcp-full.json             → gene-tool-mcp-full
    """
    path = Path(rel_path)
    # Strip category-specific prefix to get the meaningful part
    parts = list(path.parts)

    # Remove leading dir components that are already in category
    if category == "agents" and parts and parts[0] == ".claude":
        parts = parts[1:]  # remove .claude
        if parts and parts[0] == "agents":
            parts = parts[1:]  # remove agents
    elif category == "protocols" and parts and parts[0] == "protocols":
        parts = parts[1:]
    elif category == "infrastructure" and len(parts) >= 2 and parts[0] == "memory":
        parts = parts[2:]  # remove memory/scripts
    elif category == "tool" and parts and parts[0] == "mcp":
        parts = parts[1:]
    elif category == "substrate" and parts and parts[0] == "infra":
        parts = parts[1:]
    elif category == "knowledge" and len(parts) >= 2:
        parts = parts[2:]  # remove docs/self-architecture
    elif category == "identity" and len(parts) >= 2:
        parts = parts[2:]

    # Build the suffix: join parts, strip extension from last, replace / . - with -
    if parts:
        # Strip extension from the last part
        last = Path(parts[-1]).stem
        parts[-1] = last
        suffix = "-".join(p.replace(".", "-").replace("_", "-") for p in parts)
    else:
        suffix = Path(rel_path).stem.replace(".", "-").replace("_", "-")

    gene_id = f"gene-{category}-{suffix}"
    # Collapse consecutive hyphens
    gene_id = re.sub(r"-{2,}", "-", gene_id)
    return gene_id


def classify_gene_category(rel_path: str) -> Optional[str]:
    """Return the gene category for a relative path, or None if not a gene."""
    if rel_path == "CLAUDE.md":
        return "blueprint"
    if rel_path == "docs/self-architecture/capability-map.md":
        return "identity"
    if rel_path == "docs/self-architecture/spec-registry.json":
        return "knowledge"
    if rel_path.startswith("protocols/"):
        return "protocols"
    if rel_path.startswith(".claude/agents/"):
        return "agents"
    if rel_path.startswith("memory/scripts/"):
        return "infrastructure"
    if rel_path.startswith("mcp/"):
        return "tool"
    if rel_path.startswith("infra/"):
        return "substrate"
    return None


# ---------------------------------------------------------------------------
# Workspace scan
# ---------------------------------------------------------------------------

def scan_workspace(root: Path) -> dict[str, GeneEntry]:
    """Scan a single workspace and return all genes keyed by rel_path (posix).

    A gene is any file that falls into a recognized gene category and is not
    excluded by the standard exclusion rules.
    """
    if not root.exists():
        print(f"  [WARN] Workspace does not exist: {root}", file=sys.stderr)
        return {}

    genes: dict[str, GeneEntry] = {}

    def collect_file(full_path: Path) -> None:
        rel = full_path.relative_to(root)
        if is_excluded(rel):
            return
        if not full_path.is_file():
            return
        rel_posix = rel.as_posix()
        category = classify_gene_category(rel_posix)
        if category is None:
            return
        stat = full_path.stat()
        gene_id = make_gene_id(category, rel_posix)
        genes[rel_posix] = GeneEntry(
            gene_id=gene_id,
            category=category,
            rel_path=rel_posix,
            file_size=stat.st_size,
            mtime=stat.st_mtime,
            parent="",  # will be set by build_gene_map
        )

    # Scan gene directories
    gene_dirs = [
        "protocols",
        ".claude/agents",
        "memory/scripts",
        "mcp",
        "infra",
    ]
    for dir_rel in gene_dirs:
        full_dir = root / dir_rel
        if full_dir.is_dir():
            for fp in sorted(full_dir.rglob("*")):
                collect_file(fp)

    # Scan individual gene files
    gene_files = [
        "CLAUDE.md",
        "docs/self-architecture/spec-registry.json",
        "docs/self-architecture/capability-map.md",
    ]
    for file_rel in gene_files:
        fp = root / file_rel
        if fp.exists():
            collect_file(fp)

    return genes


# ---------------------------------------------------------------------------
# Gene map construction
# ---------------------------------------------------------------------------

def build_gene_map(
    genes_a: dict[str, GeneEntry],
    genes_b: dict[str, GeneEntry],
) -> list[dict]:
    """Compare genes from both parents and build the combined gene map.

    Returns list of gene dicts. Genes in both parents get selection=null
    (pending fitness evaluation). Exclusive genes are auto-selected.
    """
    all_paths = set(genes_a.keys()) | set(genes_b.keys())
    gene_map: list[dict] = []

    for rel_path in sorted(all_paths):
        in_a = rel_path in genes_a
        in_b = rel_path in genes_b

        # Pick the primary entry for metadata
        entry = genes_a[rel_path] if in_a else genes_b[rel_path]

        record: dict = {
            "id": entry.gene_id,
            "category": entry.category,
            "rel_path": rel_path,
            "parent": "",
            "selection": None,
            "fitness_score_a": genes_a[rel_path].file_size if in_a else 0,
            "fitness_score_b": genes_b[rel_path].file_size if in_b else 0,
            "mtime_a": genes_a[rel_path].mtime if in_a else None,
            "mtime_b": genes_b[rel_path].mtime if in_b else None,
        }

        if in_a and not in_b:
            record["parent"] = "parent_a"
            record["selection"] = "parent_a"
        elif in_b and not in_a:
            record["parent"] = "parent_b"
            record["selection"] = "parent_b"
        else:
            # Both have this gene — needs fitness evaluation
            record["parent"] = "both"
            record["selection"] = None

        gene_map.append(record)

    return gene_map


# ---------------------------------------------------------------------------
# Integrity score extraction from meditation log
# ---------------------------------------------------------------------------

def _parse_integrity_from_meditation_log(root: Path) -> Optional[float]:
    """Try to parse the latest integrity score from meditation-log.md.

    Returns a float in [0.0, 1.0] or None if unavailable.
    """
    log_path = root / "docs" / "self-architecture" / "meditation-log.md"
    if not log_path.exists():
        return None
    try:
        content = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    # Look for lines like: ## Session N — DATE | Intensity | Integrity: 0.60
    matches = re.findall(r"Integrity:\s*([\d.]+)", content)
    if not matches:
        return None
    try:
        return float(matches[-1])  # Latest entry
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Fitness evaluation
# ---------------------------------------------------------------------------

def evaluate_fitness(
    gene_map: list[dict],
    root_a: Path,
    root_b: Path,
) -> list[dict]:
    """For genes with parent='both', pick the fitter parent.

    Heuristics:
      - Larger file (more content) → +1 point for that parent
      - More recently modified   → +1 point for that parent
      - Workspace integrity score → +integrity/10 per parent (shared bonus)
    Force-merge genes always get selection="merge".
    """
    integrity_a = _parse_integrity_from_meditation_log(root_a)
    integrity_b = _parse_integrity_from_meditation_log(root_b)

    for record in gene_map:
        if record["parent"] != "both":
            continue  # Already decided

        filename = Path(record["rel_path"]).name

        # Hardcoded force-merge
        if filename in FORCE_MERGE_GENES:
            record["selection"] = "merge"
            continue

        score_a = 0.0
        score_b = 0.0

        size_a = record.get("fitness_score_a", 0) or 0
        size_b = record.get("fitness_score_b", 0) or 0

        if size_a > size_b:
            score_a += 1.0
        elif size_b > size_a:
            score_b += 1.0

        mtime_a = record.get("mtime_a") or 0.0
        mtime_b = record.get("mtime_b") or 0.0
        if mtime_a > mtime_b:
            score_a += 1.0
        elif mtime_b > mtime_a:
            score_b += 1.0

        if integrity_a is not None:
            score_a += integrity_a / 10.0
        if integrity_b is not None:
            score_b += integrity_b / 10.0

        # Break ties in favor of parent_a (primary parent)
        record["fitness_score_a"] = round(score_a, 4)
        record["fitness_score_b"] = round(score_b, 4)

        if score_b > score_a:
            record["selection"] = "parent_b"
        else:
            record["selection"] = "parent_a"

    return gene_map


# ---------------------------------------------------------------------------
# Dual manifest
# ---------------------------------------------------------------------------

def get_dual_manifest(
    root_a: Path,
    root_b: Path,
    gene_map: list[dict],
) -> list[tuple[str, Path, str]]:
    """Return (rel_path, source_root, selection_reason) tuples.

    For merge genes, source_root = root_a (used as base). Actual merging
    is logged in lineage but file content comes from parent_a for safety.
    """
    manifest: list[tuple[str, Path, str]] = []

    for record in gene_map:
        sel = record["selection"]
        rel = record["rel_path"]

        if sel == "parent_a":
            source = root_a
            reason = f"exclusive_a" if record["parent"] == "parent_a" else f"fitness_a"
        elif sel == "parent_b":
            source = root_b
            reason = f"exclusive_b" if record["parent"] == "parent_b" else f"fitness_b"
        elif sel == "merge":
            source = root_a   # parent_a as base for merge genes
            reason = "merge_base_a"
        else:
            # selection is None — should not happen after evaluate_fitness
            print(f"  [WARN] Gene {record['id']} has no selection — defaulting to parent_a", file=sys.stderr)
            source = root_a
            reason = "fallback_a"

        manifest.append((rel, source, reason))

    return manifest


# ---------------------------------------------------------------------------
# Content transforms (mirrors + extends clone.py)
# ---------------------------------------------------------------------------

def transform_claude_md(content: str) -> str:
    """Insert _WORKFLOW_NEEDS_INIT marker before ## Role if not already present."""
    marker = "<!-- _WORKFLOW_NEEDS_INIT -->"
    if marker in content:
        return content
    return re.sub(
        r"(## Role)",
        f"{marker}\n\\1",
        content,
        count=1,
    )


def transform_accord(content: str) -> str:
    """Strip FalkVelt/OkiAra identifiers and mark the accord as a template."""
    content = re.sub(
        r"\*\*Status:\*\*\s*ACTIVE\s*\(ratified[^)]*\)",
        "**Status:** TEMPLATE — Not yet ratified",
        content,
    )
    content = re.sub(
        r"\*\*Parties:\*\*\s*FalkVelt\s*\(_follower_\),\s*OkiAra\s*\(_primal_\)",
        "**Parties:** {new_coordinator} (TBD), {partner} (TBD)",
        content,
    )
    disclaimer = (
        "\n---\n"
        "**This is a TEMPLATE. This instance has not entered any bilateral accord.**\n"
        "**To ratify a new accord, follow the ratification process in §7.1.**\n"
        "---\n"
    )
    content = content.rstrip() + disclaimer
    return content


def transform_build_registry_crossbreed(
    parent_a_name: str,
    parent_b_name: str,
    ver_a: str,
    ver_b: str,
) -> str:
    """Return a build-registry stub describing the crossbreed origin."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    offspring_ver = _max_version(ver_a, ver_b)
    stub = {
        "builds": [
            {
                "id": "build-crossbreed-001",
                "type": "crossbreed",
                "from_version": "0.2",
                "to_version": "1.0",
                "timestamp": now,
                "changes": [
                    f"Crossbred from {parent_a_name} v{ver_a} + {parent_b_name} v{ver_b}",
                    f"Offspring base version: {offspring_ver}",
                    "Fresh initialization required",
                ],
                "status": "pending",
            }
        ]
    }
    return json.dumps(stub, indent=2)


CROSSBREED_TRANSFORMS: set[str] = {
    "CLAUDE.md",
    "docs/self-architecture/build-registry.json",
    "protocols/agents/knowledge-exchange-accord.md",
}


def apply_crossbreed_transform(
    rel_posix: str,
    content: str,
    parent_a_name: str,
    parent_b_name: str,
    ver_a: str,
    ver_b: str,
) -> tuple[str, bool]:
    """Apply transform for known paths. Returns (transformed_content, was_transformed)."""
    if rel_posix == "CLAUDE.md":
        return transform_claude_md(content), True
    if rel_posix == "docs/self-architecture/build-registry.json":
        return transform_build_registry_crossbreed(parent_a_name, parent_b_name, ver_a, ver_b), True
    if rel_posix == "protocols/agents/knowledge-exchange-accord.md":
        return transform_accord(content), True
    return content, False


# ---------------------------------------------------------------------------
# Version comparison helpers
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '2.98' into a comparable tuple."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0,)


def _max_version(ver_a: str, ver_b: str) -> str:
    """Return the higher of two version strings."""
    if _parse_version(ver_a) >= _parse_version(ver_b):
        return ver_a
    return ver_b


# ---------------------------------------------------------------------------
# Lineage generation
# ---------------------------------------------------------------------------

def generate_lineage(
    gene_map: list[dict],
    root_a: Path,
    root_b: Path,
    ver_a: str,
    ver_b: str,
) -> dict:
    """Create a lineage record describing the crossbreed operation."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    from_a = sum(1 for g in gene_map if g["selection"] == "parent_a")
    from_b = sum(1 for g in gene_map if g["selection"] == "parent_b")
    merged = sum(1 for g in gene_map if g["selection"] == "merge")
    total = len(gene_map)
    mutations = 0  # reserved for future mutation tracking

    gene_details = [
        {
            "id": g["id"],
            "source": (
                "merge" if g["selection"] == "merge"
                else "parent_a" if g["selection"] == "parent_a"
                else "parent_b" if g["selection"] == "parent_b"
                else "mutation"
            ),
            "path": g["rel_path"],
        }
        for g in gene_map
    ]

    return {
        "type": "crossbreed",
        "created_at": now,
        "parent_a": {
            "name": root_a.name,
            "version": ver_a,
            "root": str(root_a),
        },
        "parent_b": {
            "name": root_b.name,
            "version": ver_b,
            "root": str(root_b),
        },
        "offspring_version": _max_version(ver_a, ver_b),
        "genes": {
            "total": total,
            "from_parent_a": from_a,
            "from_parent_b": from_b,
            "from_both_merged": merged,
            "mutations": mutations,
        },
        "gene_details": gene_details,
    }


# ---------------------------------------------------------------------------
# Core copy + transform logic
# ---------------------------------------------------------------------------

def copy_with_dual_transforms(
    target_dir: Path,
    manifest: list[tuple[str, Path, str]],
    dry_run: bool,
    parent_a_name: str,
    parent_b_name: str,
    ver_a: str,
    ver_b: str,
    lineage: Optional[dict] = None,
) -> int:
    """Copy all manifest files to target_dir applying crossbreed transforms.

    Returns count of files processed.
    """
    count = 0

    for rel_posix, source_root, reason in manifest:
        source_path = source_root / rel_posix
        target_path = target_dir / rel_posix

        if not source_path.exists():
            print(f"  [SKIP]      {rel_posix} (source missing in {source_root.name})", file=sys.stderr)
            continue

        try:
            raw_content = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file — copy as bytes, no transform
            if dry_run:
                print(f"  [BINARY]    {rel_posix}  ({reason})")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes())
            count += 1
            continue

        final_content, was_transformed = apply_crossbreed_transform(
            rel_posix, raw_content, parent_a_name, parent_b_name, ver_a, ver_b
        )

        if dry_run:
            tag = "[TRANSFORM] " if was_transformed else f"[{reason[:10].upper():<10}]"
            print(f"  {tag} {rel_posix}")
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

    # Write lineage.json
    if lineage is not None:
        lineage_path = target_dir / "lineage.json"
        if dry_run:
            print(f"  [CREATE]    lineage.json")
        else:
            (target_dir).mkdir(parents=True, exist_ok=True)
            lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")

    # Ensure docs/self-architecture/ dir exists
    sa_dir = target_dir / "docs" / "self-architecture"
    if not dry_run:
        sa_dir.mkdir(parents=True, exist_ok=True)

    return count


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_crossbreed(target_dir: Path, gene_map: list[dict]) -> list[str]:
    """Verify the offspring is structurally correct.

    Extends clone.py verify_clone() with gene-map and lineage checks.
    Returns list of error strings (empty = pass).
    """
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    # --- Inherited checks from clone.py ---
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

    mcp_full = target_dir / "mcp" / "mcp-full.json"
    if mcp_full.exists():
        mcp_content = mcp_full.read_text(encoding="utf-8")
        check(
            "__WORKSPACE_ROOT__" in mcp_content,
            "mcp/mcp-full.json missing __WORKSPACE_ROOT__ placeholder",
        )
    # mcp-full.json is optional if parent_b didn't have it either

    check(not (target_dir / "mcp" / "mcp.json").exists(), "mcp/mcp.json must not exist in offspring")
    check(not (target_dir / "secrets" / ".env").exists(), "secrets/.env must not exist in offspring")
    check(not (target_dir / "user-identity.md").exists(), "user-identity.md must not exist in offspring")

    accord = target_dir / "protocols" / "agents" / "knowledge-exchange-accord.md"
    if accord.exists():
        check(
            "TEMPLATE" in accord.read_text(encoding="utf-8"),
            "knowledge-exchange-accord.md missing TEMPLATE marker",
        )

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

    # --- Crossbreed-specific checks ---

    # lineage.json must exist and be valid JSON
    lineage_path = target_dir / "lineage.json"
    if lineage_path.exists():
        try:
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
            check(lineage.get("type") == "crossbreed", "lineage.json missing or wrong 'type' field")
            check("parent_a" in lineage, "lineage.json missing 'parent_a'")
            check("parent_b" in lineage, "lineage.json missing 'parent_b'")
            check("genes" in lineage, "lineage.json missing 'genes' summary")
        except json.JSONDecodeError as exc:
            errors.append(f"lineage.json is not valid JSON: {exc}")
    else:
        errors.append("lineage.json does not exist")

    # Every selected gene must exist in target
    missing_genes: list[str] = []
    for record in gene_map:
        gene_path = target_dir / record["rel_path"]
        if not gene_path.exists():
            missing_genes.append(record["rel_path"])
    if missing_genes:
        errors.append(
            f"{len(missing_genes)} selected gene(s) missing from offspring: "
            + ", ".join(missing_genes[:5])
            + (" ..." if len(missing_genes) > 5 else "")
        )

    # No duplicate protocol files (same filename in different subdirs)
    protocol_dir = target_dir / "protocols"
    if protocol_dir.is_dir():
        seen_filenames: dict[str, list[str]] = {}
        for fp in protocol_dir.rglob("*.md"):
            fn = fp.name
            seen_filenames.setdefault(fn, []).append(fp.relative_to(target_dir).as_posix())
        duplicates = {fn: paths for fn, paths in seen_filenames.items() if len(paths) > 1}
        if duplicates:
            dup_list = [f"{fn}: {paths}" for fn, paths in list(duplicates.items())[:3]]
            errors.append(
                f"Duplicate protocol filenames detected ({len(duplicates)}): "
                + "; ".join(dup_list)
            )

    return errors


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

def run_scan_mode(path_a: Path, path_b: Path) -> None:
    """Scan both workspaces and write gene-map.json."""
    out_path = SCRIPT_ROOT / "docs" / "self-architecture" / "gene-map.json"

    print(f"Scanning parent_a: {path_a}")
    genes_a = scan_workspace(path_a)
    print(f"  Found {len(genes_a)} genes")

    print(f"Scanning parent_b: {path_b}")
    genes_b = scan_workspace(path_b)
    print(f"  Found {len(genes_b)} genes")

    print("Building gene map...")
    gene_map = build_gene_map(genes_a, genes_b)

    only_a = sum(1 for g in gene_map if g["parent"] == "parent_a")
    only_b = sum(1 for g in gene_map if g["parent"] == "parent_b")
    shared = sum(1 for g in gene_map if g["parent"] == "both")
    print(f"  Total genes: {len(gene_map)} (A-only: {only_a}, B-only: {only_b}, shared: {shared})")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(gene_map, indent=2, default=str), encoding="utf-8")
    print(f"\n[OK] Gene map written to: {out_path}")


# ---------------------------------------------------------------------------
# Crossbreed to local directory
# ---------------------------------------------------------------------------

def crossbreed_to_local(
    target: str,
    root_a: Path,
    root_b: Path,
    gene_map: list[dict],
    dry_run: bool,
    init_git: bool,
    ver_a: str,
    ver_b: str,
) -> None:
    """Crossbreed parents into a local directory offspring."""
    target_dir = Path(target).expanduser().resolve()

    parent_a_name = root_a.name
    parent_b_name = root_b.name

    manifest = get_dual_manifest(root_a, root_b, gene_map)
    lineage = generate_lineage(gene_map, root_a, root_b, ver_a, ver_b)

    print(f"Target:   {target_dir} (local)")
    print(f"Parent A: {root_a.name} v{ver_a}")
    print(f"Parent B: {root_b.name} v{ver_b}")
    print(f"Genes:    {len(gene_map)} total")
    print()

    if not dry_run and target_dir.exists():
        print(f"[ERROR] Target directory already exists: {target_dir}", file=sys.stderr)
        print("        Remove it first or choose a different path.", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print("[DRY RUN] Files that would be copied:")
        copy_with_dual_transforms(
            target_dir=target_dir,
            manifest=manifest,
            dry_run=True,
            parent_a_name=parent_a_name,
            parent_b_name=parent_b_name,
            ver_a=ver_a,
            ver_b=ver_b,
            lineage=lineage,
        )
        print()
        if init_git:
            print(f"[DRY RUN] Would run: git init && git commit in {target_dir}")
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    print("Copying genes...")
    count = copy_with_dual_transforms(
        target_dir=target_dir,
        manifest=manifest,
        dry_run=False,
        parent_a_name=parent_a_name,
        parent_b_name=parent_b_name,
        ver_a=ver_a,
        ver_b=ver_b,
        lineage=lineage,
    )
    print(f"  {count} files written")

    if init_git:
        print("Initializing git...")
        subprocess.run(["git", "init"], cwd=target_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=target_dir, check=True, capture_output=True, text=True)
        commit_msg = (
            f"chore: crossbreed offspring from {parent_a_name} v{ver_a} "
            f"+ {parent_b_name} v{ver_b}"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=target_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        print("  git init + initial commit done")

    print()
    print(f"[OK] Offspring written to {target_dir}")


# ---------------------------------------------------------------------------
# Crossbreed to GitHub
# ---------------------------------------------------------------------------

def crossbreed_to_github(
    target: str,
    root_a: Path,
    root_b: Path,
    gene_map: list[dict],
    dry_run: bool,
    ver_a: str,
    ver_b: str,
) -> None:
    """Crossbreed parents into a new private GitHub repository."""
    if not shutil.which("gh"):
        print("[ERROR] GitHub CLI (gh) not found. Install it: https://cli.github.com/", file=sys.stderr)
        sys.exit(1)

    parent_a_name = root_a.name
    parent_b_name = root_b.name

    manifest = get_dual_manifest(root_a, root_b, gene_map)
    lineage = generate_lineage(gene_map, root_a, root_b, ver_a, ver_b)

    print(f"Target:   {target} (GitHub)")
    print(f"Parent A: {parent_a_name} v{ver_a}")
    print(f"Parent B: {parent_b_name} v{ver_b}")
    print(f"Genes:    {len(gene_map)} total")
    print()

    with tempfile.TemporaryDirectory(prefix="crossbreed-") as tmp:
        tmp_path = Path(tmp)

        if dry_run:
            print("[DRY RUN] Files that would be copied:")
            copy_with_dual_transforms(
                target_dir=tmp_path,
                manifest=manifest,
                dry_run=True,
                parent_a_name=parent_a_name,
                parent_b_name=parent_b_name,
                ver_a=ver_a,
                ver_b=ver_b,
                lineage=lineage,
            )
            print()
            print(f"[DRY RUN] Would create GitHub repo: {target} (private)")
            commit_msg = f"chore: crossbreed offspring from {parent_a_name} v{ver_a} + {parent_b_name} v{ver_b}"
            print(f"[DRY RUN] Would push with commit: {commit_msg}")
            return

        print("Copying genes...")
        count = copy_with_dual_transforms(
            target_dir=tmp_path,
            manifest=manifest,
            dry_run=False,
            parent_a_name=parent_a_name,
            parent_b_name=parent_b_name,
            ver_a=ver_a,
            ver_b=ver_b,
            lineage=lineage,
        )
        print(f"  {count} files written to temp dir")

        print("Initializing git...")
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
        commit_msg = (
            f"chore: crossbreed offspring from {parent_a_name} v{ver_a} "
            f"+ {parent_b_name} v{ver_b}"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
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
        print(f"[OK] Offspring pushed to https://github.com/{target}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crossbreed two coordinator instances into a hybrid offspring workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/crossbreed.py --scan /path/to/parent_a /path/to/parent_b\n"
            "  python3 memory/scripts/crossbreed.py /path/to/target --parent-a /path/a --parent-b /path/b\n"
            "  python3 memory/scripts/crossbreed.py owner/repo --parent-a /path/a --parent-b /path/b\n"
            "  python3 memory/scripts/crossbreed.py /path/to/target --dry-run\n"
            "  python3 memory/scripts/crossbreed.py /path/to/target --init-git\n"
            "  python3 memory/scripts/crossbreed.py /path/to/target --gene-map /path/to/gene-map.json\n"
        ),
    )

    # --scan mode: positional args are the two parent paths
    parser.add_argument(
        "--scan",
        nargs=2,
        metavar=("PARENT_A", "PARENT_B"),
        help="Scan mode: scan both workspaces and write docs/self-architecture/gene-map.json. No offspring created.",
    )

    # Crossbreed mode: target is positional
    parser.add_argument(
        "target",
        nargs="?",
        help="Offspring destination: 'owner/repo' for GitHub, '/path/to/dir' for local.",
    )
    parser.add_argument(
        "--parent-a",
        type=Path,
        default=DEFAULT_PARENT_A,
        metavar="PATH",
        help=f"Path to parent A workspace (default: {DEFAULT_PARENT_A})",
    )
    parser.add_argument(
        "--parent-b",
        type=Path,
        default=DEFAULT_PARENT_B,
        metavar="PATH",
        help=f"Path to parent B workspace (default: {DEFAULT_PARENT_B})",
    )
    parser.add_argument(
        "--gene-map",
        type=Path,
        metavar="FILE",
        help="Use existing gene-map.json instead of generating a fresh one.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without actually doing it.",
    )
    parser.add_argument(
        "--init-git",
        action="store_true",
        help="Initialize a git repo in the local target directory (local offspring only).",
    )

    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Scan mode
    # -----------------------------------------------------------------------
    if args.scan:
        path_a = Path(args.scan[0]).expanduser().resolve()
        path_b = Path(args.scan[1]).expanduser().resolve()
        run_scan_mode(path_a, path_b)
        return

    # -----------------------------------------------------------------------
    # Crossbreed mode — target required
    # -----------------------------------------------------------------------
    if not args.target:
        parser.error("target is required for crossbreed mode (or use --scan for scan-only mode)")

    root_a = args.parent_a.expanduser().resolve()
    root_b = args.parent_b.expanduser().resolve()

    print(f"Parent A: {root_a}")
    print(f"Parent B: {root_b}")
    print()

    # Load or generate gene map
    if args.gene_map:
        gene_map_path = args.gene_map.expanduser().resolve()
        if not gene_map_path.exists():
            print(f"[ERROR] gene-map file not found: {gene_map_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Loading gene map from: {gene_map_path}")
        gene_map = json.loads(gene_map_path.read_text(encoding="utf-8"))
        print(f"  Loaded {len(gene_map)} genes")
    else:
        print("Scanning parent workspaces...")
        genes_a = scan_workspace(root_a)
        genes_b = scan_workspace(root_b)
        print(f"  Parent A: {len(genes_a)} genes | Parent B: {len(genes_b)} genes")
        gene_map = build_gene_map(genes_a, genes_b)
        print(f"  Combined: {len(gene_map)} genes")

    # Evaluate fitness for shared genes
    print("Evaluating gene fitness...")
    gene_map = evaluate_fitness(gene_map, root_a, root_b)

    from_a = sum(1 for g in gene_map if g["selection"] == "parent_a")
    from_b = sum(1 for g in gene_map if g["selection"] == "parent_b")
    merged = sum(1 for g in gene_map if g["selection"] == "merge")
    print(f"  From A: {from_a}  |  From B: {from_b}  |  Merged: {merged}")
    print()

    # Extract parent versions
    ver_a = get_source_version(root_a)
    ver_b = get_source_version(root_b)

    github_target = is_github_target(args.target)

    if github_target:
        if args.init_git:
            print("[WARN] --init-git is ignored for GitHub targets (git is always initialized).")
        try:
            crossbreed_to_github(
                target=args.target,
                root_a=root_a,
                root_b=root_b,
                gene_map=gene_map,
                dry_run=args.dry_run,
                ver_a=ver_a,
                ver_b=ver_b,
            )
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] Command failed: {exc.cmd}", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
            sys.exit(1)
    else:
        try:
            crossbreed_to_local(
                target=args.target,
                root_a=root_a,
                root_b=root_b,
                gene_map=gene_map,
                dry_run=args.dry_run,
                init_git=args.init_git,
                ver_a=ver_a,
                ver_b=ver_b,
            )
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] Command failed: {exc.cmd}", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, file=sys.stderr)
            sys.exit(1)
        except PermissionError as exc:
            print(f"[ERROR] Permission denied: {exc}", file=sys.stderr)
            sys.exit(1)

    # Skip verification in dry-run or GitHub mode
    if args.dry_run:
        return
    if github_target:
        print("[INFO] Skipping local verify for GitHub offspring (repo is remote).")
        return

    target_dir = Path(args.target).expanduser().resolve()
    print("Verifying offspring...")
    errors = verify_crossbreed(target_dir, gene_map)
    if errors:
        print(f"[WARN] Verification found {len(errors)} issue(s):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("[OK] Verification passed.")

    print()
    print("Summary:")
    print(f"  Genes from A:   {from_a}")
    print(f"  Genes from B:   {from_b}")
    print(f"  Merged genes:   {merged}")
    print(f"  Total genes:    {len(gene_map)}")
    print(f"  Parent A:       {root_a.name} v{ver_a}")
    print(f"  Parent B:       {root_b.name} v{ver_b}")
    print(f"  Offspring ver:  {_max_version(ver_a, ver_b)}")
    print(f"  Target:         {args.target}")
    print(f"  Verification:   {'PASS' if not errors else f'WARN ({len(errors)} issues)'}")
    print()
    print("Next step: run initialization inside the new offspring workspace.")


if __name__ == "__main__":
    main()
