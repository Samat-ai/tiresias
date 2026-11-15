#!/bin/sh
set -eu

# Called by scripts/deploy_vultr.py after the source and environment are staged.
release_id="$1"
hostname="$2"
case "$release_id" in *[!0-9a-z-]*|'') exit 2 ;; esac
case "$hostname" in *[!0-9a-z.-]*|'') exit 2 ;; esac
site_hosts="$hostname"
shift 2
for alias in "$@"; do
    case "$alias" in *[!0-9a-z.-]*|'') exit 2 ;; esac
    site_hosts="$site_hosts, $alias"
done
release_dir="/opt/tiresias/releases/$release_id"
test -d "$release_dir/deploy"
test -f "/etc/tiresias/tiresias.env"

export DEBIAN_FRONTEND=noninteractive
if test "$(dpkg-query -W -f='${Status}' python3-venv 2>/dev/null || true)" != 'install ok installed' ||
   test "$(dpkg-query -W -f='${Status}' caddy 2>/dev/null || true)" != 'install ok installed'; then
    apt-get update -qq
    apt-get -o DPkg::Lock::Timeout=180 install -y -qq python3-venv caddy
fi
if ! id tiresias >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/tiresias --create-home --shell /usr/sbin/nologin tiresias
fi
install -d -o tiresias -g tiresias -m 0750 /var/lib/tiresias
chown root:tiresias /etc/tiresias/tiresias.env
chmod 0640 /etc/tiresias/tiresias.env
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/pip" install --disable-pip-version-check --quiet -e "$release_dir"

# Keep the previous release available for rollback. Never copy local credentials
# into a release or run the camera/FaceTime worker on this web-only host.
if test -L /opt/tiresias/current; then
    readlink -f /opt/tiresias/current > /opt/tiresias/previous-release
fi
ln -sfn "$release_dir" /opt/tiresias/current
install -m 0644 "$release_dir/deploy/tiresias-web.service" /etc/systemd/system/tiresias-web.service
sed "s/__HOSTNAMES__/$site_hosts/g" "$release_dir/deploy/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl enable tiresias-web caddy
systemctl restart tiresias-web
ufw allow 80/tcp
ufw allow 443/tcp
systemctl restart caddy

attempt=0
until curl --silent --fail http://127.0.0.1:8000/healthz; do
    attempt=$((attempt + 1))
    if test "$attempt" -ge 15; then
        echo 'Web health check failed; inspect journalctl -u tiresias-web.' >&2
        exit 1
    fi
    sleep 2
done
printf '\nWeb service healthy. HTTPS hostname: %s\n' "$hostname"
