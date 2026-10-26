#!/usr/bin/env bash
# Atualiza o agente na VPS: baixa o código novo, instala dependências e reinicia.
#   sudo bash /opt/agente/deploy/atualizar.sh
set -euo pipefail
APP_DIR=/opt/agente
[ "$(id -u)" -eq 0 ] || { echo "rode como root: sudo bash $0" >&2; exit 1; }

echo "==> backup antes de atualizar"
runuser -u agente -- "$APP_DIR/.venv/bin/agente-backup" --destino /var/lib/agente/backups --manter 14

echo "==> código"
runuser -u agente -- git -C "$APP_DIR" pull --ff-only

echo "==> dependências"
runuser -u agente -- "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
runuser -u agente -- env HOME=/var/lib/agente "$APP_DIR/.venv/bin/python" -m playwright install chromium

echo "==> serviços"
install -m 644 "$APP_DIR"/deploy/agente*.service "$APP_DIR"/deploy/agente*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart agente
sleep 3
systemctl --no-pager --lines=5 status agente
