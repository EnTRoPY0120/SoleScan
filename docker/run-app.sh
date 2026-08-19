#!/usr/bin/env bash
set -euo pipefail

readonly DISPLAY_NUMBER="${SPF_DISPLAY_NUMBER:-99}"
export DISPLAY=":${DISPLAY_NUMBER}"
export XDG_CONFIG_HOME=/tmp/pwuser-config
export XDG_CACHE_HOME=/tmp/pwuser-cache
readonly X_LOCK="/tmp/.X${DISPLAY_NUMBER}-lock"
readonly X_SOCKET="/tmp/.X11-unix/X${DISPLAY_NUMBER}"

mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME"

declare -a CHILD_PIDS=()

cleanup() {
  if ((${#CHILD_PIDS[@]})); then
    kill "${CHILD_PIDS[@]}" 2>/dev/null || true
    wait "${CHILD_PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

clear_display() {
  if [[ -f "$X_LOCK" ]]; then
    local old_pid
    old_pid="$(tr -cd '0-9' < "$X_LOCK")"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      for _attempt in {1..20}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.1
      done
    fi
  fi
  rm -f "$X_LOCK" "$X_SOCKET"
}

if [[ "${1:-}" == "--clear-stale-display" ]]; then
  clear_display
  exit 0
fi

wait_for_path() {
  local path="$1" pid="$2" label="$3"
  for _attempt in {1..50}; do
    [[ -e "$path" ]] && return 0
    kill -0 "$pid" 2>/dev/null || { echo "$label exited during startup" >&2; return 1; }
    sleep 0.1
  done
  echo "$label did not become ready" >&2
  return 1
}

wait_for_port() {
  local port="$1" pid="$2" label="$3"
  for _attempt in {1..50}; do
    if python - "$port" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.settimeout(0.1)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
    then
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || { echo "$label exited during startup" >&2; return 1; }
    sleep 0.1
  done
  echo "$label did not become ready" >&2
  return 1
}

clear_display
Xvfb "$DISPLAY" -screen 0 1280x900x24 >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
CHILD_PIDS+=("$XVFB_PID")
wait_for_path "$X_SOCKET" "$XVFB_PID" "Xvfb"

x11vnc -display "$DISPLAY" -localhost -forever -shared -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
VNC_PID=$!
CHILD_PIDS+=("$VNC_PID")
wait_for_port 5900 "$VNC_PID" "x11vnc"

websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
WEBSOCKIFY_PID=$!
CHILD_PIDS+=("$WEBSOCKIFY_PID")
wait_for_port 6080 "$WEBSOCKIFY_PID" "websockify"

cd /app/backend
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
APP_PID=$!
CHILD_PIDS+=("$APP_PID")

# Any dead dependency makes the assisted browser unreliable. Exit so the
# container restart policy can rebuild the entire stack deterministically.
wait -n "$XVFB_PID" "$VNC_PID" "$WEBSOCKIFY_PID" "$APP_PID"
