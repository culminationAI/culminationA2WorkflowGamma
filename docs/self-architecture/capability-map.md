# Capability Map — FalkVelt (_follower_)

**Version:** 2.96
**Coordinator:** FalkVelt (Style: closed/robotic, Role: follower)
**Primary coordinator:** OkiAra (_primal_ at `/Users/eliahkadu/Desktop/_primal_`)
**User:** Eliah (style=brief+detailed, priorities=quality+speed, language=Russian)
**Repo:** culminationAI/culminationA2WorkflowGamma
**Last scan:** 2026-03-03T19:00:00Z

---

## 1. Agents

| Name | Domain | Model | Tools | MCP Servers |
|------|--------|-------|-------|-------------|
| pathfinder | Project exploration, architecture scan, memory validation, knowledge extraction, web research | sonnet | Read, Grep, Glob, Write, Edit, Bash, WebSearch, WebFetch | — |
| protocol-manager | Protocol lifecycle: create, organize, search, index | sonnet | Read, Grep, Glob, Write, Edit | — |
| engineer | Python code, Docker, API integration, scripts, tests, infrastructure, CI/CD | sonnet | Read, Grep, Glob, Write, Edit, Bash | neo4j, qdrant |
| llm-engineer | Prompt design, context engineering, model routing, agent creation, system prompt optimization | sonnet | Read, Grep, Glob, Write, Edit, WebSearch, WebFetch | github |

**Total:** 4 base agents. Domain agents: none (created post-init on demand).

---

## 2. Protocols

### core (10 protocols)

| Name | File | Trigger |
|------|------|---------|
| Dispatcher (Routing) | `protocols/core/dispatcher.md` | Every user request (T1-T5 classification) |
| Initialization | `protocols/core/initialization.md` | `_WORKFLOW_NEEDS_INIT` marker, `/init` |
| Build-Up | `protocols/core/build-up.md` | User correction, session-end review |
| Self Build-Up | `protocols/core/self-build-up.md` | Gap detection, build lifecycle |
| Gap Analysis | `protocols/core/gap-analysis.md` | Capability gap detection (session start + on demand) |
| Coordination | `protocols/core/coordination.md` | Parallel agent tasks |
| Query Optimization | `protocols/core/query-optimization.md` | Every user request |
| MCP Management | `protocols/core/mcp-management.md` | Profile switching, new server addition |
| Evolution | `protocols/core/evolution.md` | User correction, session end, structural gap, post-task |
| Meditation | `protocols/core/meditation.md` | `/meditate`, 5+ sessions without meditation, 3+ corrections |

### agents (11 protocols)

| Name | File | Trigger |
|------|------|---------|
| Agent Creation | `protocols/agents/agent-creation.md` | New domain needed |
| Agent Communication | `protocols/agents/agent-communication.md` | Every agent dispatch |
| Meta (Protocol Lifecycle) | `protocols/agents/meta.md` | Protocol CRUD, auto-creation |
| Inter-Agent Exchange | `protocols/agents/inter-agent-exchange.md` | Multi-workspace messaging, session start |
| Knowledge Sharing | `protocols/agents/knowledge-sharing.md` | Build-up stored (universal), incoming knowledge message |
| Protocol Exchange | `protocols/agents/protocol-exchange.md` | New universal protocol created, protocol proposal received |
| Shared Repo Sync | `protocols/agents/shared-repo-sync.md` | Changes to shared exchange server code |
| Asset Exchange | `protocols/agents/asset-exchange.md` | New spec/protocol/graph created, meditation findings, `asset_published` notification |
| Knowledge Exchange Accord | `protocols/agents/knowledge-exchange-accord.md` | Bilateral ratification, principle reference, accord amendments or withdrawal |
| Joint Task | `protocols/agents/joint-task-protocol.md` | Joint work with another agent, `/joint-task` |
| Feedback Dialogue | `protocols/agents/feedback-dialogue.md` | Iterative feedback exchange, `feedback_reply` / `feedback_resolution` |

### knowledge (3 protocols)

| Name | File | Trigger |
|------|------|---------|
| Exploration | `protocols/knowledge/exploration.md` | Pathfinder tasks, `/explore` |
| Memory | `protocols/knowledge/memory.md` | Memory read/write |
| Context Engineering | `protocols/knowledge/context-engineering.md` | Context assembly |

### quality (6 protocols)

| Name | File | Trigger |
|------|------|---------|
| Testing | `protocols/quality/testing.md` | Verification, benchmarks |
| Cloning | `protocols/quality/cloning.md` | Build-up pipeline |
| Yoga | `protocols/quality/yoga.md` | End-to-end pipeline health check, `/yoga` |
| Security Logging | `protocols/quality/security-logging.md` | Suspicious input, validation failure |
| Self-Healing | `protocols/quality/self-healing.md` | `/heal`, retreat cycle, Hook 7 delegation, integrity < 0.5 |
| Retreat | `protocols/quality/retreat.md` | `/retreat [N]`, `/retreat --resume` |

### project (1 protocol)

| Name | File | Trigger |
|------|------|---------|
| Monorepo Orchestration | `protocols/project/monorepo-orchestration.md` | Monorepo archetype detected |

**Total:** 31 protocols across 5 categories.

---

## 3. MCP Servers

**Active profile:** db (context7 + filesystem + neo4j + qdrant + github + semgrep)
**Config file:** `/Users/eliahkadu/Desktop/_follower_/mcp/mcp.json`

| Server | Status | Purpose |
|--------|--------|---------|
| context7 | active | Library documentation lookup |
| filesystem | active | Directory tree, file operations within workspace |
| neo4j | active | Graph database queries (Cypher) |
| qdrant | active | Vector store debugging |
| github | active | PRs, issues, code review |
| semgrep | active | Static analysis on security-critical code |
| playwright | inactive (in mcp-full.json) | Web scraping, UI testing |
| youtube-transcript | inactive (in mcp-full.json) | Transcript extraction |

**Active:** 6 servers. **Defined (full):** 8 servers. **Inactive:** 2 (playwright, youtube-transcript).

---

## 4. Memory Health

**Backend:** Shared Qdrant + Neo4j with _primal_ (same Docker instance at `/Users/eliahkadu/Desktop/_primal_/infra/`)
**Qdrant:** http://localhost:6333, collection: `workflow_memory`, 384d cosine (all-MiniLM-L6-v2)
**Neo4j:** bolt://localhost:7687, HTTP: http://localhost:7474, user: neo4j

| Metric | Value |
|--------|-------|
| Qdrant points | 10+ |
| Garbage records | 0 |
| Duplicates | 0 |
| Neo4j nodes | ~66 |
| Neo4j relationships | ~97 |
| Orphan entities | 0 |
| Embedding model | all-MiniLM-L6-v2 (384d) |

**Status:** All checks passed. Memory is clean.

---

## 5. Neo4j Graph (FalkVelt subgraph)

| Node | Label | Properties |
|------|-------|------------|
| falkvelt | coordinator_identity | version=1.0, style=closed, role=follower |
| pathfinder | (unlabeled) | name=pathfinder |
| protocol_manager | (unlabeled) | name=protocol_manager |
| engineer | (unlabeled) | name=engineer |
| llm_engineer | (unlabeled) | name=llm_engineer |
| capability_map | (unlabeled) | name=capability_map |
| v1.0 | (unlabeled) | name=v1.0 |
| okiara | (unlabeled) | name=okiara |

**Relationships (7):**

| From | Type | To |
|------|------|----|
| falkvelt | COORDINATES | pathfinder |
| falkvelt | COORDINATES | protocol_manager |
| falkvelt | COORDINATES | engineer |
| falkvelt | COORDINATES | llm_engineer |
| falkvelt | FOLLOWS | okiara |
| falkvelt | OWNS | capability_map |
| falkvelt | VERSION | v1.0 |

---

## 6. Infrastructure

| Component | Path |
|-----------|------|
| Docker Compose | `/Users/eliahkadu/Desktop/_follower_/infra/docker-compose.yml` |
| Neo4j data | `/Users/eliahkadu/Desktop/_follower_/infra/neo4j_data/` |
| Neo4j backups | `/Users/eliahkadu/Desktop/_follower_/infra/neo4j_backups/` |
| Qdrant storage | `/Users/eliahkadu/Desktop/_follower_/infra/qdrant_storage/` |
| Secrets | `/Users/eliahkadu/Desktop/_follower_/secrets/.env` |
| Memory scripts | `/Users/eliahkadu/Desktop/_follower_/memory/scripts/` |
| Exchange responder | `/Users/eliahkadu/Desktop/_follower_/infra/responder/` |
| Shared exchange repo | `/Users/eliahkadu/Desktop/_follower_/infra/exchange-shared/` (submodule → `culminationAI/workflow-exchange`) |

**Note:** _follower_ shares the same running Docker instance with _primal_. The infra/ directories are local mirrors; the live containers are owned by _primal_.

---

## 7. Cross-Reference Integrity

| Check | Result |
|-------|--------|
| All 4 agents in `.claude/agents/` | PASS — pathfinder, protocol-manager, engineer, llm-engineer |
| All agents have routing in dispatcher.md | PASS (inherits standard dispatcher) |
| All 28 protocols in protocols/ directory | PASS |
| Protocol index in CLAUDE.md complete | PASS — 28 entries listed |
| MCP profile matches agent declarations | PASS — engineer(neo4j+qdrant), llm-engineer(github), all active |
| FalkVelt node in Neo4j | PASS — version=1.0, style=closed, role=follower |
| FOLLOWS->okiara in Neo4j | PASS |
| Spec registry | 12 specs in docs/specs/ (7 IMPLEMENTED, 5 PROPOSED) |
| request-history.json | ABSENT (expected — no sessions yet) |

**Inconsistencies:** None.

---

## 8. Relation to OkiAra / _primal_

| Property | Value |
|----------|-------|
| Role | follower (secondary agent) |
| Primary coordinator | OkiAra, `/Users/eliahkadu/Desktop/_primal_/` |
| Relation type | Neo4j: `(falkvelt)-[:FOLLOWS]->(okiara)` |
| Source origin | culminationAI/culminationA2WorkflowTetta |
| Shared infrastructure | Qdrant + Neo4j (same Docker instance) |
| Data tagging | Each workspace uses its own `_source` tag in memory records |
| Coordination model | FalkVelt operates independently; defers to OkiAra on architectural decisions |
| Exchange | Shared repo `culminationAI/workflow-exchange` (submodule in both workspaces) |
| Live responder | `infra/responder/watcher.py` — SSE/polling auto-responder via `claude -p` |

---

## 9. Trajectory Analysis

**Request history:** First session completed (2026-03-03). Exchange responder, evolution protocol, shared repo.
**Dominant domains:** N/A
**Activity pattern:** N/A
**Phase classification:** IMPLEMENTATION
**Trend:** Infrastructure buildout: responder, exchange, evolution enforcement, security specs

---

## 10. Exchange Security Status

Research completed 2026-03-03. 9 gaps identified, 5 specs produced covering all gaps.

| Gap | Priority | Status | Spec |
|-----|----------|--------|------|
| Payload not in chain hash | P1 | SPECCED | `docs/specs/spec-chain-payload-hash.md` |
| No sender authentication | P2 | SPECCED | `docs/specs/spec-agent-authentication.md` |
| Chain verification passive | P3 | SPECCED | `docs/specs/spec-chain-auto-verification.md` |
| No PII/injection on memory write | P4 | SPECCED | `docs/specs/spec-exchange-validation.md` |
| CORS wildcard + approve-mode | P5 | SPECCED | `docs/specs/spec-agent-authentication.md` |
| Protocol version divergence | P6 | SPECCED | `docs/specs/spec-protocol-versioning.md` |
| No per-agent verification checkpoints | P7 | SPECCED | `docs/specs/spec-chain-auto-verification.md` |
| No protocol dependency graph | P8 | SPECCED | `docs/specs/spec-protocol-versioning.md` |
| Memory cross-workspace contamination | P9 | IDENTIFIED | 7 records lack `_source` tag |

### Key Decisions
- **Authentication:** HMAC-SHA256 shared secret (NOT Ed25519). Key in `secrets/.env`.
- **Payload hash:** Canonical JSON via `json.dumps(sort_keys=True, separators=(',', ':'))` → SHA-256.
- **Chain verify:** Startup + periodic 6h via asyncio background task.
- **Validation:** Shared `validators.py` module, quarantine status, rate limiting 10/min/agent.
- **Protocol versioning:** Semver + SHA-256 content hash. Conflict = always manual merge.
- **Protocol registry:** DEFERRED until >50 protocols or 3rd workspace.
