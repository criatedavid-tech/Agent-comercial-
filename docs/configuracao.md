# Configuração

## Arquivo `.env`

Copie `.env.example` para `.env`. O `.env` **nunca** vai para o git.

### `ANTHROPIC_API_KEY` (obrigatória)
Chave da API. Sem ela o agente não inicia uma conversa.

### `AGENT_MODEL`
Padrão: `claude-opus-5-5` (o mais capaz). Alternativas:

| Modelo | Quando usar |
|---|---|
| `claude-opus-5-5` | tarefas longas, decisões importantes (padrão) |
| `claude-sonnet-5-5` | bom equilíbrio entre custo e qualidade no dia a dia |
| `claude-haiku-5-5` | tarefas simples e repetitivas, mais barato e rápido |

### `AGENT_WORKDIR`
Padrão: `./workspace`. Pasta onde o agente cria arquivos e roda comandos. Caminhos relativos são resolvidos a partir da raiz do projeto.

> Atenção: com autonomia total, o terminal (`Bash`) **não fica preso** a essa pasta: ela é só o ponto de partida. Para isolamento real, rode o agente com um usuário Linux dedicado (veja [seguranca.md](seguranca.md)).

### `AGENT_MAX_BUDGET_USD`
Padrão: `2.00`. Teto de gasto **por pedido**. Ao atingir, o SDK interrompe e o resultado mostra `parou: error_max_budget_usd`. Não é um limite mensal: para isso, configure também um limite de gasto no painel da Anthropic (*Billing → Limits*).

### `AGENT_MAX_TURNS`
Padrão: `40`. Máximo de passos (decisão + ferramenta) por pedido. Evita loops infinitos. Tarefas grandes podem precisar de 60–100.

### `AGENT_WEB_PORT`
Padrão: `8000`. Porta da interface web de testes (`agente-web`). O servidor só escuta em `127.0.0.1`, então não fica acessível pela rede.

### `AGENT_HELP_TIMEOUT_MIN`
Padrão: `10`. Quanto tempo o agente espera você resolver algo pela ponte humana (CAPTCHA, código de dois fatores, login, decisão). Passado o tempo, ele segue sem isso e avisa no final. O limite das ferramentas MCP do SDK é ajustado automaticamente para um pouco acima desse valor.

## Memória

Arquivos em `memory/`, lidos **no início de cada conversa** (ao abrir o `agente` ou digitar `/nova`).

| Arquivo | Quem escreve | Conteúdo |
|---|---|---|
| `perfil.md` | você | quem você é, trabalho, objetivos, tom de voz, preferências |
| `notas.md` | o agente | fatos que ele aprendeu (preferências, contatos, rotinas) |

Você pode criar outros (`contatos.md`, `empresa.md`, `rotinas.md`): todo `.md` da pasta é carregado.

Dicas:
- Seja específico: "assino e-mails como 'Abs, David'" ajuda mais que "seja educado".
- Revise `notas.md` de vez em quando e apague o que estiver errado.
- Memória grande custa tokens em **todo** pedido. Mantenha-a enxuta.

## Base de conhecimento

Além da memória, o agente mantém uma base de notas em `conhecimento/`, separada por área:

| Pasta | O que vai lá |
|---|---|
| `financas/` | gastos, orçamento, investimentos, contas, impostos |
| `saude/` | exames, consultas, remédios, treino, alimentação |
| `lazer/` | viagens, passeios, restaurantes, hobbies |
| `entretenimento/` | filmes, séries, músicas, jogos, livros de ficção |
| `estudos/<nicho>/` | uma subpasta por nicho (`python/`, `ingles/`...), criada quando surge um assunto novo |
| `geral/` | o que não se encaixa nas outras |

Como funciona, em três camadas:
1. **Cache:** um resumo (quantas notas cada área tem e as mais recentes) entra no system prompt de toda conversa. Custa poucos tokens.
2. **Busca (RAG):** a ferramenta `buscar_conhecimento` procura por palavras-chave no `conhecimento/indice.db` (SQLite FTS5, ignora acentos) e devolve só as notas relevantes.
3. **Arquivo:** cada nota é um `.md` com cabeçalho (`titulo`, `data`, `area`, `tags`, `fonte`). Você pode abrir, editar ou apagar à mão; o índice é refeito a cada conversa nova.

Quem decide a área é o próprio agente, ao chamar `salvar_conhecimento`. Ele salva quando julga que algo será útil depois, não a cada mensagem.

O código **recusa** notas que pareçam conter CPF, número de cartão (validado pelo dígito verificador) ou senha/token, seja qual for o pedido.

A pasta está no `.gitignore`: são dados pessoais (saúde e finanças). Faça backup dela junto com `memory/`.

## Ferramentas liberadas

Definidas em `agente/core.py` (`TOOLS`). Para tirar uma capacidade, remova-a da lista. Exemplo: sem `Bash` ele não roda comandos.

## Subagentes

Definidos em `agente/subagents.py`. Cada um tem contexto limpo, ferramentas próprias e roda no modelo `sonnet` (mais barato):

| Subagente | Para quê | Ferramentas |
|---|---|---|
| `pesquisador` | pesquisar na web e comparar, com fontes | WebSearch, WebFetch, Read, buscar_conhecimento |
| `organizador` | juntar notas repetidas, corrigir área, resumir | Read, Glob, Grep, buscar e salvar conhecimento |
| `verificador` | conferir arquivos, contas e afirmações antes de entregar | Read, Glob, Grep, Bash, WebFetch |

## Skills

Ficam em `plugin/skills/<nome>/SKILL.md`. Só o nome e a descrição ficam sempre visíveis; o conteúdo entra no contexto quando o assunto aparece. Hoje: `financas`, `saude`, `estudos`, `compras-online`. Para criar outra, copie uma pasta, mude `name`, `description` (diga **quando** usar) e as instruções; ela é carregada automaticamente na próxima conversa.

## Custos

Você paga por token na API da Anthropic. Ordem de grandeza:

| Tipo de pedido | Passos | Custo típico |
|---|---|---|
| Pergunta simples | 1 | centavos de dólar |
| Criar ou editar um arquivo | 2–5 | centavos |
| Pesquisa na web com resumo | 5–15 | dezenas de centavos |
| Tarefa longa (projeto, relatório) | 20–40 | até alguns dólares |

O custo exato de cada pedido aparece no fim da resposta e em `logs/`. Somar o gasto do dia:

```bash
jq -s 'map(select(.type=="result").cost_usd) | add' logs/$(date +%F).jsonl
```
