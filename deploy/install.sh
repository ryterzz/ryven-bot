#!/usr/bin/env bash
#
# Bootstraps ryven bot on a Debian/Ubuntu host (tested on Oracle Cloud
# Always-Free Ubuntu 24.04, arm64). Idempotent: safe to re-run to pull
# updates and restart the service.
#
#   sudo bash deploy/install.sh
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ryven-bot}"
SERVICE_USER="${SERVICE_USER:-ryven}"
REPO_URL="${REPO_URL:-https://github.com/ryterzz/ryven-bot.git}"

log() { printf '==> %s\n' "$1"; }

# 1. System packages. ffmpeg + libopus are required for the music cog;
#    python3-venv is required for the virtualenv below.
log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates \
  ffmpeg \
  git \
  libopus0 \
  python3 \
  python3-pip \
  python3-venv

# 2. Dedicated unprivileged service user.
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  log "Creating service user '$SERVICE_USER'"
  useradd --system --create-home --home-dir "/home/$SERVICE_USER" \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# 3. Application code.
if [ -d "$APP_DIR/.git" ]; then
  log "Updating existing checkout in $APP_DIR"
  git -C "$APP_DIR" pull --ff-only
  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
else
  log "Cloning repository into $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
fi

# 4. Virtualenv and Python dependencies.
log "Building virtualenv and installing dependencies"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -q --upgrade pip wheel
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# 5. Secrets. Stop here on first run so the token can be filled in.
if [ ! -f "$APP_DIR/.env" ]; then
  log "Created $APP_DIR/.env from .env.example"
  echo
  echo ">>> Add your bot token, then re-run this script:"
  echo "    sudo nano $APP_DIR/.env"
  echo "    sudo bash deploy/install.sh"
  exit 1
fi
chmod 600 "$APP_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"

# 6. systemd unit: restarts the bot on crash and on reboot.
log "Installing systemd unit"
install -m 644 "$APP_DIR/deploy/ryven-bot.service" /etc/systemd/system/ryven-bot.service
systemctl daemon-reload
systemctl enable ryven-bot.service >/dev/null
systemctl restart ryven-bot.service

# 7. Report.
sleep 4
log "Service status"
systemctl --no-pager --lines=0 status ryven-bot.service || true
echo
echo "Logs:    journalctl -u ryven-bot -f"
echo "Restart: systemctl restart ryven-bot"
echo "Stop:    systemctl stop ryven-bot"