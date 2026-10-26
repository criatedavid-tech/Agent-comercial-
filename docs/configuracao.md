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

## Ferramentas liberadas

Definidas em `agente/core.py` (`TOOLS`). Para tirar uma capacidade, remova-a da lista. Exemplo: sem `Bash` ele não roda comandos.

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
