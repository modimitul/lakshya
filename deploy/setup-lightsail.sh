#!/usr/bin/env bash
# One-shot server setup for Ubuntu 22.04 / 24.04 on AWS Lightsail (works on any Ubuntu VM).
# Safe to re-run: it updates the code and restarts the service.
#
# Usage (run inside the VM after SSH-ing in). Either pull the code from GitHub:
#   REPO_URL=https://github.com/<user>/lakshya.git bash setup-lightsail.sh
# or install from a zip you copied to the VM with scp (no GitHub needed):
#   ZIP_PATH=~/lakshya.zip bash setup-lightsail.sh
#
# With a free DuckDNS hostname pointed at this VM's static IP, add DOMAIN to get HTTPS:
#   DOMAIN=lakshya.duckdns.org REPO_URL=https://github.com/<user>/lakshya.git bash setup-lightsail.sh
#
# Optional: APP_PASSWORD=<secret> adds a password screen in front of the app (recommended on a public IP).
#
# Firewall: open TCP 8501 for the plain-HTTP setup, or TCP 80 + 443 when DOMAIN is set.

set -euo pipefail

REPO_URL="${REPO_URL:-}"
ZIP_PATH="${ZIP_PATH:-}"
if [ -z "$REPO_URL" ] && [ -z "$ZIP_PATH" ]; then
  echo "Set REPO_URL=<git repo url> or ZIP_PATH=<path to lakshya.zip> before running this script." >&2
  exit 1
fi
DOMAIN="${DOMAIN:-}"
APP_PASSWORD="${APP_PASSWORD:-}"
APP_DIR="${APP_DIR:-$HOME/lakshya}"
SERVICE="lakshya"
APP_USER="$(id -un)"
PORT=8501

log() { printf '\n==> %s\n' "$*"; }

log "Installing system packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip git curl unzip

if ! swapon --show --noheadings | grep -q '^/swapfile'; then
  log "Adding 1 GB swap (needed on the 512 MB plan)"
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

if [ -n "$ZIP_PATH" ]; then
  log "Installing code from $ZIP_PATH"
  [ -f "$ZIP_PATH" ] || { echo "Zip not found: $ZIP_PATH" >&2; exit 1; }
  TMP="$(mktemp -d)"
  unzip -q -o "$ZIP_PATH" -d "$TMP"
  SRC="$TMP"
  [ -f "$SRC/app.py" ] || SRC="$(find "$TMP" -maxdepth 2 -name app.py -printf '%h' -quit)"
  [ -n "$SRC" ] && [ -f "$SRC/app.py" ] || { echo "app.py not found inside the zip" >&2; exit 1; }
  mkdir -p "$APP_DIR"
  # Replace the code but keep data/ and the virtualenv from a previous install.
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name data ! -name .venv -exec rm -rf {} +
  cp -a "$SRC"/. "$APP_DIR"/
  rm -rf "$TMP"
elif [ -d "$APP_DIR/.git" ]; then
  log "Updating existing checkout in $APP_DIR"
  git -C "$APP_DIR" pull --ff-only
else
  log "Cloning $REPO_URL into $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

log "Installing Python dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# With a domain, only Caddy may talk to Streamlit; without one, expose it directly.
BIND_ADDR="0.0.0.0"
[ -n "$DOMAIN" ] && BIND_ADDR="127.0.0.1"

PASSWORD_LINE=""
[ -n "$APP_PASSWORD" ] && PASSWORD_LINE="Environment=APP_PASSWORD=${APP_PASSWORD}"

log "Writing systemd service (${SERVICE})"
sudo tee /etc/systemd/system/${SERVICE}.service >/dev/null <<EOF
[Unit]
Description=Lakshya dashboard
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=LAKSHYA_DATA_DIR=${APP_DIR}/data
${PASSWORD_LINE}
ExecStart=${APP_DIR}/.venv/bin/streamlit run app.py --server.address ${BIND_ADDR} --server.port ${PORT} --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE}" >/dev/null 2>&1 || true
sudo systemctl restart "${SERVICE}"

if [ -n "$DOMAIN" ]; then
  log "Installing Caddy for HTTPS on ${DOMAIN}"
  if ! command -v caddy >/dev/null 2>&1; then
    # Ubuntu's own package first; fall back to Caddy's official repository.
    if ! sudo apt-get install -y -qq caddy 2>/dev/null; then
      sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
      sudo apt-get update -qq && sudo apt-get install -y -qq caddy
    fi
  fi
  sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${DOMAIN} {
    reverse_proxy 127.0.0.1:${PORT}
}
EOF
  sudo systemctl enable caddy >/dev/null 2>&1 || true
  sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy
fi

sleep 3
log "Status"
systemctl is-active --quiet "${SERVICE}" && echo "${SERVICE}: running" || { echo "${SERVICE}: NOT running - see: journalctl -u ${SERVICE} -n 50"; exit 1; }

PUBLIC_IP="$(curl -s --max-time 5 https://checkip.amazonaws.com || true)"
if [ -n "$DOMAIN" ]; then
  echo "Open: https://${DOMAIN}   (first load may take ~30 s while the certificate is issued)"
else
  echo "Open: http://${PUBLIC_IP:-<your-static-ip>}:${PORT}"
fi
echo "Data for each owner lives in ${APP_DIR}/data (back this folder up)."
echo "Update later: re-run this script. Logs: journalctl -u ${SERVICE} -f"
