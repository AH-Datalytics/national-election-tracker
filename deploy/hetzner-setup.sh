#!/bin/bash
# National Election Tracker — Hetzner setup script
# Run once on a fresh Hetzner server. Subsequent deploys use pull-and-run.sh.
#
# Prerequisites: Hetzner volume 105552283 attached to the server.
# Usage: bash deploy/hetzner-setup.sh

set -euo pipefail

VOLUME_ID="105552283"
VOLUME_MOUNT="/mnt/HC_Volume_${VOLUME_ID}"
APP_DIR="/opt/national-elections"
REPO_URL="https://github.com/AH-Datalytics/national-election-tracker.git"

echo "=== National Election Tracker — Hetzner Setup ==="

# --- 1. Mount volume ---
echo "[1/8] Mounting volume..."
mkdir -p "$VOLUME_MOUNT"
if ! mountpoint -q "$VOLUME_MOUNT"; then
    mount -o discard,defaults "/dev/disk/by-id/scsi-0HC_Volume_${VOLUME_ID}" "$VOLUME_MOUNT"
fi

# Add to fstab if not already there
if ! grep -q "HC_Volume_${VOLUME_ID}" /etc/fstab; then
    echo "/dev/disk/by-id/scsi-0HC_Volume_${VOLUME_ID} ${VOLUME_MOUNT} ext4 discard,nofail,defaults 0 0" >> /etc/fstab
    echo "  Added to /etc/fstab"
fi

# --- 2. Create directory structure ---
echo "[2/8] Creating directory structure..."
mkdir -p "$APP_DIR"
mkdir -p "${VOLUME_MOUNT}/elections"
mkdir -p "${VOLUME_MOUNT}/elections/maps"
mkdir -p "${VOLUME_MOUNT}/elections/backups"
mkdir -p "${VOLUME_MOUNT}/elections/logs"

# Symlink data dir to volume
ln -sfn "${VOLUME_MOUNT}/elections" "${APP_DIR}/data"
echo "  ${APP_DIR}/data -> ${VOLUME_MOUNT}/elections"

# --- 3. Clone repo ---
echo "[3/8] Cloning repository..."
if [ -d "${APP_DIR}/repo/.git" ]; then
    echo "  Repo already exists, pulling latest..."
    cd "${APP_DIR}/repo" && git pull
else
    git clone "$REPO_URL" "${APP_DIR}/repo"
fi

# --- 4. Python venv ---
echo "[4/8] Setting up Python environment..."
if [ ! -d "${APP_DIR}/venv" ]; then
    python3 -m venv "${APP_DIR}/venv"
fi
"${APP_DIR}/venv/bin/pip" install --upgrade pip --quiet
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/repo/scrapers/requirements.txt" --quiet
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/repo/api/requirements.txt" --quiet 2>/dev/null || true
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/repo/maps/requirements.txt" --quiet 2>/dev/null || true
echo "  Python packages installed"

# --- 5. Create schema ---
echo "[5/8] Creating database schema..."
cd "${APP_DIR}/repo"
ELECTIONS_DB_PATH="${APP_DIR}/data/elections.db" "${APP_DIR}/venv/bin/python" scrapers/schema.py
echo "  Schema created at ${APP_DIR}/data/elections.db"

# --- 6. Install systemd service ---
echo "[6/8] Installing systemd service..."
cp "${APP_DIR}/repo/deploy/national-elections-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable national-elections-api
echo "  Service installed and enabled"

# --- 7. Start API ---
echo "[7/8] Starting API..."
systemctl start national-elections-api
sleep 2
if systemctl is-active --quiet national-elections-api; then
    echo "  API running on port 8200"
else
    echo "  WARNING: API failed to start. Check: journalctl -u national-elections-api"
fi

# --- 8. Verify ---
echo "[8/8] Verifying..."
echo "  Volume: $(df -h ${VOLUME_MOUNT} | tail -1 | awk '{print $3 "/" $2 " used"}')"
echo "  DB: $(ls -lh ${APP_DIR}/data/elections.db | awk '{print $5}')"
echo "  API: $(curl -s http://localhost:8200/api/health 2>/dev/null | head -c 200 || echo 'not responding')"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Upload LA source DB:  scp louisiana_elections.db root@\$(hostname -I | awk '{print \$1}'):/opt/national-elections/data/louisiana_source.db"
echo "  2. Run LA import:        cd /opt/national-elections/repo && /opt/national-elections/venv/bin/python scrapers/louisiana_import.py"
echo "  3. Run IN scrape:        tmux new -s scrape && cd /opt/national-elections/repo && /opt/national-elections/venv/bin/python scrapers/runner.py scrape --state IN --ramp 2>&1 | tee /opt/national-elections/data/logs/indiana.log"
echo "  4. Test OH live:         /opt/national-elections/venv/bin/python scrapers/ohio_live.py --once"
echo "  5. Build maps:           /opt/national-elections/venv/bin/python maps/build_county_maps.py"
