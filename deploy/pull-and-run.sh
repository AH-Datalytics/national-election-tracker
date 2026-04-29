#!/bin/bash
# Quick deploy: pull latest code and restart API
# Usage: ssh root@SERVER "bash /opt/national-elections/repo/deploy/pull-and-run.sh"

set -euo pipefail

APP_DIR="/opt/national-elections"
cd "${APP_DIR}/repo"

echo "Pulling latest..."
git pull

echo "Installing dependencies..."
"${APP_DIR}/venv/bin/pip" install -r scrapers/requirements.txt --quiet
"${APP_DIR}/venv/bin/pip" install -r api/requirements.txt --quiet 2>/dev/null || true
"${APP_DIR}/venv/bin/pip" install -r maps/requirements.txt --quiet 2>/dev/null || true

echo "Restarting API..."
systemctl restart national-elections-api
sleep 2

if systemctl is-active --quiet national-elections-api; then
    echo "Deployed: $(git log --oneline -1)"
    echo "API health: $(curl -s http://localhost:8200/api/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"{d.get(\"states\",\"?\")} states, {d.get(\"elections\",\"?\")} elections")' 2>/dev/null || echo 'check manually')"
else
    echo "WARNING: API failed to start"
    journalctl -u national-elections-api --no-pager -n 20
fi
