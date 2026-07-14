#!/usr/bin/env bash
set -euo pipefail

# One-command installer for the SMOKE paper control server.
# Paper only. No exchange keys. No real orders.

APP_DIR="${SMOKE_APP_DIR:-/opt/smoke-strategy}"
REPO_URL="${SMOKE_REPO_URL:-https://github.com/SanChi117/Smoke-strategy.git}"
REPO_REF="${SMOKE_REPO_REF:-main}"
SERVICE_NAME="smoke-control"
APP_USER="smoke"
PORT="${SMOKE_PORT:-8095}"
DOMAIN="${SMOKE_DOMAIN:-_}"
ADMIN_USER="${SMOKE_ADMIN_USER:-smoke}"
PROJECT_ID="${SMOKE_PROJECT_ID:-smoke}"
PROJECT_NAME="${SMOKE_PROJECT_NAME:-SMOKE Strategy}"

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo bash deployment/install_smoke.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip nginx curl ca-certificates sudo

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/${APP_USER} --shell /usr/sbin/nologin "${APP_USER}"
fi

if [ -d "${APP_DIR}/.git" ]; then
  echo "Updating existing repository..."
  git -C "${APP_DIR}" fetch --all --prune
  git -C "${APP_DIR}" checkout "${REPO_REF}"
  git -C "${APP_DIR}" reset --hard "origin/${REPO_REF}"
else
  echo "Cloning repository..."
  rm -rf "${APP_DIR}"
  git clone --branch "${REPO_REF}" --depth 1 "${REPO_URL}" "${APP_DIR}"
fi

cd "${APP_DIR}"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
mkdir -p runtime/smoke_control results/strategy_universe_layer
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

ENV_FILE="${APP_DIR}/.env.smoke"
if [ ! -f "${ENV_FILE}" ]; then
  ADMIN_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(16))
PY
)"
  API_SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  cat > "${ENV_FILE}" <<EOF
SMOKE_PROJECT_ID=${PROJECT_ID}
SMOKE_PROJECT_NAME=${PROJECT_NAME}
SMOKE_HOST=127.0.0.1
SMOKE_PORT=${PORT}
SMOKE_ADMIN_USER=${ADMIN_USER}
SMOKE_ADMIN_PASSWORD=${ADMIN_PASSWORD}
SMOKE_API_SECRET=${API_SECRET}
SMOKE_RUNTIME_DIR=${APP_DIR}/runtime/smoke_control
SMOKE_DB_PATH=${APP_DIR}/runtime/smoke_control/smoke.sqlite3
SMOKE_AUTO_SCAN=true
SMOKE_AUTO_BOOTSTRAP_HISTORY=true
SMOKE_INTERVAL=15m
SMOKE_BOOTSTRAP_LIMIT=1200
SMOKE_HISTORY_BARS=1200
SMOKE_POLL_SECONDS=30
SMOKE_MAX_SYMBOLS=150
SMOKE_SYMBOLS_FILE=${APP_DIR}/results/strategy_universe_layer/combined_symbols.txt
SMOKE_SYMBOLS=INJUSDT,TONUSDT,DOGEUSDT,ARBUSDT,NEARUSDT,OPUSDT
SMOKE_DAILY_DD_STOP_PCT=2.0
SMOKE_WEEKLY_DD_STOP_PCT=5.0
SMOKE_MAX_STOP_STREAK=3
SMOKE_MAX_OPEN_PER_SYMBOL=1
SMOKE_MAX_OPEN_TOTAL=2
EOF
  chmod 600 "${ENV_FILE}"
else
  ADMIN_PASSWORD="$(grep '^SMOKE_ADMIN_PASSWORD=' "${ENV_FILE}" | cut -d= -f2- || true)"
  ADMIN_USER="$(grep '^SMOKE_ADMIN_USER=' "${ENV_FILE}" | cut -d= -f2- || echo smoke)"
  if ! grep -q '^SMOKE_MAX_OPEN_TOTAL=' "${ENV_FILE}"; then
    echo 'SMOKE_MAX_OPEN_TOTAL=2' >> "${ENV_FILE}"
  fi
fi

sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" scripts/build_strategy_universe_layer.py \
  --top-n-per-group 10 \
  --out-dir results/strategy_universe_layer

sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m strategy_lab.causal_history_smoke_test
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m strategy_lab.closed_context_smoke_test
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m strategy_lab.decision_engine_smoke_test
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m strategy_lab.live_market_smoke_test
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m py_compile scripts/smoke_control_server.py scripts/smoke_control_server_v2.py

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=SMOKE Paper Control Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/scripts/smoke_control_server_v2.py
Restart=always
RestartSec=5
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=${APP_DIR}/runtime ${APP_DIR}/results

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/smoke-control <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN};
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/smoke-control /etc/nginx/sites-enabled/smoke-control
nginx -t
systemctl daemon-reload
systemctl enable --now nginx
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null

IP_ADDR="$(hostname -I | awk '{print $1}')"
echo ""
echo "============================================================"
echo "SMOKE installed successfully"
echo "Panel: http://${IP_ADDR}/"
echo "Login: ${ADMIN_USER}"
echo "Password: ${ADMIN_PASSWORD}"
echo "Mode: PAPER ONLY — no real orders"
echo "Service: systemctl status ${SERVICE_NAME}"
echo "Logs: journalctl -u ${SERVICE_NAME} -f"
echo "============================================================"
