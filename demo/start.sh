#!/usr/bin/env bash
# Start the Axolotl demo build on this laptop (macOS or Linux): one command, safe to run
# again. The same steps as demo/start.ps1 and demo/DEMO_BUILD.md, skipping whatever is
# already done. Stop it with demo/stop.sh.
#
#   bash demo/start.sh                     # backend 8000, frontend 5173
#   BACKEND_PORT=8001 FRONTEND_PORT=5174 NO_BROWSER=1 bash demo/start.sh
#   REBUILD_IMAGES=1 bash demo/start.sh    # rebuild all five sandbox images
set -u

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/demo/.logs"
CONTAINER=axolotl-atlas-local

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }
port_in_use() { (command -v lsof >/dev/null && lsof -ti "tcp:$1" -sTCP:LISTEN >/dev/null) || \
                (command -v ss >/dev/null && ss -ltn | grep -q ":$1 "); }
wait_http() {
  local url="$1" deadline=$((SECONDS + $2))
  while [ $SECONDS -lt $deadline ]; do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$url")" = "200" ] && return 0
    sleep 2
  done
  return 1
}

cd "$ROOT" || fail "cannot enter $ROOT"

step "Checking the tools"
for tool in docker uv npm curl; do
  command -v "$tool" >/dev/null || fail "$tool is not installed or not on PATH. See demo/DEMO_BUILD.md."
done
docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Start it, then run this again."
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  port_in_use "$port" && fail "port $port is already in use. Run demo/stop.sh, or set BACKEND_PORT / FRONTEND_PORT."
done

step "Starting the local MongoDB ($CONTAINER)"
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker start "$CONTAINER" >/dev/null || fail "could not start $CONTAINER."
else
  docker run -d --name "$CONTAINER" -p 27017:27017 mongodb/mongodb-atlas-local >/dev/null \
    || fail "could not create $CONTAINER."
fi
deadline=$((SECONDS + 180)); health=""
while [ $SECONDS -lt $deadline ]; do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)"
  [ "$health" = "healthy" ] && break
  sleep 3
done
[ "$health" = "healthy" ] || fail "$CONTAINER did not become healthy within 3 minutes (status: $health)."

step "Checking the sandbox images"
build() {  # tag, then docker build arguments
  local tag="$1"; shift
  if [ -n "${REBUILD_IMAGES:-}" ] || ! docker image inspect "$tag" >/dev/null 2>&1; then
    echo "    building $tag (a few minutes the first time)"
    docker build -q "$@" >/dev/null || fail "building $tag failed."
  fi
}
build axolotl-runner:latest -t axolotl-runner:latest runner/
build axolotl-runner:py2.7 -t axolotl-runner:py2.7 --build-arg PYTHON_VERSION=2.7 --build-arg PYTEST_VERSION=4.6.11 runner/
build axolotl-runner:py3.14 -t axolotl-runner:py3.14 --build-arg PYTHON_VERSION=3.14 --build-arg PYTEST_VERSION=8.4.2 runner/
build axolotl-chess-cases:py27 -f runner/Dockerfile.behaviour --build-arg PYTHON_IMAGE=python:2.7.18-slim -t axolotl-chess-cases:py27 runner/
build axolotl-chess-cases:py314 -f runner/Dockerfile.behaviour --build-arg PYTHON_IMAGE=python:3.14-slim -t axolotl-chess-cases:py314 runner/

step "Checking .env"
if [ ! -f .env ]; then
  cp demo/demo.env.example .env && echo "    created .env from demo/demo.env.example"
fi
grep -Eq '^ARGON_REPLAY_FILE=[^[:space:]]+' .env \
  || fail ".env has no ARGON_REPLAY_FILE, so the demo would call Gemini live. Copy the replay lines from demo/demo.env.example."
! grep -Eq '^MONGODB_URI=mongodb\+srv' .env \
  || fail ".env points MONGODB_URI at a remote cluster. Copy MONGODB_URI from demo/demo.env.example."

step "Installing the backend dependencies"
(cd backend && uv sync -q) || fail "uv sync failed."

step "Loading the team's chess data (skipped if it's already here)"
(cd backend && uv run python -m app.demo_seed load --if-missing) || fail "loading the demo data failed."

step "Installing the frontend dependencies"
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci --no-audit --no-fund) || fail "npm ci failed."
fi

step "Starting the backend (port $BACKEND_PORT) and the frontend (port $FRONTEND_PORT)"
mkdir -p "$LOGS"
# Environment overrides beat .env, so the two servers find each other on any ports.
(cd backend && FRONTEND_ORIGIN="http://localhost:$FRONTEND_PORT" \
  nohup uv run uvicorn app.main:app --port "$BACKEND_PORT" >"$LOGS/backend.log" 2>&1 &)
(cd frontend && VITE_API_BASE="http://localhost:$BACKEND_PORT/api/v1" \
  nohup npm run dev -- --port "$FRONTEND_PORT" --strictPort >"$LOGS/frontend.log" 2>&1 &)
wait_http "http://localhost:$BACKEND_PORT/api/v1/health" 120 || fail "the backend didn't start; see demo/.logs/backend.log"
wait_http "http://localhost:$FRONTEND_PORT" 120 || fail "the frontend didn't start; see demo/.logs/frontend.log"

step "Checking the status chips"
status=""
deadline=$((SECONDS + 90))
while [ $SECONDS -lt $deadline ]; do  # a new database builds its search indexes once
  status="$(curl -s "http://localhost:$BACKEND_PORT/api/v1/system/status")"
  echo "$status" | grep -q '"keyword":"ok","vector":"ok"' && break
  sleep 5
done
echo "    $status"
echo "$status" | grep -q 'replay of' \
  || printf '\033[33mWARNING: the model is not a replay, so a migration would call Gemini live. Check ARGON_REPLAY_FILE in .env.\033[0m\n'

url="http://localhost:$FRONTEND_PORT/repos/repo_3852f5968630"
printf '\n\033[32mThe demo is running: %s\033[0m\n' "$url"
echo '  Plan -> Python 2 to Python 3 -> Create plan -> Approve -> Start migration (about 1.5-2 min, 14/14).'
echo '  Ask (on Search):  "Where is checkmate detected?"   "How is a move like e2e4 parsed?"'
echo "  Logs: demo/.logs/   Stop: BACKEND_PORT=$BACKEND_PORT FRONTEND_PORT=$FRONTEND_PORT bash demo/stop.sh"
if [ -z "${NO_BROWSER:-}" ]; then
  (command -v open >/dev/null && open "$url") || (command -v xdg-open >/dev/null && xdg-open "$url") || true
fi
