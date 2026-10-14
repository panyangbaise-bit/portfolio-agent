#!/usr/bin/env bash
# Native Qdrant v1.18.0 on Ubuntu/systemd; does not touch Portfolio Agent or its .env.
# Usage: sudo bash deploy/setup-qdrant.sh
# SKIP_START=1 installs without starting. Existing custom config/unit is preserved.
set -euo pipefail
die() { echo "[qdrant] $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || die 'Requires Linux with systemd.'
[[ ${EUID} -eq 0 ]] || die 'Run with sudo.'
[[ -d /run/systemd/system ]] || die 'systemd must be running.'
for tool in curl sha256sum tar systemctl install cmp; do
  command -v "$tool" >/dev/null || die "Missing dependency: $tool"
done
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname -m)" in
  x86_64) target=x86_64-unknown-linux-musl
    digest=76c38c3859682776d2bef61bf6c23b593b7c06682578f7c9ff9eac79c87a4268 ;;
  aarch64|arm64) target=aarch64-unknown-linux-musl
    digest=0d3c8bad27633475990b2108d0ca63a7f9d3ae5e2d85e082ef98bc004e544246 ;;
  *) die 'Supported architectures: x86_64 and aarch64.' ;;
esac
# Do not overwrite operator customizations or restart an existing deployment.
config_dst=/etc/portfolio-qdrant/config.yaml
unit_dst=/etc/systemd/system/portfolio-qdrant.service
for pair in "qdrant.yaml:$config_dst" "portfolio-qdrant.service:$unit_dst"; do
  src=${pair%%:*}; dst=${pair#*:}
  if [[ -e "$dst" ]] && ! cmp -s "$script_dir/$src" "$dst"; then
    die "Existing customized file: $dst. Review and merge manually before rerunning."
  fi
done
if [[ ! -e "$unit_dst" ]] && curl -fsS --max-time 2 http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
  die 'Port 6333 already serves Qdrant. Keep the existing deployment; do not initialize a second store.'
fi
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
curl --fail --location --retry 3 --connect-timeout 15 --max-time 300 \
  "https://github.com/qdrant/qdrant/releases/download/v1.18.0/qdrant-${target}.tar.gz" -o "$stage/qdrant.tar.gz"
printf '%s  %s\n' "$digest" "$stage/qdrant.tar.gz" | sha256sum --check --status || die 'Release checksum mismatch.'
tar -xzf "$stage/qdrant.tar.gz" -C "$stage" qdrant
"$stage/qdrant" --version
binary_dst=/opt/portfolio-qdrant/v1.18.0/qdrant
install -d -m 0755 /opt/portfolio-qdrant/v1.18.0 /etc/portfolio-qdrant
if [[ -e "$binary_dst" ]]; then
  cmp -s "$stage/qdrant" "$binary_dst" || die 'Installed binary differs; refusing to replace it.'
else
  install -m 0755 "$stage/qdrant" "$binary_dst"
fi
[[ -e "$config_dst" ]] || install -m 0644 "$script_dir/qdrant.yaml" "$config_dst"
[[ -e "$unit_dst" ]] || install -m 0644 "$script_dir/portfolio-qdrant.service" "$unit_dst"
systemctl daemon-reload
systemctl enable portfolio-qdrant.service
if [[ ${SKIP_START:-0} == 1 ]]; then
  echo '[qdrant] Installed. Start with: sudo systemctl start portfolio-qdrant'
  exit 0
fi
systemctl start portfolio-qdrant.service
for attempt in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:6333/healthz >/dev/null; then
    echo '[qdrant] Ready at http://127.0.0.1:6333; persistent data: /var/lib/portfolio-qdrant'
    exit 0
  fi
  sleep 1
done
die 'Health check failed. Inspect: journalctl -u portfolio-qdrant -n 50 --no-pager'
