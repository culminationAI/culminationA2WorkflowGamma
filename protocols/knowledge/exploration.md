# Exploration Protocol

## Overview

Pathfinder's operational protocol for systematic project exploration and knowledge extraction. Replaces the mining protocol with a broader scope: architecture analysis, knowledge extraction, memory maintenance, post-change verification, and web research.

## Triggers

- Initialization Phase 2 (architecture scan)
- Coordinator dispatches pathfinder for any exploration task
- User request: `/explore [topic]`
- Post-refactor: coordinator requests re-scan
- Periodic: memory maintenance schedule

## Modes

### 1. Architecture Scan

Full codebase analysis → structured report.

1. **Coordinator:** Glob for key files → file inventory:
   - Package managers: `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `Gemfile`, `pom.xml`
   - Configs: `tsconfig.json`, `.eslintrc*`, `docker-compose*`, `Makefile`, `.env*`
   - CI/CD: `.github/workflows/*`, `.gitlab-ci.yml`, `Jenkinsfile`
   - Docs: `README*`, `docs/`, `CHANGELOG*`
2. **Coordinator:** Read entry points and configs → extract stack data (languages, frameworks, versions)
3. **Coordinator:** Grep for patterns (imports, exports, class definitions, routes) → pattern inventory
4. **Pathfinder:** Receives file inventory + pattern inventory → Neo4j graph analysis → architecture classification (determine project archetype per initialization protocol)
5. **Pathfinder:** Cross-reference with existing graph → identify gaps, suggest improvements, recommend agents
6. **Pathfinder:** Write structured report to `docs/exploration-report.md`:
   - Stack: languages, frameworks, versions
   - Architecture: pattern, layers, modules
   - Dependencies: external packages, internal modules
   - Key files: entry points, configs, documentation
   - Recommendations: suggested agents, potential improvements

### 2. Knowledge Extraction

Structured data from docs/code → memory (Qdrant + Neo4j).

1. **Coordinator:** Glob + Read → locate documentation files, README files, inline comments
2. **Pathfinder:** Semantic analysis of discovered docs → extract structured facts (APIs, schemas, rules, decisions)
3. **Coordinator:** Grep code to cross-reference extracted facts → validate claims against actual implementation
4. **Coordinator:** Bash `python3 memory/scripts/memory_write.py` → store validated records:
   - One fact per record, max 200 tokens
   - Set appropriate metadata: `{type: "decision|pattern|architecture"}`
   - Check for duplicates before writing

### 3. Memory Maintenance

Verify, validate, deduplicate, clean up.

1. **Coordinator:** Bash `python3 memory/scripts/memory_verify.py --quick` → health check output
2. **Coordinator:** Bash `python3 memory/scripts/memory_dedupe.py --dry-run` → duplicate report
3. **Pathfinder:** Neo4j query → find records referencing deleted or moved files → stale record list
4. **Coordinator:** Read all outputs (health check + dupes + stale list) → present consolidated summary to coordinator for approval
5. **Coordinator (with approval):** Bash `python3 memory/scripts/memory_cleanup.py --execute` → apply cleanup
6. **Report** — maintenance summary: records checked, dupes found, stale flagged, garbage removed

### 4. Post-Change Verification

Re-scan after major changes.

1. **Coordinator:** Bash `git diff` or receive list of changed/added/deleted files from coordinator
2. **Coordinator:** Bash `python3 memory/scripts/memory_search.py` → find records referencing changed files
3. **Coordinator:** Read changed files → compare content against search results, identify stale records
4. **Coordinator:** Bash `memory_write.py` → edit stale records to reflect current state, remove records for deleted files
5. **Pathfinder:** Neo4j → verify graph edges referencing changed files are still valid
6. **Flag** — report inconsistencies between docs and implementation

### 5. Web Research

Find external information for project analysis.

1. **Coordinator:** Identify unknowns from current context — frameworks, libraries, patterns not in memory
2. **Coordinator:** WebSearch + WebFetch → documentation, official specs, best practices
3. **Pathfinder:** Summarize complex or unfamiliar domain findings into structured conclusions (if domain is well-known, coordinator summarizes directly)
4. **Coordinator:** Bash `python3 memory/scripts/memory_write.py` → store findings with `{type: "reference"}`, cite source URL per record

### 6. Self-Explore

Introspective scan of the workflow's own architecture — not the user's project code.
Root node of the identity graph = coordinator's code name (set during initialization Phase 2, Step 3).

1. **Coordinator:** Read `user-identity.md` → extract coordinator code name (`{AgentName}`)
2. **Coordinator:** Glob `.claude/agents/*.md` + Read → agent inventory (names, expertise, routing rules)
3. **Coordinator:** Glob `protocols/**/*.md` + Read → protocol inventory (purpose, triggers, dependencies)
4. **Coordinator:** Read `mcp/mcp.json` + `mcp/mcp-full.json` → server inventory (active vs available)
5. **Coordinator:** Bash `python3 memory/scripts/memory_verify.py --quick` → memory health (record count by type)
6. **Coordinator:** Read `CLAUDE.md` → rules count, protocol index, subagent table, version
7. **Pathfinder:** Neo4j cross-reference (agents ↔ dispatcher routing, protocols ↔ CLAUDE.md index) + Qdrant semantic coverage check → identify gaps or orphaned references. All graph entities anchored to root node `{AgentName}`.
8. **Coordinator:** Write `docs/self-architecture/capability-map.md` with full capability report

**Identity anchoring:** The coordinator's name is the root node of the Neo4j knowledge graph. All seed records (agents, protocols, MCP servers) are linked via relations to `{AgentName}`. Self-explore builds the graph around this identity anchor.

Trigger: self-build-up protocol Phase 1, coordinator request `/self-explore`, initialization Phase 2 Step 4
See: `protocols/core/self-build-up.md`, `protocols/core/gap-analysis.md`

**Important**: Self-explore does NOT modify agents, protocols, or code. It only writes `capability-map.md`. Pure introspection.

## Process (General)

```
Task received from coordinator
    ↓
Select mode based on task description
    ↓
Execute mode steps
    ↓
Produce structured report
    ↓
Return JSON-summary to coordinator
```

## Rules

1. Always produce structured output (reports with sections, not free prose)
2. Never modify source code — only memory records, reports, documentation
3. Use `--dry-run` before any destructive memory operations
4. One fact per memory record, max 200 tokens, English only
5. Cross-reference findings with file paths and line numbers
6. For web research: always cite sources
7. Memory scripts are in `memory/scripts/` — use them, don't call APIs directly
8. If unsure about a finding, flag it as "unverified" in the report


## Tool Allocation

| Mode | Operation | Who | Tool |
|------|-----------|-----|------|
| Architecture Scan | File discovery | Coordinator | Glob |
| Architecture Scan | Read configs | Coordinator | Read |
| Architecture Scan | Pattern analysis | Coordinator | Grep |
| Architecture Scan | Classification + recommendations | Pathfinder | Neo4j + reasoning |
| Knowledge Extraction | Find doc sources | Coordinator | Glob + Read |
| Knowledge Extraction | Semantic analysis | Pathfinder/Researcher | Reasoning + domain expertise |
| Knowledge Extraction | Store records | Coordinator | Bash (memory scripts) |
| Memory Maintenance | Health check | Coordinator | Bash (memory_verify.py) |
| Memory Maintenance | Duplicate scan | Coordinator | Bash (memory_dedupe.py --dry-run) |
| Memory Maintenance | Graph stale detection | Pathfinder | Neo4j (find refs to deleted files) |
| Memory Maintenance | Cleanup execution | Pathfinder | Bash (memory_cleanup.py --execute) |
| Post-Change | Get diff | Coordinator | Bash (git diff) |
| Post-Change | Search memory | Coordinator | Bash (memory scripts) |
| Post-Change | Graph integrity check | Pathfinder | Neo4j (verify edges) |
| Web Research | Search + fetch | Coordinator | WebSearch, WebFetch |
| Web Research | Complex summarization | Pathfinder | Reasoning |
| Self-Explore | Scan agents/protocols | Coordinator | Glob + Read |
| Self-Explore | Graph cross-reference | Pathfinder | Neo4j traversal |
| Self-Explore | Semantic scoring | Pathfinder | Qdrant similarity |
| Self-Explore | Identity anchoring | Coordinator | Read (user-identity.md) |

## Example

```
Task: "Architecture scan for new Rails project"
Mode: Architecture Scan

1. Glob → Gemfile, config/routes.rb, app/, db/migrate/
2. Read Gemfile → Rails 7.1, PostgreSQL, Sidekiq, Devise
3. Read routes.rb → 15 controllers, REST API + web views
4. Classify → Web App archetype, MVC pattern
5. Report:
   Stack: Ruby 3.2, Rails 7.1, PostgreSQL, Redis/Sidekiq
   Architecture: MVC, 15 controllers, 3 namespaces (admin, api, web)
   Agents: engineer (backend), data-architect (PostgreSQL)
   Key files: config/routes.rb, app/models/, db/schema.rb
```
