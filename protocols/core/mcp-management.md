# MCP Server Management Protocol

## Overview

MCP servers add ~2,000 tokens of tool definitions per server to every prompt.
8 servers × 2K = ~16K tokens overhead per message. This protocol manages server
lifecycle to minimize token waste while keeping necessary tools available.

Default profile is `core` — only 2 servers, ~4K overhead. Specialized servers are
loaded on-demand. Switch profiles before the session; changes take effect after restart.

## Server Classification

### Core Servers (always loaded)

| Server | Package | Why Always |
|--------|---------|------------|
| context7 | @upstash/context7-mcp | Library docs lookup needed in any technical session |
| filesystem | @modelcontextprotocol/server-filesystem | `directory_tree`, `move_file` — no native tool equivalents |

### Specialized Servers (on-demand)

| Server | Package | Used By | Trigger |
|--------|---------|---------|---------|
| neo4j | mcp-neo4j-cypher | data-architect, engineer | Graph DB work |
| qdrant | mcp-server-qdrant | data-architect, engineer | Vector store work |
| github | @modelcontextprotocol/server-github | engineer, llm-engineer | PRs, issues, code review |
| playwright | @playwright/mcp | engineer | Web scraping, UI testing |
| semgrep | semgrep-mcp | engineer | Security audit (rare) |
| youtube-transcript | @kimtaeyoon83/mcp-server-youtube-transcript | researcher agents | Video parsing |

## Profile System

### Profiles

| Profile | Servers | ~Token Overhead | Use When |
|---------|---------|-----------------|----------|
| `core` | context7, filesystem | ~4K | Default — most sessions |
| `db` | core + neo4j + qdrant | ~8K | Graph/vector DB work |
| `web` | core + playwright + github | ~8K | Web dev, PR review |
| `research` | core + youtube-transcript | ~6K | Video-heavy research |
| `full` | all 8 servers | ~16K | Cross-domain work, debugging |

### Switching Profiles

```bash
python3 mcp/mcp_configure.py --profile core      # default
python3 mcp/mcp_configure.py --profile db         # add DB servers
python3 mcp/mcp_configure.py --profile web        # add web servers
python3 mcp/mcp_configure.py --profile research   # add research servers
python3 mcp/mcp_configure.py --profile full       # all servers
python3 mcp/mcp_configure.py --add github         # add single server
python3 mcp/mcp_configure.py --remove semgrep     # remove single server
python3 mcp/mcp_configure.py --status             # show active servers
```

**Important:** Restart Claude Code after switching. Changes do not take effect mid-session.

## Token Budget

| Profile | Servers | Overhead/msg | Overhead/100 msgs |
|---------|---------|--------------|-------------------|
| `core` | 2 | ~4K | ~400K |
| `db` | 4 | ~8K | ~800K |
| `web` | 4 | ~8K | ~800K |
| `research` | 3 | ~6K | ~600K |
| `full` | 8 | ~16K | ~1.6M |
| **savings: core vs full** | | **-12K/msg** | **-1.2M/100 msgs** |

Rule of thumb: every unnecessary server costs ~2K tokens per message. In a 50-message
session, one extra server = ~100K tokens wasted.

## Subagent MCP Access

Subagents declare their MCP servers in YAML frontmatter `mcpServers` field.
They ONLY get what is listed — not inherited from the coordinator's active profile.

| Agent | mcpServers | Rationale |
|-------|-----------|-----------|
| engineer | neo4j, qdrant, github | Full DB access + PR workflow |
| data-architect | neo4j, qdrant | Schema design, queries |
| llm-engineer | github | PR review, agent iteration |
| pathfinder | (none) | Uses Python scripts for memory |
| protocol-manager | (none) | File-only operations |
| domain agents | Assigned during init based on project type |

Keep `mcpServers` lists minimal. Each listed server adds ~2K tokens to every subagent
prompt. Giving an agent a server it never calls wastes budget on every dispatch.

## New Server Validation Protocol

### Triggers

- User requests adding a new MCP server
- Coordinator identifies need for new capability
- Community recommends a new server

### Validation Steps

**Step 1: Origin Check**
- Package published on npm/PyPI under a verified publisher
- Repository: recent commits, >10 stars, not abandoned
- Run `npm audit signatures` (for npm packages)
- Search `"{package-name} malware"` and `"{package-name} compromised"`

**Step 2: Tool Inventory Review**
- Install in isolation — do NOT add to active config yet
- List all exposed tools and their descriptions
- Red flags: file system access beyond stated scope, unknown network calls, shell exec without confirmation

**Step 3: Permission Analysis**
- Credentials via env vars only — never hardcoded
- What filesystems, APIs, or systems can it access?
- Apply minimum necessary permissions principle

**Step 4: Isolation Test**
- Add to `mcp-full.json` only (NOT the active `mcp.json`)
- Test with `full` profile on a non-sensitive task
- Verify tool definitions match docs
- Check logs for unexpected network calls

**Step 5: Registration**
- Classify: core or specialized?
- Assign to agents: which agents need it? Update `mcpServers` frontmatter
- Add to profile(s) in `mcp_configure.py`
- Document in `mcp/servers.md`
- Update CLAUDE.md MCP table

### Red Flags — STOP and Investigate

- Package recently renamed or ownership transferred
- Publisher account less than 6 months old
- Unusually broad file system access
- Undocumented network endpoints
- Requires root or admin permissions
- Tool descriptions do not match stated purpose
- No source code available (binary-only distribution)

If any red flag is present → do NOT add the server. Report to user with specific concern.

## Initialization Integration

During Phase 5 (Deploy), the MCP profile is selected based on project archetype:

| Project Archetype | Default Profile | Rationale |
|------------------|----------------|-----------|
| AI/ML, Data | `db` | Neo4j + Qdrant for graphs/vectors |
| Content, Research | `research` | YouTube + sources |
| Web App, DevOps | `web` | Playwright + GitHub |
| General, Unknown | `core` | Minimal — add servers as needed |

Steps:
1. Detect archetype from Phase 2 analysis
2. Run `python3 mcp/mcp_configure.py --profile {profile}`
3. Inform user: "Active MCP profile: {name}, {N} servers, ~{N}K tokens/message"
4. Ask: "Need additional servers?" → add individually if yes

For multi-archetype projects: start with the primary archetype profile, then `--add`
individual servers for secondary archetypes rather than jumping to `full`.

## Rules

1. Default profile is ALWAYS `core` — never load specialized servers speculatively
2. NEVER add a server to core without explicit justification and user approval
3. Subagent `mcpServers` lists must be MINIMAL — only tools the agent actually calls
4. `mcp-full.json` is the source of truth — `mcp.json` is generated from it
5. New servers MUST pass all 5 validation steps before activation
6. After validation, server MUST be documented in `mcp/servers.md` before use
7. Profile switches should be logged in session context (why the switch was needed)
8. NEVER give a subagent access to a server it does not use — overhead is paid per message
9. Coordinator does NOT call specialized MCP tools directly for T2+ tasks — delegate to subagents

## Anti-patterns

- Loading `full` profile "just in case" — wastes ~12K tokens/message over `core`
- Adding a server to `core` because "we might need it sometimes"
- Skipping validation steps for "trusted" or "popular" packages
- Giving subagents more MCP servers than they actively call
- Not restarting Claude Code after a profile switch (changes silently do not apply)
- Using coordinator's MCP tools directly for T2+ tasks instead of delegating to subagents
- Adding a server mid-session expecting it to take effect immediately
- Running `full` profile in production — high sustained token cost
