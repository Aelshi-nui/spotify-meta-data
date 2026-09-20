#!/bin/bash
set -euo pipefail

NIC="${NIC:-eth0}"
CPORT="${CPORT:-8080}"
LIST="${LIST:-/etc/tokener-allow.list}"

allowed() { grep -vE '^\s*(#|$)' "$LIST" 2>/dev/null || true; }

while iptables -C DOCKER-USER -i "$NIC" -p tcp --dport "$CPORT" -j DROP 2>/dev/null; do
  iptables -D DOCKER-USER -i "$NIC" -p tcp --dport "$CPORT" -j DROP
done
for ip in $(allowed); do
  while iptables -C DOCKER-USER -i "$NIC" -s "$ip" -p tcp --dport "$CPORT" -j RETURN 2>/dev/null; do
    iptables -D DOCKER-USER -i "$NIC" -s "$ip" -p tcp --dport "$CPORT" -j RETURN
  done
done

iptables -I DOCKER-USER 1 -i "$NIC" -p tcp --dport "$CPORT" -j DROP
for ip in $(allowed); do
  iptables -I DOCKER-USER 1 -i "$NIC" -s "$ip" -p tcp --dport "$CPORT" -j RETURN
done

echo "tokener-fw applied on ${NIC}: $(allowed | grep -c . || echo 0) address(es) allowed, all others dropped on container port ${CPORT}"
