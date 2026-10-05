#!/usr/bin/env bash
# Runs ON the Azure VM over SSH from .github/workflows/deploy.yml.
# Pulls the requested git ref, rebuilds changed images, restarts the stack,
# and fails if any service is not healthy afterwards.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/SmartBanking}"
DEPLOY_REF="${DEPLOY_REF:-main}"

echo "== deploy $DEPLOY_REF to $REPO_DIR"
cd "$REPO_DIR"
git fetch --prune origin
git checkout -q "$DEPLOY_REF"
git pull -q --ff-only origin "$DEPLOY_REF"
echo "== at $(git log -1 --format='%h %s')"

[ -f .env ] || { echo "ERROR: .env missing on the VM (copy .env.example and set GEMINI_API_KEY)"; exit 1; }

echo "== build + start"
docker compose up --build -d --remove-orphans
docker image prune -f >/dev/null

# Release 1: the shared MCP and RAG servers are host processes, never Compose
# services. Restart both on every deploy so they run the code just pulled; the
# containers reach them through host.docker.internal (extra_hosts in compose).
echo "== host MCP + RAG servers"
LOG_DIR="$HOME/smartbank-logs"
mkdir -p "$LOG_DIR"
[ -x .venv/bin/python ] || python3 -m venv .venv \
  || { echo "ERROR: python3 -m venv failed (once on the VM: sudo apt install python3-venv)"; exit 1; }
.venv/bin/pip install -q -r requirements-agentic.txt -r requirements-mcp.txt -r requirements-rag.txt

pkill -f "python -m mcp_server.server" || true
pkill -f "python -m rag_server.server" || true
sleep 2

# Drop the generated corpus and vector index so the RAG server rebuilds them
# from the corpus just pulled; a restart alone keeps serving the old copy.
rm -rf rag_server/data/corpus.jsonl rag_server/data/chroma

# setsid + every stream redirected, so the servers outlive this SSH session.
setsid nohup .venv/bin/python -m mcp_server.server >"$LOG_DIR/mcp.log" 2>&1 </dev/null &
setsid nohup .venv/bin/python -m rag_server.server >"$LOG_DIR/rag.log" 2>&1 </dev/null &

echo "== wait for health"
probe() {  # name url
  for i in $(seq 1 15); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$2" || echo 000)
    if [ "$code" = "200" ]; then echo "PASS $1 -> $2"; return 0; fi
    sleep 4
  done
  echo "FAIL $1 -> $2 (last $code)"; return 1
}
probe home                 http://localhost:3000/
probe accounts-api         http://localhost:5001/api/health
probe loans-api            http://localhost:5002/api/health
probe fraud-api            http://localhost:5003/api/health
probe budgeting-api        http://localhost:5004/api/health
probe transactions-api     http://localhost:5005/api/health
probe accounts-web         http://localhost:3001/
probe loans-web            http://localhost:3002/tabs/loans.html
probe fraud-web            http://localhost:3003/tabs/normal.html
probe budgeting-web        http://localhost:3004/tabs/budgets.html
probe transactions-web     http://localhost:3005/tabs/transactions.html
probe rag-server           http://localhost:8200/health

# MCP answers POSTed JSON-RPC only, so it gets its own probe: tools/list must
# come back with HTTP 200.
mcp_ok=0
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST http://localhost:8100/mcp \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' || echo 000)
  if [ "$code" = "200" ]; then echo "PASS mcp-server -> http://localhost:8100/mcp"; mcp_ok=1; break; fi
  sleep 4
done
[ "$mcp_ok" = 1 ] || { echo "FAIL mcp-server -> http://localhost:8100/mcp (last $code)"; tail -20 "$LOG_DIR/mcp.log"; exit 1; }

echo "== services"
docker compose ps
