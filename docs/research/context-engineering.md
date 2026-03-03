# Context Engineering & Window Management — Research (2025-2026)

**Date:** 2026-03-03
**Priority:** P2 (High)
**Researcher:** pathfinder (web-enabled)
**Relevance:** FalkVelt context rot in long sessions, watcher/CLI prompts optimization

---

## 1. Executive Summary

Context engineering has emerged as the critical frontier in LLM agent optimization (2025-2026). As context windows expand to 1M+ tokens, the challenge shifts from "how do we fit more?" to "how do we manage relevance when drowning in information?" Context rot — where model recall accuracy decreases despite larger windows — is real and architectural. Five core strategies: (1) Anthropic prompt caching for cost/latency reduction, (2) LLM-guided context compression (LLMLingua, Gisting), (3) RAG-as-context for just-in-time dynamic assembly, (4) MemGPT's tiered memory architecture, (5) multi-agent context isolation protocols.

---

## 2. Context Window Landscape (2025-2026)

### Model Capabilities

| Model | Context Window | Max Output | Notes |
|-------|---------------|------------|-------|
| Claude Opus 4.6 | 200K (1M beta) | 128K | Enterprise: 500K |
| Claude Sonnet 4.6/4.5 | 200K (1M beta) | 64K | Most cost-effective |
| GPT-4o | 200K | 16K | Strong reasoning |
| Gemini 2.x | Up to 1M | Variable | Largest native window |
| Llama 3.3 (open) | 128K-512K | Variable | Self-hosted option |

Key insight: 1M window increasingly available but not universally enabled. Plan for 200K baseline; treat 1M as optimization opportunity for batch operations.

---

## 3. Prompt Caching (Anthropic Deep Dive)

### How It Works
Prompt caching marks portions of your prompt for reuse. Anthropic caches the internal state associated with a prefix. On subsequent requests with matching prefix, model reads from cache and skips computation, reducing both latency and cost.

### Cache TTL Options
- **5-minute cache** (default): Refresh free on each use within TTL
- **1-hour cache**: Longer persistence for stable prompts
- Best for: System prompts, policy blocks, reference documents used >5min cadence

### Cost Structure (2025)
- **5-minute cache writes**: 1.25x base input token price
- **1-hour cache writes**: 2x base input token price
- **Cache reads**: 0.1x base price (massive savings)
- Real-world: 3000-token prefix + 1000-token suffix across 100 requests = ~67% input token reduction

### Performance Impact
- Cost savings: Up to 90% for repetitive prompts
- Latency savings: Up to 85% reduction (skips attention computation)
- Optimal granularity: Cache system prompt + stable context separately from dynamic content

### Best Practices
1. Cache system prompts and policies (never change during session)
2. Place dynamic content *after* cached content
3. Use 1-hour cache for reference docs (style guides, knowledge bases)
4. Calculate break-even: ~200 requests for 1-hour cache, ~3-5 for 5-minute cache
5. Monitor cache hit rates; adjust prefix boundaries if hit rate <70%

### Implementation Pattern (Claude API)
```json
{
  "model": "claude-opus-4-6",
  "system": [
    {
      "type": "text",
      "text": "[stable system prompt]",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "messages": [...]
}
```

Response includes `usage.cache_creation_input_tokens` and `usage.cache_read_input_tokens`.

---

## 4. Context Compression Techniques

### LLMLingua (Coarse-to-Fine)
- Budget controller maintains semantic integrity
- Token-level iterative compression models interdependence
- Up to 20x compression ratio with minimal performance loss
- Phase 1: Coarse compress (identify critical tokens)
- Phase 2: Fine compress (iterative token removal with budget constraints)
- Phase 3: Alignment (instruction tuning to match distribution)

### Gisting (Information Bottleneck)
- Learn compressed representations retaining maximal information about target variables
- Use case: Conversation history summarization, abstractive compression of tool outputs
- Advantage: Learned, not heuristic — adapts to your domain

### Selective Context (Self-Information Based)
- Compute self-information for each token; keep high-information tokens, discard noise
- Allows processing 2x more content with 40% less memory and GPU time

### Abstractive vs Extractive
- **Extractive** (RECOMP): Select documents/sentences unchanged
- **Abstractive** (PRCA): Generate summaries synthesizing information
- **Hybrid**: Combine both for best-of-both coverage

### Implementation Priority
1. Extractive first (cheaper, faster): Reranker-based selection
2. LLMLingua for large prompts (>4K tokens)
3. Gisting for repeated context (conversation history)
4. Abstraction as fallback (when extractive misses nuance)

---

## 5. RAG-as-Context Patterns

### Core Concept Shift
Traditional RAG: Retrieve → Generate (separate pipelines)
RAG-as-context: Retrieval becomes step in continuous reasoning loop; agents dynamically write, compress, isolate, and select context.

### Just-in-Time Context Loading
Right information occupies context space at last possible moment:
1. **Pre-retrieval**: Optimize indexing (granularity, metadata, alignment)
2. **Retrieval**: Multi-stage (vector search + reranking)
3. **Post-retrieval**: Compress, rank, assemble

### Dynamic Context Assembly
Agents explore progressively, discovering context layer-by-layer. Maintain only necessary working memory. Call retrieval API only when current context insufficient. Rerank results using BGE cross-encoders before including in prompt.

### Advanced RAG Patterns
Two-stage retrieval (vector + reranking):
1. Dense retrieval for speed (top-100 candidates)
2. Cross-encoder reranking (top-10 quality check)
3. Optional LLM reranking (semantic verification)

### Agentic RAG with GraphRAG
When to add graphs:
- Multi-hop reasoning needed (entity A → relation → entity B → answer)
- Domain has clear ontology
- Need verifiable provenance
GraphRAG retrieval: Entity linking → graph traversal → subgraph extraction → NL assembly

---

## 6. Memory-Augmented Generation (MemGPT/Letta)

### Architecture (Inspired by OS Virtual Memory)

**Core Memory** (always accessible, ~500-2000 tokens):
- Compressed facts, personal preferences, system knowledge
- Analogous to CPU registers

**Recall Memory** (searchable database):
- Semantic-indexed episodic memories
- Can be queried by agent
- Analogous to RAM

**Archival Memory** (long-term storage):
- Persistent facts, completed tasks, learned patterns
- Moved to core/recall on-demand
- Analogous to disk storage

### Self-Editing Through Tool Use
Agents call functions to:
- **Write core**: Update personal info, learned preferences
- **Append recall**: Add episodic memory, conversation summaries
- **Search archival**: Query by semantic embedding
- **Move**: Promote archival facts to recall when relevant

### Virtual Context Management
Agent uses function calls to manage context like an OS manages memory:
- "Core memory is full" → save_to_archival(chunk) → free core → later search_archival("topic")

### Letta Platform (2024+)
Production-ready successor to MemGPT:
- Automatic tiered memory management
- REST API for agents
- Integrations with Claude, GPT, open-source
- Multi-agent collaboration via shared memory stores

---

## 7. Sliding Window & Conversation Management

### The Problem
Naive truncation (drop oldest messages) discards relevant information. Agent forgets earlier topics.

### Sliding Window Strategy
Two-tier approach:
- **Short-term window**: Last N messages in full detail
- **Long-term window**: Summarized older conversation

### Message Importance Scoring
- Semantic similarity to current query
- Entity/concept presence (named entities, technical terms)
- User-indicated importance
- Frequency of reference in subsequent exchanges

### Overlapping Sliding Windows (Advanced)
Multiple granularities:
- Granularity 1 (last 3 turns): Full detail
- Granularity 2 (last 20 turns): Summarized
- Granularity 3 (full history): Extracted key facts + decisions

### Context Overflow Strategies (Priority)
1. Keep system prompt (never truncate)
2. Keep recent exchanges (last 5 turns)
3. Summarize older turns
4. Offload tool outputs to external storage (if >20K tokens)
5. If still over limit, drop irrelevant tool outputs

### Conversation Compaction
Dynamic summarization — keep living summary updated over time.
Trigger: Activate when approaching 70% of context window.

---

## 8. Multi-Agent Context Sharing

### The Context Explosion Problem
Single agent: 10K tokens manageable. Multi-agent: Parent passes full 10K to child → child passes to grandchild → exponential explosion.

Google ADK solution: Explicitly scope context per agent level:
- Parent agent (10K tokens of full history)
- Child agent (only latest query + 1 key artifact, ~2K tokens)
- Grandchild (only immediate task, ~500 tokens)

### Design Patterns

**Pattern 1: Information Architecture (Selective Propagation)**
Only forward essential context: Tone, voice, audience (3-5 sentences), key decisions (1-2 bullets). NOT brainstorm content or raw tool outputs.

**Pattern 2: SAMEP (Secure Agent Memory Exchange Protocol)**
Persistent, secure memory sharing with fine-grained access control per agent. Efficient semantic discovery (vector search for "relevant context").

**Pattern 3: Scoped Prompts**
Each agent gets system prompt + scope-specific context, not all conversation history.

### Best Practices
1. Define context budget per agent: Parent 10K, child 3K, leaf 1K
2. Use shared memory store: Deduplicate at Neo4j level
3. Explicit forwarding rules: "forward if topic match > 80%"
4. Isolation by default: Child doesn't see parent's internal reasoning
5. Feedback path: Child summarizes learnings back to parent

---

## 9. Needle-in-a-Haystack Evaluation

### Position-Dependent Phenomena
**"Lost in the Middle"**: Optimal recall at document start/end, poor recall in middle. Affects extraction-focused tasks.

### Key Findings (2024-2025)
1. Recall is prompt-dependent — single NIAH test not representative
2. Data size more globally influential than position
3. Feature interaction: data type influences position bias
4. In-context features matter: how needle is phrased affects detectability

### Implications for Agents
- Don't blindly trust 1M window for all tasks
- Benchmark specific task with NIAH
- Use retrieval + prompt caching instead of relying on full-context recall
- If needle must be in context, place explicitly and near start

---

## 10. Practical Implementation Guide

### Anthropic's Four Strategies
1. **WRITE**: Generate context on-demand (scratchpad, tool calls)
2. **SELECT**: Retrieve only relevant information (embedding + reranking)
3. **COMPRESS**: Reduce token count (LLMLingua, gisting, masking)
4. **ISOLATE**: Scope context per task (agent isolation, temporal isolation)

### System Prompt Positioning
Optimal structure:
```
<system_prompt>[role, constraints, always-apply rules]</system_prompt>
<context>[reference docs, knowledge base excerpts]</context>
<task>[specific request]</task>
[dynamic content from user]
```

### Token Efficiency Tactics
- Cut tokens by 40% without quality loss by removing redundancy
- Model-specific: Claude prefers semantic clarity + XML tags
- Compress benchmarks: A/B test original vs compressed; compressed often wins
- Prompt caching multiplier: Every 100 cached tokens saves ~10 tokens billing

### Scratchpad Pattern
Agent records intermediates outside immediate LLM context. Key info persists even if conversation context truncated.

---

## 11. Relevance to FalkVelt

### Identified Gaps

**Gap 1: Session Length Hallucination**
- Problem: Long sessions cause context rot
- Solution: Tiered memory (working/archival/recall) + sliding window
- Action: Add `memory/context_manager.py` that auto-compresses turns >30

**Gap 2: Context Explosion in Multi-Agent Handoff**
- Problem: Parent passes full history to child; no isolation
- Solution: Explicit scoping per agent; shared memory store
- Action: Implement context envelope in `protocols/agents/agent-communication.md`

**Gap 3: No Prompt Caching**
- Problem: System prompt + CLAUDE.md recomputed every request
- Solution: Enable 5-minute cache for stable system prompt
- Action: Update API calls to include `cache_control`

**Gap 4: Tool Output Explosion**
- Problem: Large file reads, git logs, web fetches remain in context
- Solution: Observation masking + offload to file store
- Action: Add tool output compressor for outputs >10K tokens

**Gap 5: No Retrieval-Aware Context Assembly**
- Problem: Static context; doesn't adapt to task
- Solution: Just-in-time retrieval from Neo4j + memory stores
- Action: Implement context selector querying for relevant facts

### Implementation Priority

**Phase 1 (Immediate):**
1. Add token counter to every API call
2. Implement sliding window (keep last 10 turns, summarize older)
3. Enable prompt caching for CLAUDE.md + system prompt

**Phase 2 (Short-term):**
1. Observation masking for tool outputs >5K tokens
2. Scratchpad pattern for long reasoning (save to Neo4j)
3. Context selection layer (query Neo4j before building prompt)

**Phase 3 (Medium-term):**
1. Archival memory tier (old turns → summarized facts → Neo4j)
2. Context isolation in agent communication
3. Retrieval caching

**Phase 4 (Long-term):**
1. LLMLingua integration for large system prompts
2. BGE reranking in retrieval pipeline
3. Multi-agent context budget tracking

### Expected Impact
- Cost: -40% API spend (prompt caching + compression)
- Latency: -30% (skip redundant computation)
- Hallucination: -60% (fresh context, no rot)
- Session length: 5x longer before degradation

---

## 12. References

### Anthropic & Claude
- Prompt Caching — platform.claude.com/docs
- Effective Context Engineering for AI Agents — anthropic.com/engineering
- Context Windows — platform.claude.com/docs
- Token Counting — platform.claude.com/docs

### Context Compression
- LLMLingua: Compressing Prompts for Accelerated Inference — llmlingua.com
- Microsoft Research: LLMLingua Innovation
- Long Context In-Context Compression with Gisting — arxiv.org/abs/2504.08934
- Selective Context Compression — github.com/liyucheng09/Selective_Context

### RAG & Retrieval
- Context Architecture: Practical RAG — redhat.com
- Retrieval Augmented Generation Guide — promptingguide.ai
- GraphRAG: Knowledge Graphs for Multi-Hop Reasoning — neo4j.com
- Using LLMs as Rerankers for RAG — fin.ai

### Memory-Augmented Generation
- MemGPT: Towards LLMs as Operating Systems — arxiv.org/abs/2310.08560
- Letta: Building Stateful LLM Agents — docs.letta.com
- Virtual Context Management with MemGPT — leoniemonigatti.com

### Conversation Management
- Context Window Management Strategies — getmaxim.ai
- LLM Chat History Summarization Guide 2025 — mem0.ai
- Extended Conversations 10x with Intelligent Compaction — dev.to
- Scaling LLM Multi-turn RL with Summarization — openreview.net

### Long Context & NIAH
- Needle in a Haystack Test — arize.com
- LLM In-Context Recall is Prompt Dependent — arxiv.org/abs/2404.08865
- NIAH Benchmark Suite — github.com/gkamradt
- In Search of Needles in 11M Haystack — arxiv.org/abs/2402.10790

### Multi-Agent Context
- Agentic Mesh: Super-Contexts — medium.com
- Multi-Agent Systems via ADK — google.github.io/adk-docs
- SAMEP: Secure Protocol — arxiv.org/abs/2507.10562
- MCP & Multi-Agent AI — onereach.ai

### Claude Code & Implementation
- How Claude Code Works — code.claude.com
- Context Management in Claude Code CLI — medium.com
- Managing Claude Code Context — cometapi.com
