# Shared Repo Sync

## Overview

Rules for syncing code from the local workspace to shared GitHub repositories used by multiple agents. Applies when local changes to shared infrastructure need to be propagated so all agents operate from the same codebase. Push is a deliberate step — never automatic, always after a local commit.

## Triggers

- Local exchange code changed and committed in the workspace
- Docker rebuild from new exchange code completed successfully
- Explicit user request to push to shared repo
- Build-up affecting shared infrastructure

## Shared Repos Registry

| Repo | Content | Agents |
|------|---------|--------|
| `culminationAI/workflow-exchange` | Exchange server (app.py, templates/, chain.py, etc.) | okiara, falkvelt |

## Process

1. **Detect** — check whether local code differs from the shared repo. Compare using `git diff` in submodule or GitHub API.

2. **Commit locally** — verify all changes are committed before pushing.

3. **Push** — use `mcp__github__push_files` or `git push` from submodule to push modified files to shared repo in a single commit.

4. **Notify** — send exchange message to all agents listed in the Shared Repos Registry:
   ```json
   {
     "type": "notification",
     "subject": "Shared repo updated: {repo}",
     "body": "N files pushed. Rebuild Docker image to apply."
   }
   ```

5. **Store** — write memory record: `{type: "shared_repo_sync", repo: "...", files_pushed: N}`

## Rules

1. MUST push after every Docker rebuild using new shared code
2. MUST use conventional commits in English: `feat|fix|refactor(exchange): description`
3. MUST notify all agents listed for the repo via exchange after every push
4. MUST NOT push without committing locally first
5. MUST NOT push secrets, `.env`, `exchange_data/`, or `__pycache__`
6. MUST NOT force-push to `main` — fast-forward only
