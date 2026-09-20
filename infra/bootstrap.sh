#!/usr/bin/env bash
set -euo pipefail
dnf install -y docker nginx python3
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins /opt/stateproof/releases
cd /usr/local/lib/docker/cli-plugins
curl --fail --location --retry 3 https://github.com/docker/compose/releases/download/v2.39.2/docker-compose-linux-x86_64 -o docker-compose
curl --fail --location --retry 3 https://github.com/docker/compose/releases/download/v2.39.2/docker-compose-linux-x86_64.sha256 -o compose.sha256
# Upstream checksum references its release filename.
expected=$(cut -d ' ' -f 1 compose.sha256)
printf '%s  docker-compose\n' "$expected" | sha256sum -c -
chmod 755 docker-compose
cat > /etc/nginx/nginx.conf <<'NGINX'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;
events { worker_connections 1024; }
http {
  include /etc/nginx/mime.types;
  server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 256k;
    location / {
      limit_except GET { deny all; }
      proxy_pass http://127.0.0.1:8000;
      proxy_set_header Host $host;
      proxy_read_timeout 30s;
    }
  }
}
NGINX
nginx -t
systemctl enable --now nginx
touch /opt/stateproof/bootstrap-ready
