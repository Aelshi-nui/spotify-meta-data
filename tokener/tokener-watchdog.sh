#!/bin/bash
ENDPOINT="${ENDPOINT:-http://127.0.0.1:8099/api/token}"
CONTAINER="${CONTAINER:-spotify-tokener}"
LOG="${LOG:-/var/log/tokener-watchdog.log}"

probe() { curl -s --max-time 90 "$ENDPOINT" 2>/dev/null | grep -q accessToken; }

probe && exit 0
sleep 15
probe && exit 0

echo "$(date -Is) probe failed, restarting ${CONTAINER}" >> "$LOG"
docker restart "$CONTAINER" >/dev/null 2>&1

for i in $(seq 1 8); do
  sleep 15
  if probe; then
    echo "$(date -Is) recovered after $((i * 15))s" >> "$LOG"
    exit 0
  fi
done

echo "$(date -Is) still failing after restart, manual attention required" >> "$LOG"
exit 1
