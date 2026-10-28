# Produção na VPS

Como colocar o agente para rodar 24 horas numa VPS própria: serviço que reinicia sozinho, HTTPS para o WhatsApp, backups diários e alerta quando cair.

## O que você precisa

- **VPS com Ubuntu 24.04** (ou Debian 12), **2 GB de RAM** no mínimo (o Chromium e o Claude Code pesam) e 20 GB de disco. Qualquer provedor serve.
- **Um domínio** (ou subdomínio) apontando para o IP da VPS: registro DNS do tipo **A**, por exemplo `agente.seudominio.com.br`. É o endereço do webhook do WhatsApp.
- **Chave SSH** no seu computador. Se ainda não tem, crie com o comando abaixo:

```bash
ssh-keygen -t ed25519
```

## Passo a passo

1. **Cadastre sua chave na VPS** (pede a senha uma última vez):

```bash
ssh-copy-id root@IP_DA_VPS
```

2. **Entre na VPS e baixe o script:**

```bash
ssh root@IP_DA_VPS
curl -fsSLO https://raw.githubusercontent.com/criatedavid-tech/agent/claude/kind-gates-dw46rj/deploy/provisionar.sh
```

3. **Rode o provisionamento** (leva alguns minutos):

```bash
sudo bash provisionar.sh --dominio agente.seudominio.com.br
```

4. **Preencha o `.env`** (chave da Anthropic e, se for usar, as variáveis `WHATSAPP_*`):

```bash
sudo nano /opt/agente/.env
```

5. **Reinicie e veja os logs:**

```bash
sudo systemctl restart agente
sudo journalctl -u agente -f
```

6. **WhatsApp:** na Meta, cadastre o webhook `https://agente.seudominio.com.br/whatsapp/webhook` (veja [whatsapp.md](whatsapp.md)).

## O que o script faz

| Passo | Detalhe |
|---|---|
| Sistema | atualiza tudo e liga **atualizações de segurança automáticas** |
| Usuário | cria `agente`, **sem senha, sem login e sem sudo** |
| Código | clona em `/opt/agente`, cria o venv, instala as dependências e o Chromium |
| `.env` | cria a partir do exemplo, com `AGENT_BROWSER_HEADLESS=true` (VPS não tem tela) e permissão `600` |
| Serviço | `agente.service` com reinício automático e **prisão do processo** (abaixo) |
| Backup | `agente-backup.timer`: todo dia às 03:30, guarda 14 dias em `/var/lib/agente/backups` |
| Vigia | `agente-vigia.timer`: a cada 5 min confere se o agente responde; avisa no WhatsApp quando cai e quando volta |
| HTTPS | **Caddy** com certificado automático; **só o webhook do WhatsApp fica público** |
| Firewall | `ufw` liberando só SSH, 80 e 443 |
| SSH | `fail2ban` contra força bruta; **login por senha desligado** (só se já houver uma chave cadastrada, para você não ficar trancado fora) |

Pode rodar o script de novo quando quiser: cada passo confere se já foi feito.

## A prisão do processo

O agente roda comandos sem pedir confirmação. Os hooks de segurança barram o óbvio; na VPS, o próprio sistema operacional limita o resto (`deploy/agente.service`):

- roda como o usuário `agente`, sem privilégios e sem poder ganhar novos (`NoNewPrivileges`);
- o sistema inteiro é **somente leitura** para ele (`ProtectSystem=strict`); só escreve em `/opt/agente` e `/var/lib/agente`;
- **o próprio código, o venv, o plugin de skills e o `.env` são somente leitura**: ele não consegue se reprogramar nem trocar as chaves;
- sem acesso a `/home`, ao kernel e ao relógio do sistema; memória limitada a 1,8 GB (acima disso o serviço reinicia em vez de travar a VPS).

## Acessar o painel e o chat

Eles **não ficam expostos na internet**. Use um túnel SSH a partir do seu computador:

```bash
ssh -L 8000:127.0.0.1:8000 root@IP_DA_VPS
```

Com o túnel aberto, acesse http://127.0.0.1:8000 (chat) e http://127.0.0.1:8000/painel no seu navegador.

## Dia a dia

| Tarefa | Comando |
|---|---|
| Ver se está rodando | `sudo systemctl status agente` |
| Logs ao vivo | `sudo journalctl -u agente -f` |
| Reiniciar | `sudo systemctl restart agente` |
| Atualizar para a versão nova (faz backup antes) | `sudo bash /opt/agente/deploy/atualizar.sh` |
| Backup agora | `sudo -u agente /opt/agente/.venv/bin/agente-backup --destino /var/lib/agente/backups` |
| Últimos alertas do vigia | `sudo journalctl -u agente-vigia -n 20` |

## Restaurar um backup

```bash
sudo systemctl stop agente
cd /opt/agente
sudo -u agente tar xzf /var/lib/agente/backups/agente-backup-AAAAMMDD-HHMMSS.tar.gz
sudo systemctl start agente
```

O backup traz memória, base de conhecimento, agenda e conversas. **Não traz o `.env`**: guarde as chaves num cofre de senhas. Os logins do navegador só entram com `--com-navegador`.

**Copie os backups para fora da VPS** de vez em quando (se o provedor perder a VPS, os backups vão junto). Do seu computador:

```bash
scp root@IP_DA_VPS:/var/lib/agente/backups/*.tar.gz .
```

## Testar o deploy sem VPS

Antes de mexer em `deploy/`, teste num Ubuntu 24.04 descartável com Docker. Primeiro faça commit (o teste clona os commits locais) e depois rode, na pasta do projeto:

```bash
docker run --rm -v "$PWD:/src:ro" ubuntu:24.04 bash /src/deploy/testar-no-container.sh
```

No Git Bash do Windows, coloque `MSYS_NO_PATHCONV=1` antes do comando.

Ele roda o `provisionar.sh` duas vezes, valida as units com `systemd-analyze`, sobe o agente como o usuário `agente`, confere que o Caddy só deixa passar o webhook, testa backup, vigia, Chromium invisível e Claude Code, e roda a suíte inteira no Python do Ubuntu. Container não tem systemd, então serviços, firewall e SSH só são testados numa VPS de verdade.

## Limitações atuais

- O navegador próprio roda invisível na VPS. Logins e verificações se resolvem pela tela remota: o aviso de login expirado traz um link temporário (precisa de `--dominio`, que preenche `AGENT_PUBLIC_URL`). Veja [acessos.md](acessos.md).
- O backup ainda não leva a pasta `navegador/` (logins salvos): se a VM for perdida, alguém da equipe entra de novo pela tela remota.
- O alerta do vigia pelo WhatsApp segue a regra das 24 h da Meta. Fora dela, o registro fica em `journalctl -u agente-vigia`.
