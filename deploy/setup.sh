#!/usr/bin/env bash
# Sets up the Loupe backend on a fresh Ubuntu 24.04 server. Safe to run again to update.
# Usage: sudo DOMAIN=203-0-113-7.sslip.io [BRANCH=main] bash deploy/setup.sh
# Secrets live in /etc/loupe/backend.env, which this script never writes.
set -euo pipefail

: "${DOMAIN:?Set DOMAIN, for example 203-0-113-7.sslip.io}"
REPO_URL="${REPO_URL:-https://github.com/ethantao14/loupe.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/loupe
ENV_FILE=/etc/loupe/backend.env

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Create it from deploy/backend.env.example first." >&2
  exit 1
fi

echo "==> System packages"
# Stops iptables-persistent's install prompt from blocking; the rules are saved below.
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io git curl debian-keyring debian-archive-keyring apt-transport-https iptables-persistent
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "==> Firewall"
# Oracle's Ubuntu images reject everything except SSH in iptables, on top of the
# cloud security list, so both have to allow web traffic.
for port in 80 443; do
  rule=(-p tcp -m state --state NEW -m tcp --dport "$port" -j ACCEPT)
  iptables -C INPUT "${rule[@]}" 2>/dev/null && continue
  # Insert ahead of the image's catch-all REJECT, or append when there is none.
  reject=$(iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" { print $1; exit }')
  if [[ -n $reject ]]; then
    iptables -I INPUT "$reject" "${rule[@]}"
  else
    iptables -A INPUT "${rule[@]}"
  fi
done
netfilter-persistent save

echo "==> Service user and code"
id loupe >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/loupe --shell /usr/sbin/nologin loupe
usermod -aG docker loupe
if [[ -d "$APP_DIR/.git" ]]; then
  # The checkout belongs to loupe, and git refuses to work in it as root.
  sudo -u loupe git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  sudo -u loupe git -C "$APP_DIR" reset --quiet --hard FETCH_HEAD
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R loupe:loupe "$APP_DIR"
chown root:loupe "$ENV_FILE"
chmod 640 "$ENV_FILE"

echo "==> Python 3.13 and dependencies"
# CI tests on 3.13; Ubuntu 24.04 ships 3.12, so install the exact version.
sudo -u loupe -H bash -c '
  set -euo pipefail
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  cd /opt/loupe/backend
  uv python install 3.13
  [[ -d .venv ]] || uv venv --python 3.13 .venv
  uv pip install --quiet --python .venv/bin/python -r requirements.txt -r requirements-embeddings.txt
  .venv/bin/huggingface-cli download --quiet voyageai/voyage-4-nano >/dev/null
'

echo "==> Sandbox image"
docker pull --quiet python:3.13-slim

echo "==> Services"
install -m 644 "$APP_DIR/deploy/loupe-backend.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/loupe-keepalive.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/loupe-keepalive.timer" /etc/systemd/system/
sed "s/{\$DOMAIN}/$DOMAIN/" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now loupe-backend.service loupe-keepalive.timer
systemctl restart loupe-backend.service
systemctl reload caddy || systemctl restart caddy

echo "==> Waiting for the backend"
for _ in $(seq 60); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "Backend healthy. Public URL: https://$DOMAIN"
    exit 0
  fi
  sleep 2
done
echo "Backend did not become healthy. Check: journalctl -u loupe-backend -n 50" >&2
exit 1
