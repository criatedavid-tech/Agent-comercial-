# Solução de problemas

## Instalação

**`pip install` demora muito**
Normal na primeira vez: o SDK baixa o executável do Claude Code (algumas centenas de MB).

**`agente: command not found`**
O ambiente virtual não está ativo. Rode `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`) ou use `python -m agente.cli`.

**`.venv/bin/pip: cannot execute: required file not found`**
A pasta do projeto foi movida depois de criar o `.venv`. Apague e recrie: `rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate && pip install -e .`

**Erro de versão do Python**
É preciso 3.11 ou mais novo. Verifique com `python3 --version`.

## Execução

**Erro de autenticação / chave inválida**
- Confira `ANTHROPIC_API_KEY` no `.env` (sem aspas e sem espaços).
- Verifique se há créditos em *console.anthropic.com → Billing*.

**`CLINotFoundError`**
O executável do Claude Code não foi encontrado. Reinstale: `pip install --force-reinstall claude-agent-sdk`.

**Resposta termina com `parou: error_max_budget_usd`**
Atingiu o teto por pedido. Aumente `AGENT_MAX_BUDGET_USD` ou divida a tarefa.

**Resposta termina com `parou: error_max_turns`**
Atingiu o limite de passos. Aumente `AGENT_MAX_TURNS` ou divida a tarefa.

**Ele não lembra do que eu disse ontem**
O histórico da conversa não persiste entre sessões; só a memória em `memory/` persiste. Peça "anote isso na sua memória" ou escreva em `memory/perfil.md`.

**Mudei a memória e ele não percebeu**
A memória é lida no início da conversa. Digite `/nova`.

**Ficou lento**
Conversas longas acumulam contexto. `/nova` resolve. Modelos menores (`claude-sonnet-5-5`) também respondem mais rápido.

## Diagnóstico

```bash
# o que aconteceu hoje
jq . logs/$(date +%F).jsonl | less

# configuração carregada
python -c "from agente import config; print(config.load())"
```
