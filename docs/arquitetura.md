# Arquitetura

## Visão geral (estado atual: etapa 1)

```
┌────────────┐   texto    ┌──────────────────┐  ClaudeAgentOptions  ┌──────────────────────┐
│ agente/    │──────────► │ agente/core.py   │────────────────────► │ Claude Agent SDK     │
│ cli.py     │            │ classe Agent     │                      │ (loop + ferramentas) │
│ (terminal) │◄────────── │  .ask() → Event  │◄──────────────────── │                      │
└────────────┘  eventos   └──────────────────┘   mensagens          └──────────┬───────────┘
                             │        │                                        │
                   lê memória│        │grava log                     executa ferramentas
                             ▼        ▼                                        ▼
                      memory/*.md  logs/AAAA-MM-DD.jsonl            workspace/ · web
```

## Arquitetura alvo (etapa 7)

```
 WhatsApp ─┐                                   ┌─ MCP: Gmail, Calendar, GitHub, Vercel, Supabase
 Telegram ─┼─► servidor web (webhooks) ─┐      ├─ Navegador (Playwright, sessão persistente)
 Terminal ─┘                            ▼      ├─ Redes sociais (APIs oficiais)
                                    Agent.ask() ┼─ Pagamentos (cartão virtual + teto)
 Agendador (cron) ─────────────────────►│      ├─ Ligações (Twilio + voz)
 Eventos (e-mail novo, preço) ─────────►│      └─ Terminal e arquivos
                                        ▼
                         memória (Markdown + SQLite) · logs · resumo diário
```

Princípio central: **um único cérebro (`Agent`), várias entradas e várias ferramentas.** Interfaces e gatilhos só chamam `Agent.ask()`; capacidades novas entram como ferramentas.

## Módulos

### `agente/config.py`
- `Config`: dataclass imutável com `model`, `workdir`, `memory_dir`, `logs_dir`, `max_budget_usd`, `max_turns`.
- `load()`: lê o `.env` (via `python-dotenv`), resolve caminhos relativos à raiz do projeto e cria as pastas.

### `agente/memory.py`
- `load(memory_dir)`: lê todos os `memory/*.md` em ordem alfabética e devolve um bloco `<arquivo nome="...">…</arquivo>` para o system prompt. Arquivos vazios são ignorados.

### `agente/knowledge.py`
- `AREAS`: as áreas e o que cabe em cada uma (vai na descrição da ferramenta).
- `KnowledgeBase(root)`: cria as pastas e refaz o índice a partir dos `.md` (`reindex()`).
  - `save(area, title, content, tags, nicho, source)`: valida a área, bloqueia segredos (`find_secret`), grava `conhecimento/<área>[/<nicho>]/AAAA-MM-DD-titulo.md` e indexa.
  - `search(query, area)`: busca FTS5 (bm25, título pesa mais que corpo) sem palavras vazias.
  - `summary()`: resumo por área para o system prompt.

### `agente/human.py`
- `HumanBridge(timeout_min)`: ponte humana. `request(reason, link)` avisa a interface pelo callback `notify` e espera `answer(id, text)` ou o tempo limite; `cancel_all()` libera quem estiver esperando quando a conversa fecha.
- A web lê o WebSocket numa tarefa separada, para a resposta chegar enquanto o agente está no meio do pedido.

### `agente/guard.py`
- `check(tool, args, cfg)`: devolve o motivo do bloqueio ou `None`. `hooks(cfg, log)`: monta o `PreToolUse` que nega com `permissionDecision: "deny"` e registra no log.

### `agente/subagents.py` e `plugin/`
- `AGENTS`: definições dos subagentes. `plugin/skills/*/SKILL.md`: skills carregadas sob demanda.

### `agente/core.py`
- `TOOLS`: ferramentas liberadas (`Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebSearch`, `WebFetch`) mais as da base de conhecimento.
- `knowledge_server(kb)`: servidor MCP dentro do processo com `salvar_conhecimento` e `buscar_conhecimento`.
- `SYSTEM_PROMPT`: personalidade, regras de trabalho, regra contra prompt injection, data e hora atuais e a memória.
- `Event(kind, text)`: o que a interface recebe: `text` (fala do agente), `tool` (ferramenta usada) e `result` (fim do pedido, com passos e custo).
- `Agent`:
  - `_options()`: monta `ClaudeAgentOptions` com `cwd=workspace`, `add_dirs=[memory]` (para ele poder escrever em `notas.md`), `permission_mode="bypassPermissions"`, `max_turns` e `max_budget_usd`.
  - `start()` / `stop()` / `reset()`: abrem e fecham a sessão do `ClaudeSDKClient`. `reset()` relê a memória.
  - `ask(text)`: envia o pedido, percorre as mensagens do SDK e converte cada uma em `Event`, gravando tudo no log.

### `agente/cli.py`
- Loop de terminal com `rich`: lê a entrada (em thread, para não travar o asyncio), trata `sair` e `/nova` e imprime os eventos (Markdown para texto, cinza para ferramentas e resultado).

## Fluxo de um pedido

```
1. cli.py lê "faça X"
2. Agent.ask("faça X") → log {type: user}
3. ClaudeSDKClient.query("faça X")
4. para cada mensagem do SDK:
     AssistantMessage → TextBlock   → Event("text")  → log {type: text}
                      → ToolUseBlock → Event("tool")  → log {type: tool}
     ResultMessage                   → Event("result") → log {type: result, cost_usd}
5. cli.py imprime cada evento assim que chega (streaming)
```

## Formato do log

Um arquivo por dia em `logs/AAAA-MM-DD.jsonl`, uma linha JSON por evento:

```json
{"type": "user", "text": "crie gastos.csv", "ts": "2026-10-26T10:00:01"}
{"type": "tool", "name": "Write", "input": {"file_path": "gastos.csv", "content": "..."}, "ts": "..."}
{"type": "text", "text": "Criei workspace/gastos.csv", "ts": "..."}
{"type": "result", "subtype": "success", "turns": 2, "cost_usd": 0.0124, "ts": "..."}
```

## Decisões de projeto

| Decisão | Motivo |
|---|---|
| Claude Agent SDK em vez de loop próprio | loop, ferramentas, contexto e custo já resolvidos; suporte nativo a MCP |
| Python | ecossistema de automação (Playwright, APIs, dados) |
| Memória em Markdown | legível e editável por você; versionável no git |
| Log em JSONL | fácil de anexar, de ler com `jq` e de importar depois |
| `bypassPermissions` | escolha de autonomia total; o risco é compensado por tetos rígidos |
| Uma classe `Agent` reutilizada por todas as interfaces | evita duplicar lógica quando entrarem WhatsApp e agendador |
