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
probe transactions-api     http://localhost:5260/api/transactions
probe accounts-web         http://localhost:3001/
probe loans-web            http://localhost:3002/tabs/normal.html
probe fraud-web            http://localhost:3003/tabs/normal.html
probe budgeting-web        http://localhost:3004/tabs/budgets.html

echo "== services"
docker compose ps
