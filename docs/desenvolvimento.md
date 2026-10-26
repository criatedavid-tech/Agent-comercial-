# Desenvolvimento

Como estender o agente. Leia antes [arquitetura.md](arquitetura.md).

## Ambiente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -c "import agente.core"   # checagem rápida
```

## Regra de ouro

- **Interface nova** (WhatsApp, Telegram, API) → chama `Agent.ask()` e trata os `Event`s. Nunca reimplemente o loop.
- **Capacidade nova** → vira **ferramenta** (MCP ou ferramenta própria) registrada no `Agent`.

## Adicionar uma ferramenta própria (Python)

O SDK permite criar ferramentas em Python e expô-las como um servidor MCP interno:

```python
# agente/tools/cotacao.py
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("cotacao_dolar", "Retorna a cotação atual do dólar em reais", {})
async def cotacao_dolar(args):
    import urllib.request, json
    with urllib.request.urlopen("https://economia.awesomeapi.com.br/json/last/USD-BRL") as r:
        data = json.load(r)["USDBRL"]
    return {"content": [{"type": "text", "text": f"US$ 1 = R$ {data['bid']}"}]}

servidor = create_sdk_mcp_server(name="financas", version="1.0.0", tools=[cotacao_dolar])
```

Em `core.py`, dentro de `_options()`:

```python
from .tools.cotacao import servidor

return ClaudeAgentOptions(
    ...,
    mcp_servers={"financas": servidor},
    allowed_tools=TOOLS + ["mcp__financas__cotacao_dolar"],
)
```

Boas descrições importam: é por elas que o modelo decide quando usar a ferramenta.

## Conectar um servidor MCP externo

```python
mcp_servers={
    "github": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_TOKEN"]},
    },
}
```

As ferramentas aparecem como `mcp__github__<nome>`. Coloque as chaves no `.env` e documente em `.env.example` e `docs/configuracao.md`.

## Adicionar uma interface

Esqueleto de qualquer canal:

```python
agent = Agent(config.load())
await agent.start()

async def ao_receber(texto: str) -> str:
    partes = []
    async for ev in agent.ask(texto):
        if ev.kind == "text":
            partes.append(ev.text)
    return "\n".join(partes)
```

Para vários usuários ou conversas simultâneas, mantenha um `Agent` por conversa.

## Limites rígidos no código

Para ações perigosas, **não confie só no prompt**. Valide dentro da ferramenta:

```python
LIMITE_COMPRA = 200.0
if valor > LIMITE_COMPRA:
    return {"content": [{"type": "text", "text": f"Bloqueado: R$ {valor} acima do limite de R$ {LIMITE_COMPRA}"}], "is_error": True}
```

O SDK também aceita **hooks** (`PreToolUse`) para inspecionar e bloquear qualquer chamada de ferramenta antes de executar, útil para regras globais (ex.: proibir `rm -rf /`).

## Adicionar uma skill

1. Crie `plugin/skills/<nome>/SKILL.md` com cabeçalho `name` e `description`. A descrição decide quando o agente carrega a skill: diga o assunto e os gatilhos.
2. Escreva instruções curtas e acionáveis: o que consultar antes, como fazer, o que nunca fazer, o que salvar depois.
3. Nada de segredos na skill: o agente pode ler os arquivos.

## Adicionar um subagente

Inclua uma entrada em `AGENTS` (`agente/subagents.py`) com `description` (quando o principal deve delegar), `prompt`, `tools` (o mínimo necessário), `mcpServers` se usar a base de conhecimento, `model` e `maxTurns`.

## Adicionar uma regra de segurança

Acrescente o padrão em `BLOCKED_COMMANDS` (ou a regra em `check()`), em `agente/guard.py`, e teste os dois lados: um comando que deve ser barrado e um parecido que deve passar. Regras amplas demais travam o agente em tarefas normais.

## Checklist para cada mudança

- [ ] Código segue o padrão (identificadores em inglês, textos em português)
- [ ] `python -c "import agente.core"` passa
- [ ] Testado no chat com um pedido real
- [ ] Variáveis novas em `config.py`, `.env.example` e `docs/configuracao.md`
- [ ] Documentação atualizada (`README.md`, `docs/roadmap.md`)
- [ ] Commit em português, descrevendo o porquê
