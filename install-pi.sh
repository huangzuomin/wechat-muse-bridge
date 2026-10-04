#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/wechat-muse-bridge
CONFIG_DIR=/etc/wechat-muse-bridge
SERVICE=wechat-muse-bridge

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo ./install-pi.sh" >&2
  exit 1
fi
SERVICE_USER=${SERVICE_USER:-musebridge}
SERVICE_GROUP=${SERVICE_GROUP:-$SERVICE_USER}
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Required service account '$SERVICE_USER' does not exist." >&2
  exit 1
fi
if ! getent group "$SERVICE_GROUP" >/dev/null; then
  echo "Required service group '$SERVICE_GROUP' does not exist." >&2
  exit 1
fi
MUSEGADGET_BIN=$(sudo -u "$SERVICE_USER" sh -lc 'command -v musegadget' || true)
if [[ -z "$MUSEGADGET_BIN" || "$MUSEGADGET_BIN" != /* || ! "$MUSEGADGET_BIN" =~ ^/[A-Za-z0-9_./+-]+$ ]]; then
  echo "musegadget CLI must resolve to an absolute path using only letters, numbers, /, ., _, +, and -." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "$APP_DIR"
install -d -o root -g root -m 0755 "$CONFIG_DIR"
cp -a src pyproject.toml README.md "$APP_DIR/"
chown -R root:root "$APP_DIR"
python3 -m venv "$APP_DIR/venv"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install "$APP_DIR"
chown -R root:root "$APP_DIR/venv"

if [[ ! -e "$CONFIG_DIR/env" ]]; then
  install -o root -g "$SERVICE_GROUP" -m 0640 .env.example "$CONFIG_DIR/env"
  echo "Edit $CONFIG_DIR/env and set ALLOWED_USER_IDS before enabling the service." >&2
fi
DATA_DIR=$(sed -n 's/^WECHAT_MUSE_DATA_DIR=//p' "$CONFIG_DIR/env" | tail -n 1)
if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR=/var/lib/wechat-muse-bridge
fi
if [[ "$DATA_DIR" != /* || ! "$DATA_DIR" =~ ^/[A-Za-z0-9_./-]+$ || "$DATA_DIR" =~ (^|/)\.\.?(/|$) ]]; then
  echo "WECHAT_MUSE_DATA_DIR must be an absolute path using only letters, numbers, /, ., _, and -." >&2
  exit 1
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$DATA_DIR"
if grep -Eq '^MUSEGADGET_COMMAND[[:space:]]*=[[:space:]]*(musegadget)?[[:space:]]*$' "$CONFIG_DIR/env"; then
  sed -i "s|^MUSEGADGET_COMMAND=.*|MUSEGADGET_COMMAND=$MUSEGADGET_BIN|" "$CONFIG_DIR/env"
fi
chown root:"$SERVICE_GROUP" "$CONFIG_DIR/env"
chmod 0640 "$CONFIG_DIR/env"
sed -e "s/^User=.*/User=$SERVICE_USER/" -e "s/^Group=.*/Group=$SERVICE_GROUP/" \
  -e "s|^ReadWritePaths=.*|ReadWritePaths=$DATA_DIR|" \
  systemd/wechat-muse-bridge.service | install -o root -g root -m 0644 /dev/stdin "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
if grep -Eq '^ALLOWED_USER_IDS[[:space:]]*=[[:space:]]*(#.*)?$|replace-with-your-wechat-user-id' "$CONFIG_DIR/env"; then
  echo "Enrollment required. Run as $SERVICE_USER: $APP_DIR/venv/bin/wechat-muse-bridge enroll --env-file $CONFIG_DIR/env" >&2
  echo "Add the displayed sender ID to $CONFIG_DIR/env, then run: systemctl enable --now $SERVICE" >&2
  exit 2
fi
systemctl enable --now "$SERVICE"
systemctl --no-pager --full status "$SERVICE"
