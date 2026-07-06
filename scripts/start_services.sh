#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"

CONDA_ENV="${CONDA_ENV:-trading-lab}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
API_URL="${VITE_API_URL:-http://$BACKEND_HOST:$BACKEND_PORT}"
WS_URL="${VITE_WS_URL:-ws://$BACKEND_HOST:$BACKEND_PORT}"
PYTHON_BIN="${PYTHON_BIN:-}"
TMUX_BIN="$(command -v tmux || true)"

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda no esta disponible en PATH."
  echo "Abre una terminal con Anaconda inicializado o agrega conda al PATH."
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(conda run -n "$CONDA_ENV" python -c 'import sys; print(sys.executable)')"
fi

"$ROOT_DIR/scripts/stop_services.sh"

echo "Starting backend on http://$BACKEND_HOST:$BACKEND_PORT"
if [[ -n "$TMUX_BIN" ]]; then
  "$TMUX_BIN" new-session -d -s trading-lab-backend -c "$ROOT_DIR" \
    "$PYTHON_BIN -m uvicorn backend.main:app --host '$BACKEND_HOST' --port '$BACKEND_PORT' > '$LOG_DIR/backend.log' 2>&1"
  "$TMUX_BIN" display-message -p -t trading-lab-backend "#{pane_pid}" > "$RUN_DIR/backend.pid"
else
  nohup "$PYTHON_BIN" -m uvicorn backend.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" \
    > "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID="$!"
  echo "$BACKEND_PID" > "$RUN_DIR/backend.pid"
fi

echo "Starting frontend on http://$FRONTEND_HOST:$FRONTEND_PORT"
if [[ -n "$TMUX_BIN" ]]; then
  "$TMUX_BIN" new-session -d -s trading-lab-frontend -c "$ROOT_DIR" \
    "VITE_API_URL='$API_URL' VITE_WS_URL='$WS_URL' conda run --no-capture-output -n '$CONDA_ENV' npm run dev -- --host '$FRONTEND_HOST' --port '$FRONTEND_PORT' > '$LOG_DIR/frontend.log' 2>&1"
  "$TMUX_BIN" display-message -p -t trading-lab-frontend "#{pane_pid}" > "$RUN_DIR/frontend.pid"
else
  env VITE_API_URL="$API_URL" VITE_WS_URL="$WS_URL" nohup \
    conda run --no-capture-output -n "$CONDA_ENV" npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
    > "$LOG_DIR/frontend.log" 2>&1 &
  FRONTEND_PID="$!"
  echo "$FRONTEND_PID" > "$RUN_DIR/frontend.pid"
fi

echo
echo "Trading Lab started."
echo "Backend:  $API_URL"
echo "Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "Logs:     $LOG_DIR"
echo
echo "Para detenerlos:"
echo "  ./scripts/stop_services.sh"
