# Self-Evolving AI Systems & Meta-Learning for Agents

**Research date:** 2026-03-03
**Scope:** Self-improvement frameworks, automated prompt optimization, metacognition, continuous learning, self-evaluation, agent evolution architectures (2023–2026)
**Researcher:** pathfinder (FalkVelt)
**Consumer:** evolution.md, build-up.md, meditation.md integration analysis

---

## Table of Contents

1. [Self-Improvement Frameworks](#1-self-improvement-frameworks)
   - 1.1 Constitutional AI
   - 1.2 SELF-REFINE
   - 1.3 Reflexion
   - 1.4 Self-Play & Multi-Agent Co-Evolution
   - 1.5 Voyager (Lifelong Learning)
   - 1.6 LATS (Language Agent Tree Search)
2. [Automated Prompt Optimization](#2-automated-prompt-optimization)
   - 2.1 DSPy
   - 2.2 TextGrad
   - 2.3 OPRO
   - 2.4 APE (Automatic Prompt Engineer)
   - 2.5 PromptBreeder
   - 2.6 AFlow (Workflow Automation)
   - 2.7 EvoAgentX
3. [Metacognition in AI Agents](#3-metacognition-in-ai-agents)
   - 3.1 Metacognitive Definition & State of the Art
   - 3.2 Microsoft Metacognition Framework
   - 3.3 INoT (Introspection of Thought)
   - 3.4 ReMA (Recursive Meta-Thinking Agent)
4. [Continuous Learning & Adaptation](#4-continuous-learning--adaptation)
   - 4.1 MemRL (Non-Parametric Episodic RL)
   - 4.2 Contextual Experience Replay (CER)
   - 4.3 SkillRL / Skill Libraries
   - 4.4 SPEAR (Progressive Self-Imitation)
   - 4.5 Catastrophic Forgetting Prevention
5. [Self-Evaluation & Quality Assurance](#5-self-evaluation--quality-assurance)
   - 5.1 LLM-as-Judge
   - 5.2 Chain-of-Verification (CoVe)
   - 5.3 Self-Consistency
   - 5.4 Critique-out-Loud (CLoud)
   - 5.5 AgentBench & SWE-bench
6. [Agent Evolution Architectures](#6-agent-evolution-architectures)
   - 6.1 OpenAI Self-Evolving Agents Cookbook
   - 6.2 Behavioral Versioning & Canary Deployment
   - 6.3 Comprehensive Survey: Self-Evolving AI Agents (2025)
7. [Recommendations for FalkVelt](#7-recommendations-for-falkvelt)

---

## 1. Self-Improvement Frameworks

### 1.1 Constitutional AI (Anthropic)

**Core idea**

Constitutional AI (CAI) replaces human preference labels with a set of explicit principles (a "constitution") that the model uses to critique and revise its own outputs. The model operates as both generator and critic, guided by natural-language rules rather than reward signals from human annotators. The constitution is treated as a living document — not a frozen artifact — expected to evolve as societal expectations change.

**How it works**

Two-phase pipeline:
1. **Supervised phase (SL-CAI)** — The model is prompted to critique a response against a randomly drawn principle, then revise accordingly. This loop runs multiple times, each time with a different principle. The final revised responses become training data for SFT.
2. **RL phase (RLAIF)** — Instead of human preference labels, an AI-generated feedback signal based on the constitution selects the less-harmful output. This "AI feedback" trains a preference model that subsequently guides PPO finetuning.

**Results / effectiveness**

CAI reduces harmfulness without significant helpfulness regression. The self-critique-revise loop produces outputs humans prefer over non-CAI baselines. The 2022 paper shows that even a single critique-and-revise pass substantially reduces toxic content. Importantly: improvements are stable — the model doesn't regress when deployed.

**Relevance to FalkVelt**

- **evolution.md Hook 1 (Correction Interceptor):** The correction → classify → store → verify loop is structurally identical to CAI's critique-revise cycle. Both intercept a "wrong" output and generate a corrective revision against a principle (stored build-up rule).
- **build-up.md Quick Path:** CAI's single-pass critique maps directly to the quick path's "store → verify on 2-3 mental test cases" pattern.
- **Extension opportunity:** Introduce a "constitution validator" step in Hook 5 (Post-Task Verification) — after each task, check the output against stored build-up rules like CAI checks against its constitution. Violations trigger Hook 1.
- **meditation.md Phase 4 (Conflict Resolution):** CAI's principle-vs-output consistency check is analogous to Phase 4's MUST/MUST NOT rule conflict scan.

**Sources**
- [Constitutional AI: Harmlessness from AI Feedback (arXiv:2212.08073)](https://arxiv.org/abs/2212.08073)
- [Anthropic Research Page](https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback)
- [Specific versus General Principles for Constitutional AI](https://www.anthropic.com/research/specific-versus-general-principles-for-constitutional-ai)

---

### 1.2 SELF-REFINE

**Core idea**

SELF-REFINE enables LLMs to iteratively improve their own outputs using nothing but a single model acting as generator, feedback provider, and refiner simultaneously. No training data, no fine-tuning, no external oracle. The model generates output → critiques that output (localizing problems and prescribing improvements) → produces a refined version → repeats until a stopping criterion is met.

**How it works**

Three modules, all running on the same LLM instance:
1. **Generator (M):** produces initial output $y_0$ from input $x$
2. **Feedback (M):** critiques $y_t$ — localizes specific errors and issues improvement instructions
3. **Refine (M):** applies feedback to produce $y_{t+1}$

The loop continues until the feedback module declares the output satisfactory or a maximum iteration count is reached. Crucially, the feedback is natural language — explicit, inspectable, and logged.

**Results / effectiveness**

Evaluated on 7 diverse tasks (dialogue generation, code optimization, mathematical reasoning, sentiment reversal, acronym generation, constrained generation, story writing). Outputs with SELF-REFINE preferred by humans and automatic metrics by ~20% absolute improvement on average over one-shot generation. Works even when the model's initial output is poor — the refinement loop corrects errors it couldn't avoid on first pass.

**Relevance to FalkVelt**

- **evolution.md Hook 5 (Post-Task Verification):** Insert a lightweight self-refine loop as part of post-task check. Before closing a task, the coordinator could run a single critique pass: "Given build-up rules X, Y, Z, was this response compliant? If not, identify which rule was violated." This converts Hook 5 from a passive check into an active refinement gate.
- **build-up.md Step 2 (Plan):** The variant design step is essentially SELF-REFINE applied to plans — generate plan → critique (does it address the correction?) → refine. Making this explicit in the protocol wording aligns it with research literature.
- **Stopping criterion:** SELF-REFINE's stopping criterion (feedback declares output good) can inform the "verify on 2-3 mental test cases" step in Quick Path — codify the stopping condition as "no rule violations detected."

**Sources**
- [SELF-REFINE: Iterative Refinement with Self-Feedback (arXiv:2303.17651)](https://arxiv.org/abs/2303.17651)
- [Project page: selfrefine.info](https://selfrefine.info/)
- [GitHub: madaan/self-refine](https://github.com/madaan/self-refine)

---

### 1.3 Reflexion

**Core idea**

Reflexion replaces gradient-based weight updates with verbal reinforcement: instead of adjusting model parameters after a failure, the agent generates a natural-language self-reflection about what went wrong and stores it in a short-term episodic memory buffer. This reflection acts as a prompt-level "gradient" for the next trial.

**How it works**

Three components:
1. **Actor:** generates actions and text based on state observations
2. **Evaluator:** scores the Actor's output — can be an external signal (ground truth, compiler output, test suite) or internally simulated (self-graded)
3. **Self-Reflection model:** given the trajectory of states/actions and the evaluator's signal, produces a verbal reflection: "I failed because I assumed X without checking Y. Next time I should do Z."

The reflection text is appended to the agent's context (episodic memory buffer) for the next episode. The buffer is bounded — oldest reflections are dropped to stay within context limits.

**Results / effectiveness**

Outperforms baseline agents across reasoning (HotPotQA), decision-making (AlfWorld), and code generation (HumanEval, MBPP, LeetcodeHardGym). State-of-the-art code generation results at time of publication. Key advantage: it works without any fine-tuning and is task-agnostic.

**Relevance to FalkVelt**

- **build-up.md Step 9 (Store) + Quick Path:** The Reflexion memory buffer is functionally equivalent to FalkVelt's Qdrant memory store for build-up records. The difference: Reflexion's reflections are ephemeral (context-bounded), while FalkVelt's build-up records are permanent. This is a deliberate architectural choice FalkVelt already made correctly.
- **evolution.md Hook 3 (Adaptive Orchestrator):** The Evaluator → Self-Reflection → next trial cycle is directly applicable to gap analysis → build selection → execution. The "score each candidate" step in Hook 3 is the evaluator; the build description is the reflection text.
- **Extension opportunity:** Reflexion's "episodic memory buffer" pattern suggests adding a lightweight session-level reflection after each T3+ task: "In this task, which stored build-up rules did I apply? Which did I miss? What new pattern emerged?" This feeds Hook 4 (Predictive Loop) with richer signals than just request counts.

**Sources**
- [Reflexion: Language Agents with Verbal Reinforcement Learning (arXiv:2303.11366)](https://arxiv.org/abs/2303.11366)
- [GitHub: noahshinn/reflexion](https://github.com/noahshinn/reflexion)
- [NeurIPS 2023 Paper](https://openreview.net/forum?id=vAElhFcKW6)

---

### 1.4 Self-Play & Multi-Agent Co-Evolution

**Core idea**

Self-play extends beyond board games: LLMs improve by playing different roles against themselves (or against copies of themselves). The key insight is that the agent is simultaneously the teacher and the student — it generates challenges just hard enough to push the current skill boundary, solving them and learning from failures without external curriculum design.

Recent 2025 work extends this to **co-evolution**: three roles instantiated from a single model (Proposer, Solver, Judge) that jointly improve through RL, forming a closed loop with no reliance on pre-labeled data.

**How it works**

**Multi-Agent Evolve (MAE, Oct 2025):**
- Proposer: generates questions/challenges of calibrated difficulty
- Solver: attempts solutions
- Judge: evaluates both quality of questions and correctness of solutions
- All three trained jointly via RL with domain-agnostic self-rewarding mechanisms (Judge-based evaluation, difficulty-aware rewards, format rewards)
- No human-labeled ground truth or external verifier required

**Search Self-Play (SSP, 2025):**
- Proposer and Solver co-evolve through competition
- Proposer is rewarded when Solver fails; Solver is rewarded when it succeeds
- Adversarial dynamics ensure progressively harder challenges — automatic curriculum generation

**Results / effectiveness**

MAE on Qwen2.5-3B: +4.54% average improvement across mathematics, reasoning, and general knowledge benchmarks. SSP: substantial consistent improvements across benchmarks under both from-scratch and continual learning setups.

**Relevance to FalkVelt**

- **build-up.md Steps 3-6 (Clone, Implement, Test, Evaluate):** The full path already embodies self-play — variant A vs variant B vs variant C competes, best wins. Formalizing this as a "Proposer-Solver-Judge" triad in the protocol language would make the mechanism clearer.
- **evolution.md Hook 3 (Adaptive Orchestrator) scoring:** The scoring table maps naturally to Judge-based evaluation. The "keyword overlap" metric is a primitive Judge. Enhancement: replace keyword overlap with semantic similarity via memory_search.py — more accurate judge for gap-to-build matching.
- **meditation.md Phase 3 (Connection Weaving):** The adversarial co-evolution pattern applies here — the pathfinder acts as Proposer (generating candidate connections), the coordinator acts as Judge (validating via graph constraints), the validated connections become the Solver's output.

**Sources**
- [Multi-Agent Evolve: LLM Self-Improve through Co-evolution (arXiv:2510.23595)](https://arxiv.org/abs/2510.23595)
- [Search Self-Play (arXiv:2510.18821)](https://arxiv.org/html/2510.18821v1)
- [MARS: Reinforcing Multi-Agent Reasoning via Self-Play (arXiv:2510.15414)](https://arxiv.org/html/2510.15414v1)
- [Awesome LLM Self-Play (GitHub)](https://github.com/tim-grams/awesome-llm-self-play)

---

### 1.5 Voyager (Lifelong Learning)

**Core idea**

Voyager is the first LLM-powered embodied lifelong learning agent. It operates in Minecraft without any fine-tuning — purely through a structured loop of curriculum generation, skill writing, and iterative self-debugging. The key architectural innovation is an **ever-growing skill library**: executable code snippets representing learned behaviors, retrievable by semantic description and composable to solve new challenges.

**How it works**

Three components:
1. **Automatic curriculum:** GPT-4 proposes tasks of incrementally increasing difficulty based on current inventory and world state — automatic curriculum generation without human design
2. **Skill library:** Each successfully executed task generates a JavaScript function stored with a semantic description. Retrieved via vector similarity for future tasks. Skills are compositional — complex skills call simpler ones.
3. **Iterative prompting mechanism:** If execution fails (JS error, game feedback), GPT-4 self-reflects and debugs in the same prompt. Feedback includes execution errors, environment state, and iteration history.

**Results / effectiveness**

3.3x more unique items, 2.3x longer distances, tech tree milestones unlocked 15.3x faster than prior SOTA. Crucially: skill library is transferable — loading it into a new Minecraft world with novel tasks allows immediate generalization while other methods start from scratch.

**Relevance to FalkVelt**

- **build-up.md as Skill Library:** The build-up memory store is FalkVelt's skill library. Each stored correction/rule is a named skill (behavioral pattern). The parallel is direct. Enhancement: ensure each build-up record has a clear "activation condition" field (analogous to Voyager's skill description that enables retrieval), not just a free-text description.
- **evolution.md Hook 4 (Predictive Loop) as Automatic Curriculum:** Voyager's curriculum asks "what's the next challenge given current inventory?" Hook 4 asks "what's the next phase given request history?" Both are automatic curriculum generation — proactive rather than reactive.
- **self-build-up.md skill composition:** Voyager's compositional skills map to FalkVelt's spec composition (spec_refs in builds). When specs compose, they behave like Voyager skills that call sub-skills. Explicitly document this pattern in self-build-up.md Phase 4.
- **Iterative debugging → Hook 1:** Voyager's self-reflect-and-debug loop after execution failure is Hook 1 (Correction Interceptor) triggered by environment feedback rather than user feedback. Consider adding an "auto-trigger" pathway in Hook 1 when the coordinator's own output visibly violates a stored rule.

**Sources**
- [Voyager: An Open-Ended Embodied Agent with LLMs (arXiv:2305.16291)](https://arxiv.org/abs/2305.16291)
- [Project page: voyager.minedojo.org](https://voyager.minedojo.org/)
- [GitHub: MineDojo/Voyager](https://github.com/MineDojo/Voyager)

---

### 1.6 LATS (Language Agent Tree Search)

**Core idea**

LATS unifies reasoning, acting, and planning through Monte Carlo Tree Search (MCTS) where the LLM simultaneously serves as the action generator, value function, and reflection mechanism. Rather than committing to a single reasoning path, LATS explores a tree of candidate trajectories, backpropagates value estimates, and generates verbal reflections for failed branches.

**How it works**

Six operations per MCTS cycle:
1. **Selection:** choose which node (partial trajectory) to expand using UCB-style scoring
2. **Expansion:** generate candidate next actions from the selected node
3. **Evaluation:** LLM estimates value of the resulting state
4. **Simulation:** run trajectory to completion (or until terminal state)
5. **Backpropagation:** update value estimates along the path
6. **Reflection:** for failed trajectories, generate self-critique stored as context for future expansions

The LLM fills three roles: action generator, value function, and reflection model — all from a single model via different prompts.

**Results / effectiveness**

92.7% pass@1 on HumanEval (programming) with GPT-4. 75.9 average on WebShop (navigation) with GPT-3.5 — comparable to gradient-based fine-tuning. Accepted at ICML 2024.

**Relevance to FalkVelt**

- **build-up.md Full Path:** The clone-test-evaluate pipeline is a lightweight MCTS with depth=1 (only one level of tree expansion). Variants A/B/C are tree branches. The "evaluate best/worst" step is MCTS backpropagation. Explicitly framing this as tree search in the protocol would clarify the mechanism.
- **evolution.md Hook 3 scoring:** LATS value function (LLM estimates future value) is more powerful than keyword overlap scoring. Enhancement: use LLM reasoning over candidate description + gap description to estimate "how well does this build address this gap?" — replaces the coarse keyword scoring.
- **meditation.md Phase 3 (Connection Weaving):** The LATS reflection mechanism applies directly — failed "connection hypotheses" (Phase 3a candidates that fail graph validation in Phase 3b) should generate verbal reflections: "This connection was rejected because..." stored as context for future meditation phases.

**Sources**
- [LATS: Language Agent Tree Search (arXiv:2310.04406)](https://arxiv.org/abs/2310.04406)
- [GitHub: lapisrocks/LanguageAgentTreeSearch](https://github.com/lapisrocks/LanguageAgentTreeSearch)
- [ICML 2024 Paper](https://dl.acm.org/doi/10.5555/3692070.3694642)

---

## 2. Automated Prompt Optimization

### 2.1 DSPy (Stanford)

**Core idea**

DSPy treats LLM pipelines as declarative programs where instructions and demonstrations are learnable parameters, not handcrafted strings. You write Python modules with typed signatures (input fields → output fields), and DSPy's optimizers automatically find the best prompts and few-shot examples by compiling the program against a metric.

**How it works**

Key components:
- **Signatures:** natural language I/O specifications — `"question -> answer"`. No prompt engineering.
- **Modules:** parameterized LLM calls (`dspy.Predict`, `dspy.ChainOfThought`, `dspy.ReAct`) that can be composed
- **Optimizers:** search over instruction/demonstration space
  - **MIPROv2:** Bayesian optimization over instruction + few-shot example space, data-aware and demo-aware
  - **COPRO:** coordinate ascent — generates and refines instructions per step
  - **BetterTogether:** meta-optimizer combining prompt optimization + weight optimization

Programs are compiled: optimizer runs candidate prompts against training examples, scores via the metric function, and writes the best prompts back into the module parameters.

**Results / effectiveness**

Used in production at JetBlue, Replit, VMware, Sephora, Moody's. Consistent improvements over manually engineered prompts. MIPROv2 achieves state-of-the-art on multiple reasoning benchmarks. DSPy is now a primary framework for programmatic LLM optimization.

**Relevance to FalkVelt**

- **agent definitions (.claude/agents/*.md):** Each agent's system prompt is a fixed string. DSPy's insight: system prompts should be compiled outputs, not handwritten inputs. Future enhancement: encode each agent's tasks as DSPy signatures, compile against a metric (task completion rate), and use the optimized prompt as the agent definition.
- **build-up.md Step 2-4 (Plan, Clone, Implement):** Variants A/B/C in the full path are a manual version of DSPy's compile loop. Automating this with DSPy would make the "clone" step unnecessary — the optimizer explores the variant space without physical clones.
- **Practical integration path:** Use DSPy offline (not in live sessions) to periodically optimize core coordinator prompts (dispatcher, correction classifier). Run as a separate build-up cycle, validate against test cases from build-up records, promote winning prompts via normal build-up pipeline.

**Sources**
- [DSPy: Compiling Declarative LM Calls (arXiv:2310.03714)](https://arxiv.org/pdf/2310.03714)
- [DSPy GitHub](https://github.com/stanfordnlp/dspy)
- [DSPy Documentation](https://dspy.ai/)
- [Stanford HAI: DSPy](https://hai.stanford.edu/research/dspy-compiling-declarative-language-model-calls-into-state-of-the-art-pipelines)

---

### 2.2 TextGrad

**Core idea**

TextGrad implements automatic differentiation over text: instead of numeric gradients, it backpropagates natural-language "textual gradients" through compound LLM systems. Each component receives a feedback string ("this step was unclear because…") computed from downstream loss signals. Published in Nature (2024).

**How it works**

PyTorch-like API:
1. Define a `Variable` (e.g., a system prompt as a string)
2. Define a loss function (e.g., "was this response correct and concise?")
3. Call `loss.backward()` — LLM generates textual gradients by propagating "what went wrong" upstream through the computation graph
4. `optimizer.step()` — updates the variable (rewrites the prompt) guided by the textual gradient

2025 extensions include Monte Carlo TextGrad (sampling from input distributions for stable gradient estimation) and applications to multi-agent coordination.

**Results / effectiveness**

GPT-4o on Google-Proof QA: 51% → 55% zero-shot accuracy. LeetCode-Hard: 20% relative improvement. Radiotherapy planning optimization. Molecular design. The PyTorch API makes it applicable to any differentiable text pipeline.

**Relevance to FalkVelt**

- **build-up.md Full Path (Steps 2-8):** TextGrad is the research formalization of what the full path does manually. The "plan variants → test → evaluate best/worst" flow is gradient-free TextGrad. The "anti-pattern from worst variant" is the negative textual gradient.
- **agent system prompts:** TextGrad can directly optimize CLAUDE.md sections and agent .md files. The metric is task compliance (does the coordinator follow the rules?), the variables are the prompt sections.
- **Immediate practical use:** Run TextGrad on the `dispatcher.md` routing rules against a test set of request classifications. The optimizer would refine routing conditions — addressing routing errors that currently require manual corrections.
- **Hook 1 (Correction Interceptor) integration:** Each user correction is a textual gradient signal. Currently these are stored as discrete rules. TextGrad would treat them as gradient updates to the relevant prompt parameter — a more principled way to apply corrections.

**Sources**
- [TextGrad: Automatic Differentiation via Text (arXiv:2406.07496)](https://arxiv.org/abs/2406.07496)
- [TextGrad GitHub](https://github.com/zou-group/textgrad)
- [Stanford HAI: TextGrad](https://hai.stanford.edu/news/textgrad-autograd-text)
- [TextGrad.com](https://textgrad.com/)

---

### 2.3 OPRO (Google DeepMind)

**Core idea**

OPRO (Optimization by PROmpting) treats the LLM as an optimizer: the optimization task is described in natural language, and the LLM proposes new solutions by reasoning over the history of previous solutions and their scores. Each optimization step presents the model with a "trajectory" — (solution, score) pairs from prior iterations — and asks it to propose a better solution.

**How it works**

1. Initialize with a few candidate prompts (random or human-written)
2. Evaluate each candidate on a training set (compute metric score)
3. Construct a "meta-prompt": optimization history = [(prompt_i, score_i), ...], instruction: "Given these attempts and scores, generate a better instruction"
4. LLM generates new candidate prompt
5. Evaluate → add to history → repeat

The LLM leverages the context of what worked and what didn't, performing a form of in-context Bayesian optimization without any numerical optimization machinery.

**Results / effectiveness**

Prompts optimized by OPRO outperform human-designed prompts by up to 8% on GSM8K and up to 50% on Big-Bench Hard tasks. Published at ICLR 2024. Limitation: small-scale LLMs are insufficient optimizers — requires a capable base model.

**Relevance to FalkVelt**

- **build-up.md Step 9 (Store) as optimization history:** The memory store is already an OPRO-compatible optimization history. Each build-up record = (prompt_change, observed_outcome). The missing piece: a scoring function that rates outcomes numerically, and a meta-prompt that reads the history and proposes better rules.
- **Practical OPRO loop for FalkVelt:** Periodically (e.g., every 10 build-ups), pass all build-up records of type "correction" to an OPRO-style meta-prompt: "Given these corrections and their contexts, what single most-impactful rule addition to CLAUDE.md would prevent the most errors?" The LLM generates a candidate rule; the coordinator reviews and applies via normal build-up.
- **evolution.md Hook 4 (Predictive Loop) enhancement:** OPRO's meta-prompt pattern translates directly to Hook 4 — instead of just counting request types, pass the trajectory history to an LLM that proposes "the most useful next build to prepare."

**Sources**
- [Large Language Models as Optimizers (arXiv:2309.03409)](https://arxiv.org/abs/2309.03409)
- [OPRO GitHub](https://github.com/google-deepmind/opro)
- [ICLR 2024 Paper](https://openreview.net/forum?id=Bb4VGOWELI)

---

### 2.4 APE (Automatic Prompt Engineer)

**Core idea**

APE automates instruction generation via inference: given a set of input-output demonstrations, the LLM generates candidate instructions that would produce those outputs, evaluates them on a scoring metric, and selects the best. APE treats instruction generation as a program synthesis problem — finding the hidden instruction that explains observed behavior.

**How it works**

1. Feed demonstrations (input, output) pairs to LLM: "Given these examples, what instruction produced these outputs?"
2. Generate many candidate instructions (forward inference: direct generation; iterative: resample based on semantic similarity to current best)
3. Execute each candidate on a held-out set via the target model
4. Score outputs (exact match, semantic similarity, execution tests)
5. Select top-k candidates

Recent extensions (2024-2025): PE2 uses meta-prompts that explicitly reason about what the best prompt engineer would do. ELPO (Nov 2025) combines multiple generators + voting. PRL uses RL-based policy model for prompt generation.

**Results / effectiveness**

Human-level performance on 24/24 benchmark tasks. Discovers better CoT trigger prompts than "Let's think step by step." Spawned a generation of follow-on work (DSPy, OPRO, PromptBreeder).

**Relevance to FalkVelt**

- **New agent creation (agent-creation.md):** When creating a domain agent, APE can generate the system prompt. Instead of hand-writing the agent definition, provide 5-10 example task descriptions → APE generates candidate system prompts → coordinator selects best → normal build-up pipeline.
- **build-up.md Step 2 (Plan, variant generation):** APE's forward inference pattern is exactly how variants A/B/C should be generated — from examples of what worked and what didn't (build-up history), not from scratch.
- **Correction → rule synthesis:** Each user correction is a demonstration: (bad behavior, corrected behavior). APE can synthesize the underlying rule from a collection of such demonstrations. Run APE over batched corrections of the same type to extract a compact, generalizable rule rather than storing each correction individually.

**Sources**
- [Large Language Models Are Human-Level Prompt Engineers (arXiv:2211.01910)](https://arxiv.org/abs/2211.01910)
- [APE Project page](https://sites.google.com/view/automatic-prompt-engineer)
- [Prompt Engineering Guide: APE](https://www.promptingguide.ai/techniques/ape)

---

### 2.5 PromptBreeder

**Core idea**

PromptBreeder applies evolutionary algorithms to prompt optimization in a self-referential way: it evolves not just task-prompts but also the mutation-prompts that govern how task-prompts are mutated. This creates a two-level evolutionary system — evolution of evolution — that discovers mutation strategies the designer didn't anticipate.

**How it works**

1. Initialize population of (task-prompt, mutation-prompt) pairs
2. Each generation: apply mutation-prompt to task-prompt → new candidate
3. Evaluate task-prompt fitness on training examples
4. Select survivors by fitness → next generation
5. Multiple mutation operators: direct mutation, distribution estimation, hypermutation, Lamarckian mutation, crossover

The key innovation: mutation-prompts are themselves mutated by "hyper-mutation prompts" — a third level of self-reference. The system is not just searching prompts; it is discovering the search strategy.

**Results / effectiveness**

Outperforms Chain-of-Thought and Plan-and-Solve on arithmetic and commonsense reasoning benchmarks. Published at ICML 2024. Self-referential improvement is more efficient than fixed-operator search.

**Relevance to FalkVelt**

- **build-up.md meta-level:** FalkVelt's build-up pipeline itself can be treated as the mutation-prompt — it defines how corrections are stored and applied. PromptBreeder suggests that the build-up pipeline itself should be subject to evolution. The "anti-pattern from worst variant" is the negative fitness signal for mutation-prompt selection.
- **evolution.md Hook 3 (Adaptive Orchestrator):** The scoring table in Hook 3 is a fixed fitness function. PromptBreeder suggests this scoring function should also be optimizable — storing observed outcomes of scoring decisions and using them to refine the scoring weights over time.
- **Practical use:** Run PromptBreeder-style evolution periodically on coordinator routing rules (dispatcher.md). Let the evolutionary process discover more effective routing conditions than keyword-matching.

**Sources**
- [PromptBreeder: Self-Referential Self-Improvement Via Prompt Evolution (arXiv:2309.16797)](https://arxiv.org/abs/2309.16797)
- [ICML 2024 Publication](https://proceedings.mlr.press/v235/fernando24a.html)
- [OpenReview](https://openreview.net/forum?id=HKkiX32Zw1)

---

### 2.6 AFlow (ICLR 2025 Oral)

**Core idea**

AFlow automates agentic workflow generation by framing it as a code search problem. Workflows are programs — LLM-invoking nodes connected by edges — and AFlow uses Monte Carlo Tree Search to explore the space of possible workflow architectures, iteratively refining them through execution feedback.

**How it works**

1. Represent workflow as code (nodes = LLM calls, edges = control flow)
2. Define operators (Ensemble, Review, Revise, Custom) as high-level building blocks
3. MCTS explores workflow graph: select → expand (add/modify nodes) → evaluate on training examples → backpropagate score → reflect on failures
4. Code modification at each expansion step: add a node, change an operator, modify a prompt
5. Tree-structured experience: failed branches annotated with reflections, success paths prioritized

**Results / effectiveness**

5.7% average improvement over SOTA baselines on HumanEval, MBPP, GSM8K, MATH, HotpotQA, DROP. Enables smaller models to outperform GPT-4o on specific tasks at 4.55% of inference cost. ICLR 2025 Oral — one of the most recognized agent papers of the year.

**Relevance to FalkVelt**

- **protocols/core/ as workflow code:** FalkVelt's protocols are workflow definitions. AFlow's insight: these workflows can be automatically optimized, not just manually written. The MCTS exploration of operator sequences maps directly to testing alternative protocol step orderings.
- **self-build-up.md Phase 4-5 (Design, Build):** When designing a new build, use AFlow's operator vocabulary: does this build need an Ensemble step (multiple agents)? A Review step (self-verification)? A Revise step (iterative refinement)? AFlow provides a principled vocabulary for build architecture.
- **Immediate integration:** Use AFlow's framework as inspiration for the build-registry.json `spec_refs` structure — each spec is an AFlow operator. Build composition = workflow generation.

**Sources**
- [AFlow: Automating Agentic Workflow Generation (arXiv:2410.10762)](https://arxiv.org/abs/2410.10762)
- [GitHub: FoundationAgents/AFlow](https://github.com/FoundationAgents/AFlow)
- [ICLR 2025 Oral Presentation](https://iclr.cc/virtual/2025/oral/31731)

---

### 2.7 EvoAgentX

**Core idea**

EvoAgentX is an open-source framework that integrates multiple automated optimization strategies (TextGrad, AFlow, DSPy/MIPRO) into a unified ecosystem for building, evaluating, and evolving LLM-based agents and multi-agent workflows. It abstracts the optimization layer so developers can compose agents declaratively and let the framework handle prompt/structure optimization.

**How it works**

Three integrated optimization algorithms:
1. **TextGrad:** optimizes individual component prompts via textual gradients
2. **AFlow:** optimizes workflow topology via MCTS over code-represented workflows
3. **MIPRO (from DSPy):** optimizes instructions and few-shot examples via Bayesian search

Human-in-the-Loop (HITL) checkpoints for validation. Modular evaluation framework supporting custom metrics. Goal-driven workflow generation from high-level task description.

**Results / effectiveness**

HotPotQA F1: +7.44%. MBPP pass@1: +10%. MATH accuracy: +10%. GAIA overall: +20%. Presented at EMNLP 2025 System Demonstrations.

**Relevance to FalkVelt**

- **self-build-up.md + build-up.md combined:** EvoAgentX is the production-ready orchestration layer for what FalkVelt's build protocols do manually. The framework could be adopted as an offline evolution tool — running EvoAgentX on agent definitions outside of live sessions to propose optimized versions.
- **Agent creation (agent-creation.md):** Instead of manually designing new domain agents, use EvoAgentX goal-driven workflow generation with the task description as input. Review and approve the generated agent via normal build-up pipeline.

**Sources**
- [EvoAgentX (arXiv:2507.03616)](https://arxiv.org/abs/2507.03616)
- [GitHub: EvoAgentX/EvoAgentX](https://github.com/EvoAgentX/EvoAgentX)
- [EMNLP 2025 Demo Paper](https://aclanthology.org/2025.emnlp-demos.47/)

---

## 3. Metacognition in AI Agents

### 3.1 Metacognitive Definition & State of the Art

**Core idea**

Metacognition in AI agents = a system's ability to monitor, evaluate, and regulate its own reasoning and performance. It is a bi-level process: the metacognitive layer monitors and controls the cognitive layer. Key facets: metacognitive sensitivity (detecting when errors occur) and metacognitive calibration (accuracy of confidence estimates).

**State of the art (2025)**

Evidence from multiple 2025 papers:
- LLMs show limited but real metacognitive ability: they can detect some errors but are poorly calibrated (overconfident or underconfident)
- Abilities are context-dependent and qualitatively different from human metacognition
- Key paper: "Position: Truly Self-Improving Agents Require Intrinsic Metacognitive Learning" (2025) — argues that effective self-improvement requires the agent's intrinsic ability to evaluate, reflect on, and adapt its own learning processes, not just output quality

**Core capabilities researchers identify:**
1. Self-reflection: assessing performance and identifying improvement areas
2. Adaptability: modifying strategies based on experience
3. Error correction: detecting and correcting errors autonomously
4. Resource management: optimizing computation through meta-level planning
5. Confidence estimation: knowing when to proceed vs. when to ask for help

**Relevance to FalkVelt**

- **All 6 evolution hooks:** The entire evolution protocol is a metacognitive scaffold. Hook 1 = error detection (metacognitive sensitivity). Hook 2 = session-level reflection (periodic monitoring). Hook 3 = adaptive strategy selection. Hook 4 = predictive self-modeling. Hook 5 = post-task self-monitoring. Hook 6 = knowledge calibration.
- **Gap identified:** FalkVelt has metacognitive monitoring (detecting corrections) but limited metacognitive calibration (no confidence tracking per domain). Adding confidence scores to task responses — "I'm 70% confident this routing is correct" — would enable more precise Hook 1 triggering.

**Sources**
- [Position: Truly Self-Improving Agents Require Intrinsic Metacognitive Learning (OpenReview)](https://openreview.net/forum?id=4KhDd0Ozqe)
- [Metacognitive Capabilities in LLMs (EmergentMind)](https://www.emergentmind.com/topics/metacognitive-capabilities-in-llms)
- [Metacognition and Uncertainty Communication in Humans and LLMs (Sage Journals, 2025)](https://journals.sagepub.com/doi/10.1177/09637214251391158)
- [Evidence for Limited Metacognition in LLMs (arXiv:2509.21545)](https://arxiv.org/html/2509.21545v1)

---

### 3.2 Microsoft Metacognition Framework for AI Agents

**Core idea**

Microsoft's "AI Agents for Beginners" curriculum chapter on metacognition defines a practical framework for making AI agents self-aware. The core pattern is a reflection loop: make initial decision → collect feedback → reflect on performance → adjust strategy → generate improved output. This is described as a continuous cycle, not a one-time event.

**How it works**

Key implementation patterns:
1. **Planning framework:** define task → decompose into steps → identify resources → leverage past experience → execute → reflect
2. **Corrective RAG (C-RAG):** combine prompt guidance for retrieval, tools to evaluate relevance, and continuous performance evaluation with adjustments — the retrieval itself is subject to metacognitive regulation
3. **Environmental awareness:** schema understanding and dynamic reasoning enable behavioral adjustment based on context changes

The framework emphasizes that metacognition adds "a layer of self-awareness and adaptability" to each agent component — not a single metacognitive module but a metacognitive capability embedded throughout.

**Relevance to FalkVelt**

- **evolution.md as metacognitive scaffold:** The Microsoft framework validates FalkVelt's architecture — the evolution protocol IS a metacognitive layer over the coordinator. Each hook is a specific metacognitive mechanism: error detection, periodic review, adaptive selection, prediction, verification, knowledge export.
- **Corrective RAG → memory_search before build-up:** The C-RAG pattern supports doing a memory search as part of Hook 1 before storing a new correction — check if a highly similar build-up already exists before creating a duplicate. This is already in build-up.md Rule 6 (Deduplicate) but not enforced mechanically.
- **Environmental awareness → dispatcher routing:** The schema understanding pattern means routing rules should be evaluated dynamically against the current agent state (which builds are active? what's the current version?) not just static keyword matching.

**Sources**
- [AI Agents: Metacognition for Self-Aware Intelligence (Microsoft Community Hub)](https://techcommunity.microsoft.com/blog/educatordeveloperblog/ai-agents-metacognition-for-self-aware-intelligence---part-9/4402253)
- [Metacognition in AI Agents (Microsoft AI Agents for Beginners)](https://microsoft.github.io/ai-agents-for-beginners/09-metacognition/)
- [The Metacognitive Demands and Opportunities of GenAI (Microsoft Research)](https://www.microsoft.com/en-us/research/publication/the-metacognitive-demands-and-opportunities-of-generative-ai/)

---

### 3.3 INoT (Introspection of Thought)

**Core idea**

INoT internalizes the multi-agent debate/self-reflection loop inside a single LLM prompt using PromptCode — a structured "mini-program" embedded in XML that the LLM executes during inference. Rather than making multiple API calls for iterative refinement, INoT compresses the generate → critique → revise cycle into one forward pass, reducing token cost by 58.3% while improving performance by 11.6%.

**How it works**

1. Design a PromptCode in XML that encodes the reasoning logic: `<draft>`, `<critique>`, `<revise>`, `<output>` sections
2. The XML hierarchy provides the LLM with an intuitive, parseable structure
3. The LLM executes the PromptCode as if running a virtual multi-agent debate inside its context
4. One API call generates: initial draft → self-critique → revised answer

The key insight: multi-agent debate achieves quality gains through structured disagreement, but the agents can be virtual — instantiated within one prompt as different XML sections — rather than requiring separate LLM calls.

**Results / effectiveness**

+11.6% over baseline on reasoning benchmarks. 58.3% lower token cost than the best-performing multi-call methods. Validated on image Q&A tasks in addition to text reasoning. Published July 2025.

**Relevance to FalkVelt**

- **evolution.md Hook 1 (Correction Interceptor) efficiency:** The current quick path makes at least 2 cognitive passes (store + verify on mental test cases). INoT suggests compressing this into one structured prompt: `<correction><classify>{type}</classify><store>{rule}</store><verify>{test_cases}</verify><apply_rule>{final}</apply_rule></correction>`. More efficient and produces a structured log.
- **meditation.md Phase 1 (Grounding):** The baseline snapshot generation could use an INoT-style single-pass prompt that simultaneously gathers identity anchor, component census, and memory pulse — instead of sequential tool calls for each.
- **build-up.md Quick Path:** The "verify on 2-3 mental test cases" step can be formalized as an INoT PromptCode: `<test_case_1><scenario>...</scenario><expected>...</expected><actual>...</actual></test_case_1>`. Structured, inspectable, logged.

**Sources**
- [Introspection of Thought Helps AI Agents (arXiv:2507.08664)](https://arxiv.org/abs/2507.08664)
- [INoT Teaching AI to Reflect on Its Own Thoughts](https://www.instruction.tips/post/introspection-of-thought-ai-agents)
- [Inner Critics, Better Agents (Cognaptus blog)](https://cognaptus.com/blog/2025-07-14-inner-critics-better-agents-the-rise-of-introspective-ai/)

---

### 3.4 ReMA (Recursive Meta-Thinking Agent)

**Core idea**

ReMA instantiates metacognition as a two-level multi-agent RL architecture: a high-level meta-thinking agent (strategic oversight, task decomposition, planning) and a low-level reasoning agent (execution). Both are trained jointly via RL with agent-specific and joint rewards, explicitly decoupling metacognition from reasoning so each can improve independently.

**How it works**

- **Meta-agent:** monitors the reasoning process, decides when to intervene, decomposes complex tasks, selects strategies
- **Reasoning agent:** executes assigned sub-tasks, returns results to meta-agent
- **Joint RL:** both agents receive rewards; meta-agent is rewarded for correct strategy selection; reasoning agent is rewarded for correct execution; joint reward aligns them toward the overall goal
- Recursive structure: meta-agent can invoke itself for planning tasks of arbitrary depth

**Results / effectiveness**

Significant improvements on complex reasoning benchmarks where single-level agents plateau. Key advantage: the metacognitive layer can generalize across domains because it operates at the strategy level, not the task level.

**Relevance to FalkVelt**

- **coordinator + evolution.md = ReMA in practice:** FalkVelt's coordinator is the meta-agent; subagents are the reasoning agents. The evolution protocol is the mechanism that trains the meta-agent (via build-up). The architecture is already correct — the missing piece is explicit joint reward alignment.
- **Hook 3 (Adaptive Orchestrator) as meta-agent decision:** When Hook 3 selects a build to address a structural gap, this is the meta-agent choosing a strategy. Formalizing the scoring table as "strategy evaluation" — with observed outcomes feeding back to update the scoring weights — makes the mechanism self-improving rather than static.
- **Coordinator/subagent boundary:** ReMA validates FalkVelt's strict coordinator-vs-subagent separation (coordinator never writes code). The two-level architecture is not just organizational hygiene — it enables the metacognitive layer to develop generic strategic intelligence while keeping the execution layer specialized.

**Sources**
- [Frontiers: Cognitive Mirror Framework for AI-Powered Metacognition](https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2025.1697554/full)
- [Review: Metacognition in LLMs and Safety](https://s-rsa.com/index.php/agi/article/download/15271/11131)
- [Agentic Metacognition: Self-Aware Low-Code Framework (arXiv:2509.19783)](https://arxiv.org/pdf/2509.19783)

---

## 4. Continuous Learning & Adaptation

### 4.1 MemRL (Non-Parametric Episodic RL)

**Core idea**

MemRL (January 2026) enables LLMs to self-evolve via reinforcement learning applied to an external episodic memory system rather than to model weights. The frozen LLM reasons; a learnable retrieval policy decides which past episodes to retrieve. This separates stable reasoning from plastic adaptation, solving the stability-plasticity dilemma without fine-tuning.

**How it works**

Two-phase retrieval:
1. **Phase-A (semantic filtering):** retrieve candidates semantically similar to the current situation (analogical transfer — what situations were like this?)
2. **Phase-B (value-based selection):** select from candidates using learned Q-values (mental rehearsal — which recalled strategy expectably leads to the best outcome?)

The Q-values are updated via temporal-difference learning against observed task outcomes. The LLM remains frozen; only the retrieval policy changes. Deployed on closed-source models with low overhead.

**Results / effectiveness**

State-of-the-art on HLE, BigCodeBench, ALFWorld, and Lifelong Agent Bench. Significantly outperforms semantic-only retrieval baselines. Demonstrates continuous runtime improvement without weight updates. Reconciles the stability-plasticity dilemma — improves on new tasks without forgetting past performance.

**Relevance to FalkVelt**

- **memory_search.py as Phase-A:** FalkVelt's Qdrant semantic search is exactly Phase-A. The missing piece is Phase-B: a learned utility estimate for retrieved records. Currently, all semantically similar records are treated equally. MemRL suggests weighting them by observed utility — records that led to successful task completions should be retrieved preferentially.
- **build-up records as episodic memory:** Each build-up record is an episode: (situation description, action taken, outcome). MemRL's framework formalizes how to learn from this memory bank. Enhancement: add an `outcome_utility` field to build-up records (did this rule actually prevent the type of error it was designed for?).
- **Non-parametric learning:** MemRL confirms that FalkVelt's memory-augmented approach (not fine-tuning, but building external memory) is architecturally aligned with the state of the art. The framework is correct; the retrieval strategy can be improved.

**Sources**
- [MemRL: Self-Evolving Agents via Runtime RL on Episodic Memory (arXiv:2601.03192)](https://arxiv.org/abs/2601.03192)
- [GitHub: MemTensor/MemRL](https://github.com/MemTensor/MemRL)
- [EmergentMind summary](https://www.emergentmind.com/papers/2601.03192)

---

### 4.2 Contextual Experience Replay (CER)

**Core idea**

CER is a training-free framework for self-improvement through experience accumulation. It maintains a dynamic memory buffer of past experiences — not just facts, but structured experience summaries including environment dynamics, decision-making patterns, and outcome observations. At inference time, the most relevant experiences are retrieved and synthesized into a context-augmenting narrative.

**How it works**

1. After each task, extract and structure the experience: what was the situation? what was decided? what was the outcome? what patterns emerged?
2. Store in dynamic buffer (rolling window or importance-scored)
3. At next relevant task, retrieve similar experiences via semantic search
4. Synthesize retrieved experiences into a "lessons learned" paragraph prepended to the system prompt
5. The agent now has "memory" of analogous past situations without any weight updates

**Results / effectiveness**

Significantly improves agent performance on complex sequential decision tasks. Works with frozen backbone models. The synthesis step (not raw retrieval) is key — condensing multiple experiences into a coherent narrative is more effective than listing raw episodes.

**Relevance to FalkVelt**

- **Session-level experience accumulation:** CER's dynamic buffer maps directly to `_session_gaps` and `_correction_log` in evolution.md. Enhancement: at the start of each session, synthesize the last 10 build-up records into a "lessons learned" context block and prepend it to the coordinator's working context. This implements CER within FalkVelt's existing architecture.
- **Context Engineering protocol:** The synthesis step (experiences → narrative) should be documented in protocols/knowledge/context-engineering.md as a specific technique. Currently context engineering is focused on assembly; CER adds the synthesis-from-experience dimension.
- **Hook 2 (Session-End Review) as experience capture:** The session review already collects corrections and gaps. Explicitly framing this as "experience extraction for CER" — producing a structured episode summary stored to memory — would complete the loop.

**Sources**
- [Contextual Experience Replay for Self-Improvement of Language Agents (arXiv:2506.06698)](https://arxiv.org/abs/2506.06698)
- [OpenReview submission](https://openreview.net/forum?id=RXvFK5dnpz)

---

### 4.3 SkillRL / Skill Libraries

**Core idea**

SkillRL (Recursive Skill-Augmented Reinforcement Learning, 2026) bridges raw experience and policy improvement through automatic skill discovery. Skills are hierarchical — simple skills combine into complex skills — and the skill library co-evolves with the agent's policy through a recursive mechanism. Related work: SAGE (Skill Augmented GRPO) achieves 8.9% higher goal completion with 26% fewer steps by accumulating skills across a chain of similar tasks.

**How it works (SkillRL):**

1. Experience distillation: extract reusable patterns from successful trajectories → name them as skills
2. Skill library: hierarchical storage with adaptive retrieval (similarity + frequency + recency)
3. Recursive evolution: skills improve as the policy improves — low-level skills are refined when high-level skills using them succeed
4. At inference: retrieve relevant skill(s) → compose into execution plan → refine based on outcome

**Results / effectiveness**

SkillRL consistently outperforms flat RL and non-hierarchical skill approaches on complex long-horizon tasks. SAGE: 8.9% higher goal completion, 26% fewer steps, 59% fewer tokens on sequential agent tasks.

**Relevance to FalkVelt**

- **build-up records + spec-registry.json = skill library:** FalkVelt already has the data structures for a skill library. The `spec-registry.json` is the library catalog; `build-registry.json` is the active/buffered skill queue; build-up memory records are the learned patterns. The missing hierarchy: specs don't currently compose recursively (parent specs calling child specs).
- **Recursive composition in self-build-up.md:** Add a `sub_specs` field to spec definitions — specs that this spec depends on at the execution level (not just for context, but for actual capability composition). This implements SkillRL's hierarchical skill structure.
- **Adaptive retrieval:** Currently memory_search.py retrieves by semantic similarity only. SkillRL's adaptive retrieval (similarity + frequency + recency) would improve build-up record retrieval quality. Add `last_applied` and `apply_count` metadata to build-up records.

**Sources**
- [SkillRL: Evolving Agents via Recursive Skill-Augmented RL (arXiv:2602.08234)](https://arxiv.org/html/2602.08234)
- [Reinforcement Learning for Self-Improving Agent with Skill Library (arXiv:2512.17102)](https://arxiv.org/html/2512.17102)
- [SAGE: Skill Augmented GRPO](https://arxiv.org/html/2512.17102)

---

### 4.4 SPEAR (Progressive Self-Imitation)

**Core idea**

SPEAR (Self-imitation with Progressive Exploration for Agentic RL) addresses the cold-start problem in self-improvement: early in training, the agent has no good examples to imitate. SPEAR introduces a curriculum-based self-imitation recipe: easy tasks first (self-imitation on successful trajectories), then progressively harder tasks as competence builds. Covariance-based regularization prevents overfitting to early successes.

**Relevance to FalkVelt**

- **build-up severity escalation (build-up.md Rule: Escalate severity):** SPEAR's progressive curriculum maps to FalkVelt's severity escalation: 1st correction = normal (easy curriculum), 2nd = elevated, 3rd+ = critical (hard curriculum). The protocol already has the right intuition; SPEAR provides the theoretical foundation.
- **Hook 3 activation threshold:** SPEAR suggests that the activation threshold for full architectural changes should be adaptive — lower it early (when the system is new, improvements are cheap) and raise it as the system matures (changes become more consequential). Currently Hook 3 triggers on a fixed threshold (any STRUCTURAL gap). Adaptive thresholding based on workflow version would be more appropriate.

**Sources**
- [SPEAR: Self-imitation with Progressive Exploration (arXiv:2509.22601)](https://arxiv.org/html/2509.22601v1)

---

### 4.5 Catastrophic Forgetting Prevention (Prompt-Based Systems)

**Core idea**

For prompt-based systems (no weight updates), catastrophic forgetting manifests differently than in fine-tuned models. The threat is not weight overwriting but context crowding: as more rules, corrections, and patterns accumulate, the effective context space for any given task shrinks, older rules get diluted, and behavioral consistency degrades.

Key 2025 findings:
- "Spurious forgetting" — performance drops often reflect task alignment loss, not knowledge loss
- Conjugate Prompting: artificially makes the task look farther from known distributions to recover pretraining capabilities
- Experience replay (CER) effectively prevents context crowding by synthesizing experiences rather than listing them

**Techniques applicable to prompt-based systems:**
1. **Memory consolidation:** periodically merge similar build-up records into compact summary rules (already in build-up.md Cleanup section)
2. **Importance weighting:** retrieve high-utility records more frequently to reinforce critical rules
3. **Context compression:** summarize accumulated corrections into fewer, more general rules rather than growing the list indefinitely
4. **Periodic review:** Hook 2 (Session-End Review) acts as a consolidation checkpoint — a form of scheduled replay

**Relevance to FalkVelt**

- The MEMORY.md observation that "protocol count in memory (record says '18') is stale" is a symptom of context crowding — metadata that was accurate becomes stale as the system evolves.
- **Monthly deduplication (build-up.md Cleanup):** This is FalkVelt's catastrophic forgetting prevention. Research confirms it's the right approach. Enhancement: run consolidation more aggressively after each version boundary (e.g., at v2.0, consolidate all v1.x corrections).
- **Version boundaries as consolidation checkpoints:** At each integer version bump (1.0→2.0), run a full memory consolidation: merge similar records, archive superseded anti-patterns, compress rule sets.

**Sources**
- [Continual Learning of LLMs: A Comprehensive Survey (ACM Computing Surveys 2025)](https://dl.acm.org/doi/10.1145/3735633)
- [Mitigating Catastrophic Forgetting in LLMs (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.1108.pdf)
- [Catastrophic Forgetting in LLMs: Comparative Analysis (arXiv:2504.01241)](https://arxiv.org/abs/2504.01241)
- [Towards Lifelong Learning of LLMs: A Survey (ACM)](https://dl.acm.org/doi/10.1145/3716629)

---

## 5. Self-Evaluation & Quality Assurance

### 5.1 LLM-as-Judge

**Core idea**

LLM-as-Judge uses an LLM to evaluate LLM outputs, replacing or supplementing human evaluators and fixed metrics. The judge provides rubric-driven, interpretive assessments that capture nuanced quality signals missed by rule-based metrics. Recent evolution: self-rewarding language models (SRLMs) use the model as its own judge during training — removing the dependency on fixed reward models.

**Key 2024-2025 developments:**
- **Agent-as-Judge (2025):** instead of a single LLM call, a full agent (with tools, multi-step reasoning) evaluates outputs — handles complex evaluation criteria that require information retrieval or code execution
- **ChatEval:** multi-agent referee team debates response quality, with different personas arguing different positions
- **CLoud (Critique-out-Loud):** reward model first generates natural language critique, then evaluates (prompt + response + critique) to predict scalar reward — interpretable and improvable

**Relevance to FalkVelt**

- **evolution.md Hook 5 (Post-Task Verification):** The "correction check" in Hook 5 is a primitive LLM-as-Judge pattern: the coordinator evaluates its own output against stored build-up rules. Formalizing this as an explicit judgment prompt — with a rubric derived from all active build-up records — would make it more reliable and auditable.
- **build-up.md Step 6 (Evaluate variants):** "Compare variants → identify best/worst → extract anti-patterns" is a judge operation. Using a structured rubric (generated from stored rules) rather than free-form evaluation would improve consistency.
- **Automated quality gate:** Add a CLoud-style critique step before finalizing any T3+ task output: coordinator critiques its own response against build-up rules, generates a critique, then produces a final output that addresses the critique. This is a one-step quality gate that doesn't require a full Hook 1 correction.

**Sources**
- [LLMs-as-Judges: A Comprehensive Survey (arXiv:2412.05579)](https://arxiv.org/html/2412.05579v2)
- [When AIs Judge AIs: Agent-as-a-Judge (arXiv:2508.02994)](https://arxiv.org/html/2508.02994v1)
- [LLM Judges as Reward Models (Atla AI)](https://atla-ai.com/post/llm-judges-as-reward-models)
- [Opportunities and Challenges of LLM-as-a-Judge (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.138.pdf)

---

### 5.2 Chain-of-Verification (CoVe)

**Core idea**

CoVe addresses hallucination by structuring self-verification as a multi-step pipeline: generate initial response → identify verifiable claims → create independent verification questions for each claim → answer verification questions (without seeing the original response) → produce a final response that incorporates verification results.

**How it works**

1. Generate baseline response
2. Plan verifications: "What specific facts in this response could be wrong?"
3. Execute verifications: answer each verification question independently (without the original response in context — prevents confirmation bias)
4. Final generation: incorporate verification results

The independence of the verification step is critical — the LLM must answer verification questions without seeing its own answer to avoid confirming its own errors.

**Results / effectiveness**

Significantly better than Zero-Shot, Few-Shot, and CoT baselines on factuality benchmarks. Hallucinations reduced substantially. Accepted at ACL 2024 Findings.

**Relevance to FalkVelt**

- **Hook 5 (Post-Task Verification) enhancement:** The current post-task verification asks "was there a correction?" CoVe suggests adding: "What claims did this response make? Which of those claims can be independently verified against stored rules or documentation?" This is a structured hallucination check for coordinator outputs.
- **meditation.md Phase 4 (Conflict Resolution, step 4d):** The "Memory-Reality Divergence" scan in Phase 4d is a CoVe-style verification: identify claims in memory records → verify against current codebase reality → flag divergences.
- **Research output quality gate:** For research deliverables (like this document), run a CoVe pass before finalizing: identify factual claims → verify each claim against source URLs → flag unverifiable claims.

**Sources**
- [Chain-of-Verification Reduces Hallucination in LLMs (ACL 2024 Findings)](https://aclanthology.org/2024.findings-acl.212.pdf)
- [LearnPrompting: CoVe](https://learnprompting.org/docs/advanced/self_criticism/chain_of_verification)
- [CoVe Framework Overview (EmergentMind)](https://www.emergentmind.com/topics/chain-of-verification-cove)

---

### 5.3 Self-Consistency

**Core idea**

Self-consistency samples multiple independent reasoning paths from the same prompt (via temperature > 0) and takes the majority vote as the final answer. The insight: correct reasoning paths tend to converge on the same answer, while incorrect paths diverge. Consensus = reliability signal.

**Relevance to FalkVelt**

- **build-up.md Step 6 (Evaluate variants):** Running 3 variants and picking the best-scored is a form of self-consistency. Enhancement: before selecting the winner, check if the top-2 variants agree on the core behavioral rule — if they diverge, classify as a "soft conflict" requiring full path rather than quick path.
- **Hook 1 (Correction Interceptor) classification:** The "classify correction" step (correction/routing/workflow/architectural) could use self-consistency: classify independently 2-3 times, take the majority — reduces misclassification of corrections as the wrong type.

**Sources**
- [Self-Consistency Improves Chain of Thought Reasoning (Semantic Scholar)](https://www.semanticscholar.org/paper/Self-Consistency-Improves-Chain-of-Thought-in-Wang-Wei/5f19ae1135a9500940978104ec15a5b8751bc7d2)
- [Self-Consistency Prompting (LearnPrompting)](https://learnprompting.org/docs/intermediate/self_consistency)

---

### 5.4 OpenAI Self-Evolving Agents Cookbook (2025)

**Core idea**

A practical guide for building self-improving production agents with a feedback loop: baseline execution → feedback collection → eval-driven scoring → prompt optimization → redeployment. Introduces GEPA (Genetic-Pareto) — an evolutionary framework that samples agent trajectories, reflects on them in natural language, proposes prompt revisions, and evolves the system through iterative feedback loops.

**Key implementation patterns:**

1. **VersionedPrompt class:** maintains historical prompts with timestamps and associated eval runs — enables instant rollback if optimization regresses
2. **Multi-grader evaluation:** combines deterministic checks (entity preservation, length), semantic validation (cosine similarity), and LLM-as-judge rubric scoring — prevents any single grader failure from stalling optimization
3. **Lenient thresholds:** 75% graders passing OR 85% average score — allows progress despite imperfect runs
4. **Metaprompt templating:** the optimizer receives failure reasoning and produces targeted improvements, not random mutations

**Relevance to FalkVelt**

- **build-up.md Step 9 (Store) → VersionedPrompt pattern:** FalkVelt should store not just the current rule but the version history of each CLAUDE.md section alongside its build-up record. The `backup-{date}-CLAUDE.md` in Step 7 is a good start; making this queryable by rule section would enable surgical rollback.
- **Multi-grader evaluation → build-up.md Step 5 (Test):** The testing step currently runs a generic benchmark. The cookbook's multi-grader approach provides a specific framework: deterministic graders (does the rule change preserve existing behavior?), semantic graders (is the new rule similar to the intended correction?), LLM judge (does the new rule correctly address the original error?).
- **GEPA as an advanced Hook 3 variant:** GEPA's genetic-pareto evolution could replace the current Hook 3 scoring table for high-stakes architectural decisions — sample multiple build trajectories, reflect on them collectively, propose the Pareto-optimal build.

**Sources**
- [Self-Evolving Agents Cookbook (OpenAI)](https://cookbook.openai.com/examples/partners/self_evolving_agents/autonomous_agent_retraining)
- [OpenAI Agents SDK + GEPA + SuperOptiX (Medium)](https://medium.com/superagentic-ai/openai-agents-sdk-gepa-superoptix-self-optimizing-ai-agents-9f6325f9e2c9)

---

### 5.5 AgentBench & SWE-bench (Evaluation Infrastructure)

**Core idea**

Production-grade self-evolving systems need standardized evaluation infrastructure. AgentBench (ICLR 2024) provides 8 distinct environments for evaluating LLM agents across reasoning and decision-making tasks. SWE-bench measures the ability to solve real GitHub issues in Python projects.

**2025 evaluation landscape:**
- **SWE-bench Verified (Aug 2024):** 500 human-validated test cases — removes noise from the original benchmark
- **SWE-PolyBench:** extends to polyglot (multi-language) codebases
- **Terminal-Bench (May 2025):** evaluates multi-step command-line workflows in sandboxed environments
- **tau-bench (Sierra):** evaluates agents in realistic customer service scenarios with tool use

**Relevance to FalkVelt**

- **build-up.md Step 5 (Test) — benchmark infrastructure:** FalkVelt's testing step references `protocols/quality/testing.md` but lacks a concrete test suite. SWE-bench Verified's approach (curated, human-validated test cases) is the model to follow. Build a FalkVelt-specific benchmark: 20-30 test prompts per agent, covering known edge cases from build-up history.
- **Hook 2 (Session-End Review) metrics:** The review currently counts corrections. Adding benchmark-style metrics — correct routing rate, build-up application rate, hook compliance rate — would make the session review more objective and comparable across sessions.
- **Regression testing for build-up:** After every build-up, run the benchmark subset relevant to the changed component. This is the "verify" step made rigorous. Currently done "mentally on 2-3 test cases."

**Sources**
- [AgentBench: Evaluating LLMs as Agents (arXiv:2308.03688)](https://arxiv.org/abs/2308.03688)
- [Best AI Agent Evaluation Benchmarks: 2025 Guide (o-mega.ai)](https://o-mega.ai/articles/the-best-ai-agent-evals-and-benchmarks-full-2025-guide)
- [8 Benchmarks Shaping the Next Generation of AI Agents (AI Native Dev)](https://ainativedev.io/news/8-benchmarks-shaping-the-next-generation-of-ai-agents)
- [tau-bench (Sierra)](https://sierra.ai/blog/benchmarking-ai-agents)

---

## 6. Agent Evolution Architectures

### 6.1 Behavioral Versioning & Canary Deployment

**Core idea**

Treating agent behavioral changes as deployable software releases: version every prompt/rule change, deploy to a small traffic subset first (canary), monitor KPIs, roll back automatically if metrics degrade. The key principle: behavioral artifacts (prompts, rules, configurations) are as deployable as code artifacts — they need the same DevOps rigor.

**Key patterns from 2025 production systems:**

1. **Immutable artifacts:** keep old behavior versions immutable for rollback targets — never overwrite, always version
2. **Traffic splitting:** route X% of requests to new behavior, (100-X)% to stable — compare performance live
3. **Automated rollback:** if a metric (error rate, correction rate, user satisfaction) exceeds threshold, automatically route all traffic to stable behavior
4. **Feature flags for behaviors:** toggle specific rule changes on/off without full deployment — isolates problems
5. **Tool versioning:** 60% of production agent failures come from tool API changes — strict semantic versioning for all tool interfaces

**Relevance to FalkVelt**

- **build-up.md Step 7 (Backup) → immutable version archive:** The current backup is a file copy. Enhance with git tags at each version boundary: `git tag v{version}` after every build-up. This enables instant rollback to any previous behavioral state.
- **Quick path as canary:** When applying a quick-path correction, treat it as a canary deployment for 1 session: apply the rule → monitor for contradictory behavior → if it generates new corrections, roll back and escalate to full path.
- **build-registry.json TTL = canary timer:** The TTL mechanism for active builds is already a canary deployment timer — the build is "deployed" for N sessions, monitored, then either promoted (kept) or buffered (rolled back). This is excellent architecture — matches production best practices.
- **Correction rate as rollback metric:** If the correction rate in a session exceeds the average, it may indicate a build-up rule is causing regressions. Hook 2 (Session-End Review) should compare this session's correction rate to the rolling average — above 2x average = trigger rollback review.

**Sources**
- [Versioning, Rollback & Lifecycle Management of AI Agents (Medium)](https://medium.com/@nraman.n6/versioning-rollback-lifecycle-management-of-ai-agents-treating-intelligence-as-deployable-deac757e4dea)
- [Bringing A/B Testing to AI Agents (AlignX AI / Medium)](https://medium.com/@AlignX_AI/bringing-a-b-testing-to-ai-agents-when-and-why-it-matters-261a063b6e93)
- [5 Strategies for A/B Testing for AI Agent Deployment (Maxim)](https://www.getmaxim.ai/articles/5-strategies-for-a-b-testing-for-ai-agent-deployment/)
- [AI Agents in Production 2025: Enterprise Trends (Cleanlab)](https://cleanlab.ai/ai-agents-in-production-2025/)
- [Dynatrace: AI Model Versioning and A/B Testing](https://www.dynatrace.com/news/blog/the-rise-of-agentic-ai-part-6-introducing-ai-model-versioning-and-a-b-testing-for-smarter-llm-services/)

---

### 6.2 Comprehensive Survey: Self-Evolving AI Agents (2025)

**Core idea**

A comprehensive survey (arXiv:2508.07407, Aug 2025) provides the first systematic review of self-evolving agents organized around three foundational questions: **what** to evolve, **when** to evolve, and **how** to evolve. A companion survey (arXiv:2507.21046, "On the Path to Artificial Super Intelligence") maps the evolutionary landscape across research directions.

**What to evolve:**
- Tool use capabilities
- Knowledge and reasoning patterns
- Planning and decision strategies
- Communication and collaboration patterns
- Memory retrieval and organization
- Evaluation criteria themselves

**When to evolve:**
- After failure or correction (reactive) — what FalkVelt currently does
- Periodically via gap analysis (proactive) — what Hook 4 partially does
- Continuously at inference time (real-time) — what MemRL does
- On phase transitions (context-aware) — what Adaptive Orchestrator does

**How to evolve:**
- Supervised: learn from demonstrations
- Reinforcement: learn from outcome signals
- Self-supervised: learn from consistency between outputs
- Collaborative: learn from other agents

**Key finding:** Static agents that only evolve reactively plateau quickly. State-of-the-art systems combine all four "when" modes and multiple "how" modes.

**Relevance to FalkVelt**

- **Current FalkVelt evolution mode:** primarily reactive (corrections → build-up) + semi-periodic (gap analysis). Missing: real-time continuous learning and self-supervised learning.
- **Self-supervised gap:** FalkVelt does not have a self-supervised learning pathway — it only learns when users provide explicit corrections. Adding self-consistency checking (Section 5.3) as a background process would add a self-supervised signal.
- **"What to evolve" expansion:** Current scope is coordinator behavior (prompts, rules). Research suggests extending to: memory retrieval strategy, evaluation criteria themselves (the scoring table in Hook 3), and agent communication protocols.

**Sources**
- [A Comprehensive Survey of Self-Evolving AI Agents (arXiv:2508.07407)](https://arxiv.org/abs/2508.07407)
- [GitHub: EvoAgentX/Awesome-Self-Evolving-Agents](https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents)
- [A Survey of Self-Evolving Agents: Path to ASI (arXiv:2507.21046)](https://arxiv.org/abs/2507.21046)
- [Building Self-Evolving Agents via Experience-Driven Lifelong Learning (arXiv:2508.19005)](https://arxiv.org/html/2508.19005v5)

---

## 7. Recommendations for FalkVelt

The following recommendations are prioritized by implementation cost vs. expected impact. Each maps to specific files in the FalkVelt architecture.

---

### Priority 1 — High Impact, Low Cost (Implement in next 1-2 sessions)

**R1: INoT-style structured prompts for Hook 1**

Replace free-form "classify → store → verify → apply" in the quick path with an INoT-style XML-structured single-pass prompt:

```xml
<correction>
  <raw_user_feedback>{correction text}</raw_user_feedback>
  <classify type="correction|routing|workflow|architectural" confidence="0-100"/>
  <store_rule>{atomic, specific rule in English}</store_rule>
  <verify>
    <test_case_1><scenario>...</scenario><passes>yes/no</passes></test_case_1>
    <test_case_2><scenario>...</scenario><passes>yes/no</passes></test_case_2>
    <test_case_3><scenario>...</scenario><passes>yes/no</passes></test_case_3>
  </verify>
  <apply_change>{what exactly changes in CLAUDE.md or agent definition}</apply_change>
</correction>
```

File to modify: `protocols/core/evolution.md` Hook 1 steps 2-4.
Benefit: produces structured, auditable correction logs; reduces processing errors; 58% token savings (INoT result).

**R2: Add `outcome_utility` field to build-up memory records**

Add a new metadata field to all build-up memory records:
```json
"outcome_utility": null  // updated when the rule prevents a future error
"last_applied_session": null
"apply_count": 0
```

This enables MemRL-style Phase-B retrieval: prefer records that have demonstrated utility over records that are merely semantically similar.

Files to modify: `protocols/core/build-up.md` Step 9 (Store schema), `memory/scripts/memory_write.py` schema documentation.

**R3: Correction rate as session health metric in Hook 2**

In Hook 2 (Session-End Review), add computation of session correction rate vs. rolling average:
```
session_correction_rate = corrections_this_session / t3plus_tasks_completed
if session_correction_rate > 2 * rolling_average_rate:
    flag_for_rollback_review = True
    report: "Correction rate elevated — possible build-up regression"
```

Compute rolling average from last 5 sessions stored in memory.
File to modify: `protocols/core/evolution.md` Hook 2 step 4 (report generation).

---

### Priority 2 — High Impact, Medium Cost (Next 1-2 weeks)

**R4: OPRO-style meta-prompt for batch rule synthesis**

Every 10 build-up corrections of the same type (subtype="correction"), trigger an OPRO meta-review:
```
"Given these {N} corrections of type {type} and their contexts,
what single most-impactful rule addition to CLAUDE.md would prevent
the most future errors of this type? The rule must be specific,
testable, and non-redundant with existing rules."
```

Store the synthesized rule as a new build-up record with `subtype: "synthesized"`.
File to modify: `protocols/core/evolution.md` — add a new Hook 7 (Synthesis Trigger) or extend Hook 4.

**R5: Add CoVe-style post-task factuality check to Hook 5**

For T3+ tasks that produce knowledge outputs (research, analysis, documentation), extend Hook 5 with a Chain-of-Verification pass:
1. Identify claims made in the output
2. For each claim: verify against source citations or stored memory records
3. Flag unverified claims in the task log

This is especially relevant for the pathfinder agent (research tasks) and for protocol creation (protocol-manager).
File to modify: `protocols/core/evolution.md` Hook 5, `protocols/agents/agent-communication.md` (post-task gate).

**R6: Build-up records with activation conditions (Voyager skill library pattern)**

Each build-up record should have an explicit `activation_condition` field alongside the rule text:
```json
{
  "text": "Rule: delegate T3+ file-writing to engineer subagent",
  "activation_condition": "when task requires creating or modifying any non-memory file",
  "anti_pattern": "coordinator writing files directly"
}
```

This transforms build-up records from passive facts into active skill triggers — more aligned with Voyager's skill library design and improves retrieval precision.
File to modify: `protocols/core/build-up.md` Step 9 schema.

---

### Priority 3 — Strategic Enhancements (Next 1-3 months)

**R7: CER session synthesis at session start**

At session start (CLAUDE.md Step 3), before memory_search for active tasks, run a CER-style synthesis:
```bash
python3 memory/scripts/memory_search.py "build_up correction" --limit 10
```
Then prompt: "Synthesize these 10 recent corrections into a coherent 'lessons learned' paragraph for this session." Prepend the synthesis to the working context.

This implements Contextual Experience Replay at the session level — the most recent behavioral lessons are always present in compressed form.
File to modify: `CLAUDE.md` Session Start step 3 (extend memory search with synthesis step).

**R8: Introduce self-supervised consistency checking (new Hook 7)**

Add a background consistency check: when the coordinator produces a T2+ response, independently re-classify the request and verify routing decision against the original classification. If they diverge: log the divergence as a potential routing issue → accumulate divergences → when 3 divergences of same type occur, auto-trigger Hook 1.

This adds a self-supervised learning signal that doesn't require user corrections.
File to create: add Hook 7 section to `protocols/core/evolution.md`.

**R9: Version boundary consolidation protocol**

At each integer version boundary (v1.99 → v2.0), trigger a consolidation build-up:
1. Retrieve all v1.x build-up records from memory
2. Run deduplication and synthesis (OPRO meta-prompt over the full set)
3. Produce a compact "v2.0 rule set" — fewer, more general rules
4. Archive v1.x records with `archived: true` metadata
5. Store the consolidated rule set as a new build-up record

This prevents catastrophic forgetting through compression rather than deletion.
File to modify: `protocols/core/build-up.md` — add "Version Boundary Consolidation" section after Cleanup.

**R10: Offline DSPy/TextGrad optimization pipeline**

Create a separate offline optimization script (`memory/scripts/optimize_prompts.py`) that:
1. Exports the coordinator's key prompt sections (dispatcher routing rules, correction classifier, build-up schema)
2. Runs TextGrad or DSPy MIPROv2 against a test set built from build-up history
3. Generates candidate improved prompt sections
4. Presents diff to user for review
5. User-approved changes enter the normal build-up full path

This implements automated prompt optimization without touching live sessions.
Files to create: `memory/scripts/optimize_prompts.py`, accompanying test set in `tests/coordinator-prompts/`.

---

### Priority 4 — Architectural Vision (Longer term)

**R11: Adaptive Hook 3 scoring via learned Q-values**

Replace the static keyword-overlap scoring table in Hook 3 with a learned utility estimate: store observed outcomes for each build selection decision (did the chosen build actually address the gap?), and use Q-value-style updates to improve scoring accuracy over time. This is MemRL Phase-B applied to the Adaptive Orchestrator.

**R12: Hierarchical spec composition (SkillRL pattern)**

Add `sub_specs` and `parent_specs` fields to spec-registry.json entries, enabling recursive skill composition. When a build activates a complex spec, the sub-specs are automatically activated as prerequisites. This eliminates the current limitation where each spec is treated as atomic — enabling composable capability assembly.

**R13: EvoAgentX integration for agent creation**

When creating new domain agents, use EvoAgentX as an offline tool: provide the task description → EvoAgentX generates a workflow topology and initial system prompt → coordinator reviews and adapts → normal agent-creation.md pipeline. This replaces manual agent design with goal-driven automated generation.

---

## Summary Table

| Framework | Core Mechanism | Effort to Integrate | Priority |
|-----------|---------------|--------------------|---------:|
| INoT | XML-structured self-reflection in one pass | Low | 1 |
| MemRL outcome tracking | `outcome_utility` field in records | Low | 1 |
| Correction rate monitoring | Hook 2 metric | Low | 1 |
| OPRO batch synthesis | Meta-prompt over correction history | Medium | 2 |
| CoVe post-task check | Claim verification in Hook 5 | Medium | 2 |
| Voyager skill activation | `activation_condition` field | Low | 2 |
| CER session synthesis | Synthesize recent corrections at session start | Low | 3 |
| Self-supervised consistency | New Hook 7 (auto-trigger on divergence) | Medium | 3 |
| Version boundary consolidation | Integer-boundary memory compression | Medium | 3 |
| DSPy/TextGrad offline optimization | Offline prompt optimizer script | High | 4 |
| MemRL Q-value scoring (Hook 3) | Learned utility estimates | High | 4 |
| Hierarchical spec composition | Sub-spec/parent-spec registry fields | High | 4 |
| EvoAgentX agent creation | Offline workflow generation | High | 4 |

---

## Key Takeaway

FalkVelt's evolution architecture is **research-validated**: the build-up + evolution hook system is structurally equivalent to the best frameworks in the literature (Constitutional AI critique-revise, Reflexion verbal RL, Voyager skill library, LATS tree search variants). The architecture is correct.

The primary gap identified across all 7 research areas: **FalkVelt evolves reactively but not proactively**. The system waits for user corrections to learn. The state-of-the-art combines reactive + periodic + continuous + self-supervised learning signals. Priority 1 and 2 recommendations are low-cost paths to closing the self-supervised and proactive evolution gaps without restructuring the existing architecture.

---

*Research compiled by pathfinder agent (FalkVelt). Sources verified at time of writing (2026-03-03). Academic links are to arXiv preprints or published conference proceedings.*
