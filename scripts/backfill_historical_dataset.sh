#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run/backfill"
LOG_DIR="$ROOT_DIR/.run/logs"
SESSION_NAME="${SESSION_NAME:-trading-dataset-backfill}"
API_URL="${API_URL:-http://127.0.0.1:8001}"
START_DATE="${START_DATE:-2017-01-01}"
END_DATE="${END_DATE:-2026-07-01}"
CHUNK_MONTHS="${CHUNK_MONTHS:-1}"
NEWS_LIMIT="${NEWS_LIMIT:-10000}"
RETRIES="${RETRIES:-4}"
SLEEP_SECONDS="${SLEEP_SECONDS:-1}"
PYTHON_BIN="${PYTHON_BIN:-}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/backfill_${START_DATE}_to_${END_DATE}.log}"
STATE_FILE="${STATE_FILE:-$RUN_DIR/state_${START_DATE}_to_${END_DATE}.txt}"
RESUME_SYMBOL="${RESUME_SYMBOL:-}"
RESUME_DATE="${RESUME_DATE:-}"
RESET_CHECKPOINT="${RESET_CHECKPOINT:-0}"

DEFAULT_TICKERS=(
  AAPL MSFT NVDA GOOGL GOOG AMZN META TSLA AVGO AMD INTC QCOM ORCL CRM NFLX ADBE IBM CSCO
  SPY QQQ IWM DIA
  JPM BAC WFC GS MS V MA PYPL
  UNH JNJ LLY PFE MRK ABBV
  XOM CVX COP
  BA CAT GE DIS WMT COST HD MCD NKE KO PEP T
)

if [[ -z "${TICKERS:-}" ]]; then
  TICKERS="${DEFAULT_TICKERS[*]}"
fi

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "python3/python is required for JSON/date handling."
    exit 1
  fi
fi

usage() {
  cat <<USAGE
Usage:
  $0 --tmux          Start the backfill in a tmux session.
  $0 --attach        Attach to the tmux session.
  $0 --status        Show tmux session and latest log lines.
  $0                 Run in the current shell.

Environment:
  API_URL=$API_URL
  START_DATE=$START_DATE
  END_DATE=$END_DATE
  CHUNK_MONTHS=$CHUNK_MONTHS
  NEWS_LIMIT=$NEWS_LIMIT
  TICKERS="$TICKERS"
  SESSION_NAME=$SESSION_NAME
  LOG_FILE=$LOG_FILE
  STATE_FILE=$STATE_FILE
  RESUME_SYMBOL=$RESUME_SYMBOL
  RESUME_DATE=$RESUME_DATE
  RESET_CHECKPOINT=$RESET_CHECKPOINT

END_DATE is inclusive. The script sends windows ending at the next midnight UTC.
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
  echo "Log: $LOG_FILE"
  tail -n 80 "$LOG_FILE" 2>/dev/null || true
  echo
  echo "Checkpoint: $STATE_FILE"
  cat "$STATE_FILE" 2>/dev/null || echo "No checkpoint"
  exit 0
fi

if [[ "${1:-}" == "--tmux" && -z "${BACKFILL_IN_TMUX:-}" ]]; then
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
    "BACKFILL_IN_TMUX=1 LOG_FILE='$LOG_FILE' STATE_FILE='$STATE_FILE' API_URL='$API_URL' START_DATE='$START_DATE' END_DATE='$END_DATE' CHUNK_MONTHS='$CHUNK_MONTHS' NEWS_LIMIT='$NEWS_LIMIT' RETRIES='$RETRIES' SLEEP_SECONDS='$SLEEP_SECONDS' TICKERS='$TICKERS' RESUME_SYMBOL='$RESUME_SYMBOL' RESUME_DATE='$RESUME_DATE' RESET_CHECKPOINT='$RESET_CHECKPOINT' '$0' 2>&1 | tee -a '$LOG_FILE'"
  echo "Started tmux session: $SESSION_NAME"
  echo "Attach: tmux attach -t $SESSION_NAME"
  echo "Watch log: tail -f $LOG_FILE"
  exit 0
fi

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1"
    exit 1
  fi
}

request_with_retry() {
  local method="$1"
  local url="$2"
  local output="$3"
  local body_file="${4:-}"
  local attempt=1
  local sleep_for=3

  while (( attempt <= RETRIES )); do
    if [[ "$method" == "GET" ]]; then
      if curl --fail --show-error --silent --location "$url" --output "$output"; then
        return 0
      fi
    else
      if curl --fail --show-error --silent --location \
        --header "Content-Type: application/json" \
        --request "$method" \
        --data-binary "@$body_file" \
        "$url" \
        --output "$output"; then
        return 0
      fi
    fi
    log "Request failed attempt=$attempt/$RETRIES method=$method url=$url"
    sleep "$sleep_for"
    attempt=$((attempt + 1))
    sleep_for=$((sleep_for * 2))
  done
  return 1
}

healthcheck() {
  local health_file="$RUN_DIR/health.json"
  for _ in $(seq 1 60); do
    if request_with_retry GET "$API_URL/api/health" "$health_file"; then
      "$PYTHON_BIN" - "$health_file" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
print(
    "Backend OK "
    f"alpaca_configured={payload.get('alpaca_configured')} "
    f"duckdb_path={payload.get('duckdb_path')}"
)
PY
      return 0
    fi
    sleep 2
  done
  log "Backend is not reachable at $API_URL. Start it first, e.g. ./scripts/start_services.sh"
  return 1
}

build_windows() {
  "$PYTHON_BIN" - "$START_DATE" "$END_DATE" "$CHUNK_MONTHS" <<'PY'
from __future__ import annotations

import calendar
import sys
from datetime import date, datetime, timedelta

start_date = date.fromisoformat(sys.argv[1])
end_inclusive = date.fromisoformat(sys.argv[2])
chunk_months = int(sys.argv[3])
end_exclusive = end_inclusive + timedelta(days=1)

def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

current = start_date
while current < end_exclusive:
    next_date = min(add_months(current, chunk_months), end_exclusive)
    print(
        datetime.combine(current, datetime.min.time()).isoformat() + "Z",
        datetime.combine(next_date, datetime.min.time()).isoformat() + "Z",
    )
    current = next_date
PY
}

write_news_payload() {
  local symbol="$1"
  local start="$2"
  local end="$3"
  local output="$4"
  "$PYTHON_BIN" - "$symbol" "$start" "$end" "$NEWS_LIMIT" "$output" <<'PY'
import json, sys

symbol, start, end, limit, output = sys.argv[1:6]
payload = {
    "symbol": symbol,
    "start": start,
    "end": end,
    "include_rss": False,
    "limit": int(limit),
    "relation_type": "all",
}
with open(output, "w") as file:
    json.dump(payload, file)
PY
}

write_sentiment_payload() {
  local symbol="$1"
  local news_file="$2"
  local scores_file="$3"
  local output="$4"
  "$PYTHON_BIN" - "$symbol" "$news_file" "$scores_file" "$output" <<'PY'
import json, sys

symbol, news_file, scores_file, output = sys.argv[1:5]
news_payload = json.load(open(news_file))
score_payload = json.load(open(scores_file))
articles = news_payload.get("articles", [])
existing = {
    score.get("article_id")
    for score in score_payload
    if score.get("article_id") and score.get("model") == "ProsusAI/finbert"
}
pending = [article["id"] for article in articles if article.get("id") and article["id"] not in existing]
with open(output, "w") as file:
    json.dump({"symbol": symbol, "article_ids": pending, "use_ollama": False}, file)
print(len(pending))
PY
}

summarize_news_response() {
  local file="$1"
  "$PYTHON_BIN" - "$file" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1]))
summary = payload.get("summary", {})
daily = summary.get("daily", {})
market = summary.get("market_data") or {}
timeframes = market.get("timeframes") or []
tf_text = ", ".join(
    f"{item.get('timeframe')}:total={item.get('total')} new={item.get('new')} fetched={item.get('fetched')} failed={item.get('failed_windows')}"
    for item in timeframes
)
print(
    f"news total={summary.get('total')} new={summary.get('new')} "
    f"existing={summary.get('existing')} fetched={summary.get('fetched')} "
    f"daily_avg={daily.get('average')} market=[{tf_text}]"
)
PY
}

summarize_sentiment_response() {
  local file="$1"
  "$PYTHON_BIN" - "$file" <<'PY'
import json, sys

payload = json.load(open(sys.argv[1]))
labels = {"positive": 0, "neutral": 0, "negative": 0}
for item in payload:
    label = item.get("label")
    if label in labels:
        labels[label] += 1
print(f"sentiment scored={len(payload)} positive={labels['positive']} neutral={labels['neutral']} negative={labels['negative']}")
PY
}

urlencode_query() {
  "$PYTHON_BIN" - "$1" "$2" "$3" <<'PY'
from urllib.parse import urlencode
import sys
print(urlencode({"symbol": sys.argv[1], "start": sys.argv[2], "end": sys.argv[3]}))
PY
}

write_checkpoint() {
  local symbol="$1"
  local start="$2"
  local temp_file="${STATE_FILE}.tmp"
  printf '%s %s\n' "$symbol" "$start" > "$temp_file"
  mv "$temp_file" "$STATE_FILE"
}

require_command curl

log "Backfill starting"
log "API_URL=$API_URL"
log "Date range inclusive: $START_DATE to $END_DATE"
log "Chunk months: $CHUNK_MONTHS"
log "Tickers: $TICKERS"
log "Log file: $LOG_FILE"
log "Checkpoint file: $STATE_FILE"

if [[ "$RESET_CHECKPOINT" == "1" ]]; then
  rm -f "$STATE_FILE"
  log "Checkpoint reset requested"
fi

if [[ -z "$RESUME_SYMBOL" && -f "$STATE_FILE" ]]; then
  read -r RESUME_SYMBOL RESUME_DATE < "$STATE_FILE"
fi

if [[ "$RESUME_SYMBOL" == "COMPLETE" ]]; then
  log "Backfill already complete according to checkpoint"
  exit 0
fi

if [[ -n "$RESUME_SYMBOL" ]]; then
  RESUME_DATE="${RESUME_DATE:-$START_DATE}"
  log "Resuming at symbol=$RESUME_SYMBOL date=$RESUME_DATE"
fi

if ! healthcheck; then
  exit 1
fi

WINDOWS=()
while IFS= read -r window_line; do
  WINDOWS+=("$window_line")
done < <(build_windows)
TOTAL_WINDOWS="${#WINDOWS[@]}"
FAILED_WINDOWS=0
COMPLETED_WINDOWS=0
SYMBOLS=($TICKERS)
RESUME_REACHED=0

if [[ -z "$RESUME_SYMBOL" ]]; then
  RESUME_REACHED=1
fi

for symbol_index in "${!SYMBOLS[@]}"; do
  symbol="${SYMBOLS[$symbol_index]}"
  if (( RESUME_REACHED == 0 )); then
    if [[ "$symbol" != "$RESUME_SYMBOL" ]]; then
      log "===== SKIP SYMBOL $symbol (before checkpoint) ====="
      continue
    fi
    RESUME_REACHED=1
  fi

  symbol_dir="$RUN_DIR/$symbol"
  mkdir -p "$symbol_dir"
  log "===== SYMBOL $symbol windows=$TOTAL_WINDOWS ====="

  window_index=0
  for window in "${WINDOWS[@]}"; do
    window_index=$((window_index + 1))
    read -r window_start window_end <<<"$window"
    if [[ "$symbol" == "$RESUME_SYMBOL" && "$window_start" < "${RESUME_DATE}T00:00:00Z" ]]; then
      continue
    fi
    safe_start="${window_start//[:]/-}"
    safe_end="${window_end//[:]/-}"
    payload_file="$symbol_dir/news_${safe_start}_${safe_end}.payload.json"
    news_file="$symbol_dir/news_${safe_start}_${safe_end}.response.json"
    scores_file="$symbol_dir/scores_${safe_start}_${safe_end}.response.json"
    sentiment_payload_file="$symbol_dir/sentiment_${safe_start}_${safe_end}.payload.json"
    sentiment_file="$symbol_dir/sentiment_${safe_start}_${safe_end}.response.json"

    log "[$symbol $window_index/$TOTAL_WINDOWS] Fetching news+OHLCV $window_start -> $window_end"
    write_news_payload "$symbol" "$window_start" "$window_end" "$payload_file"
    if ! request_with_retry POST "$API_URL/api/news/fetch" "$news_file" "$payload_file"; then
      log "[$symbol $window_index/$TOTAL_WINDOWS] FAILED news+OHLCV $window_start -> $window_end"
      FAILED_WINDOWS=$((FAILED_WINDOWS + 1))
      continue
    fi
    log "[$symbol $window_index/$TOTAL_WINDOWS] $(summarize_news_response "$news_file")"

    query="$(urlencode_query "$symbol" "$window_start" "$window_end")"
    if ! request_with_retry GET "$API_URL/api/sentiment?$query" "$scores_file"; then
      log "[$symbol $window_index/$TOTAL_WINDOWS] FAILED sentiment lookup $window_start -> $window_end"
      FAILED_WINDOWS=$((FAILED_WINDOWS + 1))
      continue
    fi

    pending_count="$(write_sentiment_payload "$symbol" "$news_file" "$scores_file" "$sentiment_payload_file")"
    if (( pending_count > 0 )); then
      log "[$symbol $window_index/$TOTAL_WINDOWS] Scoring pending sentiment count=$pending_count"
      if request_with_retry POST "$API_URL/api/sentiment/run" "$sentiment_file" "$sentiment_payload_file"; then
        log "[$symbol $window_index/$TOTAL_WINDOWS] $(summarize_sentiment_response "$sentiment_file")"
      else
        log "[$symbol $window_index/$TOTAL_WINDOWS] FAILED sentiment scoring count=$pending_count"
        FAILED_WINDOWS=$((FAILED_WINDOWS + 1))
        continue
      fi
    else
      log "[$symbol $window_index/$TOTAL_WINDOWS] sentiment pending=0"
    fi

    COMPLETED_WINDOWS=$((COMPLETED_WINDOWS + 1))
    if (( window_index < TOTAL_WINDOWS )); then
      next_window="${WINDOWS[$window_index]}"
      read -r next_window_start _ <<<"$next_window"
      write_checkpoint "$symbol" "${next_window_start%%T*}"
    elif (( symbol_index + 1 < ${#SYMBOLS[@]} )); then
      write_checkpoint "${SYMBOLS[$((symbol_index + 1))]}" "$START_DATE"
    else
      write_checkpoint "COMPLETE" "$END_DATE"
    fi
    sleep "$SLEEP_SECONDS"
  done
done

log "Backfill done completed_windows=$COMPLETED_WINDOWS failed_windows=$FAILED_WINDOWS"
if (( FAILED_WINDOWS > 0 )); then
  exit 2
fi
