# Yoga Report — 2026-03-03 17:44:33

**Flexibility Score:** 67%
**Poses:** 2 FLOWING / 1 PARTIAL / 0 BLOCKED

---

## Pranayama — FLOWING
**Pipeline:** Memory Write → Vector Retrieve → Graph Search

| Step | Status | Detail |
|------|--------|--------|
| Embedding service (Ollama) reachable | PASS | HTTP 200 |
| Qdrant reachable | PASS | HTTP 200, 88 points |
| Write test record | PASS | ok |
| Vector search retrieves test record | PASS | test record found |
| Graph search executes (fallback OK) | PASS | graph search executed |
| Neo4j memory_fulltext index exists | PASS | index present |
| Cleanup test records from Qdrant | PASS | HTTP 200 |

## Tadasana — PARTIAL
**Pipeline:** Session Start Checks
**Tension point:** Meditation log: no critical (P0) items

| Step | Status | Detail |
|------|--------|--------|
| CLAUDE.md: no _WORKFLOW_NEEDS_INIT marker | PASS | initialized |
| Workflow update check | PASS | [WARN] Could not check for updates (network error). Skipping. |
| Memory search (active tasks blockers) | PASS | 5 results |
| capability-map.md exists | PASS | age 0.0d |
| build-registry.json valid | PASS | 2 builds |
| Session lock create/delete | PASS | ok |
| Exchange server reachable | PASS | HTTP 200 |
| Exchange inbox accessible | PASS | 0 pending messages |
| Meditation log: no critical (P0) items | FAIL | P0:3 P1:6 P2:7 |

## Savasana — FLOWING
**Pipeline:** Exchange Server Pipeline

| Step | Status | Detail |
|------|--------|--------|
| Exchange health check | PASS | HTTP 200 |
| Send test message | PASS | HTTP 201, id=9fb348f8-7d1a-4af8-b1d0-ebd96d51ab6e |
| Test message visible in inbox | PASS | 1 yoga test message(s) found |
| Watcher process running | PASS | pid(s): 24412 |
| Cleanup test messages | PASS | marked 1/1 message(s) as read |

---

**Manual poses** (require coordinator reasoning):
- Vrikshasana (3) — Knowledge graph connectivity review
- Warrior (4) — Protocol conflict analysis
- Lotus (6) — Meditation reflection and integration
