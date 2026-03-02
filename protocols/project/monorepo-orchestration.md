# Monorepo Orchestration Protocol

## Overview

Specialized coordination strategy for monorepo workspaces. Extends initialization Phase 4 and coordination protocol with package-aware agent spawning, dependency resolution, and scoped testing.

## Triggers

- Archetype = Monorepo (detected in Phase 2)
- Signals: pnpm-workspace.yaml, turbo.json, lerna.json, nx.json, packages/*, apps/*

## Phase 2 Extension: Package Mapping

After archetype detection, pathfinder performs additional scan:

1. **List packages** — read workspace config:
   - pnpm: `pnpm-workspace.yaml` → `packages:` array
   - turbo: `turbo.json` → check alongside package.json workspaces
   - lerna: `lerna.json` → `packages:` array
   - nx: `nx.json` + `project.json` files

2. **Classify packages** by type:
   - `app` — deployable application (has `start` script, server entry point)
   - `lib` — shared library (consumed by other packages)
   - `config` — shared configuration (eslint, tsconfig, tailwind)
   - `tool` — build tooling, scripts, CLI
   - `test` — test utilities, fixtures, e2e suites

3. **Map dependencies** — build internal dependency graph:
   - Read each package.json → extract `dependencies` and `devDependencies` referencing workspace packages
   - Produce adjacency list: `{package_name: [dependency_names]}`

4. **Store in exploration report:**
   ```json
   {
     "monorepo": {
       "tool": "pnpm|turbo|lerna|nx",
       "packages": [
         {"name": "web", "path": "apps/web", "type": "app", "deps": ["ui", "config"]},
         {"name": "ui", "path": "packages/ui", "type": "lib", "deps": ["config"]},
         {"name": "config", "path": "packages/config", "type": "config", "deps": []}
       ]
     }
   }
   ```

## Phase 4 Extension: Agent Spawning

### Rules

1. **Max 4 concurrent per-package agents** — coordinator manages queue if more packages exist
2. **One engineer per distinct domain** — group related packages:
   - All `config` packages → single engineer (config)
   - All `app` packages of same type (e.g., web apps) → single engineer (web)
   - Complex `lib` packages → dedicated engineer per lib
3. **Shared context** for all package agents:
   - Root `tsconfig.json` / `tsconfig.base.json`
   - Workspace config (pnpm-workspace.yaml, turbo.json)
   - CI/CD pipeline definition
   - Root package.json (scripts, engines)

### Agent Creation Template

```
Agent: engineer (packages/[name])
Domain: [package_name] — [package_type] in [monorepo_tool] workspace
Scope: [package_path]/
Dependencies: [list of internal deps]
Dependents: [list of packages that depend on this one]
Shared context: [root configs to always consider]
```

## Coordination Patterns

### Pattern 1: Isolated Change (single package)

```
User request → targets 1 package
  → dispatch engineer (packages/[name])
  → run tests: affected package only
  → no cross-package coordination needed
```

**Test command:** `turbo run test --filter=[package]` or `pnpm --filter [package] test`

### Pattern 2: Cross-Package Refactor

```
User request → affects 2+ packages
  → coordinator identifies affected packages from dependency graph
  → assign lead engineer (package with most dependents)
  → lead proposes interface changes
  → coordinator dispatches dependent package engineers sequentially
  → each dependent adapts to interface changes
  → run tests: affected + all downstream dependents
```

**Critical rule:** Interface changes flow top-down (dependency → dependents). Never parallelize changes to a package and its dependents simultaneously.

### Pattern 3: Workspace-Wide Change

```
User request → affects root config, CI, workspace setup
  → coordinator handles directly (T1-T2) or dispatches single engineer
  → run ALL tests across workspace
```

**Test command:** `turbo run test` or `pnpm -r test`

### Pattern 4: New Package Creation

```
User request → create new package
  → coordinator decides package type (app/lib/config/tool)
  → dispatch engineer to scaffold package using workspace conventions
  → update workspace config (add to pnpm-workspace.yaml if needed)
  → update root tsconfig references
  → create dedicated engineer agent if package warrants one
```

## Testing Strategy

| Change Scope | Test Scope | Command Pattern |
|-------------|------------|-----------------|
| Single package, no API change | Package only | `--filter=[package]` |
| Single package, API change | Package + downstream | `--filter=...[package]` |
| Multiple packages | All affected + downstream | `--filter=[pkg1] --filter=[pkg2]...` |
| Root config / CI | All packages | No filter (full run) |

### Dependency-Aware Test Order

1. Sort affected packages topologically (leaves first)
2. Test leaf packages first (no internal deps)
3. Test intermediate packages
4. Test root packages (apps) last

## Memory Records

For monorepo projects, store:
- Package list with types: `{type: "project_fact", subtype: "monorepo_packages"}`
- Dependency graph: `{type: "project_fact", subtype: "monorepo_deps"}`
- Agent-to-package mapping: `{type: "decision", subtype: "agent_assignment"}`

## Anti-Patterns

1. **DON'T** create one agent per package for large monorepos (100+ packages) — group by domain
2. **DON'T** run all tests for isolated changes — use filter
3. **DON'T** parallelize changes to a package and its dependents — interface contracts may break
4. **DON'T** modify root configs without running full test suite
5. **DON'T** ignore workspace tool conventions — if project uses turbo, use turbo commands
