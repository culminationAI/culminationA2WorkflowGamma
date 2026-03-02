# Cloning Protocol

## Overview

Creates isolated copies of the coordinator with variant rule sets for build-up testing. Each clone is a self-contained environment where modified rules can be tested without affecting the main workspace.

## Mechanisms

### Git Projects
Use Claude Code worktree isolation:
```
Task tool with isolation: "worktree"
```
or
```
EnterWorktree tool with name: "bu-{YYYY-MM-DD}-v{N}"
```

Creates an isolated git worktree with its own copy of the repo. Changes in the worktree don't affect the main branch until explicitly merged.

### Non-Git Directories (main/)
Copy config files to a temporary directory:
```bash
CLONE_DIR="/tmp/bu-$(date +%Y%m%d)-v{N}"
mkdir -p "$CLONE_DIR/.claude/agents"
cp CLAUDE.md "$CLONE_DIR/"
cp -r .claude/agents/ "$CLONE_DIR/.claude/agents/"
cp -r protocols/ "$CLONE_DIR/protocols/"
```

## Process

### 1. Prepare
- Define what changes each variant will test
- Ensure changes are scoped (don't modify unrelated configs)
- Document variant description in evolve/ registry

### 2. Create
- One clone per variant (max 3 simultaneous)
- Each clone gets its variant's modified files
- Clone inherits all unchanged configs from parent

### 3. Register
Track clones in `evolve/active-clones.json`:
```json
{
  "clones": [
    {
      "id": "bu-2026-03-02-v1",
      "description": "Strict delegation: add CRITICAL rule to Query Optimization",
      "files_modified": ["CLAUDE.md"],
      "created": "2026-03-02T10:00:00Z",
      "status": "testing"
    }
  ]
}
```

### 4. Test
Hand off to testing protocol. Each clone runs the same test suite.

### 5. Cleanup
After evaluation:
- **Best clone**: merge changes into main config
- **Other clones**: delete (worktrees auto-cleanup, temp dirs `rm -rf`)
- Update registry: set status to "merged" or "rejected"

## Constraints

- Max 3 simultaneous clones
- Each clone must be self-contained (no cross-clone dependencies)
- Clone lifetime: max 1 session (don't leave orphan clones)
- Always clean up after evaluation

## Naming Convention

`bu-{YYYY-MM-DD}-v{N}` where N is the variant number (1, 2, 3)
