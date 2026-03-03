#!/usr/bin/env python3
"""Self-Healing Pipeline — Hook 7: Automated Repair for FalkVelt Evolution Pipeline.

Automates mechanical infrastructure repairs collected from meditation and yoga sessions.
Five categories:
  1. version_sync   — Sync version values across Neo4j, capability-map, memory
  2. graph_repair   — Fix missing edges, phantom nodes, add IMPLEMENTS/GOVERNS
  3. memory_cleanup — Supersede stale records, add missing _source/type metadata
  4. infra_repair   — Create missing infrastructure files/directories
  5. index_repair   — Flag for protocol-manager (not auto-fixable)

Usage:
    python3 memory/scripts/self_healing.py                          # full auto-heal
    python3 memory/scripts/self_healing.py --category version_sync  # single category
    python3 memory/scripts/self_healing.py --dry-run                # preview only
    python3 memory/scripts/self_healing.py --json                   # machine output
    python3 memory/scripts/self_healing.py --max-priority P2        # P0/P1/P2 only
    python3 memory/scripts/self_healing.py --input meditation       # source filter
"""
from __future__ import annotations

import argparse
import base64
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
# Source root: 3 levels up from memory/scripts/self_healing.py
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Auto-load secrets/.env (same pattern as embedding.py)
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Load secrets/.env using os.environ.setdefault — never overrides existing vars."""
    env_path = SOURCE_ROOT / "secrets" / ".env"
    if not env_path.is_file():
        return
    with env_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_env_file()

# ---------------------------------------------------------------------------
# Neo4j / Qdrant config from environment
# ---------------------------------------------------------------------------

NEO4J_HTTP_PORT = os.environ.get("NEO4J_HTTP_PORT", "7474")
NEO4J_USERNAME  = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD  = os.environ.get("NEO4J_PASSWORD", "workflow")
NEO4J_URL       = f"http://localhost:{NEO4J_HTTP_PORT}/db/neo4j/tx/commit"

QDRANT_URL      = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = "workflow_memory"

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
# Priority ordering
# ---------------------------------------------------------------------------

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5,
                  "P6": 6, "P7": 7, "P8": 8, "P9": 9}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RepairItem:
    id: str              # "SH-{NNN}"
    priority: str        # P0-P5
    description: str     # what to fix
    source: str          # "meditation" | "yoga"
    source_id: str       # meditation session id or "yoga-report"
    category: str = ""   # assigned by classify()
    status: str = "pending"  # pending | fixed | failed | skipped | rejected | flagged
    detail: str = ""     # execution detail
    verified: bool = False

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no requests)
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: int = 8) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        raise


def http_post(
    url: str,
    body: dict,
    timeout: int = 8,
    auth: Optional[tuple[str, str]] = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth is not None:
        credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body_bytes = e.read()
            return e.code, json.loads(body_bytes) if body_bytes else {}
        except Exception:
            return e.code, {}
    except Exception:
        raise


def http_put(
    url: str,
    body: dict,
    timeout: int = 8,
    auth: Optional[tuple[str, str]] = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth is not None:
        credentials = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    req = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def neo4j_query(statement: str, parameters: dict | None = None) -> tuple[int, dict]:
    """Execute a single Cypher statement via Neo4j HTTP API."""
    payload = {
        "statements": [
            {"statement": statement, "parameters": parameters or {}}
        ]
    }
    return http_post(NEO4J_URL, payload, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# ---------------------------------------------------------------------------
# Data collection — meditation
# ---------------------------------------------------------------------------

def collect_from_meditation(path: Path) -> list[RepairItem]:
    """Parse meditation-log.md and extract recommendations from the LAST session."""
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")

    # Find all JSON code blocks (each session has one)
    json_blocks = re.findall(r"```json\s*([\s\S]*?)```", content)
    if not json_blocks:
        return []

    # Take the last session's JSON block
    last_block = json_blocks[-1]
    try:
        session = json.loads(last_block)
    except json.JSONDecodeError:
        return []

    session_id = (
        session.get("meditation_id")
        or session.get("session_id")
        or "meditation-unknown"
    )

    items: list[RepairItem] = []
    counter = [0]  # mutable counter for closures

    def make_id() -> str:
        counter[0] += 1
        return f"SH-{counter[0]:03d}"

    # Extract recommendations
    for rec in session.get("recommendations", []):
        priority = rec.get("priority", "P5")
        action   = rec.get("action", "").strip()
        if not action:
            continue
        items.append(RepairItem(
            id=make_id(),
            priority=priority,
            description=action,
            source="meditation",
            source_id=session_id,
        ))

    # Extract hard conflicts as additional items
    findings = session.get("findings", {})
    for conflict in findings.get("hard_conflicts", []):
        desc = conflict.get("description", "").strip()
        action = conflict.get("action", "").strip()
        if not desc:
            continue
        full_desc = f"{desc}" + (f" — Action: {action}" if action else "")
        # Hard conflicts are at least P1
        items.append(RepairItem(
            id=make_id(),
            priority="P1",
            description=full_desc,
            source="meditation",
            source_id=session_id,
        ))

    # Extract soft conflicts as P3 items
    for conflict in findings.get("soft_conflicts", []):
        status = conflict.get("status", "")
        # Skip conflicts that have been explicitly resolved
        if "RESOLVED" in status.upper() or "FIXED" in status.upper():
            continue
        desc = conflict.get("description", "").strip()
        if not desc:
            continue
        items.append(RepairItem(
            id=make_id(),
            priority="P3",
            description=desc,
            source="meditation",
            source_id=session_id,
        ))

    return items


# ---------------------------------------------------------------------------
# Data collection — yoga
# ---------------------------------------------------------------------------

def collect_from_yoga(path: Path) -> list[RepairItem]:
    """Parse yoga-report.md and extract tension points from PARTIAL/BLOCKED poses."""
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    items: list[RepairItem] = []
    counter = [1000]  # offset to avoid collision with meditation IDs

    def make_id() -> str:
        counter[0] += 1
        return f"SH-Y{counter[0] - 1000:03d}"

    # Find PARTIAL or BLOCKED pose sections
    # Sections look like: ## PoseName — STATUS
    section_pattern = re.compile(
        r"## (\w+) — (PARTIAL|BLOCKED)\n([\s\S]*?)(?=\n## |\Z)",
        re.MULTILINE,
    )

    for match in section_pattern.finditer(content):
        pose_name = match.group(1)
        pose_status = match.group(2)
        section_body = match.group(3)

        # Extract tension point if present
        tension_match = re.search(r"\*\*Tension point:\*\*\s*(.+)", section_body)
        if tension_match:
            tension = tension_match.group(1).strip()
            items.append(RepairItem(
                id=make_id(),
                priority="P2" if pose_status == "BLOCKED" else "P3",
                description=f"Yoga {pose_name} {pose_status}: tension point — {tension}",
                source="yoga",
                source_id="yoga-report",
            ))

        # Extract FAIL steps from the table
        fail_pattern = re.compile(r"\|\s*(.+?)\s*\|\s*FAIL\s*\|\s*(.+?)\s*\|")
        for fail_match in fail_pattern.finditer(section_body):
            step_name = fail_match.group(1).strip()
            step_detail = fail_match.group(2).strip()
            # Skip header rows
            if step_name.lower() in ("step", "---"):
                continue
            items.append(RepairItem(
                id=make_id(),
                priority="P2" if pose_status == "BLOCKED" else "P3",
                description=f"Yoga {pose_name}: FAIL step '{step_name}' — {step_detail}",
                source="yoga",
                source_id="yoga-report",
            ))

    return items


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _word_overlap(a: str, b: str) -> float:
    """Return fraction of overlapping words between two strings (Jaccard-style)."""
    words_a = set(re.split(r"\W+", a.lower())) - {"", "the", "a", "an", "is", "are", "to", "of", "in", "and", "or", "for"}
    words_b = set(re.split(r"\W+", b.lower())) - {"", "the", "a", "an", "is", "are", "to", "of", "in", "and", "or", "for"}
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union else 0.0


def deduplicate(items: list[RepairItem]) -> list[RepairItem]:
    """Remove exact duplicates and items with > 80% word overlap. Keep highest priority."""
    if not items:
        return []

    # Sort by priority ascending (P0 first)
    sorted_items = sorted(items, key=lambda x: PRIORITY_ORDER.get(x.priority, 99))
    kept: list[RepairItem] = []

    for candidate in sorted_items:
        is_duplicate = False
        for existing in kept:
            # Exact match
            if candidate.description.strip() == existing.description.strip():
                is_duplicate = True
                break
            # Word overlap > 80%
            overlap = _word_overlap(candidate.description, existing.description)
            if overlap > 0.80:
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(candidate)

    # Re-assign sequential IDs after dedup
    for i, item in enumerate(kept, 1):
        item.id = f"SH-{i:03d}"

    return kept


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "version_sync": [
        "version", "version node", "capability-map version", "workflow_version",
        "version alignment", "v1.", "v2.", "v3.", "→v", "→ v",
    ],
    "graph_repair": [
        "edge", "owns_spec", "implements", "governs", "triggers", "phantom node",
        "neo4j node", "graph", "topology", "owns_protocol", "missing edge",
        "missing bridge", "graph enrichment", "add edge", "no edge",
        "star topology", "precedes", "invoked_by", "feeds", "missing bridges",
    ],
    "memory_cleanup": [
        "stale record", "_source tag", "untagged", "supersede", "memory record",
        "type field", "type metadata", "qdrant record", "untyped", "_source=main",
        "_source=_follower_", "tag", "payload",
    ],
    "infra_repair": [
        "missing file", "missing directory", "evolve/", "request-history",
        "create directory", "create evolve", "request-history.json",
        "directory", "initial schema",
    ],
    "index_repair": [
        "claude.md index", "readme.md", "spec-registry", "protocol index",
        "ghost entries", "ghost entry", "ghost readme", "readme lists",
        "ghost file", "missing protocol", "add.*protocol.*index", "index table",
        "update.*index", "protocol table",
    ],
}

# Behavioral keywords — items with these get rejected from self-healing
_BEHAVIORAL_KEYWORDS = [
    "must rule", "must not rule", "routing change", "dispatch behavioral",
    "priority rule", "ordering", "precedence", "resolve rc-",
    "rule conflict", "rc-00", "rc-0",
]

# Protected files — items targeting these get security-rejected
_PROTECTED_FILES = [
    "build-up.md",
    "security-logging.md",
    "research_validate.py",
    "memory_write.py",
]


def classify(item: RepairItem) -> str:
    """Assign category to a repair item using keyword matching."""
    desc_lower = item.description.lower()

    # Score each category by number of keyword hits
    scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in desc_lower)
        if score > 0:
            scores[category] = score

    if not scores:
        return "infra_repair"  # safe default

    # Return highest-scoring category (ties broken by category order)
    return max(scores, key=lambda c: scores[c])


def is_behavioral(item: RepairItem) -> bool:
    """Return True if item describes a behavioral/rule change (not mechanically fixable)."""
    desc_lower = item.description.lower()
    return any(kw in desc_lower for kw in _BEHAVIORAL_KEYWORDS)


def security_check(item: RepairItem) -> bool:
    """Return False (reject) if item targets protected files or would weaken MUST rules."""
    desc_lower = item.description.lower()

    # Check for protected file targets
    for protected in _PROTECTED_FILES:
        if protected.lower() in desc_lower:
            return False

    # Reject items that would weaken MUST/MUST NOT rules
    weakening_patterns = [
        r"remove.*must",
        r"disable.*must",
        r"weaken.*rule",
        r"bypass.*rule",
        r"skip.*validation",
    ]
    for pattern in weakening_patterns:
        if re.search(pattern, desc_lower):
            return False

    return True


# ---------------------------------------------------------------------------
# Cross-session dedup: check already-fixed items in memory
# ---------------------------------------------------------------------------

def load_already_fixed() -> set[str]:
    """Query memory_search.py for previously recorded self-healing repairs."""
    already_fixed: set[str] = set()
    try:
        result = subprocess.run(
            ["python3", "memory/scripts/memory_search.py", "repair self_healing fixed", "--limit", "20"],
            capture_output=True, text=True, cwd=str(SOURCE_ROOT), timeout=15,
        )
        if result.returncode == 0:
            hits = json.loads(result.stdout)
            for hit in hits:
                memory_text = hit.get("memory", "")
                # Extract SH-NNN ids mentioned in memory records
                for sh_id in re.findall(r"SH-\d{3}", memory_text):
                    already_fixed.add(sh_id)
    except Exception:
        pass  # Non-critical — proceed without cross-session dedup
    return already_fixed


# ---------------------------------------------------------------------------
# Fix: version_sync
# ---------------------------------------------------------------------------

def fix_version_sync(item: RepairItem, dry_run: bool) -> bool:
    """Synchronize version across Neo4j VERSION node and capability-map.md."""
    # Read current version from CLAUDE.md
    claude_md = SOURCE_ROOT / "CLAUDE.md"
    if not claude_md.exists():
        item.detail = "CLAUDE.md not found"
        return False

    claude_content = claude_md.read_text(encoding="utf-8")
    version_match = re.search(r"WORKFLOW_VERSION:\s*([\d.]+)", claude_content)
    if not version_match:
        item.detail = "WORKFLOW_VERSION not found in CLAUDE.md"
        return False

    current_version = version_match.group(1).strip()

    actions: list[str] = []
    success = True

    # Check Neo4j VERSION node
    try:
        status_code, response = neo4j_query(
            "MATCH (f {name:'falkvelt'})-[:VERSION]->(v) RETURN v.name AS version"
        )
        if status_code == 200:
            results = response.get("results", [])
            rows = results[0].get("data", []) if results else []
            if rows:
                neo4j_version = str(rows[0].get("row", [None])[0] or "").lstrip("v")
                if neo4j_version != current_version:
                    # Update Neo4j
                    if dry_run:
                        actions.append(f"[DRY RUN] Would update Neo4j VERSION {neo4j_version} → v{current_version}")
                    else:
                        upd_code, _ = neo4j_query(
                            "MATCH (f {name:'falkvelt'})-[:VERSION]->(v) SET v.name = $version",
                            {"version": f"v{current_version}"},
                        )
                        if upd_code == 200:
                            # Verify
                            verify_code, verify_resp = neo4j_query(
                                "MATCH (f {name:'falkvelt'})-[:VERSION]->(v) RETURN v.name AS version"
                            )
                            verify_rows = (verify_resp.get("results", [{}])[0].get("data", []))
                            if verify_rows:
                                new_val = str(verify_rows[0].get("row", [None])[0] or "").lstrip("v")
                                if new_val == current_version:
                                    actions.append(f"Neo4j VERSION: {neo4j_version} → v{current_version} (verified)")
                                else:
                                    actions.append(f"Neo4j VERSION update unverified (got {new_val})")
                                    success = False
                            else:
                                actions.append("Neo4j VERSION node not found after update")
                                success = False
                        else:
                            actions.append(f"Neo4j VERSION update failed (HTTP {upd_code})")
                            success = False
                else:
                    actions.append(f"Neo4j VERSION already v{current_version} (OK)")
            else:
                actions.append("Neo4j: no VERSION node found for falkvelt — skipping")
        else:
            actions.append(f"Neo4j query failed (HTTP {status_code})")
            success = False
    except Exception as e:
        actions.append(f"Neo4j unreachable: {e}")
        # Not a hard failure — may be offline

    # Check capability-map.md version
    cap_map = SOURCE_ROOT / "docs" / "self-architecture" / "capability-map.md"
    if cap_map.exists():
        cap_content = cap_map.read_text(encoding="utf-8")
        cap_version_match = re.search(r"\*\*Version:\*\*\s*([\d.]+)", cap_content)
        if cap_version_match:
            cap_version = cap_version_match.group(1).strip()
            if cap_version != current_version:
                if dry_run:
                    actions.append(f"[DRY RUN] Would update capability-map v{cap_version} → v{current_version}")
                else:
                    new_cap_content = cap_content.replace(
                        f"**Version:** {cap_version}",
                        f"**Version:** {current_version}",
                        1,
                    )
                    cap_map.write_text(new_cap_content, encoding="utf-8")
                    # Verify
                    verify_content = cap_map.read_text(encoding="utf-8")
                    if f"**Version:** {current_version}" in verify_content:
                        actions.append(f"capability-map: v{cap_version} → v{current_version} (verified)")
                        item.verified = True
                    else:
                        actions.append(f"capability-map update failed to verify")
                        success = False
            else:
                actions.append(f"capability-map version already {current_version} (OK)")
                item.verified = True
        else:
            actions.append("capability-map: no version header found")
    else:
        actions.append("capability-map.md not found — skipping")

    item.detail = "; ".join(actions)
    return success


# ---------------------------------------------------------------------------
# Fix: graph_repair
# ---------------------------------------------------------------------------

def fix_graph_repair(item: RepairItem, dry_run: bool) -> bool:
    """Fix missing edges or phantom nodes in Neo4j."""
    desc_lower = item.description.lower()
    actions: list[str] = []

    # Detect what kind of graph repair is needed
    cypher_statements: list[tuple[str, dict, str]] = []  # (statement, params, description)

    # OWNS_SPEC edge repair
    owns_spec_match = re.search(r"spec-([\w-]+)\s+(?:missing\s+)?owns_spec", desc_lower)
    if owns_spec_match:
        spec_name = "spec-" + owns_spec_match.group(1)
        cypher_statements.append((
            "MATCH (a {name:'falkvelt'}), (s:Spec {name:$spec}) MERGE (a)-[:OWNS_SPEC]->(s) RETURN count(*) AS created",
            {"spec": spec_name},
            f"OWNS_SPEC edge for {spec_name}",
        ))

    # IMPLEMENTS edge repair (agents → specs)
    if "implements" in desc_lower and "edge" in desc_lower:
        # Generic: add IMPLEMENTS edges from all agents to their relevant specs
        # Parse agent and spec from description if possible
        impl_match = re.search(r"([\w-]+)\s+implements\s+(spec-[\w-]+)", desc_lower)
        if impl_match:
            agent_name = impl_match.group(1)
            spec_name  = impl_match.group(2)
            cypher_statements.append((
                "MATCH (a {name:$agent}), (s {name:$spec}) MERGE (a)-[:IMPLEMENTS]->(s) RETURN count(*) AS created",
                {"agent": agent_name, "spec": spec_name},
                f"IMPLEMENTS edge {agent_name}→{spec_name}",
            ))
        else:
            # No specific agent/spec — flag as too ambiguous for auto-fix
            item.detail = "IMPLEMENTS edge repair requires specific agent+spec names — flagged for manual fix"
            item.status = "skipped"
            return False

    # GOVERNS edge repair
    if "governs" in desc_lower and "edge" in desc_lower:
        gov_match = re.search(r"(spec-[\w-]+)\s+governs\s+([\w-]+)", desc_lower)
        if gov_match:
            spec_name     = gov_match.group(1)
            protocol_name = gov_match.group(2)
            cypher_statements.append((
                "MATCH (s {name:$spec}), (p {name:$protocol}) MERGE (s)-[:GOVERNS]->(p) RETURN count(*) AS created",
                {"spec": spec_name, "protocol": protocol_name},
                f"GOVERNS edge {spec_name}→{protocol_name}",
            ))

    # Phantom node removal (OkiAra phantom agents)
    if "phantom" in desc_lower:
        if "okiara" in desc_lower:
            cypher_statements.append((
                "MATCH (n) WHERE n.name CONTAINS 'okiara' AND NOT n.name = 'okiara' DELETE n RETURN count(*) AS deleted",
                {},
                "Remove phantom OkiAra nodes",
            ))
        else:
            item.detail = "Phantom node removal requires specific node names — flagged for manual fix"
            item.status = "skipped"
            return False

    # capability_map node label fix
    if "capability_map" in desc_lower and "label" in desc_lower:
        cypher_statements.append((
            "MATCH (n {name:'capability_map'}) WHERE size(labels(n)) = 0 SET n:CapabilityMap RETURN count(*) AS updated",
            {},
            "Add CapabilityMap label to capability_map node",
        ))

    # _source tag on agent nodes
    if "_source tag" in desc_lower and ("agent" in desc_lower or "falkvelt" in desc_lower):
        cypher_statements.append((
            "MATCH (f {name:'falkvelt'})-[:OWNS]-(a) WHERE a._source IS NULL SET a._source = '_follower_' RETURN count(*) AS updated",
            {},
            "Add _source tag to FalkVelt agent nodes",
        ))

    if not cypher_statements:
        item.detail = "Could not determine specific graph repair — needs manual intervention"
        item.status = "skipped"
        return False

    success = True
    for statement, params, description in cypher_statements:
        if dry_run:
            actions.append(f"[DRY RUN] Would execute: {description}")
        else:
            try:
                status_code, response = neo4j_query(statement, params)
                if status_code == 200:
                    results = response.get("results", [])
                    errors  = response.get("errors", [])
                    if errors:
                        actions.append(f"Neo4j error for {description}: {errors[0].get('message', '')[:80]}")
                        success = False
                    else:
                        actions.append(f"OK: {description}")
                        item.verified = True
                else:
                    actions.append(f"HTTP {status_code} for {description}")
                    success = False
            except Exception as e:
                actions.append(f"Exception for {description}: {e}")
                success = False

    item.detail = "; ".join(actions)
    return success


# ---------------------------------------------------------------------------
# Fix: memory_cleanup
# ---------------------------------------------------------------------------

def fix_memory_cleanup(item: RepairItem, dry_run: bool) -> bool:
    """Tag untagged Qdrant records, supersede stale records, add type field."""
    desc_lower = item.description.lower()
    actions: list[str] = []
    success = True

    # Fix missing _source tag
    if "_source" in desc_lower and ("tag" in desc_lower or "untagged" in desc_lower or "_follower_" in desc_lower):
        # Scroll records without _source
        try:
            scroll_body: dict = {
                "filter": {
                    "must_not": [
                        {"key": "metadata._source", "match": {"any": ["_follower_", "main"]}}
                    ]
                },
                "limit": 100,
                "with_payload": True,
            }
            status_code, response = http_post(
                f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
                scroll_body,
            )
            if status_code == 200:
                points = response.get("result", {}).get("points", [])
                ids_to_tag = [p["id"] for p in points if p.get("id")]
                if ids_to_tag:
                    if dry_run:
                        actions.append(f"[DRY RUN] Would add _source=_follower_ to {len(ids_to_tag)} records")
                    else:
                        # Use Qdrant set_payload API
                        payload_body = {
                            "payload": {"metadata": {"_source": "_follower_"}},
                            "points": ids_to_tag,
                        }
                        upd_code, _ = http_post(
                            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
                            payload_body,
                        )
                        if upd_code in (200, 201):
                            actions.append(f"Tagged {len(ids_to_tag)} records with _source=_follower_")
                            item.verified = True
                        else:
                            actions.append(f"Failed to tag records (HTTP {upd_code})")
                            success = False
                else:
                    actions.append("All records already have _source tag (OK)")
                    item.verified = True
            else:
                actions.append(f"Qdrant scroll failed (HTTP {status_code})")
                success = False
        except Exception as e:
            actions.append(f"Qdrant unreachable: {e}")
            success = False

    # Fix _source=main → _source=_follower_
    elif "_source=main" in desc_lower or "source=main" in desc_lower:
        try:
            scroll_body = {
                "filter": {
                    "must": [
                        {"key": "metadata._source", "match": {"value": "main"}}
                    ]
                },
                "limit": 100,
                "with_payload": True,
            }
            status_code, response = http_post(
                f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
                scroll_body,
            )
            if status_code == 200:
                points = response.get("result", {}).get("points", [])
                ids_to_fix = [p["id"] for p in points]
                if ids_to_fix:
                    if dry_run:
                        actions.append(f"[DRY RUN] Would update {len(ids_to_fix)} records: _source=main → _source=_follower_")
                    else:
                        payload_body = {
                            "payload": {"metadata": {"_source": "_follower_"}},
                            "points": ids_to_fix,
                        }
                        upd_code, _ = http_post(
                            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
                            payload_body,
                        )
                        if upd_code in (200, 201):
                            actions.append(f"Updated {len(ids_to_fix)} records: _source=main → _follower_")
                            item.verified = True
                        else:
                            actions.append(f"Payload update failed (HTTP {upd_code})")
                            success = False
                else:
                    actions.append("No _source=main records found (OK)")
                    item.verified = True
            else:
                actions.append(f"Qdrant scroll failed (HTTP {status_code})")
                success = False
        except Exception as e:
            actions.append(f"Qdrant unreachable: {e}")
            success = False

    # Fix type field missing
    elif "type" in desc_lower and ("untyped" in desc_lower or "type field" in desc_lower or "type metadata" in desc_lower):
        try:
            # Scroll records without type in metadata
            scroll_body = {
                "filter": {
                    "must_not": [
                        {"has_id": []},  # placeholder — Qdrant doesn't have "field absent" filter directly
                    ]
                },
                "limit": 100,
                "with_payload": True,
            }
            # Simpler approach: scroll all and filter in Python
            scroll_body_all: dict = {"limit": 100, "with_payload": True}
            status_code, response = http_post(
                f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
                scroll_body_all,
            )
            if status_code == 200:
                points = response.get("result", {}).get("points", [])
                untyped_ids = []
                for p in points:
                    payload = p.get("payload", {})
                    metadata = payload.get("metadata") or {}
                    if not metadata.get("type"):
                        untyped_ids.append(p["id"])
                if untyped_ids:
                    if dry_run:
                        actions.append(f"[DRY RUN] Would add type='knowledge' to {len(untyped_ids)} untyped records")
                    else:
                        payload_body = {
                            "payload": {"metadata": {"type": "knowledge"}},
                            "points": untyped_ids,
                        }
                        upd_code, _ = http_post(
                            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
                            payload_body,
                        )
                        if upd_code in (200, 201):
                            actions.append(f"Added type='knowledge' to {len(untyped_ids)} records")
                            item.verified = True
                        else:
                            actions.append(f"Type update failed (HTTP {upd_code})")
                            success = False
                else:
                    actions.append("All records already have type field (OK)")
                    item.verified = True
            else:
                actions.append(f"Qdrant scroll failed (HTTP {status_code})")
                success = False
        except Exception as e:
            actions.append(f"Qdrant unreachable: {e}")
            success = False

    # Supersede stale records
    elif "supersede" in desc_lower or "stale record" in desc_lower:
        # Extract point IDs from description (8-char hex patterns like 97d702d2)
        point_ids = re.findall(r"\b([0-9a-f]{8})\b", item.description.lower())
        if point_ids:
            if dry_run:
                actions.append(f"[DRY RUN] Would mark {len(point_ids)} records as superseded: {', '.join(point_ids)}")
            else:
                # Mark as superseded via payload update
                payload_body = {
                    "payload": {"metadata": {"status": "superseded", "superseded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}},
                    "points": point_ids,
                }
                try:
                    upd_code, _ = http_post(
                        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
                        payload_body,
                    )
                    if upd_code in (200, 201):
                        actions.append(f"Marked {len(point_ids)} records as superseded")
                        item.verified = True
                    else:
                        actions.append(f"Supersede update failed (HTTP {upd_code})")
                        success = False
                except Exception as e:
                    actions.append(f"Qdrant unreachable: {e}")
                    success = False
        else:
            actions.append("No specific record IDs found in description — needs manual review")
            item.status = "skipped"
            success = False
    else:
        actions.append("Memory cleanup action not recognized — needs manual review")
        item.status = "skipped"
        success = False

    item.detail = "; ".join(actions)
    return success


# ---------------------------------------------------------------------------
# Fix: infra_repair
# ---------------------------------------------------------------------------

def fix_infra_repair(item: RepairItem, dry_run: bool) -> bool:
    """Create missing infrastructure files or directories."""
    desc_lower = item.description.lower()
    actions: list[str] = []
    success = True

    # evolve/ directory
    if "evolve/" in desc_lower or "evolve/" in item.description or "evolve directory" in desc_lower:
        evolve_dir = SOURCE_ROOT / "evolve"
        if not evolve_dir.exists():
            if dry_run:
                actions.append(f"[DRY RUN] Would create directory: {evolve_dir}")
            else:
                try:
                    evolve_dir.mkdir(parents=True, exist_ok=True)
                    if evolve_dir.exists():
                        actions.append(f"Created directory: evolve/")
                        item.verified = True
                    else:
                        actions.append("Directory creation unverified")
                        success = False
                except Exception as e:
                    actions.append(f"Failed to create evolve/: {e}")
                    success = False
        else:
            actions.append("evolve/ already exists (OK)")
            item.verified = True

    # request-history.json
    if "request-history" in desc_lower or "request-history.json" in desc_lower:
        # Check both common locations
        candidate_paths = [
            SOURCE_ROOT / "evolve" / "request-history.json",
            SOURCE_ROOT / "docs" / "self-architecture" / "request-history.json",
        ]
        target_path = candidate_paths[0]  # prefer evolve/
        existing = [p for p in candidate_paths if p.exists()]
        if existing:
            actions.append(f"request-history.json already exists at {existing[0].relative_to(SOURCE_ROOT)} (OK)")
            item.verified = True
        else:
            if dry_run:
                actions.append(f"[DRY RUN] Would create: {target_path.relative_to(SOURCE_ROOT)}")
            else:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    initial_content = json.dumps(
                        {
                            "schema_version": "1.0",
                            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "entries": [],
                        },
                        indent=2,
                    )
                    target_path.write_text(initial_content, encoding="utf-8")
                    if target_path.exists():
                        actions.append(f"Created request-history.json at evolve/")
                        item.verified = True
                    else:
                        actions.append("request-history.json creation unverified")
                        success = False
                except Exception as e:
                    actions.append(f"Failed to create request-history.json: {e}")
                    success = False

    # Generic missing directory
    dir_match = re.search(r"create (?:directory|dir)[:\s]+([^\s.]+)", desc_lower)
    if dir_match and "evolve" not in dir_match.group(1):
        dir_name = dir_match.group(1).strip("/")
        target_dir = SOURCE_ROOT / dir_name
        if not target_dir.exists():
            if dry_run:
                actions.append(f"[DRY RUN] Would create directory: {dir_name}/")
            else:
                try:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if target_dir.exists():
                        actions.append(f"Created directory: {dir_name}/")
                        item.verified = True
                    else:
                        actions.append(f"Directory {dir_name}/ creation unverified")
                        success = False
                except Exception as e:
                    actions.append(f"Failed to create {dir_name}/: {e}")
                    success = False
        else:
            actions.append(f"{dir_name}/ already exists (OK)")
            item.verified = True

    if not actions:
        actions.append("Infra repair action not recognized — needs manual review")
        item.status = "skipped"
        success = False

    item.detail = "; ".join(actions)
    return success


# ---------------------------------------------------------------------------
# Flag: index_repair
# ---------------------------------------------------------------------------

def flag_index_repair(item: RepairItem) -> RepairItem:
    """Mark index_repair items as flagged — requires protocol-manager subagent."""
    item.status = "flagged"
    item.detail = "Needs protocol-manager subagent (CLAUDE.md / README.md / spec-registry edits)"
    return item


# ---------------------------------------------------------------------------
# Execute a single repair item
# ---------------------------------------------------------------------------

def execute_item(item: RepairItem, dry_run: bool) -> RepairItem:
    """Route item to correct fix function based on category."""
    if item.category == "index_repair":
        return flag_index_repair(item)

    fix_fn = {
        "version_sync":   fix_version_sync,
        "graph_repair":   fix_graph_repair,
        "memory_cleanup": fix_memory_cleanup,
        "infra_repair":   fix_infra_repair,
    }.get(item.category)

    if fix_fn is None:
        item.status = "skipped"
        item.detail = f"Unknown category: {item.category}"
        return item

    try:
        success = fix_fn(item, dry_run)
        if item.status not in ("skipped", "rejected", "flagged"):
            item.status = "fixed" if success else "failed"
    except Exception as e:
        item.status = "failed"
        item.detail = f"Unhandled exception: {e}"

    return item


# ---------------------------------------------------------------------------
# Terminal rendering
# ---------------------------------------------------------------------------

def print_item_result(item: RepairItem) -> None:
    status_fn = {
        "fixed":    GREEN,
        "failed":   RED,
        "skipped":  YELLOW,
        "flagged":  CYAN,
        "rejected": DIM,
    }.get(item.status, BOLD)

    print(
        f"  {BOLD(f'[{item.category}]')} {DIM(item.id)} {BOLD(item.priority)}: "
        + item.description[:80]
        + ("..." if len(item.description) > 80 else "")
    )
    if item.detail:
        print(f"    {status_fn(item.detail)}")


def print_summary(items: list[RepairItem]) -> None:
    fixed    = sum(1 for i in items if i.status == "fixed")
    failed   = sum(1 for i in items if i.status == "failed")
    skipped  = sum(1 for i in items if i.status == "skipped")
    flagged  = sum(1 for i in items if i.status == "flagged")
    rejected = sum(1 for i in items if i.status == "rejected")

    print()
    print(BOLD("  Summary"))
    parts = [
        f"Fixed: {GREEN(str(fixed))}",
        f"Failed: {RED(str(failed))}",
        f"Skipped: {YELLOW(str(skipped))}",
        f"Flagged: {CYAN(str(flagged))}",
        f"Rejected: {DIM(str(rejected))}",
    ]
    print("  " + "  ".join(parts))
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description="Self-Healing Pipeline — Hook 7: automated infrastructure repairs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 memory/scripts/self_healing.py\n"
            "  python3 memory/scripts/self_healing.py --category version_sync\n"
            "  python3 memory/scripts/self_healing.py --dry-run\n"
            "  python3 memory/scripts/self_healing.py --json\n"
            "  python3 memory/scripts/self_healing.py --max-priority P2\n"
            "  python3 memory/scripts/self_healing.py --input meditation\n"
        ),
    )
    parser.add_argument(
        "--category", "-c",
        choices=["version_sync", "graph_repair", "memory_cleanup", "infra_repair", "index_repair"],
        help="Run a single repair category only.",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview repairs without making changes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of terminal display.",
    )
    parser.add_argument(
        "--max-priority",
        default="P2",
        metavar="P0-P9",
        help="Only process items at or above this priority (default: P2).",
    )
    parser.add_argument(
        "--input",
        choices=["meditation", "yoga", "both"],
        default="meditation",
        help="Source to collect repair items from (default: meditation).",
    )
    args = parser.parse_args()

    if args.json_output:
        USE_COLOR = False

    # Validate --max-priority
    max_prio = args.max_priority.upper()
    if max_prio not in PRIORITY_ORDER:
        print(f"Invalid --max-priority: {args.max_priority}. Use P0-P9.", file=sys.stderr)
        sys.exit(1)
    max_prio_value = PRIORITY_ORDER[max_prio]

    # --- Header ---
    if not args.json_output:
        print()
        print(BOLD("  Self-Healing Pipeline"))
        print(DIM(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}"))
        if args.dry_run:
            print(YELLOW("  [DRY RUN] No changes will be made"))
        print()

    # --- Collect ---
    med_log  = SOURCE_ROOT / "docs" / "self-architecture" / "meditation-log.md"
    yoga_rep = SOURCE_ROOT / "docs" / "self-architecture" / "yoga-report.md"

    all_items: list[RepairItem] = []
    collection_notes: list[str] = []

    if args.input in ("meditation", "both"):
        if not args.json_output:
            print(DIM("  Collecting from meditation..."))
        med_items = collect_from_meditation(med_log)
        if med_items:
            session_id = med_items[0].source_id if med_items else "unknown"
            note = f"{len(med_items)} items from {session_id}"
        else:
            note = "0 items (file missing or no JSON block)"
        collection_notes.append(f"meditation: {note}")
        if not args.json_output:
            print(f"    {note}")
        all_items.extend(med_items)

    if args.input in ("yoga", "both"):
        if not args.json_output:
            print(DIM("  Collecting from yoga..."))
        yoga_items = collect_from_yoga(yoga_rep)
        note = f"{len(yoga_items)} items from yoga report"
        collection_notes.append(f"yoga: {note}")
        if not args.json_output:
            print(f"    {note}")
        all_items.extend(yoga_items)

    # --- Dedup ---
    deduped = deduplicate(all_items)
    if not args.json_output:
        print()
        print(f"  After dedup: {BOLD(str(len(deduped)))} items")

    # --- Priority filter ---
    priority_filtered = [
        i for i in deduped
        if PRIORITY_ORDER.get(i.priority, 99) <= max_prio_value
    ]
    if not args.json_output:
        print(f"  After priority filter ({max_prio} and above): {BOLD(str(len(priority_filtered)))} items")

    # --- Behavioral filter ---
    behavioral_rejected: list[RepairItem] = []
    behavioral_passed:   list[RepairItem] = []
    for item in priority_filtered:
        if is_behavioral(item):
            item.status   = "rejected"
            item.detail   = "Behavioral change — send to build-up protocol"
            item.category = "behavioral"
            behavioral_rejected.append(item)
        else:
            behavioral_passed.append(item)

    if not args.json_output:
        print(
            f"  After behavioral filter: {BOLD(str(len(behavioral_passed)))} items "
            f"({len(behavioral_rejected)} rejected → build-up)"
        )

    # --- Security check ---
    security_blocked:  list[RepairItem] = []
    security_passed:   list[RepairItem] = []
    for item in behavioral_passed:
        if security_check(item):
            security_passed.append(item)
        else:
            item.status = "rejected"
            item.detail = "Security check failed — targets protected file or weakens MUST rule"
            security_blocked.append(item)

    if not args.json_output:
        print(
            f"  After security check: {BOLD(str(len(security_passed)))} items "
            f"({len(security_blocked)} blocked)"
        )

    # --- Classify ---
    for item in security_passed:
        item.category = classify(item)

    # --- Category filter ---
    if args.category:
        security_passed = [i for i in security_passed if i.category == args.category]
        if not args.json_output:
            print(f"  Category filter ({args.category}): {len(security_passed)} items")

    # --- Cross-session dedup (check already-fixed) ---
    already_fixed = load_already_fixed()
    previously_fixed: list[RepairItem] = []
    to_execute: list[RepairItem] = []
    for item in security_passed:
        if item.id in already_fixed:
            item.status = "skipped"
            item.detail = "Already fixed in a previous session (memory record found)"
            previously_fixed.append(item)
        else:
            to_execute.append(item)

    if previously_fixed and not args.json_output:
        print(f"  Cross-session dedup: {len(previously_fixed)} already fixed, {len(to_execute)} remaining")

    # --- Execute repairs ---
    if not args.json_output and to_execute:
        print()
        print(BOLD("  Executing repairs..."))
        print()

    # Execution order: version_sync first, then graph, memory, infra, index
    CATEGORY_ORDER = ["version_sync", "graph_repair", "memory_cleanup", "infra_repair", "index_repair"]

    def sort_key(item: RepairItem) -> tuple[int, int]:
        cat_rank = CATEGORY_ORDER.index(item.category) if item.category in CATEGORY_ORDER else 99
        prio_rank = PRIORITY_ORDER.get(item.priority, 99)
        return (cat_rank, prio_rank)

    to_execute.sort(key=sort_key)

    executed: list[RepairItem] = []
    for item in to_execute:
        if not args.json_output:
            print_item_result(item)
        execute_item(item, args.dry_run)
        executed.append(item)
        if not args.json_output:
            # Print result detail (updated after execute)
            status_fn = {
                "fixed":    GREEN,
                "failed":   RED,
                "skipped":  YELLOW,
                "flagged":  CYAN,
                "rejected": DIM,
            }.get(item.status, BOLD)
            if item.detail:
                # detail already printed in execute — reprint with status color
                pass  # detail was printed by print_item_result before execute; update below
            status_label = item.status.upper()
            print(f"    → {status_fn(status_label)}: {item.detail}")
            print()

    # Combine all items for output
    all_processed = (
        executed
        + previously_fixed
        + security_blocked
        + behavioral_rejected
        + [i for i in deduped if i not in priority_filtered]  # filtered by priority
    )

    # --- Output ---
    if args.json_output:
        fixed    = sum(1 for i in all_processed if i.status == "fixed")
        failed   = sum(1 for i in all_processed if i.status == "failed")
        skipped  = sum(1 for i in all_processed if i.status in ("skipped",))
        flagged  = sum(1 for i in all_processed if i.status == "flagged")
        rejected = sum(1 for i in all_processed if i.status == "rejected")
        output = {
            "items": [asdict(i) for i in all_processed],
            "summary": {
                "fixed": fixed,
                "failed": failed,
                "skipped": skipped,
                "flagged": flagged,
                "rejected": rejected,
                "total_collected": len(all_items),
                "after_dedup": len(deduped),
                "after_priority_filter": len(priority_filtered),
            },
            "collection": collection_notes,
            "dry_run": args.dry_run,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(all_processed)

    # Exit code: 0 = all fixed/flagged/skipped, 1 = any failures
    any_failed = any(i.status == "failed" for i in all_processed)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
