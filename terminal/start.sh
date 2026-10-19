#!/usr/bin/env bash
# K Terminal: build and start everything with Docker (macOS, Linux).
#
#   cd terminal
#   ./start.sh            # first run: creates secrets, builds, starts, offers to create your login
#   ./start.sh            # later runs: rebuilds what changed and restarts; data is kept
#
# Stop with:  docker compose --project-directory deploy -f deploy/docker-compose.yml stop
# Windows: use start.ps1. Step-by-step guide: docs/18-quick-start.md.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop, wait until it says it is running, then run ./start.sh again." >&2
  exit 1
fi

# Secrets live only on this machine (deploy/secrets is never committed).
mkdir -p deploy/secrets
chmod 700 deploy/secrets
new_secret() {
  local file="deploy/secrets/$1"
  if [ ! -f "$file" ]; then
    od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > "$file"
    chmod 444 "$file"
    echo "created $file"
  fi
}
new_secret postgres_password
new_secret session_secret
if [ ! -f deploy/secrets/oanda_token ]; then
  : > deploy/secrets/oanda_token
  chmod 644 deploy/secrets/oanda_token
  echo "created deploy/secrets/oanda_token (empty: paste your OANDA token into it to trade FX, gold and indices)"
fi

compose() {
  if [ -f .env ]; then
    docker compose --project-directory deploy --env-file .env -f deploy/docker-compose.yml "$@"
  else
    docker compose --project-directory deploy -f deploy/docker-compose.yml "$@"
  fi
}

echo "Building and starting (the first time takes a few minutes)..."
compose up -d --build

echo "Waiting for the terminal to answer..."
for _ in $(seq 1 90); do
  if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)" </dev/null >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ -z "${ready:-}" ]; then
  echo "The terminal did not become ready. Its logs:" >&2
  compose logs --tail=40 api migrate >&2
  exit 1
fi

if compose exec -T api kterminal users list </dev/null 2>/dev/null | grep -q "^no users yet"; then
  echo
  echo "Create your dashboard login (password: at least 12 characters)."
  read -r -p "Username (a-z, 0-9, '.', '_', '-'): " username
  if [ -n "$username" ]; then
    compose exec api kterminal users add "$username" --role ADMIN || true
  fi
fi

echo
echo "K Terminal is running: open https://localhost in your browser."
echo "Your browser will warn about the certificate the first time (it is made on this"
echo "computer): choose Advanced, then continue to localhost."
