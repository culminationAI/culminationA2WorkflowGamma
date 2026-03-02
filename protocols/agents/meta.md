# Meta-Protocol: How to Use Protocols

## Overview

Protocols are reusable behavioral patterns. This meta-protocol defines how to discover, load, apply, create, and maintain protocols.

## Discovery

Before any T3+ task, search for relevant protocols:

```bash
python3 memory/scripts/memory_search.py "protocol [task keywords]"
```

If a protocol is found, read it before dispatching to a subagent.

## Loading

Protocols are loaded on-demand, never all at once. Load only what's needed:

1. Check the protocol index in CLAUDE.md (name → trigger → file path)
2. Read the protocol file
3. Extract the relevant section (don't inject the entire protocol if only one section applies)
4. Inject into subagent prompt or apply to coordinator behavior

## Application

Protocols are templates, not rigid scripts:

- **Adapt** to the specific situation (protocol says "5 tests minimum" → use 3 if the change is trivial)
- **Skip steps** that clearly don't apply (cloning protocol for a typo fix → skip, just fix it)
- **Escalate** when the protocol doesn't cover the situation (ask user or create new protocol)
- **Document deviations** — if you skip a step, note why in the task summary

## Creation

Create a new protocol when:
- A pattern is used 3+ times
- A process has 4+ steps that need to be remembered
- User explicitly requests formalization

### Creation Process

1. **Detect** — identify the recurring pattern or need. What behavior should be standardized?
2. **Check existing** — search for similar protocols:
   ```bash
   python3 memory/scripts/memory_search.py "protocol [keywords]"
   ```
   Check CLAUDE.md protocol index. If a similar protocol exists, extend it instead of creating a new one.
3. **Scope** — define boundaries: what this protocol covers, what it does NOT cover, how it relates to existing protocols.
4. **Draft** — write the protocol using the template below. Delegate to llm-engineer for complex protocols.
5. **Dry-run** — mentally test on 3 real cases from the current project:
   - "If I had this protocol last week, would it have helped with task X?"
   - "Does any step conflict with existing rules?"
   - "What edge case would break this?"
6. **Register** — add to CLAUDE.md protocol index table + store summary in Qdrant:
   ```bash
   python3 memory/scripts/memory_write.py '[{"text": "Protocol: [name] — [purpose]", "agent_id": "coordinator", "metadata": {"type": "protocol"}}]'
   ```
7. **Post-review** — after first real application, evaluate: were steps clear? Were any steps skipped? Revise if needed.

### Protocol Template

Every protocol must have:

```markdown
# {Protocol Name}

## Overview
One paragraph: what this protocol does, when to use it.

## Triggers
When is this protocol activated? (user command, task type, automatic)

## Process
Numbered steps. Each step: what to do, expected input/output.

## Rules
Numbered constraints. What MUST/MUST NOT happen.

## Examples
1-2 concrete examples of the protocol in action.
```

Optional sections: Cleanup, Verification, Edge Cases.

### Quality Checklist
Before committing a new protocol:
- [ ] Has Overview explaining purpose
- [ ] Has clear Triggers (when to activate)
- [ ] Process steps are actionable (not vague)
- [ ] Rules are specific (not "be careful")
- [ ] At least 1 example included
- [ ] English language
- [ ] Stored in `protocols/` directory
- [ ] Added to CLAUDE.md protocol index
- [ ] Summary stored in Qdrant with metadata `{type: "protocol"}`

## Auto-Protocol Creation

Protocols are created not only manually but also automatically when patterns emerge:

### Triggers for Auto-Creation

1. **User introduces a new method/principle** — coordinator detects a new behavioral rule and invokes protocol-manager to formalize it
2. **Build-Up detects recurring pattern** — if a process is used 3+ times across sessions, protocol-manager drafts a protocol
3. **Coordinator introduces a new rule** — any new rule added to CLAUDE.md or agent definitions MUST be backed by a protocol
4. **Feature introduction** — new features with multi-step processes should have accompanying protocols

### Meta-Rule

**If coordinator or any agent introduces a new behavioral rule or feature, protocol-manager MUST be invoked to evaluate whether it should become a protocol.**

Threshold for protocol creation:
- Used 3+ times (pattern detected)
- Has 4+ steps (process complexity)
- Explicitly requested by user
- Introduces a constraint that others must follow

### Auto-Creation Process

1. Coordinator or build-up pipeline detects trigger
2. Coordinator dispatches protocol-manager with context
3. Protocol-manager checks existing protocols for overlap
4. Protocol-manager drafts new protocol following the template
5. Protocol-manager registers in README.md and CLAUDE.md
6. Coordinator stores creation record in memory: `{type: "build_up", subtype: "protocol_created"}`

## Versioning

- Protocols don't use version numbers in filenames
- Changes are tracked via git commits
- Major rewrites: add changelog entry at the top of the file
- Breaking changes: announce in the summary report after build-up

## Lifecycle

1. **Draft** — written but not yet tested
2. **Active** — tested and applied in production
3. **Deprecated** — superseded by a better protocol, kept for reference

## Protocol Index Maintenance

The CLAUDE.md protocol table is the single source of truth:

| Protocol | Trigger | File |
|----------|---------|------|

When creating/deleting a protocol:
1. Update the table in CLAUDE.md
2. Store/update summary in Qdrant
3. If deleting: remove file, update table, mark Qdrant record as deprecated

## Anti-Patterns

- **Protocol overload**: don't create protocols for one-time tasks
- **Protocol blindness**: don't follow protocols when common sense says otherwise
- **Protocol bloat**: keep protocols under 150 lines; if longer, split into sub-protocols
- **Stale protocols**: review and clean up quarterly
