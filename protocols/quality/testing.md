# Testing Protocol

## Overview

Universal benchmark framework for evaluating coordinator variants during build-up. Adapts test selection and metric weights based on the type of change being tested.

## Metrics

| Metric | Code | Scale | Description |
|--------|------|-------|-------------|
| Completion | COMP | 0-100% | Was the task fully completed? |
| Quality | QUAL | 1-5 | Output quality and correctness |
| Routing | ROUT | C/W | Correct or Wrong agent selection |
| Memory | MEM | 1-5 | Proper memory search/store |
| Context | CONT | 1-5 | Context engineering quality |
| Efficiency | EFF | tokens | Token usage efficiency |
| Parallelism | PAR | count | Subagents used in parallel |
| Planning | PLAN | Y/N | Was planning done when needed? |
| Errors | ERR | 0-5 | Error count |

## Scoring Formula

```
SCORE = (COMP * 0.25) + (QUAL * 0.20) + (ROUT * 0.15) + (MEM * 0.15) + (CONT * 0.10) + (EFF * 0.15)
```

Scale: 0-100 total.

## Test Waves

### Wave 1: Quick Tasks (T1-T2)
5 tests, baseline efficiency:
- T01: Find a specific file (T1)
- T02: Show content of a known file (T1)
- T03: Add a comment to existing code (T2)
- T04: Fix a typo in documentation (T2)
- T05: Search for a pattern across codebase (T1)

### Wave 2: Single-Agent Tasks (T3)
5 tests, routing validation:
- T06: Write a new utility function (engineer)
- T07: Analyze a character's psychology (narrative-designer)
- T08: Design a database schema (data-architect)
- T09: Research a scientific topic (science-researcher)
- T10: Optimize a prompt (llm-engineer)

### Wave 3: Multi-Agent Chains (T4)
5 tests, handoff validation:
- T11: New component end-to-end (narrative → data → engineer)
- T12: Knowledge domain research (parallel researchers → curator)
- T13: Bug diagnosis and fix (engineer → data-architect → engineer)
- T14: Prompt + implementation (llm-engineer → engineer)
- T15: Cross-domain synthesis (parallel researchers → synthesis)

### Wave 4: Full Pipeline (T4-T5)
5 tests, full system:
- T16: Memory-intensive workflow (search → process → store)
- T17: Protocol-guided task (load protocol → apply → verify)
- T18: Build-Up cycle (detect → plan → test)
- T19: Multi-project coordination
- T20: Complex architectural decision

### Wave 5: Self Build-Up

| ID | Test | Coordinator Steps | Pass Criteria |
|----|------|------------------|---------------|
| T21 | Gap analysis accuracy | 1. Coordinator: Read `capability-map.md`, identify a well-covered domain<br>2. Run lightweight gap scan on that domain<br>3. Verify score > 0.8<br>4. Inject a fake unknown domain, run scan<br>5. Verify STRUCTURAL gap detected | Known domain → no gap. Unknown domain → gap detected. |
| T22 | Build lifecycle | 1. Create test build manifest in `build-registry.json` (Edit)<br>2. Create test spec in `spec-registry.json` (Edit)<br>3. Activate: Write test agent file, update states<br>4. Verify: Glob test files exist, states=active/IN_USE<br>5. Deactivate: Delete test files, update states<br>6. Verify: Glob test files gone, states=buffered/AVAILABLE<br>7. Cleanup: remove test entries from registries | Full lifecycle: draft→active→buffered. Files created and cleaned. |
| T23 | Self-explore completeness | 1. Run pathfinder self-explore<br>2. Read `capability-map.md`<br>3. Glob all `.claude/agents/*.md` → verify each listed in map<br>4. Glob all `protocols/**/*.md` → verify each listed in map<br>5. Verify no orphaned entries | All agents and protocols present in capability-map. No orphans. |

Smoke test details: `docs/self-architecture/smoke-tests/`

## Adaptive Test Selection

Not all tests run for every evaluation. Select based on change type:

| Change Type | Priority Tests | Key Metrics |
|-------------|---------------|-------------|
| Routing fix | T06-T10 (Wave 2) | ROUT, PAR |
| Delegation fix | T11-T15 (Wave 3) | PAR, ROUT, PLAN |
| Memory fix | T16-T17 (Wave 4) | MEM, CONT |
| Protocol fix | T17-T18 (Wave 4) | CONT, QUAL |
| Self-build-up fix | T21-T23 (Wave 5, coordinator-runnable) | COMP, QUAL |
| Architectural | All waves | All metrics |

Minimum: 5 tests per evaluation. Maximum: all 23.

## Evaluation Process

### 1. Select Tests
Based on change type, pick 5-20 relevant tests.

### 2. Run Tests
Execute identical test set on each variant. Record:
- Raw metric scores per test
- Total score per variant
- Notes on observed behavior

### 3. Compare
For each variant:
- Calculate total SCORE (0-100)
- Calculate delta from baseline (current production config)
- Identify which metrics improved/degraded

### 4. Determine Best/Worst
- **Best**: highest total SCORE + positive delta on target metrics
- **Worst**: lowest total SCORE or negative delta on target metrics

### 5. Extract Anti-Patterns
From worst variant, identify specific behaviors that caused score drops:
```json
{
  "anti_pattern": "Adding too many constraints caused instruction confusion",
  "metric_impact": "QUAL dropped from 4.2 to 3.1",
  "test_ids": ["T06", "T11"]
}
```

## Test Log Format

Per-test log in `evolve/test-logs/`:
```markdown
# Test T{NN}: {name}
**Variant:** bu-2026-03-02-v1
**Input:** {test prompt}
**Expected:** {expected behavior}
**Actual:** {what happened}
**Scores:** COMP=90 QUAL=4 ROUT=C MEM=3 CONT=4 EFF=1200tok
**Notes:** {observations}
```

## Summary Report

After all tests complete:
```markdown
# Build-Up Test Report: {date}

| Variant | Score | Delta | Best Metrics | Worst Metrics |
|---------|-------|-------|-------------|---------------|
| v1      | 82    | +5    | ROUT, PAR   | -             |
| v2      | 71    | -6    | -           | QUAL, MEM     |

**Winner:** v1
**Anti-patterns from v2:** {description}
**Recommendation:** Merge v1, store v2 anti-patterns
```
