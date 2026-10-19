#!/usr/bin/env bash
# K Terminal: build and start everything with Docker (macOS, Linux).
#
#   cd terminal
#   bash start.sh           # first run: creates secrets, builds, starts, asks for your login
#   bash start.sh           # later runs: rebuilds what changed and restarts; data is kept
#   bash start.sh --login   # only create a dashboard login (the terminal must be running)
#
# Run without a keyboard (by an assistant or a scheduler), it never waits for input:
# a missing login is created in a new Terminal window (macOS) or the command is printed.
# Stop with:  docker compose --project-directory deploy -f deploy/docker-compose.yml stop
# Windows: use start.ps1. Step-by-step guide: docs/18-quick-start.md.
set -euo pipefail
cd "$(dirname "$0")"

login_only=0
for arg in "$@"; do
  case "$arg" in
    --login) login_only=1 ;;
    *) echo "unknown option: $arg (the only option is --login)" >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop, wait until it says it is running, then run this again." >&2
  exit 1
fi

compose() {
  if [ -f .env ]; then
    docker compose --project-directory deploy --env-file .env -f deploy/docker-compose.yml "$@"
  else
    docker compose --project-directory deploy -f deploy/docker-compose.yml "$@"
  fi
}

no_users_yet() {
  compose exec -T api kterminal users list </dev/null 2>/dev/null | grep -q "^no users yet"
}

# Ask for the username here (checked before anything runs in Docker), then `users add`
# asks for the password twice. Only the password is asked again after a rejection:
# a prompt after an interactive `docker compose exec` may read a disturbed terminal.
create_login() {
  local attempt username=""
  while :; do
    echo
    echo "Create your dashboard login."
    read -r -p "Username (3-32 characters: a letter first, then letters, digits, '.', '_' or '-'): " username || username=""
    username=$(printf '%s' "$username" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    if [ -z "$username" ]; then
      echo "No login created. Create one later with: bash start.sh --login"
      return 0
    fi
    if printf '%s' "$username" | grep -Eq '^[a-z][a-z0-9_.-]{2,31}$'; then
      break
    fi
    echo "That username is not allowed."
  done
  echo "Now choose a password of at least 12 characters (asked twice; nothing shows while you type)."
  for attempt in 1 2 3; do
    if compose exec api kterminal users add "$username" --role ADMIN; then
      return 0
    fi
  done
  echo "No login created. Try again with: bash start.sh --login"
}

if [ "$login_only" = 1 ]; then
  if ! compose exec -T api true </dev/null >/dev/null 2>&1; then
    echo "The terminal is not running. Start it first: bash start.sh" >&2
    exit 1
  fi
  create_login
  exit 0
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

echo "Building and starting (the first time takes a few minutes)..."
compose up -d --build </dev/null

echo "Waiting for the terminal to answer..."
ready=""
for _ in $(seq 1 90); do
  if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)" </dev/null >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "The terminal did not become ready. Its logs:" >&2
  compose logs --tail=40 api migrate >&2
  exit 1
fi

if no_users_yet; then
  if [ -t 0 ]; then
    create_login
  else
    # No keyboard here: let the person type their own username and password in a
    # window of their own (never through whoever runs this script).
    here=$(pwd)
    case "$here" in *[\'\"\\]*) opened="" ;; *) opened=maybe ;; esac
    if [ -n "$opened" ] && [ "$(uname)" = Darwin ] && command -v osascript >/dev/null 2>&1 \
      && osascript -e "tell application \"Terminal\" to do script \"cd '$here' && bash start.sh --login\"" \
        -e 'tell application "Terminal" to activate' >/dev/null 2>&1; then
      echo "No dashboard login yet: a Terminal window has opened to create it."
    else
      echo "No dashboard login yet. In a terminal window, in this folder, run: bash start.sh --login"
    fi
  fi
fi

echo
echo "K Terminal is running: open https://localhost in your browser."
echo "Your browser will warn about the certificate the first time (it is made on this"
echo "computer): choose Advanced, then continue to localhost."
