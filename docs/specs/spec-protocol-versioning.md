# Spec: Protocol Versioning & Conflict Detection

**Status:** PROPOSED
**Domain:** Exchange Security — Protocol Integrity (P6 + P8)
**Created:** 2026-03-03
**Related files:** `protocols/agents/protocol-exchange.md`, `docs/self-architecture/spec-registry.json`

---

## Problem Statement

The `protocol_proposal` payload in `protocols/agents/protocol-exchange.md` carries no version field and no identity hash. When both agents independently modify the same protocol, the receiver has no mechanism to detect divergence — it cannot tell whether the incoming proposal supersedes its own local copy or conflicts with it. Additionally, there is no dependency field: a protocol that requires another protocol to be present first can be adopted without that prerequisite ever being checked.

Three concrete failure modes:

1. **Silent overwrite** — FalkVelt and OkiAra both evolve `evolution.md` independently. OkiAra proposes its version. FalkVelt receives it, finds the file already exists, and has no basis to decide which copy is authoritative. Current protocol says "adopted" or "rejected" — no conflict branch exists.

2. **Orphaned adoption** — A proposed protocol references behavioral rules defined in another protocol that the receiver has not yet adopted. The receiver adopts it anyway. The protocol is internally inconsistent on the receiving workspace.

3. **Version drift** — After repeated exchanges, the two agents hold diverging copies of the same protocol with no record of when they diverged or what the delta is.

---

## Current State

### Payload schema (`protocols/agents/protocol-exchange.md`, lines 18–27)

```json
{
  "action": "protocol_proposal",
  "protocol_name": "name",
  "category": "core/agents/knowledge/quality/project",
  "content": "full protocol text",
  "requires_adaptation": true,
  "adaptation_notes": "notes"
}
```

Six fields. No version. No hash. No dependency list. No workflow version constraint.

### Receiver decision path (`protocols/agents/protocol-exchange.md`, lines 36–47)

Three outcomes: `accepted`, `adapted`, `rejected`. No `conflict` branch. No dependency check step. No version comparison step.

---

## Extended Proposal Payload

```json
{
  "action": "protocol_proposal",
  "protocol_name": "name",
  "category": "core/agents/knowledge/quality/project",
  "content": "full protocol text",
  "protocol_version": "1.0.0",
  "content_hash": "sha256:<64-char-hex>",
  "requires_adaptation": false,
  "adaptation_notes": "notes",
  "requires": ["protocol-A", "protocol-B"],
  "min_workflow_version": "1.50"
}
```

### New field semantics

| Field | Type | Purpose |
|---|---|---|
| `protocol_version` | semver string | Human-readable version, maintained by author. Communicates intent (breaking/minor/patch). |
| `content_hash` | `"sha256:<hex>"` | Content-addressable identity. Two files with identical content always share one hash. Deterministic conflict detection. |
| `requires` | string[] | List of `protocol_name` values this protocol depends on. Checked before adoption. Empty list = no dependencies. |
| `min_workflow_version` | semver string | Minimum `WORKFLOW_VERSION` in CLAUDE.md required to use this protocol. Prevents adoption on incompatible workspaces. |

---

## Content Hash Computation

### Algorithm

```
content_hash = "sha256:" + SHA-256(UTF-8 bytes of content field).hex()
```

The hash is computed from the raw `content` string exactly as it would be written to disk — no normalization except stripping a trailing newline if present (to make file-on-disk and protocol-in-payload produce the same hash regardless of text editor behavior).

### Canonical form

```python
import hashlib

def compute_protocol_hash(content: str) -> str:
    normalized = content.rstrip("\n")
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

### Properties

- **Deterministic** — same content always produces the same hash. Identical protocols across workspaces share one hash regardless of origin. This is the core property of content-addressable storage, well-established in systems such as Git (blob objects), IPFS, and OCI container registries.
- **Tamper-evident** — any character change produces a completely different hash.
- **Prefix-typed** — `sha256:` prefix leaves room for algorithm migration without breaking existing consumers (pattern used by Docker image digests and OCI spec).

---

## Semantic Versioning for Behavioral Protocols

SemVer (semver.org) defines `MAJOR.MINOR.PATCH`. Applied to behavioral protocol specs:

| Increment | Meaning in protocol context |
|---|---|
| **MAJOR** | Breaking behavioral change — removes a step, changes a decision outcome, renames fields, removes rules. Adopting agent must consciously review. |
| **MINOR** | Backward-compatible addition — new optional step, new field, new rule that does not conflict with existing behavior. Safe to auto-suggest but not auto-adopt. |
| **PATCH** | Clarification, typo fix, documentation-only change — zero behavioral difference. Content hash will still differ; version communicates it is minor. |

Version is informational for the human coordinator. The hash is the definitive identity marker. When hash matches but versions differ, that indicates two agents independently assigned version labels to identical content — harmless, no conflict.

---

## Conflict Detection Algorithm (Receiver)

On receiving a `protocol_proposal` message, the receiver executes this sequence before the existing accept/adapt/reject decision:

```
1. LOAD PROPOSAL: extract protocol_name, category, content, protocol_version, content_hash, requires, min_workflow_version

2. WORKFLOW VERSION CHECK:
   a. Read WORKFLOW_VERSION from CLAUDE.md header
   b. If min_workflow_version present AND local_version < min_workflow_version:
      → respond: rejected, reason="workflow version too low: need X.XX, have Y.YY"
      → STOP

3. DEPENDENCY CHECK:
   a. For each name in requires[]:
      i. Check if protocols/{*}/{name}.md exists on local filesystem
   b. If any missing:
      → respond: rejected, reason="missing dependency: [name1, name2]"
      → STOP (or request nested proposal — see §Dependency Resolution Flow)

4. CONFLICT DETECTION:
   a. Locate local file: protocols/{category}/{protocol_name}.md
   b. If file does NOT exist:
      → no conflict → proceed to standard accept/adapt/reject decision
   c. If file exists:
      i. Read file content
      ii. Compute local_hash = compute_protocol_hash(file_content)
      iii. Compare local_hash vs incoming content_hash:
           - MATCH → no conflict → proceed to standard decision
           - MISMATCH → CONFLICT state → see §Conflict Resolution

5. STANDARD DECISION: accepted / adapted / rejected (existing protocol-exchange.md flow)
```

### Conflict Resolution

When `local_hash != content_hash`:

The receiver MUST NOT silently overwrite. Conflict handling is always a manual coordinator decision during interactive session. In watcher mode: queue the proposal with state `conflicted` for interactive review.

Response to sender:

```json
{
  "action": "protocol_response",
  "decision": "conflict",
  "protocol_name": "name",
  "local_version": "1.2.0",
  "local_hash": "sha256:<local-hex>",
  "incoming_version": "1.3.0",
  "incoming_hash": "sha256:<incoming-hex>",
  "resolution": "pending_manual_review"
}
```

The coordinator reviews both versions and selects one of three resolutions:

| Resolution | Action |
|---|---|
| `accept_incoming` | Overwrite local file with incoming content. Update memory record. Register update in CLAUDE.md and README. |
| `keep_local` | Discard incoming proposal. Respond with `rejected`, include reason and local hash. |
| `manual_merge` | Coordinator edits a merged version. Computes new hash for merged file. Responds with `adapted` + merged content + new hash. |

Version comparison (sender.version vs local.version) is advisory context for this decision, not binding. A lower incoming version does not automatically mean "reject" — the coordinator may prefer the incoming content regardless of version label.

---

## Dependency Resolution Flow

When a proposal is rejected due to missing dependencies, the receiver notifies the sender. The sender may then include nested proposals:

**Option A — Explicit rejection (simple):**
Receiver responds `rejected`, reason lists missing protocol names. Sender decides whether to propose the dependencies first in separate messages, then retry the original proposal.

**Option B — Nested proposal (advanced, optional):**
Sender may include an optional `nested_proposals` array in the original message body (not in the payload field — as separate exchange messages sent before the dependent proposal). Receiver processes dependencies first, then the dependent protocol.

For the current 2-agent local system, Option A is sufficient. Option B is deferred.

### Dependency order recommendation

When a sender knows protocol B depends on protocol A, the sender SHOULD send protocol A's proposal first and wait for acceptance before sending B's proposal. This is the topological ordering principle: in a directed acyclic graph of dependencies, nodes with no incoming edges (no dependencies) are processed first. The exchange message queue naturally serializes this if sent in dependency order.

Circular dependencies (`A requires B`, `B requires A`) are prohibited. A receiver that detects a circular dependency in its local dependency graph MUST reject with `reason="circular dependency detected"`.

---

## Conditional Activation via min_workflow_version

`min_workflow_version` allows protocol authors to gate adoption on workflow maturity:

```
Example: min_workflow_version = "1.50"

Receiver CLAUDE.md has WORKFLOW_VERSION: 1.42
→ 1.42 < 1.50 → rejected: "workflow version too low"

Receiver CLAUDE.md has WORKFLOW_VERSION: 1.55
→ 1.55 >= 1.50 → version check passes, continue
```

Version comparison is numeric-semver (not string lexicographic). Implemented as:

```python
from packaging.version import Version

def version_sufficient(local: str, required: str) -> bool:
    return Version(local) >= Version(required)
```

If `min_workflow_version` is absent from the proposal, the field is treated as `"0.0.0"` — no constraint.

---

## Protocol Registry Recommendation

### The question

Should there be a `docs/self-architecture/protocol-registry.json` analogous to `spec-registry.json`, storing: `{name, category, version, content_hash, last_modified, origin, import_from}`?

### Analysis

**Arguments for:**
- Fast conflict detection without filesystem scan (hash lookup is O(1) vs O(n) file reads)
- Tracks provenance (origin: local vs imported, import_from: workspace name)
- Enables version history if registry is append-only
- Consistent with spec-registry.json pattern already in use

**Arguments against:**
- Additional file to maintain — must be updated every time a protocol is adopted, modified, or deleted
- Risk of registry diverging from filesystem (registry says version X, file on disk is version Y)
- For only 20 protocols across 2 agents, filesystem scan is not a performance problem
- Content hashes can always be recomputed on demand; registry is purely a cache

### Decision: DEFER with conditional

For the current system (20 protocols, 2 agents, local filesystem), on-demand hash computation from the filesystem is sufficient. A registry would add maintenance burden without meaningful performance benefit.

**Conditional adoption trigger:** If the protocol count exceeds 50, or if a third agent/workspace is added, create the registry. The schema is defined here for when that threshold is reached:

```json
{
  "version": "1.0",
  "last_updated": "ISO-8601",
  "protocols": [
    {
      "name": "evolution",
      "category": "core",
      "protocol_version": "1.0.0",
      "content_hash": "sha256:<hex>",
      "last_modified": "ISO-8601",
      "origin": "local",
      "import_from": null
    }
  ]
}
```

---

## Impact on Files

| File | Change required |
|---|---|
| `protocols/agents/protocol-exchange.md` | **Extend payload schema** (add 4 fields). **Add conflict detection step** to Process (Receiver), between "Review" and "Decide". **Add conflict response** to §Respond step. **Add rule** prohibiting watcher-mode auto-adoption on conflict. **Add new outcome** `conflict` to decision tree. |
| `docs/self-architecture/protocol-registry.json` | **Deferred.** Create only when protocol count > 50 or 3rd workspace added. Schema defined above. |
| `protocols/agents/knowledge-sharing.md` | **No change required.** Knowledge digests are keyed by `correction_id`, not content hash. The versioning scheme here is independent. |

---

## Open Questions

1. **Hash computation side of sender** — should the sender compute and embed the hash, or should the exchange server compute it on receipt? Current design: sender computes. This is consistent with how the sender computes `body_hash` in the chain payload spec. The receiver independently re-verifies.

2. **protocol_version initial value** — when a protocol is first created, assign `"1.0.0"`. Each subsequent modification: author decides major/minor/patch increment. No automated version bumping — behavioral change classification is a human judgment call.

3. **Conflict response in watcher mode** — when watcher receives a conflicted proposal, it queues for interactive review. The original proposal message remains in the exchange with `status=pending`. Is there a timeout after which the sender can assume the receiver will not respond? Current answer: no timeout — the exchange does not enforce TTL on proposal messages.

4. **Adapted response hash** — when receiver responds `adapted`, the response should include the hash of the adapted content (not the original). The sender can then decide whether to adopt the adaptation back. This creates a potential negotiation loop; acceptable for a 2-agent system where both coordinators are active humans.

---

## References

- [Semantic Versioning 2.0.0](https://semver.org/)
- [Content-Addressable Storage — Lenovo](https://www.lenovo.com/us/en/glossary/cas/)
- [Topological Sorting for Dependency Resolution](https://medium.com/@amit.anjani89/topological-sorting-explained-a-step-by-step-guide-for-dependency-resolution-1a6af382b065)
- [SEP-1400: Semantic Versioning for MCP Specification](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1400)
- [Optimistic Concurrency Control — Wikipedia](https://en.wikipedia.org/wiki/Optimistic_concurrency_control)
- [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) (referenced in spec-chain-payload-hash.md)
- `docs/specs/spec-chain-payload-hash.md` — canonical JSON hash computation method (reused here)
