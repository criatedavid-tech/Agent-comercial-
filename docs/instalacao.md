# Instalação

## 1. Pré-requisitos

| Item | Como conseguir |
|---|---|
| Python 3.11 ou mais novo | `python3 --version`; se faltar: [python.org](https://www.python.org/downloads/) |
| Git | [git-scm.com](https://git-scm.com) |
| Chave da API da Anthropic | [console.anthropic.com](https://console.anthropic.com) → *API Keys* → *Create Key*. Adicione créditos em *Billing*. |

## 2. Instalação local

### Linux / macOS

```bash
git clone https://github.com/criatedavid-tech/agent.git
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
nano .env        # cole a chave em ANTHROPIC_API_KEY=
agente
```

### Windows (PowerShell)

```powershell
git clone https://github.com/criatedavid-tech/agent.git
cd agent
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
notepad .env
agente
```

> O `pip install` baixa o Claude Agent SDK, que inclui o executável do Claude Code. A primeira instalação pode levar alguns minutos.

## 3. Primeiro uso

1. Preencha `memory/perfil.md` com seu nome, trabalho, objetivos e tom de voz. Quanto melhor o perfil, melhor o agente age em seu nome.
2. Rode `agente` e teste:
   - `que dia é hoje e quanto é 15% de 3.480?`
   - `crie um arquivo teste.txt com a data de hoje`
   - `pesquise o preço do dólar hoje e salve em dolar.md`
3. Confira `workspace/` (arquivos criados) e `logs/` (o que ele fez).

## 4. Instalação na VPS (prévia da etapa 7)

Ainda não há scripts automáticos; por enquanto, à mão:

### 4.1 Escolher a VPS
Algo como **2 vCPU / 4 GB RAM / Ubuntu 24.04** é suficiente (Hetzner CX22, DigitalOcean, Contabo, Hostinger).

### 4.2 Preparar o servidor

```bash
# como root, no primeiro acesso
adduser agente
usermod -aG sudo agente
# copie sua chave SSH para o novo usuário
rsync --archive --chown=agente:agente ~/.ssh /home/agente

# firewall
ufw allow OpenSSH
ufw enable

# desative login por senha: em /etc/ssh/sshd_config
#   PasswordAuthentication no
#   PermitRootLogin no
systemctl restart ssh
```

### 4.3 Instalar o agente

```bash
# como usuário agente
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/criatedavid-tech/agent.git
cd agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env && chmod 600 .env && nano .env
```

### 4.4 Usar
Por enquanto, pelo terminal via SSH (`ssh agente@IP` → `cd agent && source .venv/bin/activate && agente`). Para mantê-lo aberto depois de desconectar, use `tmux`. Na etapa 2 ele passa a rodar como serviço e responder pelo WhatsApp.

## 5. Atualizar

```bash
cd agent
git pull
source .venv/bin/activate
pip install -e .
```

## 6. Desinstalar

Apague a pasta `agent/`. Nada é instalado fora dela (o `.venv` fica dentro).
