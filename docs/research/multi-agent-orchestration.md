# Multi-Agent Orchestration Patterns — Research (2025-2026)

**Date:** 2026-03-03
**Priority:** P1 (Critical)
**Researcher:** pathfinder (web-enabled)
**Relevance:** FalkVelt dispatcher + 4 agents, STAR topology, CONNECTION_DENSITY=0.35

---

## 1. Executive Summary

This research covers 8 major multi-agent orchestration frameworks and their architectural patterns as of 2025-2026. The landscape has consolidated around three dominant approaches: **graph-based workflows** (LangGraph), **role-based orchestration** (CrewAI), and **conversation-based patterns** (AutoGen/AG2). Google's A2A protocol is emerging as a standardization layer for inter-agent communication, complementing MCP for tool access.

Key finding for FalkVelt: the current STAR topology (all paths through coordinator hub) is a known scaling bottleneck. Production systems are moving toward **hybrid topologies** combining lightweight hub orchestration with event-driven pub-sub for agent-to-agent communication. The recommended transition is STAR → Hybrid (hub + pub-sub + conditional graph edges).

---

## 2. Framework Analysis

### 2.1 LangGraph

**Architecture:** Graph-based workflow orchestration built on directed graphs (DAG and cyclic). Nodes are agent functions, edges are transitions (conditional or unconditional).

**Core concepts:**
- **StateGraph** — typed state passed between nodes, reducers for merging
- **Conditional edges** — route based on state (e.g., tool call results → different nodes)
- **Checkpointing** — durable execution with PostgresSaver, snapshot at every node
- **Human-in-the-loop** — interrupt before/after specific nodes, approve/edit state
- **Subgraphs** — nested graphs for modular agent teams

**Communication:** State-passing. Agents don't communicate directly — they read/write shared state. The graph structure defines who can influence whom.

**Task delegation:** Supervisor node routes to worker nodes based on state. No peer-to-peer by default — requires explicit edges.

**Error handling:** Built-in retry (with exponential backoff + jitter), node-level error boundaries, fallback nodes. Checkpointing enables resume from last successful node.

**Key insight:** LangChain publicly shifted: "Use LangGraph for agents, not LangChain." 600-800 companies expected in production by end 2025.

**Pros:** Fine-grained control, durable execution, visual debugging, cyclic graphs for iterative agents
**Cons:** Complex for simple use cases, learning curve, Python-centric

### 2.2 CrewAI

**Architecture:** Role-based agent orchestration. Each agent has a role, goal, backstory, and set of tools.

**Core concepts:**
- **Agents** — role + goal + backstory (persona)
- **Tasks** — units of work assigned to agents, with expected output format
- **Crew** — team of agents with a process type
- **Process types:** Sequential (waterfall), Hierarchical (manager delegates), Consensual (agents vote)

**Communication:** Message-based between agents in a crew. Manager agent coordinates in hierarchical mode.

**Task delegation:** Manager agent assigns tasks based on agent capabilities. Autonomous task assignment via capability matching.

**Memory:** Built-in short-term (conversation), long-term (persistent), and entity memory (knowledge about entities).

**Pros:** Intuitive role-based design, low barrier to entry, built-in memory
**Cons:** Less control than LangGraph, limited cyclic workflows, opinionated architecture

### 2.3 AutoGen / AG2

**Architecture:** Conversation-based multi-agent framework. Agents interact via conversations (not state or task assignment).

**Core concepts:**
- **ConversableAgent** — base class, all agents can converse
- **GroupChat** — multiple agents in a shared conversation
- **GroupChatManager** — selects next speaker (round-robin, random, or LLM-driven)
- **Nested chats** — hierarchical conversation trees
- **Teachable agents** — learn from conversations across sessions

**AG2 v0.9 evolution:**
- Unified Group Chat architecture
- **AutoPattern** — LLM-driven speaker selection (most flexible)
- **RoundRobinPattern**, **SelectorPattern**, **DefaultPattern**
- Better observability and debugging

**Communication:** Conversational message passing. All agents see the shared conversation (or filtered subsets).

**Pros:** Natural conversation flow, flexible speaker selection, teachable agents
**Cons:** Hard to control execution order, conversation can drift, high token usage

### 2.4 Claude Agent SDK (Anthropic)

**Architecture:** Subagent-based orchestration. Parent agent spawns subagents for parallelization and isolated context.

**Core concepts:**
- **Agent teams** — parallel subagents with isolated context windows
- **Tool use orchestration** — structured tool calls with validation
- **Multi-turn conversations** — maintained conversation state
- **Context isolation** — each subagent has its own context window (protects parent from context explosion)

**Communication:** Parent-child only. Subagents return results to parent. No peer-to-peer communication between subagents.

**Key pattern:** Fan-out / fan-in. Parent spawns multiple subagents in parallel, collects results, synthesizes.

**Pros:** Clean context isolation, natural parallelization, simple mental model
**Cons:** No peer-to-peer (hub-and-spoke by design), parent is bottleneck

### 2.5 OpenAI Swarm (→ Agents SDK)

**Architecture:** Lightweight agent handoffs. Agents are functions with instructions + tools. Handoff = transfer conversation to another agent.

**Core concepts:**
- **Agents** — instructions + functions (tools)
- **Handoffs** — transfer control to another agent (warm handoff with full context)
- **Routines** — sequence of steps an agent follows
- **Context variables** — shared mutable state across handoffs

**Communication:** Sequential handoffs. Only one agent is active at a time. Context is passed forward (not backwards).

**Evolved into Agents SDK (2025):** Added guardrails, tracing, multi-agent orchestration patterns beyond simple handoffs.

**Pros:** Extremely simple (< 200 LOC core), easy to understand, debuggable
**Cons:** Sequential only, no parallelism, no cyclic workflows, basic error handling

### 2.6 Microsoft Semantic Kernel

**Architecture:** Plugin-based orchestration with planners. Plugins expose functions, planners compose them into execution plans.

**Core concepts:**
- **Plugins** — collections of functions (native code or LLM prompts)
- **Planners** — automatic function composition (Sequential, Stepwise, Handlebars)
- **Agent orchestration patterns:** Sequential, Concurrent, Group Chat, Magentic-One
- **Multi-agent support** — AgentGroupChat, AgentChannel abstractions

**Communication:** Through kernel (shared context). Agents access shared chat history.

**Pros:** Enterprise-grade, multi-language (C#, Python, Java), strong Microsoft integration
**Cons:** Heavy framework, complex planner behavior, enterprise-oriented

### 2.7 Google A2A Protocol

**Architecture:** Standardized inter-agent communication protocol. HTTP/SSE/JSON-RPC based. Donated to Linux Foundation.

**Core concepts:**
- **Agent Cards** — JSON metadata describing agent capabilities (like MCP tool listings)
- **Tasks** — unit of work with lifecycle (submitted → working → completed/failed)
- **Messages** — communication within tasks
- **Parts** — content within messages (text, file, data)
- **Streaming** — SSE for long-running tasks

**Key properties:**
- Complementary to MCP (A2A = agent↔agent, MCP = agent↔tool)
- 150+ organizations supporting
- Built on existing web standards
- Supports opaque agents (don't need to expose internals)

**Pros:** Standard protocol, vendor-neutral, web-native, growing ecosystem
**Cons:** Early stage, limited production deployments, overhead for simple use cases

---

## 3. Orchestration Patterns Taxonomy

### 3.1 Supervisor (Hub-and-Spoke / STAR)

```
        Supervisor
       /    |    \
    Agent  Agent  Agent
```

- Centralized decision-making
- Supervisor routes tasks, collects results
- **Used by:** Claude Agent SDK, Swarm (implicit), LangGraph (supervisor node)
- **Pros:** Simple, predictable, easy to debug
- **Cons:** Bottleneck at supervisor, context explosion, single point of failure
- **Scale limit:** ~10-30 agents before context/latency degrades

### 3.2 Hierarchical

```
     Manager
    /       \
  Lead      Lead
  / \       / \
Agent Agent Agent Agent
```

- Multi-level supervision
- Managers delegate to leads, leads delegate to agents
- **Used by:** CrewAI (hierarchical process), Semantic Kernel (nested agents)
- **Pros:** Scales better than flat STAR, domain separation
- **Cons:** Latency from multiple hops, complex error propagation

### 3.3 Peer-to-Peer / Mesh

```
Agent --- Agent
  |    X    |
Agent --- Agent
```

- Direct agent-to-agent communication
- **Used by:** AutoGen (group chat), A2A protocol
- **Pros:** No bottleneck, agents can collaborate directly
- **Cons:** O(n²) communication complexity, hard to control/debug

### 3.4 Event-Driven Pub-Sub

```
Agent → [Topic A] → Agent
Agent → [Topic B] → Agent, Agent
```

- Message broker mediates communication
- Agents publish events, subscribe to topics
- **Used by:** Kafka/NATS-based systems, HiveMQ for IoT agents
- **Pros:** O(n) connections, decoupled, scalable
- **Cons:** Eventual consistency, harder to reason about ordering

### 3.5 Blackboard

```
Agent ↔ [Shared Memory / Blackboard] ↔ Agent
```

- Shared memory space all agents read/write
- Agents autonomously check blackboard and contribute
- **Research finding:** 13-57% better end-to-end success vs sequential/hierarchical in recent studies
- **Pros:** Agents act autonomously, natural for iterative refinement
- **Cons:** Concurrency issues, hard to attribute contributions

### 3.6 Swarm / Marketplace

```
[Task Pool] ← Agent (bids)
             ← Agent (bids)
             ← Agent (bids)
```

- Agents bid on tasks based on capability/availability
- Market mechanism allocates work
- **Used by:** Research systems, some CrewAI patterns
- **Pros:** Dynamic load balancing, capability-driven allocation
- **Cons:** Complex bidding logic, potential starvation

---

## 4. Communication Patterns

### 4.1 State Passing (LangGraph style)
- Typed state flows through graph edges
- Reducers handle state conflicts
- Best for: structured workflows with clear data flow

### 4.2 Message Passing (AutoGen / Exchange style)
- Agents send/receive messages
- Conversation history as shared context
- Best for: flexible, emergent collaboration

### 4.3 Shared Memory / Blackboard
- Central data store all agents access
- Agents read context, write contributions
- Best for: iterative refinement, many independent contributions

### 4.4 Event-Driven
- Publish/subscribe with topic routing
- Decoupled producers and consumers
- Best for: large-scale, loosely coupled agent systems

### 4.5 Hybrid (Recommended for FalkVelt)
- Coordinator hub for orchestration decisions (keep dispatcher)
- Event bus for agent notifications (replace direct exchange)
- Shared state for collaborative tasks (use Neo4j as blackboard)
- Direct handoffs for tight agent coupling (specific workflow edges)

---

## 5. State Management & Persistence

| Approach | Framework | Durability | Complexity |
|----------|-----------|------------|------------|
| In-memory state | Swarm, basic LangGraph | Session only | Low |
| Checkpointing (PostgresSaver) | LangGraph | Across sessions | Medium |
| Conversation memory | AutoGen, CrewAI | Configurable | Medium |
| External DB (Redis/Postgres) | Semantic Kernel | Persistent | High |
| Graph-based state | Neo4j integration | Persistent, queryable | High |

**Key insight:** Production systems use tiered memory:
- **Working memory** — current conversation context (fast, ephemeral)
- **Short-term memory** — session-scoped checkpoints (minutes to hours)
- **Long-term memory** — persistent store (days to months)
- **Episodic memory** — specific interaction traces (for learning)

---

## 6. Error Handling & Recovery

### Classification
1. **Transient errors** — API timeouts, rate limits → retry with backoff
2. **Semantic errors** — wrong tool use, bad parameters → self-correction loop
3. **Structural errors** — agent can't complete task → escalate or reassign
4. **Catastrophic errors** — entire workflow fails → checkpoint recovery

### Patterns
- **Retry with exponential backoff + jitter** — standard for transient errors
- **Self-correction loop** — agent reviews own output, retries with feedback
- **Fallback nodes** — alternative agent/path when primary fails
- **Checkpoint recovery** — resume from last successful state
- **Supervisor escalation** — failed agent reports to supervisor for reassignment
- **Circuit breaker** — stop retrying after N failures, mark agent as degraded

### Multi-agent specific
- **Role reassignment on failure** — another agent takes over failed agent's task
- **Consensus validation** — multiple agents verify critical outputs
- **Graceful degradation** — system continues with reduced capability

---

## 7. Relevance to FalkVelt

### Current State
- STAR topology (dispatcher → 4 agents)
- CONNECTION_DENSITY = 0.35 (lowest meditation score)
- No agent-to-agent communication
- No shared state beyond Qdrant/Neo4j
- Context isolation via subagents (Claude Agent SDK pattern)

### Recommended Evolution: STAR → Hybrid

**Phase 1 — Enrich existing STAR:**
- Add IMPLEMENTS edges in Neo4j (agents → specs)
- Add GOVERNS edges (specs → protocols)
- This alone should raise CONNECTION_DENSITY to ~0.55

**Phase 2 — Add event-driven layer:**
- Exchange server already exists — use it as lightweight event bus
- Define topics: `task.completed`, `build.new`, `meditation.findings`, `error.critical`
- Agents subscribe to relevant topics (watcher already handles this partially)

**Phase 3 — Introduce conditional graph edges:**
- Dispatcher already classifies T1-T5 — make routing a graph traversal
- Add conditional edges: if T3 + domain=security → engineer + llm-engineer (parallel)
- Enable agent-to-agent delegation (engineer can invoke pathfinder for exploration)

**Phase 4 — Shared state via Neo4j blackboard:**
- Use Neo4j as shared blackboard for collaborative tasks
- Agents write intermediate results as nodes/edges
- Other agents query for context before executing

### Framework Lessons Applied

| Framework Pattern | FalkVelt Adaptation |
|-------------------|---------------------|
| LangGraph conditional edges | Dispatcher routing as graph, not if/else |
| CrewAI role-based delegation | Already have roles — formalize capability matching |
| AutoGen group chat | Could enable for T5 collaborative tasks |
| Swarm handoffs | Engineer → pathfinder handoff for context gathering |
| A2A Agent Cards | Capability map already serves this role — formalize as JSON |
| Blackboard pattern | Neo4j as shared workspace for multi-agent tasks |

### Topology Target

```
Current (STAR):              Target (Hybrid):
    Coordinator                  Coordinator
   / | | \                      / | | \
  P  PM E  LE                 P  PM E  LE
                               |    \ /
                              [Neo4j Blackboard]
                               |
                              [Event Bus (Exchange)]
```

CONNECTION_DENSITY target: 0.35 → 0.70+

---

## 8. References

### Core Frameworks
- LangGraph Multi-Agent Orchestration Guide 2025 — latenode.com
- LangGraph State Management 2025 — sparkco.ai
- CrewAI Platform — crewai.com
- CrewAI Role-Based Orchestration — digitalocean.com
- AG2 v0.9 Group Chat Release — docs.ag2.ai
- AutoGen Multi-Agent Conversation Framework — microsoft.github.io/autogen
- Claude Agent SDK Building Agents — anthropic.com/engineering
- OpenAI Swarm — github.com/openai/swarm
- Semantic Kernel Agent Orchestration — learn.microsoft.com
- A2A Protocol — developers.googleblog.com

### Communication & Topology
- Event-Driven Architecture for AI Agent Communication — hivemq.com
- Event-Driven Multi-Agent System Patterns — confluent.io
- Blackboard Architecture for LLM Systems — arxiv.org/abs/2510.01285
- Multi-Agent Orchestration Pattern Selection — kore.ai
- Scaling LLM Agents (ICLR 2025) — proceedings.iclr.cc

### State & Error Handling
- LangGraph Checkpointing Best Practices 2025 — sparkco.ai
- Agent Retry Logic Deep Dive 2025 — sparkco.ai
- Error Recovery in AI Agents — convogenie.ai
- Multi-Turn Conversations Microsoft Agent Framework — learn.microsoft.com

### Advanced
- Handoff & Escalation Design — bucher-suter.com
- Scaling Agent Systems Research — research.google
- Graph-Theoretic Methods in Multiagent Networks — mdpi.com
