#!/usr/bin/env bash
# Stop the Axolotl demo build's backend and frontend (macOS or Linux). The local MongoDB
# is left running; `docker stop axolotl-atlas-local` stops it, and its data is kept.
#   bash demo/stop.sh            BACKEND_PORT=8001 FRONTEND_PORT=5174 bash demo/stop.sh
for port in "${BACKEND_PORT:-8000}" "${FRONTEND_PORT:-5173}"; do
  pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null)"
  if [ -z "$pids" ]; then echo "port $port: nothing running"; continue; fi
  kill $pids 2>/dev/null && echo "port $port: stopped"
done
