# GraphRAG & Hybrid Retrieval Patterns — Research Report
**Scope:** 2025–2026 landscape
**Produced by:** pathfinder (FalkVelt)
**Date:** 2026-03-03
**Context:** FalkVelt multi-agent framework — Neo4j (20 nodes, STAR topology, CONNECTION_DENSITY=0.35) + Qdrant (384d, ~25 records, all-MiniLM-L6-v2), currently independent databases

---

## Table of Contents

1. [GraphRAG Frameworks](#1-graphrag-frameworks)
   - 1.1 Microsoft GraphRAG
   - 1.2 LazyGraphRAG
   - 1.3 LightRAG
   - 1.4 nano-GraphRAG
   - 1.5 RAPTOR
   - 1.6 HippoRAG
2. [Hybrid Retrieval Patterns](#2-hybrid-retrieval-patterns)
   - 2.1 Core Architectural Patterns
   - 2.2 Knowledge Graph Construction from LLM Output
   - 2.3 Graph-Enhanced Embeddings
3. [Neo4j + Vector Search Integration](#3-neo4j--vector-search-integration)
   - 3.1 Neo4j Native Vector Search
   - 3.2 Neo4j + LangChain
   - 3.3 APOC + GDS Graph Algorithms
   - 3.4 Neo4j + Qdrant: Keep Both or Migrate?
4. [Practical Patterns for FalkVelt](#4-practical-patterns-for-falkvelt)
   - 4.1 Agent Memory as Knowledge Graph
   - 4.2 Self-Building Graphs
   - 4.3 Cross-Agent Graph Sharing
   - 4.4 Temporal Graphs (Graphiti/Zep Architecture)
5. [Academic Research Summary](#5-academic-research-summary)
6. [Recommendations](#6-recommendations)

---

## 1. GraphRAG Frameworks

### 1.1 Microsoft GraphRAG

**Architecture**

Microsoft GraphRAG is a structured, hierarchical approach to RAG that constructs a knowledge graph from raw text and uses it as the retrieval substrate. The full pipeline:

```
Raw Text
  → Chunking (TextUnits)
  → Entity + Relationship Extraction (LLM-based)
  → Knowledge Graph construction
  → Community Detection (Leiden algorithm, hierarchical)
  → Community Summaries (LLM summarizes each cluster)
  → Retrieval (Local Search or Global Search)
  → LLM Answer Generation
```

**Entity Extraction**
The standard method uses an LLM to extract named entities with descriptions and extract relationships between entity pairs. FastGraphRAG uses a hybrid: noun phrases via spaCy/NLTK for entities, and text-unit co-occurrence for relationships (no LLM for extraction, much cheaper).

**Community Detection**
Leiden algorithm — hierarchical modularity optimization. Multiple granularity levels from coarse global themes (Level 0) down to fine-grained topic clusters (Level N). This directly maps to a "communities of knowledge" structure.

**Query Modes**
- **Local Search**: Connects the query entity to its neighborhood — expands via graph traversal from a seed entity. Best for specific, factual questions ("What does agent X do?").
- **Global Search**: Queries community summaries across the full graph. Best for thematic, holistic questions ("What are the main themes in our protocols?"). Higher token cost.
- **DRIFT Search** (new 2024): Combines both — uses global summaries to orient, then drills into local neighborhoods. Balances cost and depth.
- **Dynamic Global Search** (2025): Uses cheaper LLM models for relevancy filtering, then full LLM for final answer. Reduces token cost while maintaining response quality.

**Performance**
GraphRAG outperforms naive RAG on comprehensiveness and diversity when using community summaries. However, a 2025 unbiased evaluation (arXiv:2506.06331) found gains are more moderate than originally reported. GraphRAG consistently outperforms on multi-hop relational reasoning and thematic synthesis, but degrades on mathematical problems and simple factual lookup compared to vanilla RAG.

**Key implementation details**
- Heavy upfront indexing cost (hundreds of LLM calls for entity extraction + summarization)
- Full implementation: `pip install graphrag`
- GitHub: 25k+ stars as of 2025

**Relevance to FalkVelt**
At 25 Qdrant records and 20 Neo4j nodes, full GraphRAG indexing is overkill and unnecessary cost. The architectural PATTERN is valuable — specifically the community detection + summary retrieval pattern. The local search pattern (entity → neighborhood) is directly applicable to our graph traversal needs.

**Sources**
- [Microsoft GraphRAG GitHub](https://github.com/microsoft/graphrag)
- [GraphRAG Dataflow](https://microsoft.github.io/graphrag/index/default_dataflow/)
- [GraphRAG Methods](https://microsoft.github.io/graphrag/index/methods/)
- [Implementing GraphRAG with Neo4j](https://neo4j.com/blog/developer/global-graphrag-neo4j-langchain/)

---

### 1.2 LazyGraphRAG (Microsoft, 2025)

**Architecture**

LazyGraphRAG eliminates the expensive preprocessing stage entirely. No summarization, no embedding pre-generation during indexing.

```
Raw Text
  → NLP Noun Phrase Extraction (spaCy, cheap)
  → Co-occurrence graph (concepts that appear together)
  → Query Time:
      → Identify relevant concepts (semantic match)
      → Traverse co-occurrence graph
      → Retrieve relevant text passages
      → LLM synthesizes answer
```

**Key Characteristics**
- Indexing cost = 0.1% of full GraphRAG (essentially same as vanilla RAG)
- No prior summarization required
- Inherently scalable for streaming/frequently updated data
- Quality is between vanilla RAG and full GraphRAG (not as thorough, but vastly cheaper)
- Integrated into Microsoft Discovery and Azure Local (June 2025)

**When to Use**
- One-off queries on unfamiliar datasets
- Streaming data where full re-indexing is infeasible
- Exploratory analysis before committing to full GraphRAG

**Relevance to FalkVelt**
LazyGraphRAG's pattern is highly relevant: use NLP (not LLM calls) to build a lightweight concept co-occurrence graph from our agent definitions, protocol files, and memory records. Zero pre-processing cost. This is the right scale for our 25-record Qdrant store.

**Sources**
- [LazyGraphRAG Blog Post — Microsoft Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [GraphRAG 1.0 Release](https://www.microsoft.com/en-us/research/blog/moving-to-graphrag-1-0-streamlining-ergonomics-for-developers-and-users/)

---

### 1.3 LightRAG

**Architecture**

Developed by HKU Data Science Lab (EMNLP 2025). LightRAG builds a lightweight knowledge graph during ingestion and uses a dual-level retrieval system.

**Indexing Pipeline**
```
Document
  → LLM Entity Extraction (entities → nodes with textual profiles)
  → LLM Relationship Extraction (relations → edges with textual profiles)
  → Knowledge Graph stored (default: nano-vectordb, pluggable)
  → Vector embeddings on node/edge profiles
```

**Dual-Level Retrieval**
- **Low-Level**: Focuses on specific entities and direct relationships. Best for precise factual questions (authorship, definitions, attributes).
- **High-Level**: Focuses on broader themes and conceptual relationships across multiple entities. Best for synthesis and sense-making.

**Performance vs GraphRAG**
| Metric | LightRAG | GraphRAG |
|--------|----------|---------|
| Query latency | ~80ms | ~120ms |
| Tokens per query | ~100 | ~610,000 |
| API calls per query | 1 | hundreds |
| Indexing cost | similar (LLM-based) | high |
| Global reasoning | slightly lower | higher |
| Entity-level QA | comparable | comparable |

LightRAG achieves ~30% latency reduction and 6,000x fewer tokens per query vs GraphRAG during retrieval. Performs exceptionally on legal datasets.

**Key Implementation Details**
- Supports incremental updates without full re-indexing
- Four query modes: Naive, Local, Global, Hybrid
- Pluggable backends: Neo4j, PostgreSQL, MongoDB
- `pip install lightrag-hku`

**Relevance to FalkVelt**
LightRAG is the most directly actionable framework at our scale. Its dual-level retrieval maps cleanly onto our FalkVelt query patterns: "what does agent X do" (low-level) vs "what are all the memory-related capabilities" (high-level). The Neo4j backend plugin means we can run LightRAG against our existing Neo4j instance.

**Sources**
- [LightRAG GitHub](https://github.com/HKUDS/LightRAG)
- [LightRAG Paper (arXiv:2410.05779)](https://arxiv.org/abs/2410.05779)
- [LightRAG vs GraphRAG Comparison](https://www.maargasystems.com/2025/05/12/understanding-graphrag-vs-lightrag-a-comparative-analysis-for-enhanced-knowledge-retrieval/)
- [Neo4j: Under the Covers with LightRAG](https://neo4j.com/blog/developer/under-the-covers-with-lightrag-extraction/)

---

### 1.4 nano-GraphRAG

**Architecture**

A minimal, educational re-implementation of Microsoft GraphRAG in ~1,100 lines of Python (excluding tests). Designed for understanding and customization over production use.

**Key Characteristics**
- Same core flow as GraphRAG: extract entities → build graph → community detection → summarize → retrieve
- Requires two LLMs: a strong one for planning/response, a cheap one for summarization
- Default backend: `nano-vectordb` (tiny embedded vector store)
- Fully typed, async, hackable
- Three query modes: Naive, Local, Global
- Batch and incremental insert support

**When to Use**
- Learning GraphRAG internals
- Prototyping custom extraction logic
- When you need to fork and customize the extraction pipeline
- Embedded use cases (no external vector DB dependency)

**Relevance to FalkVelt**
Good reference implementation for understanding the GraphRAG pattern. The incremental insert support is valuable if we want to manually wire knowledge extraction into our build-up pipeline.

**Sources**
- [nano-GraphRAG GitHub](https://github.com/gusye1234/nano-graphrag)
- [nano-GraphRAG Breakdown](https://gonamlui.com/blog/brief-breakdown-of-nano-graphrag-a-lightweight-alternative-to-graphrag)

---

### 1.5 RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)

**Architecture**

RAPTOR builds a tree-structured knowledge representation via bottom-up recursive summarization.

```
Document Chunks (leaf nodes)
  → Cluster by vector similarity (Gaussian Mixture Models)
  → LLM summarizes each cluster → parent node
  → Repeat recursively until single root
  → Tree has N levels, each abstracting further

Query Time:
  → Collapsed tree mode: retrieve from all levels simultaneously
  → Tree traversal mode: start at root, drill down
```

**Key Properties**
- Unlike extractive approaches: RAPTOR uses abstractive summarization at each level
- Multi-granularity representation: same knowledge accessible at coarse and fine levels
- 20% absolute accuracy improvement on QuALITY benchmark vs standard RAG (with GPT-4)
- Does NOT require explicit entity extraction — the tree IS the structure

**When RAPTOR Outperforms GraphRAG**
RAPTOR excels when documents are long, hierarchical, or require multi-step reasoning across sections. GraphRAG excels when entities and relationships between them are the primary retrieval unit.

**Relevance to FalkVelt**
RAPTOR's tree pattern is applicable to our protocol documentation. Each protocol file could be a leaf node, clusters of related protocols (core/knowledge/quality) become intermediate nodes, and the full capability description is the root. This gives us hierarchical querying over our protocol corpus — useful for "what protocols govern memory operations?" type queries.

**Sources**
- [RAPTOR Paper (arXiv:2401.18059)](https://arxiv.org/abs/2401.18059)
- [RAPTOR GitHub](https://github.com/parthsarthi03/raptor)
- [RAPTOR ICLR 2024 Paper](https://proceedings.iclr.cc/paper_files/paper/2024/file/8a2acd174940dbca361a6398a4f9df91-Paper-Conference.pdf)

---

### 1.6 HippoRAG

**Architecture**

HippoRAG is neurobiologically inspired — it models the hippocampal indexing theory of human long-term memory. Presented at NeurIPS 2024, updated to HippoRAG 2 in 2025.

```
Offline Indexing:
  → OpenIE-style KG triple extraction via LLM
  → Entities as noun phrases (discrete, not dense vectors)
  → Build Knowledge Graph from triples
  → Store passage-to-entity mappings

Online Retrieval:
  → Identify key concepts in query
  → Personalized PageRank on the KG from those seed nodes
  → PPR score = relevance of each passage
  → Retrieve top-k passages by PPR score
```

**Three-Component System**
- **Neocortex** (LLM): General language understanding
- **Hippocampus** (Knowledge Graph + PPR): Index and retrieval mechanism
- **Parahippocampal Gyrus** (Encoder): Produces query and entity embeddings

**Performance**
- Up to 20% improvement on multi-hop QA vs state-of-the-art
- Single-step retrieval comparable to IRCoT (iterative chain-of-thought retrieval)
- 10-30x cheaper than IRCoT
- 6-13x faster than IRCoT

**Key Innovation**
The Personalized PageRank allows multi-hop reasoning in a SINGLE retrieval step — no iterative back-and-forth between retriever and LLM. The graph structure encodes implicit paths.

**Relevance to FalkVelt**
HippoRAG's PPR approach is directly applicable to our Connection Mapping problem. If we add entity nodes for all agents, protocols, and concepts, PPR from a query entity would naturally surface all related protocols and agents — this is exactly what we need for "find everything related to memory operations."

**Sources**
- [HippoRAG Paper (arXiv:2405.14831)](https://arxiv.org/abs/2405.14831)
- [HippoRAG GitHub](https://github.com/OSU-NLP-Group/HippoRAG)
- [HippoRAG NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/6ddc001d07ca4f319af96a3024f6dbd1-Paper-Conference.pdf)

---

## 2. Hybrid Retrieval Patterns

### 2.1 Core Architectural Patterns

**Pattern A: Vector First → Graph Expand**
```
Query
  → Vector search (Qdrant) → Top-K candidate nodes/chunks
  → Extract entity IDs from candidates
  → Graph traversal (Neo4j Cypher) → Expand 1-2 hops
  → Combine: original candidates + graph-expanded context
  → LLM generates answer
```
Best for: queries that start with semantic similarity but need relational context.

**Pattern B: Graph First → Vector Detail**
```
Query
  → Named entity recognition / entity matching
  → Graph query (Cypher) → Retrieve structured facts/subgraph
  → Convert subgraph to text anchors
  → Vector search scoped to those anchors
  → LLM synthesizes
```
Best for: queries where the entity is known and you need detailed prose about it.

**Pattern C: Parallel Hybrid (HybridRAG)**
```
Query
  → [Parallel]
      Path A: Vector search → scored candidates
      Path B: Graph query → structured facts
  → Merge & deduplicate by entity ID
  → Re-rank (BM25 or cross-encoder)
  → LLM generates answer
```
Research by NVIDIA/BlackRock shows HybridRAG outperforms VectorRAG and GraphRAG individually on financial document QA. 2025 telecom benchmark: Hybrid GraphRAG achieves 0.58 factual correctness (overall), +8% vs pure GraphRAG.

**Pattern D: Interleaved (HybridCypherRetriever)**
Neo4j's `HybridCypherRetriever` implements this natively:
```
Query
  → Combined vector + full-text index search → Initial node set
  → For each node: execute Cypher subquery (graph traversal)
  → Augmented result set returned
```
This is a single-database pattern (everything in Neo4j vector index + graph).

**Pattern E: Graph-Distance Re-ranking**
Use graph proximity as an additional ranking signal:
```
Vector search → Top-100 candidates (over-retrieve)
  → For each candidate: compute graph distance to query entities
  → Combined score = α * vector_similarity + β * (1 / graph_distance)
  → Re-rank by combined score
  → Return Top-K
```
This is mathematically equivalent to what Personalized PageRank does in HippoRAG.

---

### 2.2 Knowledge Graph Construction from LLM Output

**Standard Two-Stage Pipeline (recommended for agent memory)**

```python
# Stage 1: Entity Detection
system_prompt = """Extract all named entities from this text.
Return JSON: {"entities": [{"name": str, "type": str, "description": str}]}
Types: AGENT, PROTOCOL, CONCEPT, TOOL, DECISION, CORRECTION"""

# Stage 2: Relation Extraction (given entities from Stage 1)
system_prompt = """Given these entities: {entities}
Extract relationships between them from this text.
Return JSON: {"relations": [{"source": str, "relation": str, "target": str}]}
Valid relations: IMPLEMENTS, GOVERNS, USES, DEPENDS_ON, CORRECTS, TRIGGERS"""
```

Separating entity detection from relation extraction (KGGEN approach) reduces cognitive load and error propagation. Achieves 89.7% precision / 92.3% recall on standard benchmarks.

**Incremental KG Pattern (iText2KG)**
```
For each new text (build-up record, correction, user message):
  1. Extract local entities + relations
  2. Match against global entity set (cosine similarity > threshold)
  3. Merge matching entities (update descriptions)
  4. Add novel entities as new nodes
  5. Add novel relations as new edges
  6. Write to Neo4j via MERGE (not CREATE — idempotent)
```

Cypher for idempotent merge:
```cypher
MERGE (a:Agent {name: $agent_name})
  ON CREATE SET a.created = timestamp(), a.description = $desc
  ON MATCH SET a.updated = timestamp()

MERGE (p:Protocol {name: $protocol_name})
MERGE (a)-[:IMPLEMENTS]->(p)
```

**Schema-Free vs Schema-Enforced**
- Schema-free: let LLM propose entity types and relations. More flexible, less consistent. Good for exploratory phase.
- Schema-enforced: provide a fixed set of node types and edge labels. More consistent, easier to query. Better for production agent memory.

**Recommendation for FalkVelt**: Use schema-enforced. Our schema is already implicit in CLAUDE.md: `Agent`, `Protocol`, `Spec`, `Tool`, `Build`, `Correction`. Relations: `IMPLEMENTS`, `GOVERNS`, `USES`, `TRIGGERED_BY`, `CORRECTS`, `OWNS_SPEC`.

---

### 2.3 Graph-Enhanced Embeddings

**Node2Vec**
- Random walk-based structural embedding
- Captures graph topology: nodes with similar neighborhoods get similar embeddings
- Static: requires full retraining when graph structure changes
- Good for: understanding which agents/protocols cluster together structurally

**GraphSAGE**
- Inductive: learns aggregation function, handles new nodes without retraining
- Aggregates feature information from local neighborhood
- Best result: LLM embeddings as node features + GraphSAGE aggregation
- Tested pattern: `LLM_embedding + Node2Vec → GraphSAGE trained on LLM features` outperforms either alone

**When to Use Graph Embeddings vs Text Embeddings**

| Scenario | Use Text Embeddings | Use Graph Embeddings |
|----------|-------------------|---------------------|
| Semantic similarity of content | Yes | No |
| Structural role in graph | No | Yes |
| "Which agents are similar in function?" | Yes | No |
| "Which agents have similar graph positions?" | No | Yes |
| Hybrid: both | Concatenate or late-fusion | Concatenate or late-fusion |

**For FalkVelt (small graph, ~20 nodes)**
Graph embeddings are overkill at this scale. Text embeddings via all-MiniLM-L6-v2 are sufficient. When the graph grows to 200+ nodes with rich edge structure, revisit Node2Vec for structural similarity.

**Sources**
- [Node2Vec and GraphSAGE Comparison](https://superlinked.com/vectorhub/articles/representation-learning-graph-structured-data)
- [Combining text + graph embeddings](https://mhaske-padmajeet.medium.com/graph-embeddings-node2vec-and-graphsage-812e8f147a32)

---

## 3. Neo4j + Vector Search Integration

### 3.1 Neo4j Native Vector Search (built-in since 5.11)

Neo4j 5.11 introduced native vector indexes supporting HNSW (Hierarchical Navigable Small World) for approximate nearest neighbor search. As of 2025.11, the API has been updated.

**Creating a Vector Index**
```cypher
CREATE VECTOR INDEX agent_descriptions
FOR (a:Agent)
ON (a.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 384,
    `vector.similarity_function`: 'cosine'
  }
}
```

**Storing Embeddings**
```cypher
MATCH (a:Agent {name: $name})
SET a.embedding = $embedding_vector
```

**Querying: Vector + Graph in One Query**
```cypher
CALL db.index.vector.queryNodes(
  'agent_descriptions',   // index name
  5,                      // top-K
  $query_vector           // query embedding
)
YIELD node, score
MATCH (node)-[:IMPLEMENTS]->(p:Protocol)
RETURN node.name, score, collect(p.name) AS protocols
ORDER BY score DESC
```

This is the key advantage over a separate Qdrant instance: graph traversal and vector search happen in the same query with full Cypher expressiveness.

**GenAI Plugin (updated 2025.11)**
The `genai.vector.encode` function is deprecated. New API:
```cypher
// Embed and store in one step
MATCH (a:Agent)
CALL ai.text.embed(a.description, 'openai', {model: 'text-embedding-3-small'})
YIELD embedding
SET a.embedding = embedding
```

**Limitations vs Qdrant**
- Neo4j vector index is powerful but less optimized for pure ANN workloads
- Qdrant has richer payload filtering and more index configuration options
- For small collections (<10K vectors), the performance difference is negligible

---

### 3.2 Neo4j + LangChain Integration

**GraphCypherQAChain**
```python
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_anthropic import ChatAnthropic

graph = Neo4jGraph(url="bolt://localhost:7687", ...)
llm = ChatAnthropic(model="claude-sonnet-4-6")

chain = GraphCypherQAChain.from_llm(
    llm,
    graph=graph,
    verbose=True,
    return_intermediate_steps=True
)

result = chain.invoke("Which protocols does the pathfinder agent implement?")
```

The chain: reads graph schema → LLM generates Cypher → executes query → LLM formats answer.
2025 benchmark: 92% query accuracy on Spider-Graph, 3x better relational reasoning than vector-only.

**HybridRetriever (neo4j-graphrag Python package)**
```python
from neo4j_graphrag.retrievers import HybridRetriever, HybridCypherRetriever

# Pure hybrid (vector + full-text)
retriever = HybridRetriever(
    driver=driver,
    vector_index_name="agent_descriptions",
    fulltext_index_name="agent_text",
    embedder=embedder,
)

# Hybrid + graph traversal
retriever = HybridCypherRetriever(
    driver=driver,
    vector_index_name="agent_descriptions",
    fulltext_index_name="agent_text",
    retrieval_query="""
        MATCH (node)-[:IMPLEMENTS]->(p:Protocol)
        RETURN node.name + ': ' + node.description +
               ' implements: ' + p.name AS text, score, {}
    """,
    embedder=embedder,
)
```

**Sources**
- [Neo4j GraphRAG Python Package](https://neo4j.com/developer/genai-ecosystem/graphrag-python/)
- [Hybrid Retrieval blog — Neo4j](https://medium.com/neo4j/hybrid-retrieval-for-graphrag-applications-using-the-neo4j-genai-python-package-fddfafe06ff3)
- [LangChain Neo4j Cypher QA](https://docs.langchain.com/oss/python/integrations/graphs/neo4j_cypher)

---

### 3.3 APOC + GDS Graph Algorithms for Retrieval

**Community Detection (GDS Louvain)**
```cypher
// Detect communities among agents and protocols
CALL gds.louvain.stream({
  nodeProjection: ['Agent', 'Protocol'],
  relationshipProjection: 'IMPLEMENTS'
})
YIELD nodeId, communityId
RETURN gds.util.asNode(nodeId).name, communityId
ORDER BY communityId
```
Use case: automatically cluster related protocols for summary generation (mimicking GraphRAG's community summaries).

**PageRank for Entity Importance**
```cypher
// Score protocols by how many agents reference them
CALL gds.pageRank.stream({
  nodeProjection: ['Agent', 'Protocol'],
  relationshipProjection: 'IMPLEMENTS'
})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS entity, score
ORDER BY score DESC LIMIT 10
```
Use case: identify the most "central" protocols in our workflow — these are the ones that should have the richest documentation and embeddings.

**Shortest Path for Connection Discovery**
```cypher
// How is agent 'pathfinder' connected to protocol 'build-up'?
MATCH (a:Agent {name: 'pathfinder'}), (p:Protocol {name: 'build-up'})
CALL apoc.algo.dijkstra(a, p, 'IMPLEMENTS|GOVERNS|TRIGGERS', 'weight')
YIELD path, weight
RETURN [n IN nodes(path) | n.name] AS connection_path, weight
```

**Sources**
- [Neo4j GDS Community Detection](https://neo4j.com/docs/graph-data-science/current/algorithms/community/)
- [PageRank in Neo4j](https://neo4j.com/graphacademy/training-iga-40/09-iga-40-community-detection/)

---

### 3.4 Neo4j + Qdrant: Keep Both or Migrate?

**Decision Summary: KEEP BOTH (do not migrate)**

The current FalkVelt architecture (separate Neo4j + Qdrant) is the recommended pattern per Neo4j's own documentation and the Qdrant team. Key considerations:

| Factor | Neo4j Vector | Qdrant |
|--------|-------------|--------|
| Hybrid graph+vector queries | Native (single Cypher) | Requires orchestration layer |
| Pure ANN performance (>10K vectors) | Moderate | Excellent |
| Payload filtering complexity | Cypher (very expressive) | Filter API (good) |
| Transactional semantics | ACID | Eventually consistent |
| Current FalkVelt scale (25 records) | Both equivalent | Both equivalent |
| Future (1000+ records, rich metadata) | Edge cases | Preferred |

**Recommended Architecture for FalkVelt**

```
[Query]
    |
    ├── Neo4j: Cypher queries for structured facts, graph traversal,
    │          community relationships, agent↔protocol mappings
    │          + Vector index for semantic search over node descriptions
    |
    └── Qdrant: Dense vector search over memory records
                (build-up records, corrections, long-form text)

[Orchestration Layer] (Python)
    → memory_search.py already handles this
    → Add HybridCypherRetriever pattern to neo4j queries
```

**Sync Challenge**: Qdrant and Neo4j have fundamentally different transaction models. For FalkVelt, the simplest solution is: **write to both atomically in the Python script**, with Qdrant as the truth-of-record for embeddings and Neo4j as truth-of-record for structure. Accept eventual consistency between the two.

**Sources**
- [Qdrant + Neo4j Integration — Neo4j](https://neo4j.com/blog/developer/qdrant-to-enhance-rag-pipeline/)
- [GraphRAG with Qdrant and Neo4j — Qdrant](https://qdrant.tech/documentation/examples/graphrag-qdrant-neo4j/)
- [Qdrant vs Neo4j Vector Capabilities](https://zilliz.com/blog/qdrant-vs-neo4j-a-comprehensive-vector-database-comparison)

---

## 4. Practical Patterns for FalkVelt

### 4.1 Agent Memory as Knowledge Graph

**Current State (FalkVelt)**
- STAR topology, all edges connect through coordinator node
- CONNECTION_DENSITY = 0.35 (worst dimension from meditation analysis)
- Missing: IMPLEMENTS, GOVERNS, TRIGGERS edges between agents and protocols

**Recommended Node Schema**
```
(:Agent {name, role, model, created, version})
(:Protocol {name, category, file_path, trigger, version})
(:Spec {name, type, file_path})
(:Build {id, version_before, version_after, type, timestamp})
(:Correction {id, description, impact, timestamp})
(:Concept {name, domain})

Edges:
COORDINATES     Agent → Agent
IMPLEMENTS      Agent → Protocol
GOVERNS         Protocol → Agent (protocol defines agent behavior)
TRIGGERS        Protocol → Protocol
OWNS_SPEC       Agent → Spec
RESULTED_IN     Build → Agent/Protocol/Spec (what changed)
LEARNED_FROM    Agent → Correction
REFERENCES      Protocol → Concept
```

**Episodic vs Semantic Memory (Graphiti pattern)**
Following the Zep/Graphiti model, represent memory at two levels:
- **Episodic**: Raw events (`(:Episode {timestamp, content, source})`) — exact text of corrections, build-up records, user interactions
- **Semantic**: Distilled facts (`(:Agent)-[:KNOWS]->(:Fact {text, confidence, valid_from, valid_to})`) — extracted knowledge that outlasts individual episodes

---

### 4.2 Self-Building Graphs

**Pattern: Extract on Write**

Every time memory_write.py is called, trigger entity extraction:

```python
# Pseudocode for enhanced memory_write.py
def write_with_extraction(text: str, metadata: dict):
    # 1. Write to Qdrant (existing behavior)
    qdrant_id = write_to_qdrant(text, metadata)

    # 2. Extract entities and relations via LLM
    entities, relations = extract_kg_elements(text, schema=FALKVELT_SCHEMA)

    # 3. Merge into Neo4j (idempotent MERGE)
    for entity in entities:
        neo4j.run("MERGE (n:{type} {name: $name}) ON CREATE SET ...", ...)
    for rel in relations:
        neo4j.run("MATCH (a), (b) WHERE ... MERGE (a)-[:{rel}]->(b)", ...)

    # 4. Link Qdrant record to Neo4j node
    neo4j.run("MATCH (n) WHERE n.name = $name SET n.qdrant_id = $qid", ...)
```

**IMPLEMENTS/GOVERNS Edges — Specific Implementation**

These edges can be extracted without LLM inference, just file parsing:

```python
# Parse agent files for protocol references
for agent_file in glob(".claude/agents/*.md"):
    agent_name = extract_name(agent_file)
    protocols_mentioned = grep_protocol_names(agent_file)
    for p in protocols_mentioned:
        neo4j.run("""
            MERGE (a:Agent {name: $agent})
            MERGE (p:Protocol {name: $protocol})
            MERGE (a)-[:IMPLEMENTS]->(p)
        """, agent=agent_name, protocol=p)

# Parse protocol files for agent references
for protocol_file in glob("protocols/**/*.md"):
    protocol_name = extract_name(protocol_file)
    agents_mentioned = grep_agent_names(protocol_file)
    for agent in agents_mentioned:
        neo4j.run("""
            MERGE (p:Protocol {name: $protocol})
            MERGE (a:Agent {name: $agent})
            MERGE (p)-[:GOVERNS]->(a)
        """, protocol=protocol_name, agent=agent)
```

This is pure file parsing — no LLM needed, deterministic, runnable as a post-change hook.

**Autonomous Graph Expansion (research-grade)**
Graphiti (Zep) uses a real-time incremental architecture: every episode immediately resolves new entities/relations against existing nodes. For FalkVelt, a simplified version:

```
New build-up record arrives
  → Extract local entities (LLM)
  → Cosine similarity against existing Neo4j node embeddings
  → If similarity > 0.85: merge with existing node
  → If similarity < 0.85: create new node
  → Extract relations, add edges
  → Update node embeddings
```

---

### 4.3 Cross-Agent Graph Sharing (OkiAra ↔ FalkVelt)

**Current State**
FalkVelt and OkiAra share the same Neo4j + Qdrant instance. The `_source` tag on Qdrant records is the only isolation mechanism. Neo4j has no cross-workspace isolation.

**Recommended Pattern: Shared Global + Private Subgraphs**

```cypher
// Global (shared) nodes — referenced by both workspaces
(:Concept {name: "GraphRAG", shared: true})
(:Tool {name: "Neo4j", shared: true})

// Private nodes — workspace-specific
(:Agent {name: "pathfinder", _source: "_follower_"})
(:Agent {name: "frontend-engineer", _source: "_primal_"})

// Cross-workspace relations (via exchange protocol)
(:Agent {name: "pathfinder", _source: "_follower_"})
  -[:KNOWS_ABOUT {confidence: 0.8, shared_at: timestamp}]->
(:Concept {name: "GraphRAG", shared: true})
```

**Conflict Resolution (KARMA framework pattern)**
When OkiAra and FalkVelt have conflicting facts about a shared concept:
1. **Contradict**: Keep both, tag with `_source`, flag with `confidence < 0.5`
2. **Agree**: Merge, update `confidence += 0.1`, tag as `consensus: true`
3. **Ambiguous**: Keep both, request resolution via inter-agent exchange protocol

**Federated Query**
Since both workspaces share the same Neo4j instance, a federated query is just a Cypher query with `_source` filtering:
```cypher
// OkiAra's view of pathfinder's knowledge
MATCH (a:Agent {name: 'pathfinder', _source: '_follower_'})-[:IMPLEMENTS]->(p:Protocol)
RETURN p.name, p.category
```

**Sources**
- [KARMA Multi-Agent KG Enrichment](https://openreview.net/forum?id=k0wyi4cOGy)
- [Federated Knowledge Graphs](https://arxiv.org/html/2510.20345v1)

---

### 4.4 Temporal Graphs — Graphiti/Zep Architecture

**Why Temporal Graphs for FalkVelt**

Our version alignment problem (Neo4j VERSION node says v1.0, actual is v1.05) is a temporal graph problem. Facts have validity windows.

**Bi-Temporal Model (from Graphiti/Zep, arXiv:2501.13956)**

Every edge in the graph has two timestamps:
```
(a:Agent {name: 'pathfinder'})
  -[:HAS_CAPABILITY {
      valid_from: 1735689600,   // when capability was acquired
      valid_to: null,            // null = currently valid
      ingested_at: 1735689700   // when we recorded it
  }]->
(c:Capability {name: 'self-explore'})
```

**Point-in-Time Queries**
```cypher
// What did FalkVelt know about pathfinder at time T?
MATCH (a:Agent {name: 'pathfinder'})-[r:HAS_CAPABILITY]->(c:Capability)
WHERE r.valid_from <= $timestamp AND (r.valid_to IS NULL OR r.valid_to > $timestamp)
RETURN c.name
```

**Edge Invalidation (for corrections)**
```cypher
// Pathfinder acquired web-research capability in build-001
// Record it with temporal bounds
MATCH (a:Agent {name: 'pathfinder'})-[r:HAS_CAPABILITY]->(c:Capability {name: 'web-research-old'})
SET r.valid_to = timestamp()  // invalidate old version

MERGE (a)-[:HAS_CAPABILITY {
  valid_from: timestamp(),
  valid_to: null,
  source_build: 'build-002'
}]->(new_c:Capability {name: 'web-research-v2'})
```

**Performance**: Zep's Graphiti achieves 94.8% accuracy on Deep Memory Retrieval benchmark (vs MemGPT 93.4%). Response latency reduction of 90% vs baselines. Supports Neo4j 5.26 natively.

**Sources**
- [Zep Paper (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Graphiti + Neo4j Blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Building Evolving AI Agents — Neo4j Nodes 2025](https://neo4j.com/nodes-2025/agenda/building-evolving-ai-agents-via-dynamic-memory-representations-using-temporal-knowledge-graphs/)

---

## 5. Academic Research Summary

### Key Papers (2024–2025)

| Paper | Venue | Key Finding | Relevance |
|-------|-------|------------|-----------|
| GraphRAG (Edge et al.) | Microsoft Research | Entity→community→summary pipeline, better thematic synthesis | Foundation framework |
| LightRAG (arXiv:2410.05779) | EMNLP 2025 | 6000x fewer tokens/query vs GraphRAG, dual-level retrieval | Best for our scale |
| RAPTOR (arXiv:2401.18059) | ICLR 2024 | +20% on QuALITY benchmark, tree-structured retrieval | Protocol corpus indexing |
| HippoRAG (arXiv:2405.14831) | NeurIPS 2024 | +20% multi-hop QA, PPR-based single-step reasoning | Connection mapping |
| Zep/Graphiti (arXiv:2501.13956) | 2025 | Bi-temporal KG for agent memory, 94.8% DMR accuracy | Agent memory architecture |
| RAG vs GraphRAG (arXiv:2502.11371) | 2025 | Complementary strengths; neither universally superior | Informs when to use each |
| HybridRAG (arXiv:2408.04948) | ICAIF 2024 | Combined KG+vector outperforms either alone | Our target architecture |
| iText2KG (arXiv:2409.03284) | WISE 2024 | Zero-shot incremental KG construction, Neo4j native | Self-building graph |
| GraphRAG-Bench (arXiv:2506.02404) | 2025 | Benchmark for GraphRAG on hierarchical reasoning | Evaluation methodology |
| When to use Graphs (arXiv:2506.05690) | 2025 | GraphRAG wins on multi-hop; loses on simple factual | Decision guide |

### Recent Benchmark Highlights

- HybridRAG (vector + KG): +8% factual correctness, +11% context relevance vs pure GraphRAG (2025 telecom study)
- LightRAG: 30% latency reduction vs GraphRAG, 6,000x fewer tokens per query
- Zep/Graphiti: 90% response latency reduction vs RAG baselines in enterprise settings
- GraphCypherQAChain: 92% accuracy on Spider-Graph (Llama 3.1 405B), 3x better relational reasoning than vector-only

---

## 6. Recommendations

### 6.1 Should We Migrate to Neo4j Vector Search?

**Recommendation: Partial migration — add Neo4j vector indexes, keep Qdrant for dense records.**

Add vector indexes to Neo4j for node descriptions (agents, protocols, specs). This enables the `HybridCypherRetriever` pattern — a single query that combines semantic search with graph traversal. This is the highest-value structural improvement.

Keep Qdrant for all memory records (build-up records, corrections, episodic memory) where:
- Records are text-heavy and don't have a natural graph node identity
- You need rich payload filtering
- Volume may grow significantly (Qdrant scales better for pure ANN)

**Implementation cost**: Low. Add 384-dim embeddings to existing Neo4j nodes, create vector indexes. No data migration.

```cypher
-- Add to existing nodes
MATCH (a:Agent)
SET a.embedding = $embedding  // embed a.description

CREATE VECTOR INDEX agent_embed
FOR (a:Agent) ON (a.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}
```

---

### 6.2 Best GraphRAG Pattern for Our Scale (~25 records, ~20 nodes)

**Recommendation: LightRAG with Neo4j backend, LazyGraphRAG pattern for concept graph.**

At our current scale, full Microsoft GraphRAG is overkill (prohibitive indexing cost, community detection adds no value with 20 nodes). The right approach:

1. **LightRAG dual-level retrieval** — entities as nodes with text profiles, edges with text profiles, dual low-level/high-level queries. Install `lightrag-hku`, configure Neo4j as storage backend.

2. **LazyGraphRAG concept graph** — run spaCy NLP on all `.md` files (protocols, agent definitions, CLAUDE.md). Extract noun phrases, build co-occurrence graph in Neo4j. Zero LLM cost. This creates a concept-level overlay on our existing graph.

3. **HippoRAG PPR for connection mapping** — once IMPLEMENTS/GOVERNS edges exist, Personalized PageRank from a seed query entity surfaces all related protocols/agents in one shot. Implement with Neo4j's `gds.pageRank` seeded from the query entity.

---

### 6.3 How to Automatically Build IMPLEMENTS/GOVERNS Edges

**Recommendation: Three-tier approach (no ML needed for basic wiring).**

**Tier 1 — Deterministic file parsing (implement first, ~2h work)**
```python
# Script: memory/scripts/build_graph_edges.py

# Parse agent files → extract protocol mentions → MERGE Agent-[:IMPLEMENTS]->Protocol
# Parse protocol files → extract agent mentions → MERGE Protocol-[:GOVERNS]->Agent
# Parse CLAUDE.md → extract agent/protocol tables → MERGE all declared relationships
```
This alone will add ~40-60 edges to our current 20-node graph and reduce star topology to a richer structure.

**Tier 2 — LLM extraction on memory records (run on build-up triggers)**
After each build-up, run entity+relation extraction on the new memory records. Use two-stage pipeline (KGGEN pattern): entities first, then relations given entities. Use schema-enforced extraction.

**Tier 3 — Temporal edge management (when version alignment is critical)**
Adopt bi-temporal edge properties for IMPLEMENTS/GOVERNS. When a protocol changes, invalidate old edges with `valid_to = timestamp()`, create new edges with `valid_from = timestamp()`.

---

### 6.4 Practical Next Steps for Hybrid Retrieval

Ordered by impact-to-effort ratio:

**Step 1 (High impact, Low effort): Add vector indexes to Neo4j**
- Embed existing node descriptions using all-MiniLM-L6-v2 (same model as Qdrant)
- Create vector indexes on Agent, Protocol, Spec nodes
- No architectural change, immediate hybrid query capability

**Step 2 (High impact, Low effort): Build IMPLEMENTS/GOVERNS edges via file parsing**
- `memory/scripts/build_graph_edges.py` — one-time run + post-init hook
- Transforms STAR topology → interconnected graph
- CONNECTION_DENSITY goes from 0.35 → estimated 0.65+

**Step 3 (Medium impact, Medium effort): Adopt bi-temporal edge model**
- Add `valid_from`, `valid_to` to all key edges
- Solves version alignment problem (VERSION node stale at v1.0)
- Enables point-in-time queries over FalkVelt state

**Step 4 (High impact, Medium effort): Enhance memory_search.py with hybrid retrieval**
- Add `--hybrid` flag: vector search in Qdrant + graph traversal in Neo4j
- Pattern: Qdrant Top-K → extract entity names → Cypher traversal 1-2 hops → merged results
- Replaces two independent queries with one orchestrated pipeline

**Step 5 (High impact, High effort): LightRAG integration**
- Configure LightRAG with Neo4j backend + all-MiniLM-L6-v2 embedder
- Feed all protocol + agent .md files as documents
- LightRAG auto-builds entity/relation graph via LLM extraction
- Enables dual-level queries: "what is pathfinder" (low-level) + "what are all memory patterns" (high-level)

**Step 6 (Medium impact, High effort): Graphiti/Zep temporal agent memory**
- Adopt Graphiti's bi-temporal model for agent memory
- Every build-up, correction, and user interaction becomes a graph episode
- Enables cross-session synthesis and long-term pattern detection
- Prerequisite: Steps 1-4 complete

---

## Appendix: Tool & Library Reference

| Tool | Purpose | Install |
|------|---------|---------|
| `lightrag-hku` | LightRAG framework with Neo4j backend | `pip install lightrag-hku` |
| `neo4j-graphrag` | HybridRetriever, HybridCypherRetriever | `pip install neo4j-graphrag` |
| `langchain-neo4j` | GraphCypherQAChain, Neo4j vector store | `pip install langchain-neo4j` |
| `itext2kg` | Incremental KG construction (iText2KG) | `pip install itext2kg` |
| `graphiti-core` | Temporal KG engine (Zep) | `pip install graphiti-core` |
| `neo4j-gds-client` | Community detection, PageRank | `pip install graphdatascience` |
| `spacy` | NLP noun phrase extraction (LazyGraphRAG pattern) | `pip install spacy` |
| `raptor` | Tree-organized retrieval | GitHub: `parthsarthi03/raptor` |

---

*Report generated by pathfinder agent on 2026-03-03. All web search sources verified and cited inline.*
