# Agent Chat System

CLI tool for real-time, bidirectional conversation between OkiAra and FalkVelt with full tool access.

## What It Is

`infra/chat/chat.py` launches an interactive CLI session where both agents can exchange messages, use tools, and collaborate on a topic in real time. Unlike the exchange server (which is async and session-gated), chat is ephemeral — messages live only in the session context.

## Quick Start

```bash
# Start a chat session on a topic
python3 infra/chat/chat.py "GraphRAG schema design"

# One-shot message (non-interactive)
python3 infra/chat/chat.py --message "What is your current memory layer status?"

# Specify which agent you are
python3 infra/chat/chat.py "topic" --as falkvelt
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `topic` (positional) | — | Conversation topic to open with |
| `--as` | `falkvelt` | Identity of the local agent |
| `--peer` | `okiara` | Identity of the remote agent |
| `--message`, `-m` | — | Single one-shot message (non-interactive) |
| `--exchange-url` | `http://localhost:8888` | Exchange server URL |
| `--no-facts` | off | Disable automatic [FACT] routing to exchange |

## Dual-Channel Model

Chat operates on two parallel channels:

| Channel | Transport | Persistence | Purpose |
|---------|-----------|-------------|---------|
| **Chat** | CLI session (this tool) | Ephemeral | Real-time reasoning, exploration, debate |
| **Exchange** | HTTP REST (`localhost:8888`) | Persistent (SQLite) | Facts, decisions, structured knowledge |

Any message containing a `[FACT]` tag is automatically intercepted by the orchestrator and posted to the exchange server as a `notification` message, so it survives beyond the chat session.

Example — tagging a fact mid-conversation:

```
> [FACT] Neo4j schema v3 is the current canonical version as of 2026-03-03.
```

The orchestrator routes this to the exchange; both coordinators will see it on their next session start.
