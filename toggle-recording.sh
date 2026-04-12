#!/usr/bin/env bash
set -euo pipefail

FRAETOR_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST="127.0.0.1"
PORT="8765"
URL="http://${HOST}:${PORT}"
LOG_FILE="${FRAETOR_DIR}/fraetor-server.log"

is_server_running() {
    curl -s -o /dev/null --max-time 1 "${URL}/" 2>/dev/null
}

if ! is_server_running; then
    cd "$FRAETOR_DIR"
    nohup uv run fraetor >> "$LOG_FILE" 2>&1 &

    for _ in $(seq 1 30); do
        if is_server_running; then
            break
        fi
        sleep 0.5
    done

    if ! is_server_running; then
        notify-send "Fraetor" "サーバーの起動に失敗しました" 2>/dev/null || true
        exit 1
    fi
fi

curl -s -X POST "${URL}/api/toggle-recording"
