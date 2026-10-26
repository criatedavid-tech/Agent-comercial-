#!/usr/bin/env bash
# Testa o deploy da VPS num Ubuntu 24.04 limpo, sem tocar no seu computador. Do Windows/Linux/Mac, na pasta do projeto:
#   docker run --rm -v "$PWD:/src:ro" ubuntu:24.04 bash /src/deploy/testar-no-container.sh
# (no Git Bash do Windows, prefixe com MSYS_NO_PATHCONV=1). Clona os commits locais: faça commit antes.
set -uo pipefail
ok() { printf 'OK   %s\n' "$*"; }
falha() { printf 'FALHA %s\n' "$*"; FALHAS=$((FALHAS+1)); }
FALHAS=0

apt-get update -q >/dev/null && apt-get install -y -q git ca-certificates curl >/dev/null
git config --system --add safe.directory '*'

echo "=== provisionar.sh ==="
if bash /src/deploy/provisionar.sh --dominio agente.exemplo.com --repo /src --branch claude/kind-gates-dw46rj > /tmp/prov.log 2>&1; then
  ok "provisionar.sh terminou sem erro"
else
  falha "provisionar.sh falhou"; tail -40 /tmp/prov.log; exit 1
fi
grep -E "aviso|==>" /tmp/prov.log | sed 's/\x1b\[[0-9;]*m//g'

echo "=== segunda execução (idempotente) ==="
bash /src/deploy/provisionar.sh --dominio agente.exemplo.com --repo /src --branch claude/kind-gates-dw46rj > /tmp/prov2.log 2>&1 \
  && ok "rodar de novo funciona" || { falha "segunda execução"; tail -20 /tmp/prov2.log; }

echo "=== arquivos e permissões ==="
id agente && ok "usuário agente existe"
[ "$(stat -c %a /opt/agente/.env)" = 600 ] && ok ".env com permissão 600" || falha ".env permissão $(stat -c %a /opt/agente/.env)"
grep -q '^AGENT_BROWSER_HEADLESS=true' /opt/agente/.env && ok "navegador invisível na VPS" || falha "headless"
[ "$(stat -c %U /opt/agente/agente/core.py)" = agente ] && ok "código pertence ao agente" || falha "dono do código"
grep -q 'agente.exemplo.com {' /etc/caddy/Caddyfile && ok "Caddyfile com o domínio" || falha "Caddyfile"
[ -f /etc/apt/apt.conf.d/20auto-upgrades ] && ok "atualizações automáticas" || falha "auto-upgrades"

echo "=== units do systemd ==="
apt-get install -y -q systemd >/dev/null 2>&1
cp /opt/agente/deploy/agente*.service /opt/agente/deploy/agente*.timer /etc/systemd/system/
for u in agente.service agente-backup.service agente-vigia.service agente-backup.timer agente-vigia.timer; do
  out=$(systemd-analyze verify "/etc/systemd/system/$u" 2>&1 | grep -v -E "Cannot add dependency|Failed to open /dev/tty|bpf|cgroup" || true)
  [ -z "$out" ] && ok "systemd-analyze verify $u" || { falha "verify $u"; echo "$out"; }
done

echo "=== servidor rodando como agente ==="
runuser -u agente -- env HOME=/var/lib/agente sh -c 'cd /opt/agente && .venv/bin/agente-web > /tmp/web.log 2>&1 &'
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8000/api/status >/dev/null && break; sleep 1; done
curl -sf http://127.0.0.1:8000/api/status && echo && ok "agente-web responde em 127.0.0.1:8000" || { falha "agente-web não subiu"; cat /tmp/web.log; }
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: agente.exemplo.com' http://127.0.0.1:8000/api/painel)
[ "$code" = 403 ] && ok "painel recusado pelo domínio público (403)" || falha "painel com Host público deu $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: agente.exemplo.com' -X POST http://127.0.0.1:8000/whatsapp/webhook)
[ "$code" = 404 ] && ok "webhook alcançável pelo domínio (404: WhatsApp ainda não configurado)" || falha "webhook deu $code"

echo "=== Caddy: só o webhook passa ==="
sed 's/^agente.exemplo.com {/:8080 {/; /output file/d; /^\tlog {/,/^\t}/d' /etc/caddy/Caddyfile > /tmp/Caddyfile.http
caddy start --config /tmp/Caddyfile.http --adapter caddyfile >/dev/null 2>&1; sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8080/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=x')
[ "$code" = 403 ] && ok "Caddy repassa o webhook ao agente (403 do token = chegou no agente)" || falha "webhook via Caddy deu $code"
for path in /api/painel / /painel /api/conversas; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8080$path")
  [ "$code" = 404 ] && ok "Caddy bloqueia $path (404)" || falha "Caddy deixou passar $path ($code)"
done
caddy stop >/dev/null 2>&1

echo "=== backup e vigia ==="
runuser -u agente -- env HOME=/var/lib/agente sh -c 'cd /opt/agente && .venv/bin/agente-backup --destino /var/lib/agente/backups' && ok "backup" || falha "backup"
ls /var/lib/agente/backups/*.tar.gz >/dev/null && ok "arquivo de backup criado"
runuser -u agente -- env HOME=/var/lib/agente sh -c 'cd /opt/agente && .venv/bin/agente-vigia' | grep -q "vigia: ok" && ok "vigia vê o agente no ar" || falha "vigia"

echo "=== navegador invisível e Claude Code (Linux) ==="
runuser -u agente -- env HOME=/var/lib/agente sh -c 'cd /opt/agente && .venv/bin/python -c "
import asyncio
from agente import config
from agente.core import Agent
async def main():
    a = Agent(config.load())
    print((await a.browser.open(\"https://example.com\")).splitlines()[0])
    await a.browser.close()
    await a.start()
    info = await a.client.get_server_info() or {}
    await a.stop()
    print(\"claude code:\", info.get(\"claude_code_version\"), \"hooks:\", info.get(\"hooks_applied\"))
asyncio.run(main())
"' > /tmp/agent.log 2>&1
grep -q "Página: Example Domain" /tmp/agent.log && ok "Chromium invisível abriu um site" || { falha "navegador"; tail -5 /tmp/agent.log; }
grep -q "hooks: True" /tmp/agent.log && ok "Claude Code conectou no Linux ($(grep -o 'claude code: [^ ]*' /tmp/agent.log))" || { falha "claude code"; tail -5 /tmp/agent.log; }

echo "=== suíte de testes no Python do Ubuntu ($(python3 --version)) ==="
runuser -u agente -- sh -c 'cd /opt/agente && .venv/bin/pip install -q -e ".[dev]"' >/dev/null 2>&1
runuser -u agente -- env HOME=/var/lib/agente sh -c 'cd /opt/agente && .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3' > /tmp/pytest.log
cat /tmp/pytest.log
grep -qE "^[0-9]+ passed" /tmp/pytest.log && ! grep -q "failed" /tmp/pytest.log && ok "pytest passou no Python do Ubuntu" || falha "pytest no Ubuntu"

echo
[ "$FALHAS" -eq 0 ] && echo "RESULTADO: tudo certo" || echo "RESULTADO: $FALHAS falha(s)"
