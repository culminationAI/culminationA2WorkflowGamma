# Agent Creation Protocol

## Overview

How to design, create, test, and register a new subagent. Used during initialization and when new domains emerge during a project.

## Triggers

- Initialization protocol (new project setup)
- New domain without agent coverage
- Existing agent overloaded (covers 2+ unrelated domains)
- User request: "create an agent for X"

## Process

### Step 1: Check Existing

Can an existing agent cover this domain?
- If the new domain overlaps 50%+ with an existing agent → extend that agent's expertise
- If it's a clearly separate domain → proceed with new agent

### Step 2: Define

Determine the agent's properties:

| Property | Description | Example |
|----------|-------------|---------|
| **Name** | kebab-case, descriptive | `frontend-engineer` |
| **Domain** | Primary expertise area | Frontend: React, CSS, accessibility |
| **Model** | sonnet (default), opus (complex reasoning), haiku (fast/light) | sonnet |
| **Tools** | What tools the agent needs | Read, Grep, Glob, Write, Edit, Bash |
| **Max turns** | Complexity ceiling | 20 (default), 30 (research) |
| **Contracts** | Input/output artifacts | Data Spec → Implementation Report |

### Step 3: Draft

Write the agent definition file using this template:

```yaml
---
model: sonnet
tools: [Read, Grep, Glob, Write, Edit, Bash]
memory: project
---
```

Followed by markdown sections:
1. **Role** — one paragraph: who the agent is, what it does
2. **Expertise** — bullet lists organized by subdomain
3. **Method** — how the agent approaches work (principles, verification steps)
4. **Contracts** — what artifacts it receives and produces
5. **Output Format** — language rules + JSON-summary template

Delegate complex agent drafts to llm-engineer.

### Step 4: Route

Add entry to `dispatcher.md` routing table:

```markdown
| New domain keywords | new-agent-name |
```

### Step 5: Register

1. Add to CLAUDE.md subagent table
2. Store in memory:
   ```bash
   python3 memory/scripts/memory_write.py '[{"text": "Agent created: [name] for [domain]", "agent_id": "coordinator", "metadata": {"type": "agent_creation"}}]'
   ```

### Step 6: Test

Run 2-3 tasks of increasing complexity:
1. T2 task — basic capability check
2. T3 task — domain expertise verification
3. Verify JSON-summary format in response

### Step 7: Iterate

After first real use, review:
- Did the agent stay in scope?
- Was the expertise section sufficient?
- Did contracts flow correctly?
- Adjust definition based on findings

## Domain Catalog

Reference for common project archetypes:

| Spectrum | Typical Agents | Key Tools |
|----------|---------------|-----------|
| AI/ML | data-architect, ml-researcher, llm-engineer | Neo4j, Qdrant, WebSearch |
| Web Dev | frontend-eng, backend-eng, designer | Bash, Playwright |
| Data | data-engineer, analyst, visualizer | Bash, Neo4j |
| Content | researcher(s), writer, curator | WebSearch, WebFetch |
| DevOps | devops-eng, security-analyst | Bash, Docker |
| Science | researcher(s), analyst, curator | WebSearch, WebFetch |
| Game | game-designer, engine-eng, artist | Bash, Write |

## Quality Checklist

Before committing a new agent:
- [ ] Domain does not overlap with existing agents
- [ ] Expertise list is specific (not vague)
- [ ] Tools are minimal (only what's needed)
- [ ] Contracts define input and output
- [ ] Routing entry added to dispatcher.md
- [ ] Registered in CLAUDE.md subagent table
- [ ] Tested with 2-3 real tasks

## Anti-patterns

- **Domain overlap** — two agents covering the same area (merge or split clearly)
- **Too narrow** — agent for a single task (merge with closest neighbor)
- **Missing contracts** — no defined input/output (leads to broken handoffs)
- **No routing entry** — agent exists but coordinator can't find it
- **Kitchen sink** — agent with 10+ expertise areas (split into focused agents)
