#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_NAME="${SESSION_NAME:-trading-crypto-backfill}"
CONDA_ENV="${CONDA_ENV:-trading-lab}"
START_DATE="${START_DATE:-2021-01-01}"
END_DATE="${END_DATE:-2026-07-01}"
CHUNK_MONTHS="${CHUNK_MONTHS:-1}"
CRYPTO_DUCKDB_PATH="${CRYPTO_DUCKDB_PATH:-$ROOT_DIR/data/crypto/crypto.duckdb}"
LOG_DIR="$ROOT_DIR/.run/logs"
LOG_FILE="${LOG_FILE:-$LOG_DIR/crypto_backfill_${START_DATE}_to_${END_DATE}.log}"

mkdir -p "$LOG_DIR" "$(dirname "$CRYPTO_DUCKDB_PATH")"

usage() {
  cat <<USAGE
Usage:
  $0 --tmux       Start crypto backfill in a tmux session.
  $0 --attach     Attach to the tmux session.
  $0 --status     Show session and latest log lines.
  $0              Run in the current shell.

Environment:
  SESSION_NAME=$SESSION_NAME
  CONDA_ENV=$CONDA_ENV
  CRYPTO_DUCKDB_PATH=$CRYPTO_DUCKDB_PATH
  START_DATE=$START_DATE
  END_DATE=$END_DATE
  CHUNK_MONTHS=$CHUNK_MONTHS
  CRYPTO_SYMBOLS="${CRYPTO_SYMBOLS:-default top Alpaca USD pairs}"
  CRYPTO_TIMEFRAMES="${CRYPTO_TIMEFRAMES:-1Min 5Min 15Min 1Hour 1Day}"
  LOG_FILE=$LOG_FILE

Examples:
  CRYPTO_SYMBOLS="BTC/USD ETH/USD SOL/USD" $0 --tmux
  CRYPTO_TIMEFRAMES="1Hour 1Day" $0 --tmux
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--attach" ]]; then
  exec tmux attach -t "$SESSION_NAME"
fi

if [[ "${1:-}" == "--status" ]]; then
  tmux list-sessions 2>/dev/null | grep "$SESSION_NAME" || true
  echo
  echo "Database: $CRYPTO_DUCKDB_PATH"
  echo "Log:      $LOG_FILE"
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  exit 0
fi

if [[ "${1:-}" == "--tmux" && -z "${CRYPTO_BACKFILL_IN_TMUX:-}" ]]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is required for --tmux."
    exit 1
  fi
  if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux session already exists: $SESSION_NAME"
    echo "Attach: tmux attach -t $SESSION_NAME"
    echo "Status: $0 --status"
    exit 0
  fi
  tmux new-session -d -s "$SESSION_NAME" -c "$ROOT_DIR" \
    "CRYPTO_BACKFILL_IN_TMUX=1 START_DATE='$START_DATE' END_DATE='$END_DATE' CHUNK_MONTHS='$CHUNK_MONTHS' CRYPTO_DUCKDB_PATH='$CRYPTO_DUCKDB_PATH' CRYPTO_SYMBOLS='${CRYPTO_SYMBOLS:-}' CRYPTO_TIMEFRAMES='${CRYPTO_TIMEFRAMES:-}' LOG_FILE='$LOG_FILE' '$0' 2>&1 | tee -a '$LOG_FILE'"
  echo "Started tmux session: $SESSION_NAME"
  echo "Attach: tmux attach -t $SESSION_NAME"
  echo "Watch log: tail -f $LOG_FILE"
  echo "Database: $CRYPTO_DUCKDB_PATH"
  exit 0
fi

cd "$ROOT_DIR"

exec conda run --no-capture-output -n "$CONDA_ENV" python "$ROOT_DIR/scripts/backfill_crypto_dataset.py" \
  --db "$CRYPTO_DUCKDB_PATH" \
  --start "$START_DATE" \
  --end "$END_DATE" \
  --chunk-months "$CHUNK_MONTHS"
