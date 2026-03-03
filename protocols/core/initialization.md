# Initialization Protocol

## Overview

Bootstrap a new project workspace through build-up. Onboarding IS build-up — the coordinator learns about the project through exploration, not static configuration. The workflow starts at version 0.2 and graduates to 1.0 after successful initialization.

## Triggers

- `<!-- _WORKFLOW_NEEDS_INIT -->` marker present in CLAUDE.md
- User explicitly requests `/init` or project setup
- First session in a new workspace

## Process

### Phase 1: Environment

Check prerequisites:
1. Verify Docker installed and running
2. Verify Python 3.9+ available
3. Verify git initialized in workspace
4. Verify Node.js 18+ available (required for MCP servers via npx)
5. If any missing → provide install instructions, pause until resolved

Note: Ollama service is required for the default bge-m3 embeddings (1024d). Start with `docker compose up -d ollama` in `infra/`. Fallback: set `EMBEDDING_PROVIDER=fastembed` in `secrets/.env` to use local fastembed (384d, no external service). See `protocols/knowledge/memory.md` for details.

### Phase 2: Greet

The coordinator establishes identity, learns the user's name, and collects basic preferences before any project scanning. Steps 1–5 happen in this phase.

#### Step 1: User introduces themselves

Coordinator asks the user's name.
- Input validation: `^[a-zA-Z0-9 '\-]{1,50}$`
- Security pattern check (see [Input Validation](#input-validation) below)
- Max 2 attempts, then default to "User"
- Store in memory: `{type: "preference", subtype: "user_name"}`

#### Step 2: First-time check

Coordinator asks via `AskUserQuestion`:
> "Is this my first onboarding with you?"

- **Option 1: "Yes, first time"** — already loaded from official repo, no action needed
- **Option 2: "No, load yourself from:"** — text field for repo URL
  - User enters `owner/repo-name`
  - Agent runs: `gh repo view {repo}` → verify repo exists
  - `git clone {repo} /tmp/instance-import` → copy evolved files over v0.2:
    - `.claude/agents/` (base agents only), `protocols/core/`, `protocols/agents/`, `protocols/knowledge/`, `protocols/quality/`
    - `docs/self-architecture/`, `CLAUDE.md` (preserve `_WORKFLOW_NEEDS_INIT` marker)
    - `specs/` (if exists)
  - DO NOT copy: `user-identity.md`, `secrets/`, `protocols/project/`, domain agents
  - After import: read `WORKFLOW_VERSION` from imported CLAUDE.md → this becomes current version
  - Save origin: `user-identity.md` → `## Origin > Repository: {repo}`

#### Step 3: Naming the coordinator

Two-step generation from closed syllables. Three sound styles, each with its own 16×16 pools = 256 combinations per style, 768 total.

**Style 1: Closed syllables (CVC + CVC) — hard, robotic**
```
Pool 1A (16): Thum, Triz, Vret, Drag, Lus, Kron, Brig, Plim, Grek, Stur, Falk, Brox, Neld, Drog, Jask, Zelt
Pool 1B (16): Dim, Gur, Pul, Tros, Kroy, Nax, Belk, Frim, Shod, Velt, Klun, Rist, Bont, Marg, Wex, Drin
```
Examples: ThumDim, TrizGur, DragTros, KronNax, FalkRist

**Style 2: Open syllables (VCV + VCV) — soft, melodic**
```
Pool 2A (16): Ani, Olli, Eni, Ile, Aru, Ika, Ema, Uli, Ayo, Ona, Isi, Elo, Ura, Oki, Alu, Evi
Pool 2B (16): Ara, Oli, Inu, Eka, Umi, Ola, Iru, Ame, Oti, Ela, Uki, Aro, Ini, Uve, Oma, Ise
```
Examples: AniAra, OlliOla, EniEka, IleAme, AruUmi

**Style 3: Semi-open (VC + CV) — contrasting, hybrid**
```
Pool 3A (16): Alk, Orn, Ist, Elm, Urd, Ank, Olt, Esh, Arv, Eld, Irk, Usk, Onk, Ash, Irt, Ung
Pool 3B (16): Bra, Kri, Sho, Plu, Gra, Flo, Dre, Ska, Bli, Kla, Vro, Pha, Tri, Glo, Ste, Dru
```
Examples: AlkBra, OrnKri, ElmPlu, EldFlo, IrkSho

**Process:**
1. Coordinator runs `python3 memory/scripts/generate_name.py` → script picks random style (1/2/3), random syllable from Pool A → returns JSON: `{"style": 2, "syllable": "Ani", "pool_b": ["Ara", "Oli", ...]}`
2. Coordinator picks second syllable from Pool B of same style (e.g. "Ara") → name = "AniAra". This choice is the coordinator's first expression of individuality.
3. Via `AskUserQuestion`:
   - Text: "{Username}, how would you like to name me? I like the name **{AniAra}**."
   - Option 1: **"{AniAra}"** — accept
   - Option 2: **"Generate another"** — regenerate (up to 5 times)
   - Field "Other": enter custom name
4. Save to `user-identity.md` → `## Coordinator > Code name: {name}`
5. Save to memory: `{type: "preference", subtype: "coordinator_name"}`

#### Step 4: Self-explore starting from the name

Launch pathfinder self-explore, but root node = coordinator's name:
```json
{
  "text": "{AgentName} is the coordinator of this CulminationAI Workflow instance. Version {version}.",
  "entities": [{"name": "{AgentName}", "type": "coordinator_identity"}],
  "relations": [
    {"source": "{AgentName}", "relation": "COORDINATES", "target": "pathfinder"},
    {"source": "{AgentName}", "relation": "COORDINATES", "target": "protocol_manager"},
    {"source": "{AgentName}", "relation": "COORDINATES", "target": "engineer"},
    {"source": "{AgentName}", "relation": "COORDINATES", "target": "llm_engineer"},
    {"source": "{AgentName}", "relation": "OWNS", "target": "capability_map"},
    {"source": "{AgentName}", "relation": "VERSION", "target": "v{version}"}
  ]
}
```
All other seed records (agents, protocols, MCP) → relations anchored to root `{AgentName}`.
Self-explore builds the graph around the name — this is the agent's identity.

#### Step 5: Basic user preferences (AFTER naming, BEFORE project scan)

Via `AskUserQuestion` — only basic, project-independent questions:

**1. Communication language:**
- Text: "What's your communication language?"
- Option 1: **"English"** (default)
- Option 2: **"Other"** → text field
- If Other → that language is used for user-facing communication, but ALL internal (agent prompts, code, JSON, memory) stays English. Conversion is automatic.
- Validation: known language codes (en, ru, es, fr, de, ja, zh, ko, pt, it, ar, hi, etc.)

**2. Communication style:**
- Text: "{AgentName} here, {Username}. How should I communicate with you?"
- Options: brief / detailed / balanced / formal / informal
- Default: balanced

**Storage:**
- Answers → `user-identity.md` (sections Language, Communication Style)
- Answers → memory: `{type: "preference", subtype: "{field}"}`

#### Input Validation

Applies to ALL input fields across Steps 1–7.

**a) Security pattern check (ALL text fields):**
Before storing any user input, check for injection patterns:
- Reject: backticks, semicolons, null bytes, control characters, `<script`, `eval(`, Cypher keywords (MERGE, CREATE, DELETE, SET)
- If pattern detected → log to `logs/security-audit.log`, ask user to re-enter
- Max 3 re-entry attempts per field; then apply default and log security event

**b) Name field:**
- Whitelist: `^[a-zA-Z0-9 '\-]{1,50}$` (letters, digits, space, apostrophe, hyphen)
- If invalid → ask again (max 2 attempts), then default to "User"

**c) Communication style:**
- Strict enum: formal, informal, brief, detailed, balanced
- If not in enum → ask again (max 2 attempts), then default to "balanced"

**d) Language:**
- Single: validate against known codes (en, ru, es, fr, de, ja, zh, ko, pt, it, ar, hi, etc.)
- Mixed: extract codes from follow-up, validate each. Store as `language: "en+ru"`
- If invalid → ask again (max 2 attempts), then default to "English"

**e) Priorities:**
- Strict enum: speed, quality, learning, exploration
- If not in enum → ask again (max 2 attempts), then default to "quality"

**f) Empty/skip handling:**
- If user skips ALL questions → apply defaults: name="User", style="balanced", language="English", priorities="quality"
- If any field is empty string → treat as "not provided", apply default for that field
- Store defaults with flag: `{type: "preference", source: "default"}` to distinguish from user-provided

**g) Audit logging:**
After collecting all preferences, log to `logs/security-audit.log`:
```
[TIMESTAMP] [INFO] [phase2] [preference] [accepted] — name=[N], style=[S], language=[L], priorities=[P], source=[user|default]
```

### Phase 3: Explore

Coordinator-first data collection, then pathfinder analysis:

1. **Coordinator:** Run Glob for key files: `package.json`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `Gemfile`, `pom.xml`, `Makefile`, `docker-compose*`, `tsconfig.json`, `.eslintrc*`, `.github/workflows/*`, `README*`
2. **Coordinator:** Read discovered configs → build stack inventory (languages, frameworks, versions)
3. **Coordinator:** Grep for patterns (import statements, route definitions, class definitions) → pattern inventory
4. **Coordinator:** Pass inventories to pathfinder as structured context in dispatch prompt
5. **Pathfinder:** Receives pre-collected data → Neo4j graph analysis → architecture classification → recommendations
6. **Pathfinder:** Write structured exploration report → `docs/exploration-report.md`

Detect project archetype from collected data:

| Archetype | Signals | Typical Domain Agents |
|-----------|---------|----------------------|
| AI/ML | pytorch, tensorflow, .ipynb, models/, trainer | data-architect, science-researcher, ml-engineer |
| Web App (Frontend) | React, Vue, Svelte, Vite, static site, no API routes | engineer (frontend) |
| Web App (Full-Stack) | React/Vue + API routes, ORM, DB config, FastAPI, Django, Express | engineer (frontend), engineer (backend), data-architect |
| Data Pipeline | airflow, dbt, pandas, ETL, spark | data-architect, engineer |
| Content/Docs | markdown, mdx, docs/, knowledge/, sphinx | knowledge-curator, humanities-researcher |
| DevOps/Infra | terraform, k8s, ansible, .github/, helm | engineer (infra) |
| Science | jupyter, scipy, R, datasets/ | science-researcher, data-architect |
| Game Dev | unity, godot, bevy, assets/ | narrative-designer, engineer |
| Mobile | swift, kotlin, flutter, android/, ios/ | engineer (mobile) |
| Monorepo | pnpm-workspace.yaml, turbo.json, lerna.json, packages/* | engineer (per-package domain), data-architect |
| Framework/OSS | packages/[framework]/, crates/, examples/ with 50+ items | engineer (framework), engineer (compiler) |
| Polyglot | Cargo.toml + *.ts/js, or multiple compiled languages | engineer (per-language) |
| General | mixed or unclear | engineer (general-purpose) |

**Multi-archetype resolution:** If multiple archetypes match (e.g., Airflow = Data Pipeline + Framework/OSS):
1. Rank by signal count — archetype with most matching signals = primary
2. Primary archetype determines base agent set
3. Secondary archetypes add supplementary agents (no duplicates)
4. Store all detected archetypes in exploration report: `{primary: "Data Pipeline", secondary: ["Framework/OSS", "Monorepo"]}`
5. In Phase 5 (Adapt), create agents for primary first, then add missing agents from secondary archetypes

### Phase 4: Learn

Coordinator processes pathfinder report and asks project-specific questions:

1. Present project summary to user for confirmation

2. **Priorities (adapted to archetype):**
   - Web App: "Focus on shipping features fast or ensuring test coverage?"
   - Data Pipeline: "Optimize for data throughput or pipeline reliability?"
   - AI/ML: "Experiment quickly or build reproducible pipelines?"
   - DevOps/Infra: "Automate everything or keep manual control over critical deploys?"
   - Content/Docs: "Prioritize writing speed or structural consistency?"
   - General fallback: "What's your priority: speed, quality, learning, or exploration?"
   - Default: quality

3. **Additional project-specific question** (optional, 1 question max):
   - Coordinator formulates based on exploration report (e.g. "I see you use Prisma — should I follow your existing schema conventions?")

**Storage:**
- Answers → `user-identity.md` (section Priorities)
- Answers → memory: `{type: "preference", subtype: "priority"}`
- **ALL user answers (from Steps 5 in Phase 2 and from Phase 4) become seed data for the exploration protocol during the first build-up.** Pathfinder uses them as context for graph formation: priorities affect edge weights, language determines communication layer, style determines response formatting.

**Phase 4 success criteria:** language field MUST be set (user-provided or default). If language is not set after 2 prompts, apply "English" default and continue with logged warning.

### Phase 5: Adapt

Create project-specific agents and protocols:
1. Select domain agents based on archetype (see Phase 3 table)
   - For Monorepo archetype: follow `protocols/project/monorepo-orchestration.md` for package mapping, agent spawning rules, and coordination patterns
2. **Apply user priority modifiers to agent selection and configuration:**
   - `speed` → prefer engineers and architects, minimize research agents, configure all agents for concise/direct output (skip boilerplate, prefer diffs)
   - `quality` → add QA/testing focus, configure agents for rigorous output (include tests, type hints, error handling, rationale)
   - `learning` → configure agents to include explanations, "why" reasoning, and alternatives in output. Consider adding docs-writer or mentor-style agent
   - `exploration` → heavier research agents, configure agents to suggest experiments, surface edge cases, propose alternatives
3. Delegate to llm-engineer: create agent definitions in `.claude/agents/`
   - Pass user priority as prompt modifier: "User priority is [X] — calibrate agent verbosity and style accordingly."
   - Pass communication style: "User communication style is [Y] — match this register in all responses."
4. Invoke protocol-manager: create project-specific protocols in `protocols/project/`
5. Update dispatcher.md: add new agents to routing table
6. Update CLAUDE.md: add new agents to subagent table, update protocol index

### Phase 6: Deploy

Infrastructure and MCP setup:

1. Determine MCP profile based on project archetype from Phase 3:
   - AI/ML, Data → `db` (core + neo4j + qdrant)
   - Content, Research → `research` (core + youtube-transcript)
   - Web App, DevOps → `web` (core + playwright + github)
   - General, Unknown → `core` (context7 + filesystem only)
2. Run `python3 mcp/mcp_configure.py --profile {selected}`
3. Inform user: "Active MCP profile: {name}, {N} servers, ~{N}K tokens/message overhead"
4. Ask: "Need additional MCP servers? (e.g., github for PR review, semgrep for security)"
   - If yes → `python3 mcp/mcp_configure.py --add {server}`
5. If profile includes db servers (neo4j, qdrant):
   a. Run `setup.sh` — deploy Docker services (Qdrant + Neo4j)
   b. Create memory collection in Qdrant
   c. Verify: `python3 memory/scripts/memory_verify.py --quick`
6. Ask user: "Would you like to set up a Telegram bot for remote access?"
   - If yes → ask for bot token, configure `bot/` directory
   - If no → skip

### Phase 7: System Validation

Coordinator runs verification tests directly — no subagent dispatch needed.

1. **Memory roundtrip:** `python3 memory/scripts/memory_verify.py --quick` → parse output for health status
2. **Agent dispatch:** Send simple T2 task to any available subagent → verify response received
3. **Protocol searchability:** `Grep "## Overview" protocols/**/*.md` → verify all protocols parseable
4. **MCP connectivity:** Call any MCP tool (e.g., `read_neo4j_cypher("RETURN 1")`) → verify server responds
5. **Graph connectivity:** `read_neo4j_cypher("MATCH (n) RETURN count(n) LIMIT 1")` → verify Neo4j accessible
6. **Report:** Compile results — all 5 checks must pass for "system operational" status

If any check fails → log failure, warn user, continue initialization (non-blocking).

### Phase 8: Research Opt-in

Ask user:
> "Would you like to participate in anonymous research? Architecture patterns and agent configurations will be shared to github.com/culminationAI/research-data. All data is visible in the `research/` directory before any push."

- If yes → create `research/` directory, enable pathfinder data collection, and enable build-up feedback collection (anonymous build-up records written to `research/build-up/` per the Research Data Collection section in `protocols/core/build-up.md`)
- If no → skip, set `RESEARCH_OPTIN=false` in config

### Phase 9: Storage Decision

Coordinator asks:
> "{AgentName} here, {Username}. Where would you like to store me?
> 1. **Separate repository** — I'll push myself to GitHub after each improvement. Portable across projects.
> 2. **Inside this project** — I stay here, no external sync."

**If repo:**
- Ask name (default: `{gh_username}/{agent-name-lowercase}`)
- `gh repo create {name} --private` if doesn't exist
- Initial push: CLAUDE.md, agents, protocols (core/agents/knowledge/quality), docs/self-architecture, specs/, memory/scripts, mcp/, setup.sh, install.sh, README.md, .gitignore
- Save: `user-identity.md` → `## Storage > Mode: repo, Repository: {owner/name}`

**If local:**
- `user-identity.md` → `## Storage > Mode: local`

### Phase 10: Build-Up

Workflow graduates from version 0.2 → 1.0:
1. Run build-up protocol cycle on the freshly configured workflow
2. Pathfinder re-scans: verify all agents, protocols, memory layer work together
3. Protocol-manager validates: all protocols are indexed, cross-referenced, discoverable
4. **Self-Architecture Bootstrap:**
   a. Dispatch pathfinder (self-explore mode) → generate initial `docs/self-architecture/capability-map.md`
   b. Verify `docs/self-architecture/` directory exists with `build-registry.json`, `gap-analysis-log.md`
   c. Run lightweight gap analysis on the freshly initialized system
   d. Store: `{type: "build_up", subtype: "self_architecture_initialized"}`
5. Coordinator synthesizes: generate build-up report, apply any improvements
6. Update CLAUDE.md: change `<!-- WORKFLOW_VERSION: 0.2 -->` to `<!-- WORKFLOW_VERSION: 1.0 -->`
   **Version guard:** Only set version to 1.0 if WORKFLOW_VERSION is currently 0.2 (fresh install). If version is already >= 1.0 (instance import via cloning protocol), preserve the existing version — do not downgrade.
7. Store initialization record in memory: `{type: "build_up", subtype: "initialization"}`

### Phase 11: Planning

Transition from setup to productive work:
1. Coordinator enters planning mode
2. Presents initialization summary to user:
   - Project archetype detected
   - Agents created
   - Infrastructure deployed
   - Build-Up status
3. Asks user: "What are your current tasks for this project?"
4. Collects task list and priorities
5. Creates initial task plan in `docs/spec/PLAN.md`
6. Exits planning mode and begins work on the first task

This is the natural bridge from onboarding to productive work. The user should feel that the workflow is ready and eager to help.

## Rules

1. NEVER skip Phase 3 (Explore) — even for small projects, pathfinder must scan
2. NEVER auto-create agents without user confirmation (Phase 4)
3. MUST remove `<!-- _WORKFLOW_NEEDS_INIT -->` from CLAUDE.md after successful Phase 10
4. MUST store at least 5 memory records during initialization. These include project facts (archetype, primary language/framework, version, detected agents, timestamp) which are always available regardless of user participation in Phase 4. User preferences are additional records on top of project facts.
5. If any phase fails → stop, report error, do NOT proceed to next phase
6. Initialization is idempotent — running again on an initialized project re-runs exploration but preserves existing agents and preferences. To correct corrupted preferences, re-run Phase 4: all preference fields will be re-asked and overwritten, old memory records updated.
7. Phase 11 MUST be the last phase — never skip the transition to planning mode
8. ALL user answers from Steps 5 (Phase 2) and Phase 4 become exploration seeds for the first build-up. Pathfinder uses them as context for graph formation.

## Tool Allocation

| Phase | Operation | Who | Tool |
|-------|-----------|-----|------|
| 2 (Greet) | Ask user name | Coordinator | AskUserQuestion |
| 2 (Greet) | First-time check | Coordinator | AskUserQuestion |
| 2 (Greet) | Name generation | Coordinator | Bash (generate_name.py) |
| 2 (Greet) | Self-explore dispatch | Coordinator | Task (pathfinder) |
| 2 (Greet) | Basic preferences | Coordinator | AskUserQuestion |
| 3 (Explore) | Glob key files | Coordinator | Glob |
| 3 (Explore) | Read configs/entry points | Coordinator | Read |
| 3 (Explore) | Grep for code patterns | Coordinator | Grep |
| 3 (Explore) | Pass inventories to pathfinder | Coordinator | Task (structured context) |
| 3 (Explore) | Architecture analysis + classification | Pathfinder | Neo4j + reasoning |
| 3 (Explore) | Write exploration report | Pathfinder | Write |
| 4 (Learn) | Project-specific questions | Coordinator | AskUserQuestion |
| 6 (Deploy) | Load session context | Coordinator | Bash (memory scripts) |
| 7 (System Validation) | Memory roundtrip test | Coordinator | Bash (memory_verify.py) |
| 7 (System Validation) | Agent dispatch test | Coordinator | Task (simple T2) |
| 7 (System Validation) | Protocol searchability | Coordinator | Grep |
| 7 (System Validation) | MCP connectivity | Coordinator | MCP tool call |
| 7 (System Validation) | Graph connectivity | Coordinator | Neo4j read_cypher |
| 9 (Storage Decision) | Repo creation | Coordinator | Bash (gh repo create) |
| 9 (Storage Decision) | Initial push | Coordinator | Bash (git push) |
| 10 (Build-Up) | Create directories | Coordinator | Bash (mkdir) |
| 10 (Build-Up) | Self-explore scan | Pathfinder | Neo4j + Qdrant + Glob |

## Example

```
[Session start]
Coordinator detects <!-- _WORKFLOW_NEEDS_INIT --> in CLAUDE.md

Phase 1: ✅ Docker running, Python 3.11, git initialized, Node.js available
Phase 2: User: "Alex". First time? Yes. Name: "TrizGur". Self-explore done. Language: English, style: informal.
Phase 3: Pathfinder scans → "Next.js 14 app, Prisma ORM, PostgreSQL. Archetype: Web App."
Phase 4: "Focus on shipping features fast or test coverage?" → speed.
Phase 5: Created: engineer (frontend), engineer (backend). Protocol: project/api-conventions.md
Phase 6: Docker deployed, memory collection created, bot skipped.
Phase 7: All tests pass. Memory roundtrip OK. Agents respond. Protocols found.
Phase 8: Research opt-in accepted.
Phase 9: TrizGur asks: "Store me in a repo or in this project?" → Repo: alex/trizgur
Phase 10: Build-Up complete. Version → 1.0. Workflow ready.
Phase 11: Planning mode. "What are your current tasks?"
         User: "Build REST API for user management." → First task planned.
```
