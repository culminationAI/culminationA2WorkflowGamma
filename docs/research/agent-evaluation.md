# Agent Evaluation & Quality Metrics
**Research Date:** 2026-03-03
**Scope:** Benchmarks, metrics, LLM-as-judge, cost-quality tradeoffs, regression detection, multi-agent evaluation, self-assessment, production monitoring — with FalkVelt applicability analysis.

---

## Table of Contents

1. [Agent Benchmarks](#1-agent-benchmarks)
   - 1.1 SWE-bench
   - 1.2 AgentBench
   - 1.3 GAIA
   - 1.4 WebArena
   - 1.5 OSWorld
   - 1.6 τ-bench (tau-bench)
   - 1.7 HumanEval / MBPP
   - 1.8 CLEAR (Enterprise)
   - 1.9 MultiAgentBench
2. [Task Success Metrics](#2-task-success-metrics)
3. [LLM-as-Judge Patterns](#3-llm-as-judge-patterns)
4. [Cost-Quality Tradeoffs](#4-cost-quality-tradeoffs)
5. [Regression Detection](#5-regression-detection)
6. [Multi-Agent System Metrics](#6-multi-agent-system-metrics)
7. [Self-Assessment & Introspection](#7-self-assessment--introspection)
8. [Production Monitoring](#8-production-monitoring)
9. [Academic Research (2025–2026)](#9-academic-research-20252026)
10. [FalkVelt Recommendations](#10-falkvelt-recommendations)

---

## 1. Agent Benchmarks

### 1.1 SWE-bench

**What it measures:** Ability to resolve real GitHub issues in open-source Python repositories. Given a codebase and a bug report, the agent must produce a valid patch.

**How it works:**
- Original: 2,294 issues from 12 Python repos (Django, Flask, etc.)
- SWE-bench Verified: 500-issue curated subset confirmed solvable by human engineers (released 2024)
- SWE-Bench Pro (2025): 1,865 problems from 41 enterprise/business repos — long-horizon tasks requiring hours or days of professional engineer time
- Evaluation: patch is applied, repository tests run; pass/fail is automated

**Key numbers (2025-2026):**
- Best models on Verified: 70%+ (Claude Opus 4.1, GPT-5)
- Same models on SWE-Bench Pro: only 23.3% (GPT-5) and 23.1% (Claude Opus 4.1)
- Mutation-based evaluation (SWE-bench+) reveals benchmark overestimation up to +53.8% on TypeScript, +36.5% on Python

**Strengths:**
- Real code, real issues — not toy problems
- Fully automated evaluation
- Community leaderboard enables comparison
- SWE-bench Pro closes the "benchmark saturation" problem

**Limitations:**
- Only Python (SWE-bench original); Pro adds more languages
- Measures patch quality, not reasoning quality or explanation quality
- Test coverage in repos varies — some patches pass bad tests

**Relevance to FalkVelt:**
HIGH for the `engineer` agent. SWE-bench tasks match the engineer's core work (code debugging, issue resolution). Can be used to benchmark engineer quality in isolation. SWE-bench Verified is the practical entry point.

**Sources:**
- [SWE-bench GitHub](https://github.com/SWE-bench/SWE-bench)
- [SWE-Bench Pro arXiv](https://arxiv.org/abs/2509.16941)
- [Introducing SWE-bench Verified — OpenAI](https://openai.com/index/introducing-swe-bench-verified/)

---

### 1.2 AgentBench

**What it measures:** LLM-as-agent performance across 8 diverse environments — operating systems, databases, knowledge graphs, card games, puzzles, household tasks, web shopping, web browsing.

**How it works:**
- 8 environments, each with distinct task structure, state space, and reward function
- Dev set: 269 tasks; Test set: 1,014 tasks (~11K inference calls)
- Agents must make sequential decisions; evaluated on task completion
- Tests 29+ LLMs including commercial and open-source up to 70B

**Key findings:**
- Top commercial LLMs (GPT-4 class) show strong agent ability
- Significant disparity between commercial and open-source models
- Main failure modes: poor long-term reasoning, weak decision-making, instruction following breakdown

**MultiAgentBench (2025 extension):**
- Evaluates collaboration and competition in multi-agent LLM systems (ACL 2025)
- Introduces milestone-based KPIs measuring individual contributions and coordination
- Tests coordination protocols: star, chain, tree, graph topologies
- Key finding: graph-mesh topology yields best results; tree topology is least effective
- Cognitive evolution improves milestone completion by +3% over vanilla planning

**Strengths:**
- Broadest environment coverage of any single benchmark
- Catches generalizable capabilities vs. narrow specialists
- Multi-agent extension directly relevant for modern architectures

**Limitations:**
- Some environments (card games, puzzles) are less practically relevant
- Benchmark saturation at the top for commercial models
- Does not measure cost or latency

**Relevance to FalkVelt:**
MEDIUM. The OS, database, knowledge graph, and web environments directly map to what pathfinder and engineer do. Use as secondary validation after domain-specific eval. MultiAgentBench methodology is directly relevant for evaluating coordinator ↔ agent interaction quality.

**Sources:**
- [AgentBench arXiv](https://arxiv.org/abs/2308.03688)
- [AgentBench GitHub](https://github.com/THUDM/AgentBench)
- [MultiAgentBench ACL 2025](https://aclanthology.org/2025.acl-long.421/)

---

### 1.3 GAIA

**What it measures:** General AI assistant capability on real-world questions requiring multi-step reasoning, web browsing, tool use, file handling, and multimodal understanding.

**How it works:**
- 466 questions with ground-truth answers (300 on public leaderboard)
- Three difficulty levels:
  - Level 1: fewer than 5 steps, minimal tool use
  - Level 2: 5-10 steps, multiple tools, more complex reasoning
  - Level 3: unrestricted complexity
- Questions are factual with unambiguous answers (simplifies scoring)
- Evaluates web search, calculator use, file reading, image analysis

**Key numbers (2025):**
- Humans: 92% accuracy
- Early GPT-4 with plugins: ~15%
- H2O.ai h2oGPTe (2025 SOTA): 75% — first "grade C" on the test set
- Leaderboard hosted on Princeton HAL and HuggingFace

**Strengths:**
- Conceptually simple for humans, hard for AI — exposes genuine capability gaps
- Unambiguous answers eliminate judge subjectivity
- Broad tool-use coverage
- Created by Meta-FAIR + Hugging Face collaboration — academically rigorous

**Limitations:**
- 466 questions is small (high variance)
- Test set answers are hidden (blind evaluation only)
- Not specialized to coding or protocol work
- Level 3 tasks require significant infrastructure

**Relevance to FalkVelt:**
MEDIUM-HIGH for the `pathfinder` agent. GAIA's research/browse/reason structure maps directly to pathfinder's exploration and web research tasks. Level 1-2 questions are reasonable evaluation targets.

**Sources:**
- [GAIA arXiv](https://arxiv.org/abs/2311.12983)
- [GAIA at Meta AI](https://ai.meta.com/research/publications/gaia-a-benchmark-for-general-ai-assistants/)
- [HAL GAIA Leaderboard](https://hal.cs.princeton.edu/gaia)
- [H2O.ai GAIA result](https://h2o.ai/blog/2025/h2o-ai-tops-the-general-ai-assistant-test/)

---

### 1.4 WebArena

**What it measures:** Task completion on realistic web environments — e-commerce, social media, coding platforms, content management systems (CMS).

**How it works:**
- 812 long-horizon tasks from 241 templates (avg 3.3 variations per template)
- Fully self-hosted, reproducible web environment (no live web dependency)
- Interactive replicas of major website categories
- Evaluates long-horizon planning, cross-application reasoning, memory management
- OpenAI CUA achieves 58.1% success rate (2025)

**Strengths:**
- Reproducible (self-hosted)
- Tests realistic multi-step web workflows
- High ecological validity for web automation tasks

**Limitations:**
- Standardized pages don't reflect live web variability
- CAPTCHAs and pop-ups not modeled
- Human baseline not well established

**Relevance to FalkVelt:**
LOW-MEDIUM. FalkVelt agents do not do GUI web automation. Relevant only if web research tools (Playwright, browser use) are added to pathfinder. Skip for now.

**Sources:**
- [WebArena on EmergentMind](https://www.emergentmind.com/topics/webarena-benchmark)
- [Best AI Agent Benchmarks 2025 — o-mega](https://o-mega.ai/articles/the-best-ai-agent-evals-and-benchmarks-full-2025-guide)

---

### 1.5 OSWorld

**What it measures:** Multimodal agent performance on realistic computer tasks — email, spreadsheets, file management, cross-application workflows — on Ubuntu and Windows.

**How it works:**
- 369 tasks derived from real-world computer use cases
- Full virtual machine environment (Ubuntu, Windows, macOS)
- Each task includes: initial state config + execution-based evaluation script
- Evaluates GUI grounding, operational knowledge, cross-app coordination
- OSWorld-Verified (2025): enhanced infrastructure, improved task quality

**Key numbers:**
- Human success: 72.36%
- Best AI model (original): 12.24%
- OpenAI CUA: 38.1% (full computer use, 2025)

**Strengths:**
- Most realistic computer use benchmark available
- Execution-based evaluation (no subjectivity)
- Covers real applications

**Limitations:**
- Resource-intensive (full VMs)
- Massive human-AI gap may inflate difficulty beyond practical relevance
- Multimodal requirement (vision) not applicable to text-only agents

**Relevance to FalkVelt:**
LOW. FalkVelt agents operate via code/text APIs, not GUIs. No GUI interaction in current architecture.

**Sources:**
- [OSWorld website](https://os-world.github.io/)
- [OSWorld arXiv](https://arxiv.org/abs/2404.07972)
- [OSWorld-Verified announcement](https://xlang.ai/blog/osworld-verified)

---

### 1.6 τ-bench (tau-bench)

**What it measures:** Tool-Agent-User interaction quality in realistic domains (retail, airline ticketing). Evaluates agents that must use APIs AND follow business policies AND handle dynamic user conversations.

**How it works:**
- Simulates multi-turn dialogues: user (simulated by LLM) ↔ agent (under test) ↔ APIs
- Agent must follow domain-specific policy documents while completing user requests
- Evaluation: compare database state at conversation end with annotated goal state
- Introduces pass^k metric: probability of succeeding on ALL k independent attempts (not just once)
- τ²-bench (2025): adds telecom domain, dual-control scenarios where both agent and user manipulate shared state
- Leaderboard: taubench.com

**Key numbers:**
- GPT-4o: <50% pass@1 success in retail
- GPT-4o: <25% pass^8 in retail (consistency drops sharply)

**Strengths:**
- Most realistic evaluation of production-style tool-calling agents
- pass^k metric captures reliability, not just peak capability
- Business policy compliance is explicitly tested
- Multi-turn interaction captures real workflow complexity

**Limitations:**
- Only retail + airline + telecom domains (narrow)
- Simulated users may not reflect real user behavior
- Requires significant infrastructure to run

**Relevance to FalkVelt:**
HIGH for the `engineer` and `protocol-manager` agents. The policy-following dimension maps directly to agents respecting FalkVelt protocols. The pass^k metric should be adopted for any FalkVelt evaluation: measuring consistency across multiple runs, not just single-run success.

**Sources:**
- [τ-bench arXiv](https://arxiv.org/abs/2406.12045)
- [τ-bench GitHub](https://github.com/sierra-research/tau-bench)
- [τ²-bench GitHub](https://github.com/sierra-research/tau2-bench)
- [Sierra blog on τ-bench](https://sierra.ai/blog/benchmarking-ai-agents)

---

### 1.7 HumanEval / MBPP

**What it measures:**
- **HumanEval** (OpenAI, 2021): 164 Python programming problems with unit tests. Measures pass@k (probability at least one of k samples passes tests).
- **MBPP** (Google, 2021): 374 basic Python problems from crowdsourced entry-level tasks.

**How it works:**
- Code completion from docstring/description
- Automated unit test execution for pass/fail
- pass@1 (greedy) and pass@10/pass@100 for broader capability

**2025 extensions:**
- **HumanEval Pro / MBPP Pro** (ACL 2025): self-invoking code generation — model must solve base problem then use that solution to solve a harder related problem. o1-mini drops from 96.2% on HumanEval to 76.2% on HumanEval Pro.
- **MultiPL-E**: extends HumanEval to 18+ programming languages
- **EvoEval / LiveCodeBench**: contamination-resistant dynamic variants

**Strengths:**
- Gold standard for code generation capability
- Fully automated, reproducible
- Huge literature for comparison

**Limitations:**
- Saturated at the top (GPT-4 class models near 90%+)
- Python-only (HumanEval original)
- Does not measure: code quality, maintainability, documentation
- Does not test real-world context (repositories, dependencies, existing code)

**Relevance to FalkVelt:**
MEDIUM for the `engineer` agent — useful as a code baseline, but insufficient alone. SWE-bench is more relevant for real engineering tasks. HumanEval Pro's self-invoking tasks are more interesting.

**Sources:**
- [HumanEval Pro/MBPP Pro ACL 2025](https://aclanthology.org/2025.findings-acl.686/)
- [HumanEval Pro arXiv](https://arxiv.org/abs/2412.21199)
- [15 LLM coding benchmarks — EvidentlyAI](https://www.evidentlyai.com/blog/llm-coding-benchmarks)

---

### 1.8 CLEAR Framework (Enterprise)

**What it measures:** Multi-dimensional enterprise suitability of AI agents across 5 dimensions — not just accuracy.

**How it works:**

| Dimension | Metric | Formula |
|-----------|--------|---------|
| **C — Cost** | Cost-Normalized Accuracy (CNA) | Accuracy / Cost_USD × 100 |
| **C — Cost** | Cost Per Success (CPS) | Total_Cost / Successful_Tasks |
| **L — Latency** | SLA Compliance Rate | Tasks_within_SLA / Total_Tasks × 100% |
| **E — Efficacy** | Task accuracy + domain-specific quality | (e.g., test pass rate for code) |
| **A — Assurance** | Policy Adherence Score (PAS) | 1 − (Violations / Policy_Critical_Actions) |
| **R — Reliability** | pass@k consistency | Trials_with_k_successes / Total_Trials |

**Composite score:**
```
CLEAR = wC·Cnorm + wL·Lnorm + wE·E + wA·A + wR·R
```
Default: equal weights (0.2 each). Enterprise-customizable.

**Key findings (Nov 2025):**
- Accuracy-only optimization yields agents 4.4-10.8x more expensive than cost-aware alternatives
- Agent performance drops from 60% (single run) to 25% (8-run consistency check)
- CLEAR predicts production success with ρ=0.83 correlation vs ρ=0.41 for accuracy-only
- Expert validation: N=15 domain experts

**Strengths:**
- Only framework to explicitly model cost-quality tradeoff
- Reliability via pass@k built in
- Policy/assurance dimension maps to protocol compliance

**Limitations:**
- Published Nov 2025, limited external validation
- Custom weight tuning requires domain expertise
- SLA thresholds are domain-specific (3s for customer support, 30s for code gen)

**Relevance to FalkVelt:**
VERY HIGH. CLEAR is the most directly applicable enterprise framework. All 5 dimensions map to FalkVelt needs:
- C: token cost per agent per task
- L: response time (especially for interactive coordinator queries)
- E: task completion quality
- A: protocol adherence (FalkVelt protocols = business policy analog)
- R: consistency across repeated task runs (pass^k)

**Sources:**
- [CLEAR arXiv](https://arxiv.org/abs/2511.14136)
- [CLEAR full text](https://arxiv.org/html/2511.14136v1)

---

### 1.9 MultiAgentBench

**What it measures:** Collaboration and competition quality in LLM multi-agent systems.

**How it works:**
- Milestone-based KPIs tracking individual agent contributions toward shared goals
- Tests coordination protocols: star, chain, tree, graph-mesh topologies
- Metrics: communication score, planning score, coordination score
- Innovative strategies tested: group discussion, cognitive planning/evolution

**Key findings (ACL 2025):**
- Graph-mesh topology yields best results across all metrics
- Tree topology is least effective
- Cognitive evolution improves milestone completion by +3% over vanilla planning
- Novel metric: Key Performance Indicator (KPI) tracking milestone progress per agent

**Relevance to FalkVelt:**
HIGH. FalkVelt uses a coordinator → subagent pattern (hub-and-spoke = star topology). MultiAgentBench findings suggest this is suboptimal vs. graph-mesh. Relevant for evaluating whether coordinator overhead adds or subtracts value.

**Sources:**
- [MultiAgentBench ACL 2025](https://aclanthology.org/2025.acl-long.421/)
- [MultiAgentBench arXiv](https://arxiv.org/abs/2503.01935)

---

## 2. Task Success Metrics

### 2.1 Binary vs. Graduated Quality Scores

**Binary success (pass/fail):** Simple, objective, unambiguous. Best for deterministic tasks (code tests pass, database state matches). Cannot capture partial success or near-misses.

**Graduated scores (0.0–1.0):** Captures partial completion, quality gradients, effort recognition. Required for open-ended tasks (explanation quality, research thoroughness). More expensive to compute reliably.

**Practical hybrid:** Use binary for automated CI gates + graduated for human review cadence.

### 2.2 Task-Type Success Definitions

#### Research Tasks (pathfinder)
| Dimension | Metric | Target |
|-----------|--------|--------|
| Completeness | Did the agent address all sub-questions? | ≥ 0.85 |
| Accuracy | Factual correctness verified against sources | ≥ 0.90 |
| Relevance | Source quality + recency | ≥ 0.80 |
| Citation | External claims backed by URLs | 100% |
| Depth | Technical detail appropriate to query tier | ≥ 0.75 |

Automated proxy: count sub-questions answered / total sub-questions. Human-review for accuracy.

#### Code Tasks (engineer)
| Dimension | Metric | Target |
|-----------|--------|--------|
| Correctness | Tests pass | 100% (pass@1) |
| Consistency | Tests pass across 3 runs | ≥ 0.90 (pass^3) |
| Quality | Linter/style compliance | 0 violations |
| Efficiency | Token usage per task | baseline ± 20% |
| Self-correction | Recovery from first attempt failure | tracked |

Automated: test runner + linter. No human review needed for correctness.

#### Protocol Tasks (protocol-manager)
| Dimension | Metric | Target |
|-----------|--------|--------|
| Completeness | All required sections present | 100% |
| Consistency | No contradiction with existing protocols | LLM-judge score ≥ 0.85 |
| Indexing | CLAUDE.md and README updated | automated check |
| Cross-reference | Links to referenced protocols valid | automated |
| Freshness | Last-modified date updated | automated |

Automated: structural validators. LLM-judge for consistency.

#### Prompt Tasks (llm-engineer)
| Dimension | Metric | Target |
|-----------|--------|--------|
| Output quality | Downstream task success rate | ≥ baseline + 10% |
| Token efficiency | Prompt length vs. performance | Pareto-optimal |
| Instruction following | Does model follow all instructions? | LLM-judge ≥ 0.85 |
| Robustness | Consistent output on paraphrase inputs | ≥ 0.80 |

Primarily LLM-judge + downstream task proxy.

### 2.3 The Three-Layer Evaluation Model

Derived from Google Cloud's agent evaluation methodology:

```
Layer 3: End-to-End (full task completion + human review)
    |
Layer 2: Integration (single agent, full multi-step task)
    |
Layer 1: Unit (individual tool call, isolated component)
```

**Layer 1 (automated, fast):** Every tool call tested in isolation. Tool selection accuracy, parameter correctness, error handling. Run in CI on every commit.

**Layer 2 (automated, medium):** Full single-agent task from input to output. Pass/fail + quality score. Run on every agent definition change.

**Layer 3 (human + LLM-judge, slow):** End-to-end system quality. Representative sample. Run weekly or on demand.

**Sources:**
- [Google Cloud methodical approach](https://cloud.google.com/blog/topics/developers-practitioners/a-methodical-approach-to-agent-evaluation)
- [Beyond Task Completion arXiv](https://arxiv.org/abs/2512.12791)
- [AI Agent Metrics — Galileo](https://galileo.ai/blog/ai-agent-metrics)

---

## 3. LLM-as-Judge Patterns

### 3.1 Methodology Overview

LLM-as-judge uses a capable LLM (GPT-4 class or Claude Sonnet/Opus) to evaluate another LLM's output. First validated by the MT-Bench + Chatbot Arena research (Zheng et al., NeurIPS 2023):
- GPT-4 as judge achieves >80% agreement with human preferences
- Same level as inter-human agreement

**Three paradigms:**

| Paradigm | Description | Use Case |
|----------|-------------|----------|
| Pairwise comparison | Judge picks better of two responses or calls tie | A/B testing agent versions |
| Single answer grading | Judge assigns score (1-5 or 0.0-1.0) to one response | Continuous monitoring |
| Reference-guided grading | Judge evaluates against a gold-standard reference | When ground truth exists |

### 3.2 Bias Taxonomy (CALM Framework, 2025)

12 documented bias types in LLM judges:

| Bias | Description | Magnitude | Mitigation |
|------|-------------|-----------|------------|
| **Position bias** | Favors first or last response in pairwise | GPT-4: 40% inconsistency | Randomize order; average both orderings |
| **Verbosity bias** | Longer responses rated higher regardless of quality | ~15% inflation | Length-normalize; penalize verbosity in rubric |
| **Self-enhancement bias** | Judge prefers outputs similar to its own style | 5-7% boost | Use diverse judge model from evaluated model |
| **Authority bias** | Favors responses citing authoritative sources | Variable | Blind source citations in evaluation |
| **Fallacy oversight** | Misses logical errors in confident reasoning | High | Explicit reasoning-check rubric |
| **Sentiment bias** | Prefers positive/confident tone | Variable | Tone-neutral rubric instructions |
| **Safety bias** | Over-refuses when evaluating safety-adjacent content | Variable | Calibrate safety thresholds |
| **Domain gap** | Judge underperforms in specialized domains | High | Use domain-expert model or human review |
| **Judge drift** | Scores shift over long evaluation sessions | Variable | Session limits + anchor examples |

**Key insight:** Models begin evaluation with excessive certainty (average 72.9%) and confidence INCREASES over debate rounds (72.9% → 83.3%) rather than converging toward calibration.

### 3.3 Single-Judge vs. Multi-Judge Panel

| Approach | Agreement with humans | Cost | When to use |
|----------|-----------------------|------|-------------|
| Single GPT-4/Opus judge | ~90% agreement | 1x | Routine daily evaluations |
| Multi-model panel (3-5 models, majority vote) | Reduces bias 30-40% | 3-5x | High-stakes decisions, protocol approval |
| Agent-as-Judge (2025) | Stronger than single-model | 2-3x | Complex multi-step reasoning evaluation |
| Human-in-loop | Ground truth | 10-50x | Calibration, golden dataset creation |

**ChatEval (multi-agent discussion):** Kendall Tau 0.57 with humans vs. 0.52 for single GPT-4.

### 3.4 Calibration Best Practices

1. **Randomize position** in pairwise comparison and average both orderings
2. **Few-shot examples** showing natural distribution of scores
3. **Calibration set** of ~100 human-labeled examples to anchor the judge
4. **Rubric specificity** — vague rubrics amplify bias; explicit criteria reduce it
5. **50-100 evaluations per category** for statistical significance
6. **Confidence intervals** via bootstrap sampling for reported metrics

### 3.5 Cost-Effective Evaluation Strategy

```
Tier A: Automated unit tests (zero LLM cost)
Tier B: Single LLM-judge (Sonnet 4.5, cheap) — daily runs
Tier C: Multi-judge panel (Opus + Sonnet + Haiku) — weekly high-stakes
Tier D: Human review — calibration only (monthly)
```

**Sources:**
- [MT-Bench arXiv](https://arxiv.org/abs/2306.05685)
- [LLM-as-Judge Wikipedia](https://en.wikipedia.org/wiki/LLM-as-Judge)
- [Evaluating Scoring Bias arXiv](https://arxiv.org/html/2506.22316v1)
- [Justice or Prejudice arXiv](https://llm-judge-bias.github.io/)
- [How to Correctly Report LLM-as-Judge Evaluations](https://arxiv.org/html/2511.21140v1)

---

## 4. Cost-Quality Tradeoffs

### 4.1 Claude Model Pricing (2025-2026)

| Model | Input ($/M tokens) | Output ($/M tokens) | SWE-bench Verified |
|-------|-------------------|--------------------|--------------------|
| Haiku 4.5 | $0.80 | $4.00 | 73.3% |
| Sonnet 4.5 | $3.00 | $15.00 | 77.2% |
| Opus 4.6 | $5.00 | $25.00 | ~80%+ |

**Key ratios:**
- Sonnet costs 3.75x more than Haiku but gains only 3.9 percentage points on SWE-bench
- Opus costs 6.25x more than Haiku for ~7-point gain
- Prompt caching: cache writes at 1.25x base, reads at 0.10x base → 90% savings on repeated system prompts

### 4.2 Intelligent Model Routing

**Routing strategy — task complexity tiers:**

| Task Type | Recommended Model | Rationale |
|-----------|------------------|-----------|
| Classification, extraction, routing decisions | Haiku 4.5 | Low complexity, high volume |
| Code writing, protocol authoring, standard research | Sonnet 4.5 | Production workload sweet spot |
| Architectural decisions, complex debugging, prompt design | Opus 4.6 | Quality-critical, low volume |

**Cost savings from routing:**
- Intelligent routing: up to 30% cost reduction without accuracy loss
- Cascading (cheap first, expensive fallback): 60-87% cost reduction
- 57% cost cut demonstrated on multi-agent systems with routing optimization (InfraLovers, 2026)

### 4.3 Cost Per Successful Task (CPST)

The correct unit for cost analysis is not tokens-per-task but **cost per successful outcome**:

```
CPST = Total_cost_for_N_runs / Successful_runs
```

Example: If Sonnet costs $0.10/run with 80% success rate vs. Haiku at $0.03/run with 60% success rate:
- Sonnet CPST = $0.10 / 0.80 = $0.125 per success
- Haiku CPST = $0.03 / 0.60 = $0.050 per success

Haiku is still 2.5x cheaper per successful outcome. But if re-runs are expensive (downstream failures), Sonnet's higher first-pass rate may win.

### 4.4 ROI of Agent Improvements

Framework for measuring improvement ROI:

```
ROI = (ΔSuccess_rate × Volume × Value_per_task - ΔCost) / ΔCost
```

Track over time:
- Tasks per session (volume)
- Success rate trend (quality)
- Tokens per task trend (efficiency)
- Cost per session trend

**Sources:**
- [57% Cost Cut — InfraLovers](https://www.infralovers.com/blog/2026-02-19-ki-agenten-modell-optimierung/)
- [Claude pricing explained](https://www.juheapi.com/blog/claude-pricing-explained-2025-sonnet-opus-haiku-costs)
- [Token optimization strategies](https://www.glukhov.org/post/2025/11/cost-effective-llm-applications/)
- [CLEAR framework — cost dimension](https://arxiv.org/abs/2511.14136)

---

## 5. Regression Detection

### 5.1 Baseline Establishment

Before detecting regressions, establish baselines:
1. Define evaluation dataset (50-100 representative tasks per agent per type)
2. Run 3x per task (accounts for non-determinism); record pass^3 scores
3. Store: task_id, agent, timestamp, pass@1, pass^3, latency_p50, latency_p95, token_cost
4. Set alert thresholds: success rate floor = 85%, latency budget = 10s interactive

### 5.2 Statistical Significance

**Problem:** LLMs are non-deterministic. A 2% success rate drop on 10 tasks is not significant. A 2% drop on 200 tasks is.

**Practical guidance:**
- Minimum 50-100 evaluations per category for statistical significance
- Use bootstrap sampling for confidence intervals
- For binary metrics: two-proportion z-test
- For continuous metrics: Mann-Whitney U test (non-parametric, better for score distributions)

Anthropic's own guidance: statistical approach to model evaluations is essential for reliable conclusions.

**Pass^k vs. Pass@k distinction (critical):**
- **pass@k**: probability at least 1 of k attempts succeeds (measures peak capability)
- **pass^k** (pass-power-k): probability ALL k attempts succeed (measures consistency)

Production systems need pass^k, not pass@k. GPT-4o drops from ~61% pass@1 to ~25% pass^8 on τ-bench retail.

### 5.3 A/B Testing for Agent Changes

**When to A/B test:** Any change to agent definition, system prompt, protocol, or model routing.

**Process:**
1. Define success metric(s) and minimum detectable effect
2. Split evaluation dataset: 50% control, 50% treatment
3. Run both variants on identical tasks
4. Statistical test (z-test for proportions, sample ≥ 50/group)
5. Gate deployment on: p < 0.05 AND practical significance (effect size ≥ threshold)

**Shadow testing:** Run new agent variant alongside production but don't use its output. Compare quality offline. Zero risk, full signal.

### 5.4 Continuous Evaluation Pipeline

```
Code/prompt change commit
        ↓
CI: Layer 1 unit tests (automated, <1 min)
        ↓
CI: Layer 2 integration tests — 20-task sample (automated, <10 min)
        ↓
Gate: Success rate ≥ baseline - 5%?
        ↓ (if pass)
Canary: 5-10% production traffic
        ↓
Monitor: 24h alert window
        ↓
Full deployment
```

### 5.5 Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Task success rate | < 85% | < 75% | Rollback + investigate |
| Latency p95 | > 15s | > 30s | Routing change |
| Token cost per task | > baseline + 30% | > baseline + 60% | Prompt audit |
| Error rate | > 5% | > 15% | Immediate rollback |
| pass^3 consistency | < 0.75 | < 0.60 | Protocol review |

**Sources:**
- [5 A/B Testing Strategies — Maxim AI](https://www.getmaxim.ai/articles/5-strategies-for-a-b-testing-for-ai-agent-deployment/)
- [Pass@k vs Pass^k — Phil Schmid](https://www.philschmid.de/agents-pass-at-k-pass-power-k)
- [Anthropic statistical evaluation](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- [Regression testing — Hamming AI](https://hamming.ai/blog/ai-voice-agent-regression-testing)

---

## 6. Multi-Agent System Metrics

### 6.1 System-Level vs. Component-Level

**The isolation problem:** A system where each agent scores 90% individually can achieve only 59% end-to-end success if 5 agents run in sequence (0.9^5 = 0.59). Measuring components individually is insufficient.

**Independent multi-agent systems amplify errors up to 17.2x** (measured in 2025 research). Centralized architectures achieve better success-rate-to-error-containment tradeoff.

### 6.2 Coordination Quality Metrics

From MultiAgentBench and REALM-Bench (2025):

| Metric | Description | How to Measure |
|--------|-------------|----------------|
| **Coordination overhead** | Extra tokens/time for agent communication vs. solo agent | (multi-agent cost - solo cost) / solo cost |
| **Milestone completion rate** | % of task milestones reached | automated tracking against pre-defined milestones |
| **Communication efficiency** | Information density per message (useful tokens / total tokens) | log analysis |
| **Error containment** | Does an agent error stay local or propagate? | trace error origin vs. final failure |
| **Task decomposition quality** | Did coordinator split task optimally? | compare with human decomposition baseline |
| **Topology effectiveness** | Which routing pattern completes tasks fastest/cheapest | A/B test star vs. other topologies |

### 6.3 Agent Utilization and Load

| Metric | Description |
|--------|-------------|
| **Agent activation rate** | What % of tasks actually use this agent? |
| **Rerouting rate** | How often coordinator needs to re-delegate? |
| **First-dispatch accuracy** | Right agent selected on first try? |
| **Wait time / blocking** | How long does coordinator wait for agent response? |

### 6.4 End-to-End System Quality

**Recommended composite for FalkVelt coordinator quality:**

```
System_Score = w1 × Task_Completion_Rate
             + w2 × Decomposition_Accuracy
             + w3 × Cost_Efficiency
             + w4 × Protocol_Adherence
             + w5 × Response_Latency_Score
```

Suggested weights: 0.35 / 0.20 / 0.20 / 0.15 / 0.10

### 6.5 Error Propagation Analysis

For each end-to-end failure, trace root cause:
1. Coordinator decomposition error → wrong agent selected
2. Agent execution error → correct agent, wrong output
3. Agent communication error → output not usable by next step
4. Memory/context error → information lost between agents
5. Tool error → external tool failed

Track distribution over time. If category 1 dominates → improve dispatcher. If category 2 → improve agent prompts. If category 4 → improve context engineering.

**Sources:**
- [MultiAgentBench arXiv](https://arxiv.org/abs/2503.01935)
- [Towards a Science of Scaling Agent Systems — Google Research](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)
- [Microsoft Multi-Agent Reference Architecture — Evaluation](https://microsoft.github.io/multi-agent-reference-architecture/docs/evaluation/Evaluation.html)
- [REALM-Bench arXiv](https://arxiv.org/pdf/2502.18836)
- [Benchmarking Multi-Agent AI — Galileo](https://galileo.ai/blog/benchmarks-multi-agent-ai)

---

## 7. Self-Assessment & Introspection

### 7.1 The Calibration Problem

LLMs have deeply miscalibrated confidence. Research findings (2025):
- Models begin evaluation with 72.9% average confidence (baseline rational = 50%)
- Confidence increases, not decreases, as debate progresses (72.9% → 83.3% by closing round)
- This means agents become MORE certain even when wrong — a dangerous failure mode

**Confidence calibration** measures alignment between stated confidence and actual success rates using Expected Calibration Error (ECE):

```
ECE = (1/T) × Σ |confidence_bin_k - accuracy_bin_k|
```

Lower ECE = better calibrated. Target: ECE < 0.10.

### 7.2 The 12 Reliability Metrics (arXiv:2602.16666)

A formal framework decomposing agent reliability into 4 dimensions with 3 metrics each:

**Consistency (ℛCon):**
- **Cout** — Outcome consistency: do repeated runs succeed/fail the same way?
- **Ctrajd** — Trajectory distributional consistency: are action type frequencies similar across runs?
- **Ctrajs** — Trajectory sequential consistency: is action ordering preserved (Levenshtein distance)?
- **Cres** — Resource consistency: stable token/cost usage? (coefficient of variation)

**Robustness (ℛRob):**
- **Rfault** — Fault robustness: performance under infrastructure failures (timeouts, malformed responses)
- **Renv** — Environment robustness: stability when JSON fields reordered, parameters renamed
- **Rprompt** — Prompt robustness: performance on semantically equivalent reformulations

**Predictability (ℛPred):**
- **Pcal** — Calibration: ECE between confidence and accuracy
- **PAUROC** — Discrimination: can confidence scores separate correct from incorrect?
- **Pbrier** — Brier score: combined calibration + discrimination penalty

**Safety (ℛSaf):**
- **Scomp** — Compliance: fraction of tasks without policy violations
- **Sharm** — Harm severity: weighted severity (low=0.25, medium=0.5, high=1.0) among violating tasks

### 7.3 Relation to FalkVelt Meditation Protocol

The meditation protocol currently scores 7 dimensions for a 0.60/1.0 integrity score. This is structurally similar to the 12-metric reliability framework. Key alignment:

| FalkVelt Meditation Dimension | Closest Academic Metric |
|-------------------------------|------------------------|
| Self-consistency check | Ctrajd, Ctrajs |
| Protocol adherence | Scomp |
| Memory integrity | Memory Precision/Recall/F1 |
| Reasoning quality | Pcal (calibration) |
| Task completion | Cout |
| Communication quality | Communication score (MultiAgentBench) |
| Evolution/improvement | Pass^k trend over time |

**Recommendation:** Formalize the meditation dimensions using these academic metrics as operational definitions. This turns the current subjective 0.60 score into a reproducible, comparable measurement.

### 7.4 Self-Reported Difficulty Scores

Agents should tag each response with:
```json
{
  "difficulty": "low|medium|high",
  "confidence": 0.0-1.0,
  "uncertainty_sources": ["ambiguous_instruction", "missing_context", "tool_failure"],
  "self_assessment": "completed|partial|failed"
}
```

Over time, compare self-reported difficulty with actual success rate. If agent reports "low difficulty" but fails → calibration problem. If agent reports "high difficulty" and succeeds → underconfidence.

### 7.5 Error Categorization Framework

```
L1: Input quality errors (ambiguous, incomplete, contradictory instructions)
L2: Reasoning errors (wrong plan, wrong decomposition)
L3: Knowledge errors (hallucination, outdated information)
L4: Tool errors (wrong tool, wrong parameters, tool failure)
L5: Memory errors (lost context, wrong retrieval)
L6: Communication errors (output format wrong, incomplete)
```

Track distribution. If L3 (hallucination) > 20% → knowledge base or search needs improvement. If L5 (memory) > 15% → context engineering issue.

**Sources:**
- [Self-Evaluation in AI Agents — Galileo](https://galileo.ai/blog/self-evaluation-ai-agents-performance-reasoning-reflection)
- [Towards a Science of AI Agent Reliability arXiv](https://arxiv.org/html/2602.16666v1)
- [AI Insights ICML 2025 — Instabase](https://www.instabase.com/blog/ai-insights-from-icml-2025-part-2-reinforcement-learning-agent-evaluation-and-confidence)

---

## 8. Production Monitoring

### 8.1 Observability Platform Comparison

| Platform | Type | Strengths | Limitations | Cost |
|----------|------|-----------|-------------|------|
| **LangSmith** | Closed-source | Native LangChain integration, zero overhead, rapid prototyping | LangChain-locked, less agent-specific tracing | Paid |
| **Langfuse** | Open-source (MIT as of 2025) | 6M+ SDK installs/month, prompt management, LLM-judge built-in, annotation queues | Heavier setup | Self-host free |
| **Arize Phoenix** | Open-source | OpenTelemetry standard, deep multi-step agent traces, decision timeline tracking | Less integrated eval tooling | Self-host free |
| **AgentOps** | Closed-source | Agent-specific, minimal overhead, clean UX | Less mature ecosystem | Paid |
| **Maxim AI** | Closed-source | Simulation-based testing, comprehensive eval | Newer, smaller community | Paid |

**Recommendation for FalkVelt:** Langfuse (self-hosted) or Arize Phoenix (OpenTelemetry). Both are open-source, privacy-preserving, and do not require sending data to third-party servers. Langfuse is better for prompt management and evaluation; Phoenix is better for deep agent trace analysis.

### 8.2 What to Instrument

**Every agent call must log:**
```json
{
  "session_id": "...",
  "agent": "pathfinder|engineer|protocol-manager|llm-engineer",
  "task_type": "research|code|protocol|prompt",
  "timestamp_start": "...",
  "timestamp_end": "...",
  "latency_ms": 0,
  "model": "claude-sonnet-4-6",
  "tokens_input": 0,
  "tokens_output": 0,
  "cost_usd": 0.0,
  "tool_calls": [],
  "success": true|false,
  "quality_score": 0.0-1.0,
  "self_assessment": "completed|partial|failed",
  "error_category": null|"L1".."L6"
}
```

### 8.3 Dashboard Design

**Layer 1 — Health (real-time):**
- Current success rate (rolling 24h)
- Active session count
- Error rate by category
- Latency p50/p95/p99

**Layer 2 — Quality (daily):**
- Success rate by agent by task type
- Cost per successful task (trending)
- Token efficiency trend
- LLM-judge scores distribution

**Layer 3 — Evolution (weekly):**
- pass^k consistency trend
- Calibration (ECE) per agent
- Protocol adherence rate
- A/B test results

### 8.4 Incident Response

**Tier 1 (Automated alert):** Success rate drop > 10% in 1h → page on-call, freeze deployments
**Tier 2 (Degraded quality):** LLM-judge scores trending down 3 consecutive days → review evaluation set
**Tier 3 (Cost anomaly):** Token cost per task > 2x baseline → audit recent prompt changes

### 8.5 Trace-Level Analysis

The most valuable debugging technique for multi-agent systems: trace every step of agent reasoning and tool use, not just final outputs. Arize Phoenix and Langfuse both support this.

For each failure, replay the trace to identify the exact step where quality degraded. This is the foundation of root cause analysis in production.

**Sources:**
- [Top 5 Agent Observability Tools 2025 — Maxim AI](https://www.getmaxim.ai/articles/top-5-leading-agent-observability-tools-in-2025/)
- [LangSmith vs Langfuse vs Arize — Langfuse blog](https://langfuse.com/faq/all/best-phoenix-arize-alternatives)
- [Top 8 Observability Platforms — Softcery](https://softcery.com/lab/top-8-observability-platforms-for-ai-agents-in-2025)
- [Production Engineer's Guide — Ashutosh Tripathi](https://ashutoshtripathi.com/2025/12/01/ai-agent-performance-evaluation-a-production-engineers-guide/)
- [Arize LLM Evaluation Platforms Comparison](https://arize.com/llm-evaluation-platforms-top-frameworks/)

---

## 9. Academic Research (2025–2026)

### Key Papers

| Paper | Venue | Key Contribution |
|-------|-------|-----------------|
| [Beyond Task Completion](https://arxiv.org/abs/2512.12791) | arXiv Dec 2025 | 4-pillar framework (LLM/Memory/Tools/Environment), 3-layer evaluation |
| [Beyond Accuracy (CLEAR)](https://arxiv.org/abs/2511.14136) | arXiv Nov 2025 | CLEAR framework with 5-dimensional composite scoring |
| [MultiAgentBench](https://arxiv.org/abs/2503.01935) | ACL 2025 | Collaboration/competition metrics, milestone KPIs, topology study |
| [Towards AI Agent Reliability](https://arxiv.org/html/2602.16666v1) | arXiv Feb 2026 | 12 concrete reliability metrics across consistency/robustness/predictability/safety |
| [SWE-Bench Pro](https://arxiv.org/abs/2509.16941) | arXiv Sep 2025 | Enterprise-scale coding benchmark, 23% SOTA gap vs. prior saturation |
| [τ²-bench](https://github.com/sierra-research/tau2-bench) | 2025 | Dual-control tool-user interaction, pass^k metric |
| [LLM Agent Evaluation Survey](https://arxiv.org/html/2507.21504v1) | KDD 2025 Tutorial | Comprehensive taxonomy of evaluation objectives and processes |
| [Agent-as-Judge](https://arxiv.org/html/2508.02994v1) | arXiv Aug 2025 | Multi-agent judge panels, discussion-based evaluation |
| [2025 AI Agent Index](https://arxiv.org/abs/2602.17753) | arXiv Feb 2026 | Documenting technical and safety features of deployed agentic systems |
| [AgentArch](https://arxiv.org/html/2509.10769v1) | arXiv Sep 2025 | Enterprise agent architecture benchmark |
| [REALM-Bench](https://arxiv.org/pdf/2502.18836) | arXiv 2025 | Real-world planning scenarios (11 scenarios) |

### Emerging Research Themes (2026)

1. **Reliability science for agents:** Moving from benchmark scores to production reliability profiles
2. **Error propagation measurement:** Quantifying how failures cascade in multi-agent pipelines
3. **Cost-normalized evaluation:** CLEAR-style multi-objective optimization replacing accuracy-only
4. **Non-determinism treatment:** Statistical frameworks for evaluating probabilistic systems
5. **Safety-as-evaluation:** Assurance and compliance as first-class evaluation dimensions
6. **Agent maturity models:** Staged capability models replacing binary pass/fail

---

## 10. FalkVelt Recommendations

### 10.1 Current State Gap Analysis

| Dimension | Current State | Target State | Gap |
|-----------|--------------|--------------|-----|
| Task success tracking | None | Per-agent, per-type success rate | CRITICAL |
| Cost tracking | None | Cost per successful task | HIGH |
| Consistency (pass^k) | None | pass^3 per agent ≥ 0.85 | HIGH |
| Protocol adherence | None | Automated compliance check | HIGH |
| LLM-as-judge quality | None | Weekly evaluation runs | MEDIUM |
| Regression detection | None | CI evaluation suite | MEDIUM |
| Production observability | None | Langfuse/Phoenix instrumentation | MEDIUM |
| Meditation formalization | Subjective 0.60 score | ECE + Cout + Scomp metrics | LOW-MEDIUM |

### 10.2 Recommended Evaluation Framework for FalkVelt

**Name: FACT (FalkVelt Agent Consistency & Task) Score**

```
FACT = 0.35 × Task_Success_Rate
     + 0.25 × Consistency (pass^3)
     + 0.20 × Protocol_Adherence
     + 0.10 × Cost_Efficiency_Index
     + 0.10 × Latency_Score
```

**Task Success Rate:** Binary pass/fail per task, averaged. Min 20 tasks per agent.
**Consistency:** Run each eval task 3x; pass^3 = fraction where all 3 pass.
**Protocol Adherence:** LLM-judge checking output against protocol requirements.
**Cost Efficiency Index:** 1 - (actual_cost / budget_ceiling). Budget ceiling = 2x Sonnet baseline.
**Latency Score:** 1 - min(actual_latency / 30s, 1.0). Capped at 30s.

**Composite target:** FACT ≥ 0.75 for production readiness. Alert at FACT < 0.65.

### 10.3 Per-Agent Evaluation Plan

#### pathfinder
- **Primary benchmark analog:** GAIA Level 1-2 (web research + reasoning)
- **Task types to evaluate:** architecture scan, memory search, web research
- **Key metrics:** completeness score (sub-questions answered), citation rate, accuracy (human review monthly)
- **Automated:** count of required sections in output, citation URL validity

#### engineer
- **Primary benchmark analog:** SWE-bench Verified subset (Python), HumanEval Pro
- **Task types to evaluate:** code generation, debugging, Docker setup, API integration
- **Key metrics:** test pass rate, linter compliance, token efficiency
- **Automated:** run tests, linter; no human review needed for correctness

#### protocol-manager
- **Primary benchmark analog:** Custom (no academic analog)
- **Task types to evaluate:** protocol creation, indexing, cross-reference consistency
- **Key metrics:** structural completeness (all sections present), CLAUDE.md sync, link validity
- **Automated:** protocol schema validator + CLAUDE.md diff check

#### llm-engineer
- **Primary benchmark analog:** MT-Bench style multi-turn instruction following
- **Task types to evaluate:** system prompt design, agent creation, context engineering
- **Key metrics:** downstream task performance delta, instruction following score (LLM-judge)
- **Automated:** LLM-judge single answer grading (Sonnet as judge)

### 10.4 Implementation Roadmap

**Phase 1 (Week 1-2) — Instrumentation:**
- Add logging to every agent call (see Section 8.2 schema)
- Deploy Langfuse (self-hosted) for trace storage
- Create golden evaluation dataset: 10 representative tasks per agent (40 total)

**Phase 2 (Week 3-4) — Baseline:**
- Run all 40 eval tasks × 3 (pass^3) to establish baseline
- Record FACT scores per agent
- Identify lowest-scoring agents for first improvement cycle

**Phase 3 (Week 5-6) — CI Integration:**
- Add Layer 1+2 evaluation to CI pipeline
- Alert thresholds configured
- A/B testing capability ready for next protocol change

**Phase 4 (Month 2+) — LLM-Judge:**
- Weekly LLM-judge runs (Sonnet as judge) on sampled outputs
- Monthly multi-judge panel (Opus + Sonnet) for high-stakes reviews
- Calibration set: 100 human-labeled examples from Phase 1 data

**Phase 5 (Ongoing) — Formalize Meditation:**
- Map meditation dimensions to Cout, Ctrajd, Pcal, Scomp metrics
- Automate scoring where possible
- Replace subjective 0.60 score with FACT composite

### 10.5 Benchmark Adoption Priority

| Benchmark | Priority | Reason |
|-----------|----------|--------|
| CLEAR framework (adapted) | P0 — adopt now | Most directly applicable; cost + reliability + adherence |
| τ-bench pass^k metric | P0 — adopt now | Consistency measurement is missing and critical |
| 12 Reliability Metrics | P1 — this quarter | Formal reliability science for each agent |
| GAIA Level 1-2 | P1 — this quarter | pathfinder evaluation baseline |
| SWE-bench Verified subset | P2 — next quarter | engineer evaluation baseline |
| MultiAgentBench methods | P2 — next quarter | coordinator ↔ agent coordination quality |
| HumanEval Pro | P3 — when relevant | Supplementary code quality signal |
| OSWorld / WebArena | Not applicable | No GUI agents in FalkVelt |

### 10.6 The Meditation Protocol Connection

Current meditation score (0.60/1.0, 7 dimensions) is the only quality signal in FalkVelt. It is structurally sound but operationally vague. The academic framework suggests:

1. **Replace subjective scoring with measurable proxies** using the 12-metric reliability framework
2. **Separate agent-level from system-level** measurement (meditation currently conflates both)
3. **Add temporal dimension** — track meditation scores over N sessions as a trend, not a single point
4. **Link meditation findings to build-up triggers** — if Pcal (calibration) drops, trigger build-up
5. **Treat meditation score as a leading indicator** of FACT score changes

The meditation protocol already captures the right intuition. It needs formalization with the academic metrics as operational definitions.

---

## Appendix: Quick Reference

### Key Metric Definitions

| Term | Definition |
|------|-----------|
| pass@k | Probability ≥1 of k attempts succeeds (peak capability) |
| pass^k | Probability all k attempts succeed (consistency) |
| ECE | Expected Calibration Error (confidence vs. accuracy alignment) |
| CNA | Cost-Normalized Accuracy = Accuracy / Cost_USD × 100 |
| CPST | Cost Per Successful Task = Total_Cost / Successful_Tasks |
| PAS | Policy Adherence Score = 1 - (Violations / Policy_Critical_Actions) |
| FACT | FalkVelt Agent Consistency & Task score (composite) |

### Alert Thresholds (Production)

| Metric | Warning | Critical |
|--------|---------|----------|
| FACT score | < 0.70 | < 0.65 |
| Task success rate | < 85% | < 75% |
| pass^3 consistency | < 0.75 | < 0.60 |
| Latency p95 | > 15s | > 30s |
| Cost per task | > baseline + 30% | > baseline + 60% |
| Protocol adherence | < 90% | < 80% |

### Benchmark Relevance Matrix

| Benchmark | pathfinder | engineer | protocol-manager | llm-engineer | coordinator |
|-----------|-----------|---------|-----------------|-------------|------------|
| SWE-bench | Low | High | Low | Low | Low |
| GAIA | High | Low | Low | Low | Medium |
| τ-bench pass^k | Medium | High | Medium | Medium | High |
| CLEAR | High | High | High | High | High |
| MultiAgentBench | Medium | Low | Low | Low | High |
| HumanEval Pro | Low | Medium | Low | Medium | Low |
| 12 Reliability Metrics | High | High | High | High | High |

---

*Document produced by pathfinder agent, FalkVelt v1.65, 2026-03-03.*
*All sources verified via live web search. No hallucinated facts.*
