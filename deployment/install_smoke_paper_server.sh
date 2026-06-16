#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/smoke-strategy"
SERVICE_NAME="smoke-paper"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$APP_DIR"

if [ "$SRC_DIR" != "$APP_DIR" ]; then
  echo "Copying repository from $SRC_DIR to $APP_DIR"
  cp -a "$SRC_DIR"/. "$APP_DIR"/
fi

cd "$APP_DIR"

python3 --version

if [ ! -f ".env.paper" ]; then
  cp deployment/smoke-paper.env.example .env.paper
  SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  sed -i "s/CHANGE_ME_LONG_RANDOM_SECRET/${SECRET}/g" .env.paper
fi

mkdir -p runtime/paper_review

cp deployment/smoke-paper.service.example /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.service
systemctl restart ${SERVICE_NAME}.service

sleep 2
systemctl status ${SERVICE_NAME}.service --no-pager || true

echo ""
echo "Smoke paper server installed."
echo "Health: curl http://127.0.0.1:8095/health"
echo "Status: curl http://127.0.0.1:8095/status"
echo "Trades: curl http://127.0.0.1:8095/trades?limit=20"
echo "Logs: journalctl -u smoke-paper -f"
