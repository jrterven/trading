#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PORTS=("$BACKEND_PORT" "$FRONTEND_PORT")
TMUX_BIN="$(command -v tmux || true)"
TMUX_SESSIONS=("trading-lab-backend" "trading-lab-frontend")

kill_pid() {
  local pid="$1"
  local label="${2:-process}"

  if [[ -z "$pid" ]]; then
    return
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    return
  fi

  echo "Stopping $label pid=$pid"
  kill "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return
    fi
    sleep 0.15
  done

  echo "Force stopping $label pid=$pid"
  kill -9 "$pid" 2>/dev/null || true
}

kill_pid_file() {
  local file="$1"
  local label="$2"

  if [[ ! -f "$file" ]]; then
    return
  fi

  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  kill_pid "$pid" "$label"
  rm -f "$file"
}

kill_port() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return
  fi

  local pids
  pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    kill_pid "$pid" "port:$port"
  done <<< "$pids"
}

kill_pid_file "$RUN_DIR/backend.pid" "backend"
kill_pid_file "$RUN_DIR/frontend.pid" "frontend"

if [[ -n "$TMUX_BIN" ]]; then
  for session in "${TMUX_SESSIONS[@]}"; do
    if "$TMUX_BIN" has-session -t "$session" 2>/dev/null; then
      echo "Stopping tmux session $session"
      "$TMUX_BIN" kill-session -t "$session" 2>/dev/null || true
    fi
  done
fi

for port in "${PORTS[@]}"; do
  kill_port "$port"
done

echo "Trading Lab services stopped."
