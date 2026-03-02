#!/bin/bash
set -euo pipefail

# ============================================================
# Workflow Setup Script
# Deploys: coordinator + subagents + protocols + memory layer
# Prerequisites: Docker, Python 3.9+, Node.js 18+
# ============================================================

WORKSPACE_ROOT="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
step() { echo -e "\n${GREEN}==>${NC} $1"; }

CHECK_ONLY=false
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=true
fi

echo "================================================"
echo "  Workflow Setup"
echo "  Workspace: $WORKSPACE_ROOT"
echo "================================================"

# --- 1. Check prerequisites ---
step "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || fail "Docker not found. Install: https://docs.docker.com/get-docker/"
command -v python3 >/dev/null 2>&1 || fail "Python 3 not found."
command -v node >/dev/null 2>&1 || fail "Node.js not found. Install: https://nodejs.org/"
command -v npx >/dev/null 2>&1 || fail "npx not found (comes with Node.js)."

# Check Python version >= 3.9
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
  fail "Python 3.9+ required (found $PY_VER)"
fi
ok "Python $PY_VER"

# Check uvx (optional but used by MCP servers)
if command -v uvx >/dev/null 2>&1; then
  ok "uvx found"
else
  warn "uvx not found. Some MCP servers (neo4j, qdrant, semgrep) need it."
  warn "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

ok "All critical prerequisites met"

# --- 2. Install Python dependencies ---
if ! $CHECK_ONLY; then
  step "Installing Python dependencies..."

  if [ ! -d "$WORKSPACE_ROOT/.venv" ]; then
    python3 -m venv "$WORKSPACE_ROOT/.venv"
    ok "Virtual environment created"
  fi
  source "$WORKSPACE_ROOT/.venv/bin/activate"
  python3 -m pip install --quiet requests fastembed
  ok "requests + fastembed installed (in .venv)"
fi

# --- 3. Setup secrets ---
if ! $CHECK_ONLY; then
  step "Setting up secrets..."

  if [ ! -f "$WORKSPACE_ROOT/secrets/.env" ]; then
    cp "$WORKSPACE_ROOT/secrets/.env.template" "$WORKSPACE_ROOT/secrets/.env"
    warn "Created secrets/.env from template"
    warn "Edit secrets/.env and fill in your API keys before using MCP servers"
  else
    ok "secrets/.env already exists"
  fi
fi

# Load .env for port values
if [ -f "$WORKSPACE_ROOT/secrets/.env" ]; then
  set -a; . "$WORKSPACE_ROOT/secrets/.env"; set +a
fi

QDRANT_PORT=${QDRANT_PORT:-6333}
NEO4J_HTTP_PORT=${NEO4J_HTTP_PORT:-7474}
NEO4J_BOLT_PORT=${NEO4J_BOLT_PORT:-7687}

# Check ports
PORT_CONFLICT=false
for port in $QDRANT_PORT $NEO4J_HTTP_PORT $NEO4J_BOLT_PORT; do
  if lsof -i :$port >/dev/null 2>&1; then
    warn "Port $port is already in use"
    PORT_CONFLICT=true
  fi
done
if $PORT_CONFLICT; then
  warn "Edit port values in secrets/.env and re-run setup"
fi

# --- 4. Patch mcp.json with workspace path ---
if ! $CHECK_ONLY; then
  step "Configuring MCP servers..."

  if grep -q "__WORKSPACE_ROOT__" "$WORKSPACE_ROOT/mcp/mcp.json"; then
    # Escape path for sed (handle slashes)
    ESCAPED_ROOT=$(echo "$WORKSPACE_ROOT" | sed 's/[\/&]/\\&/g')
    sed -i.bak "s|__WORKSPACE_ROOT__|$ESCAPED_ROOT|g" "$WORKSPACE_ROOT/mcp/mcp.json"
    rm -f "$WORKSPACE_ROOT/mcp/mcp.json.bak"
    ok "mcp.json paths configured"
  else
    ok "mcp.json already configured"
  fi

  # --- 5. Make scripts executable ---
  chmod +x "$WORKSPACE_ROOT/mcp/with-env.sh"
  ok "with-env.sh is executable"

  # --- 6. Create .mcp.json symlink ---
  step "Creating MCP symlink..."

  if [ ! -e "$WORKSPACE_ROOT/.mcp.json" ]; then
    ln -s "$WORKSPACE_ROOT/mcp/mcp.json" "$WORKSPACE_ROOT/.mcp.json"
    ok "Symlink: .mcp.json -> mcp/mcp.json"
  else
    ok ".mcp.json already exists"
  fi

  # --- 7. Start Docker services ---
  step "Starting infrastructure (Qdrant + Neo4j)..."

  if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon not running. Start Docker and re-run this script."
  fi

  cd "$WORKSPACE_ROOT/infra"
  docker compose up -d
  cd "$WORKSPACE_ROOT"

  # Wait for services
  echo "Waiting for services to become healthy..."
  for i in $(seq 1 30); do
    QDRANT_OK=false
    NEO4J_OK=false

    if curl -sf "http://localhost:$QDRANT_PORT/readyz" >/dev/null 2>&1; then
      QDRANT_OK=true
    fi

    NEO4J_PASS=${NEO4J_PASSWORD:-"workflow"}
    NEO4J_CONTAINER=${NEO4J_CONTAINER:-"workflow-neo4j"}
    if docker exec "$NEO4J_CONTAINER" cypher-shell -u neo4j -p "$NEO4J_PASS" "RETURN 1" >/dev/null 2>&1; then
      NEO4J_OK=true
    fi

    if $QDRANT_OK && $NEO4J_OK; then
      break
    fi

    sleep 2
  done

  if $QDRANT_OK; then ok "Qdrant is ready (port $QDRANT_PORT)"; else warn "Qdrant not ready yet"; fi
  if $NEO4J_OK; then ok "Neo4j is ready (port $NEO4J_BOLT_PORT)"; else warn "Neo4j not ready yet"; fi

  # --- 8. Create Qdrant collection ---
  step "Creating Qdrant collection..."

  COLLECTION="workflow_memory"
  EXISTS=$(curl -sf "http://localhost:$QDRANT_PORT/collections/$COLLECTION" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('status',''))" 2>/dev/null || echo "")

  if [ "$EXISTS" = "green" ]; then
    ok "Collection '$COLLECTION' already exists"
  else
    curl -sf -X PUT "http://localhost:$QDRANT_PORT/collections/$COLLECTION" \
      -H "Content-Type: application/json" \
      -d '{
        "vectors": {
          "size": 384,
          "distance": "Cosine"
        }
      }' >/dev/null 2>&1
    ok "Collection '$COLLECTION' created (384 dims, cosine)"
  fi

fi

# --- 10. Summary ---
echo ""
echo "================================================"
echo -e "  ${GREEN}Setup complete!${NC}"
echo "================================================"
echo ""
echo "Infrastructure:"
echo "  Qdrant:  http://localhost:$QDRANT_PORT"
echo "  Neo4j:   http://localhost:$NEO4J_HTTP_PORT (bolt://localhost:$NEO4J_BOLT_PORT)"
echo ""
echo "Memory scripts:"
echo "  Search:  python3 memory/scripts/memory_search.py \"query\""
echo "  Write:   python3 memory/scripts/memory_write.py '[{\"text\":\"...\"}]'"
echo ""
echo "Next steps:"
echo "  1. Edit secrets/.env — fill in API keys"
echo "  2. Edit CLAUDE.md — configure ## Project section"
echo "  3. Open this directory in Claude Code"
echo "  4. The workflow is active: coordinator + 8 subagents + protocols"
echo ""
