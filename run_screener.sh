#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

ACTION="${1:-start}"
PORT="${SCREENER_PORT:-8787}"
HOST="${SCREENER_HOST:-0.0.0.0}"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_FILE="$RUNTIME_DIR/screener.pid"
LOG_FILE="$RUNTIME_DIR/screener.log"

is_running() {
  [ -f "$PID_FILE" ] || return 1
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

kill_matching() {
  if command -v pkill >/dev/null 2>&1; then
    pkill -f "uvicorn screener_ui.backend.app:app" 2>/dev/null || true
  fi
}

build_ui() {
  if [ ! -f "$ROOT_DIR/screener_ui/frontend/package.json" ]; then
    echo "[ERROR] React frontend package.json not found."
    exit 1
  fi
  cd "$ROOT_DIR/screener_ui/frontend"
  if [ ! -d node_modules ]; then
    echo "[UI] Installing frontend dependencies..."
    npm install
  fi
  echo "[UI] Building React frontend..."
  npm run build
  cd "$ROOT_DIR"
}

python_cmd() {
  if [ -x "$ROOT_DIR/venv/bin/python" ]; then
    printf '%s\n' "$ROOT_DIR/venv/bin/python"
  else
    printf '%s\n' "python3"
  fi
}

start_server() {
  mkdir -p "$RUNTIME_DIR"
  if is_running; then
    echo "[Screener] Already running on PID $(cat "$PID_FILE")."
    echo "URL: http://127.0.0.1:$PORT"
    exit 0
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[ERROR] Port $PORT is already in use. Stop that process or use SCREENER_PORT."
    exit 1
  fi
  build_ui
  PYTHON_CMD="$(python_cmd)"
  export SCREENER_AGENT_ROOT="$ROOT_DIR"
  echo "[Screener] Starting backend + UI on $HOST:$PORT..."
  nohup "$PYTHON_CMD" -m uvicorn screener_ui.backend.app:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>"$LOG_FILE.err" &
  echo "$!" > "$PID_FILE"
  echo "[Screener] Started on PID $(cat "$PID_FILE")."
  echo "URL: http://127.0.0.1:$PORT"
}

stop_server() {
  if ! is_running; then
    echo "[Screener] No PID file process found. Cleaning any matching screener server process..."
    kill_matching
    rm -f "$PID_FILE"
    exit 0
  fi
  pid="$(cat "$PID_FILE")"
  echo "[Screener] Stopping PID $pid..."
  kill "$pid" 2>/dev/null || true
  sleep 2
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  kill_matching
  rm -f "$PID_FILE"
  echo "[Screener] Stopped."
}

case "$ACTION" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    if is_running; then
      echo "[Screener] Running on PID $(cat "$PID_FILE")."
      echo "URL: http://127.0.0.1:$PORT"
    else
      echo "[Screener] Not running."
    fi
    ;;
  *)
    echo "Usage: ./run_screener.sh [start|stop|restart|status]"
    exit 1
    ;;
esac
