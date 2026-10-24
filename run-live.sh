#!/usr/bin/env bash
# Start the real-time assistant: the server, the Whisper worker and the
# interpreter screen. Ctrl+C stops everything.
#
#   ./run-live.sh                                   default microphone
#   ./run-live.sh --device "MacBook Pro Microphone" a named input
#   ./run-live.sh --list-devices                    list inputs and exit
#   ./run-live.sh --file sermon-01 --start 180      a dev recording at live pace, no microphone
#   ./run-live.sh --port 8001 --no-open             other port, do not open the browser
#
# Needs a Mac with Apple Silicon, uv and ffmpeg. Logs go to
# realtime/backend/logs/run-live-<time>-{server,worker}.log. No transcript is
# saved in microphone mode.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/realtime/backend"
PORT=8000
DEVICE="default"
FILE=""
START=0
DURATION=""
OPEN=1

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --start) START="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-open) OPEN=0; shift ;;
    --list-devices)
      cd "$BACKEND"
      uv run --frozen --group stt python -c \
        "import sounddevice as sd; [print(f'{d[\"name\"]}') for d in sd.query_devices() if d['max_input_channels'] > 0]"
      exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "uv is not installed: brew install uv" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is not installed: brew install ffmpeg" >&2; exit 1; }
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is in use; stop what runs there or use --port" >&2
  exit 1
fi

cd "$BACKEND"
echo "Preparing the environment (first run downloads the Whisper model, about 1.6 GB)..."
uv sync --frozen --group stt -q

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p logs
SERVER_LOG="logs/run-live-$STAMP-server.log"
WORKER_LOG="logs/run-live-$STAMP-worker.log"
SERVER_PID=""
WORKER_PID=""

stop() {
  trap - INT TERM EXIT
  echo
  echo "Stopping..."
  # Background jobs of a script ignore SIGINT, so stop them with SIGTERM.
  [ -n "$WORKER_PID" ] && kill -TERM "$WORKER_PID" 2>/dev/null || true
  [ -n "$SERVER_PID" ] && kill -TERM "$SERVER_PID" 2>/dev/null || true
  for _ in $(seq 1 50); do
    alive=0
    for pid in $WORKER_PID $SERVER_PID; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2
  done
  for pid in $WORKER_PID $SERVER_PID; do kill -KILL "$pid" 2>/dev/null || true; done
  echo "Stopped. Logs: $BACKEND/$SERVER_LOG, $BACKEND/$WORKER_LOG"
}
trap 'stop; exit 0' INT TERM
trap stop EXIT

uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "the server stopped; see $SERVER_LOG" >&2; exit 1; }
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "the server did not start" >&2; exit 1; }
echo "Server:  http://127.0.0.1:$PORT/  (pid $SERVER_PID)"

if [ -n "$FILE" ]; then
  ARGS=(--sermon "$FILE" --start "$START" --realtime --no-save)
  [ -n "$DURATION" ] && ARGS+=(--duration "$DURATION")
  SOURCE="recording $FILE from $START s"
else
  ARGS=(--device "$DEVICE" --no-save)
  SOURCE="input \"$DEVICE\""
fi
uv run --frozen python -u -m stt_worker "${ARGS[@]}" --ws "ws://127.0.0.1:$PORT/ws" \
  >"$WORKER_LOG" 2>&1 &
WORKER_PID=$!
echo "Whisper: $SOURCE  (pid $WORKER_PID; loading the model takes a few seconds)"

[ "$OPEN" = 1 ] && open "http://127.0.0.1:$PORT/"
echo "Screen:  http://127.0.0.1:$PORT/   Press Ctrl+C to stop."

# Stay in the foreground until Ctrl+C or until either process exits.
while kill -0 "$SERVER_PID" 2>/dev/null && kill -0 "$WORKER_PID" 2>/dev/null; do
  sleep 1
done
if ! kill -0 "$WORKER_PID" 2>/dev/null; then
  echo "The Whisper worker stopped; see $WORKER_LOG"
  tail -5 "$WORKER_LOG" || true
fi
