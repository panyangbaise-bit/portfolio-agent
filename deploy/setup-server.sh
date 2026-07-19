#!/usr/bin/env bash
# One-shot deploy for Ubuntu (venv + systemd).
#
# Usage (recommended):
#   git clone https://github.com/panyangbaise-bit/portfolio-agent.git /opt/portfolio-agent
#   cd /opt/portfolio-agent
#   sudo ./deploy/setup-server.sh
#
# Optional env overrides:
#   APP_DIR=/opt/portfolio-agent
#   REPO_URL=https://github.com/panyangbaise-bit/portfolio-agent.git
#   BRANCH=main
#   SERVICE_USER=admin
#   SKIP_START=1

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/portfolio-agent}"
REPO_URL="${REPO_URL:-https://github.com/panyangbaise-bit/portfolio-agent.git}"
BRANCH="${BRANCH:-main}"
SKIP_START="${SKIP_START:-0}"
SERVICE_NAME="portfolio-agent"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() { echo "[deploy] $*"; }
die() { echo "[deploy] ERROR: $*" >&2; exit 1; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "请用 root 或 sudo 运行：sudo ./deploy/setup-server.sh"
  fi
}

detect_service_user() {
  if [[ -n "${SERVICE_USER:-}" ]]; then
    echo "${SERVICE_USER}"
    return
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    echo "${SUDO_USER}"
    return
  fi
  # Prefer a non-root login user if present.
  if id -u admin &>/dev/null; then
    echo "admin"
    return
  fi
  if id -u ubuntu &>/dev/null; then
    echo "ubuntu"
    return
  fi
  echo "root"
}

ensure_packages() {
  log "安装系统依赖..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip git curl ca-certificates
}

sync_app_code() {
  if [[ -f "${REPO_ROOT}/app/main.py" && -f "${REPO_ROOT}/requirements.txt" ]]; then
    if [[ "${REPO_ROOT}" == "${APP_DIR}" ]]; then
      log "使用当前仓库目录：${APP_DIR}"
      return
    fi
    log "从 ${REPO_ROOT} 同步代码到 ${APP_DIR}"
    mkdir -p "${APP_DIR}"
    # Prefer rsync when available; fall back to tar.
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete \
        --exclude '.venv' \
        --exclude '.git' \
        --exclude 'portfolio.db' \
        --exclude 'data/ip_blacklist.json' \
        --exclude '.env' \
        "${REPO_ROOT}/" "${APP_DIR}/"
    else
      mkdir -p "${APP_DIR}"
      tar -C "${REPO_ROOT}" \
        --exclude='.venv' --exclude='.git' --exclude='portfolio.db' \
        --exclude='data/ip_blacklist.json' --exclude='.env' \
        -cf - . | tar -C "${APP_DIR}" -xf -
    fi
    return
  fi

  if [[ -d "${APP_DIR}/.git" ]]; then
    log "更新已有仓库 ${APP_DIR} (branch=${BRANCH})"
    git -C "${APP_DIR}" fetch --depth 1 origin "${BRANCH}"
    git -C "${APP_DIR}" checkout "${BRANCH}"
    git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}" || true
    return
  fi

  log "克隆 ${REPO_URL} → ${APP_DIR}"
  mkdir -p "$(dirname "${APP_DIR}")"
  git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${APP_DIR}"
}

setup_venv() {
  log "创建/更新 Python venv 并安装依赖..."
  cd "${APP_DIR}"
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -U pip wheel
  pip install -r requirements.txt
}

setup_env_file() {
  if [[ -f "${APP_DIR}/.env" ]]; then
    log "已存在 .env，保留不覆盖"
    return
  fi
  log "从 .env.example 生成 .env（请编辑密钥与 AUTH_PASSWORD）"
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  # First-time public deploy defaults (operator should set AUTH_PASSWORD).
  sed -i 's/^AUTH_ENABLED=.*/AUTH_ENABLED=true/' "${APP_DIR}/.env"
}

fix_ownership() {
  local user="$1"
  local group
  group="$(id -gn "${user}")"
  log "设置目录属主 ${user}:${group}"
  chown -R "${user}:${group}" "${APP_DIR}"
  # Keep .env private.
  chmod 600 "${APP_DIR}/.env" || true
}

install_systemd_unit() {
  local user="$1"
  local group
  group="$(id -gn "${user}")"
  local unit_src="${APP_DIR}/deploy/portfolio-agent.service"
  local unit_dst="/etc/systemd/system/${SERVICE_NAME}.service"

  [[ -f "${unit_src}" ]] || die "缺少 ${unit_src}"

  log "安装 systemd 单元 → ${unit_dst}"
  sed \
    -e "s|__SERVICE_USER__|${user}|g" \
    -e "s|__SERVICE_GROUP__|${group}|g" \
    -e "s|__APP_DIR__|${APP_DIR}|g" \
    "${unit_src}" > "${unit_dst}"

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  if [[ "${SKIP_START}" == "1" ]]; then
    log "跳过启动（SKIP_START=1）"
    return
  fi
  systemctl restart "${SERVICE_NAME}"
  sleep 2
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
}

print_next_steps() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo
  log "部署完成。"
  echo "  1) 编辑配置：  sudo nano ${APP_DIR}/.env"
  echo "     必填 DEEPSEEK_API_KEY；公网务必设置 AUTH_PASSWORD"
  echo "  2) 重启服务：  sudo systemctl restart ${SERVICE_NAME}"
  echo "  3) 查看日志：  journalctl -u ${SERVICE_NAME} -f"
  echo "  4) 访问地址：  http://${ip:-YOUR_SERVER_IP}:8501"
  echo "  5) 云安全组 / ufw 放行 8501（以及 22）"
  echo
}

main() {
  need_root
  local user
  user="$(detect_service_user)"
  id -u "${user}" >/dev/null || die "服务用户不存在：${user}"

  log "APP_DIR=${APP_DIR}"
  log "SERVICE_USER=${user}"

  ensure_packages
  sync_app_code
  setup_venv
  setup_env_file
  fix_ownership "${user}"
  install_systemd_unit "${user}"
  print_next_steps
}

main "$@"
