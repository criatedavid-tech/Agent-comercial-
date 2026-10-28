#!/usr/bin/env bash
# Prepara uma VPS Ubuntu 24.04 (ou Debian 12) para rodar o agente pessoal.
#
#   sudo bash provisionar.sh --dominio agente.seudominio.com.br
#
# Opções:
#   --dominio D     domínio que aponta para esta VPS (obrigatório para o HTTPS do WhatsApp)
#   --repo URL      repositório (padrão: https://github.com/criatedavid-tech/agent.git)
#   --branch B      branch (padrão: claude/kind-gates-dw46rj)
#
# Pode rodar de novo quantas vezes quiser: cada passo confere se já foi feito.
# Em container sem systemd (testes), os passos de serviço, firewall e SSH são pulados.
set -euo pipefail

REPO="https://github.com/criatedavid-tech/agent.git"
BRANCH="claude/kind-gates-dw46rj"
DOMINIO=""
APP_DIR=/opt/agente
APP_USER=agente
APP_HOME=/var/lib/agente

while [ $# -gt 0 ]; do
  case "$1" in
    --dominio) DOMINIO="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

passo() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }
como_agente() { runuser -u "$APP_USER" -- "$@"; }

[ "$(id -u)" -eq 0 ] || erro "rode como root: sudo bash $0 ..."
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) erro "sistema não suportado: $PRETTY_NAME (use Ubuntu 24.04 ou Debian 12)" ;; esac
TEM_SYSTEMD=0
[ -d /run/systemd/system ] && TEM_SYSTEMD=1

passo "Atualizando o sistema e instalando pacotes"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q python3 python3-venv python3-pip git curl ca-certificates gnupg \
  ufw fail2ban unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || erro "precisa de Python 3.11 ou mais novo (este sistema tem $(python3 --version))"

passo "Atualizações de segurança automáticas"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

passo "Instalando o Caddy (HTTPS automático)"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

passo "Usuário do sistema '$APP_USER' (sem senha, sem login, sem sudo)"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$APP_HOME" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_HOME/backups"
chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod 750 "$APP_HOME"

passo "Código em $APP_DIR ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  como_agente git -C "$APP_DIR" pull --ff-only
else
  install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
  como_agente git clone --branch "$BRANCH" "$REPO" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"

passo "Ambiente Python e dependências"
[ -x "$APP_DIR/.venv/bin/python" ] || como_agente python3 -m venv "$APP_DIR/.venv"
como_agente "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
como_agente "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"

passo "Navegador próprio (Chromium e bibliotecas do sistema)"
"$APP_DIR/.venv/bin/python" -m playwright install-deps chromium
como_agente env HOME="$APP_HOME" "$APP_DIR/.venv/bin/python" -m playwright install chromium

passo "Pastas de dados"
for d in workspace memory conhecimento logs navegador; do
  install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$APP_DIR/$d"
done

passo "Arquivo .env"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  # Na VPS não há tela: o navegador próprio roda invisível.
  sed -i 's/^AGENT_BROWSER_HEADLESS=.*/AGENT_BROWSER_HEADLESS=true/' "$APP_DIR/.env"
  aviso "criei $APP_DIR/.env a partir do exemplo: preencha ANTHROPIC_API_KEY e as variáveis WHATSAPP_*"
fi
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

if [ -n "$DOMINIO" ]; then
  passo "Caddy para https://$DOMINIO (só o webhook do WhatsApp fica público)"
  sed "s/DOMINIO_AQUI/$DOMINIO/" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
  # Links da tela remota do navegador (login nos sistemas da loja) saem com este domínio.
  sed -i "s|^AGENT_PUBLIC_URL=.*|AGENT_PUBLIC_URL=https://$DOMINIO|" "$APP_DIR/.env"
  mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy 2>/dev/null || true
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
else
  aviso "sem --dominio: o HTTPS do WhatsApp não foi configurado (rode de novo com --dominio quando tiver um)"
fi

if [ "$TEM_SYSTEMD" -eq 0 ]; then
  aviso "sem systemd (container?): pulei serviços, firewall e SSH"
  exit 0
fi

passo "Serviços: agente, backup diário e vigia"
install -m 644 "$APP_DIR"/deploy/agente*.service "$APP_DIR"/deploy/agente*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now agente-backup.timer agente-vigia.timer
systemctl enable agente.service
systemctl restart agente.service
if [ -n "$DOMINIO" ]; then
  systemctl reload caddy
fi

passo "Firewall (SSH, HTTP e HTTPS)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n '1,10p'

passo "Proteção contra força bruta no SSH (fail2ban)"
systemctl enable --now fail2ban

passo "SSH só com chave"
TEM_CHAVE=0
for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do
  [ -s "$f" ] && TEM_CHAVE=1
done
if [ "$TEM_CHAVE" -eq 1 ]; then
  cat > /etc/ssh/sshd_config.d/90-agente.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  sshd -t && systemctl reload ssh
else
  aviso "nenhuma chave SSH cadastrada: mantive o login por senha para você não ficar trancado fora."
  aviso "cadastre a sua (ssh-copy-id usuario@vps) e rode este script de novo."
fi

passo "Pronto"
sleep 3
systemctl --no-pager --lines=0 status agente.service || true
cat <<EOF

Próximos passos:
  1. Preencha o .env:        sudo nano $APP_DIR/.env
  2. Reinicie o agente:      sudo systemctl restart agente
  3. Veja os logs:           sudo journalctl -u agente -f
  4. Painel no seu PC:       ssh -L 8000:127.0.0.1:8000 $(logname 2>/dev/null || echo usuario)@<ip-da-vps>
                             e abra http://127.0.0.1:8000
EOF
if [ -n "$DOMINIO" ]; then
  echo "  5. Webhook na Meta:       https://$DOMINIO/whatsapp/webhook"
fi
