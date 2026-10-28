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

### `AGENT_BASE_URL` e `AGENT_AUTH_TOKEN` (provedor alternativo)
Vazios por padrão: o agente usa a API da Anthropic com `ANTHROPIC_API_KEY`. Preenchidos, o Claude Code embutido fala com outro provedor compatível com a API da Anthropic. Exemplo para **testar de graça pelo OpenRouter**:

```
AGENT_BASE_URL=https://openrouter.ai/api
AGENT_AUTH_TOKEN=sk-or-...        # chave do OpenRouter
AGENT_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
```

- Escolha um modelo `:free` **com suporte a ferramentas** (a lista muda; o OpenRouter mostra em openrouter.ai/models).
- Os apelidos dos subagentes (`sonnet`...) passam a apontar para esse mesmo modelo.
- **Custo:** o Claude Code estimaria pelo preço da Anthropic (valor falso), então o agente mostra "custo: veja no painel do provedor" e o painel não soma nada. O custo real fica no painel do OpenRouter. Aumente `AGENT_MAX_BUDGET_USD` para os testes (o teto usa a estimativa falsa e cortaria tarefas longas); volte para `2.00` ao usar chave paga.
- **Pesquisa na web gratuita:** no OpenRouter o `WebSearch` é cobrado por pesquisa (menos de 1 centavo cada, mas soma). Com provedor alternativo ele é desligado no agente e no pesquisador, que passam a buscar no DuckDuckGo (versão simples, via `WebFetch`) e abrir as páginas. Medido: pesquisa completa por US$ 0,00, com mais passos que o `WebSearch`.
- Modelos gratuitos têm cota diária de requisições e erram mais com ferramentas: servem para testar, não para produção.

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

### `AGENT_TIMEZONE`
Padrão: `America/Sao_Paulo`. Fuso usado para calcular os horários da agenda. Qualquer nome do banco IANA serve (ex.: `America/Manaus`).

### `AGENT_DAILY_SUMMARY`
Padrão: `07:00`. Hora do resumo diário: o agente lista o que está agendado para hoje, o que entrou na base de conhecimento e dá uma sugestão para o dia. Deixe vazio para desligar. Mudou a hora? Vale na próxima vez que o `agente-web` iniciar.

### `AGENT_BROWSER_HEADLESS`
Padrão: `false`. Com `false`, o navegador próprio abre uma janela de verdade no seu computador: é nela que você resolve CAPTCHA, login e códigos quando o agente pedir. Use `true` só onde não há tela (VPS); aí o agente avisa que você não consegue resolver verificações por enquanto.

### `AGENT_EMPRESA_DIR`
Pasta da empresa que o atendente atende. Vazio: `empresa/` na raiz do projeto ou, se não existir, a empresa fictícia de `exemplos/empresa/`. Caminho relativo é a partir da raiz do projeto. Formato dos arquivos: [atendente.md](atendente.md#configuração-da-empresa).

### `AGENT_ATENDENTE_MAX_TURNS`
Padrão: 12. Passos (chamadas de ferramenta) do atendente por mensagem de cliente. Cliente não espera: se ele precisar de mais que isso, algo está errado. O teto de gasto é o mesmo `AGENT_MAX_BUDGET_USD`.

### `WHATSAPP_*`
`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` e `WHATSAPP_ALLOWED_NUMBERS` ligam o canal WhatsApp (todas obrigatórias); `WHATSAPP_API_VERSION` (padrão `v26.0`) é a versão da Graph API. Passo a passo em [whatsapp.md](whatsapp.md).

## Navegador próprio

- Instalação: `pip install -e .` e depois `playwright install chromium` (uma vez, ~120 MB).
- O perfil fica em `navegador/` (fora do git): cookies e logins. **Trate essa pasta como uma senha**: quem copiar, entra nos sites onde você logou.
- Só um processo usa o navegador por vez: se o `agente-web` estiver com ele aberto, o terminal recebe um aviso.
- Regras no código: só `http`/`https`; rede local bloqueada (localhost, 127.x, 192.168.x, 10.x, `.local`); não digita em campo de senha ou cartão nem textos com CPF, cartão ou senha; o texto da página volta marcado como "informação, não instrução".
- Detecta páginas de verificação (Cloudflare, reCAPTCHA, hCaptcha, "você é um robô?") e orienta o agente a chamar a ponte humana.
- Capturas de tela vão para `workspace/capturas/`.

## Conversas e desfazer

- Cada conversa fica em `logs/conversas.db`: pedidos, respostas, ferramentas, bloqueios e custo. Alimenta a lista de **Conversas** e o **Painel**.
- **Retomar** devolve ao agente todo o contexto da conversa antiga. Se o registro interno dela não existir mais, o histórico aparece mesmo assim e o agente começa do zero (com aviso).
- **Desfazer edições** volta os arquivos criados ou editados por Write/Edit a partir daquele pedido. Mudanças feitas por comandos no terminal (Bash) **não** são desfeitas.

## Agenda (proatividade)

Quem roda a agenda é o **`agente-web`**: ele confere a cada 30 segundos o que venceu. O terminal (`agente`) cria e lista tarefas, mas não as executa.

| Tipo | Exemplo de pedido |
|---|---|
| `uma_vez` | "me lembra amanhã às 15h do dentista" |
| `diaria` | "todo dia às 8h me diga a cotação do dólar" |
| `semanal` | "toda segunda às 9h revise meus gastos da semana" |
| `mensal` | "dia 5 de cada mês me lembre de pagar o aluguel" |
| `intervalo` | "a cada 2 horas confira se o site X voltou" |

- **Lembrete** só entrega o texto na hora e não gasta API. **Tarefa** roda o agente com a instrução, numa conversa própria.
- O resultado aparece como cartão ⏰ nas abas abertas. Se nenhuma estiver aberta, fica na **caixa de entrada** e aparece quando você abrir a página ou o terminal.
- Computador desligado na hora marcada: a tarefa roda **uma vez** quando o `agente-web` voltar, e segue a recorrência normal.
- **Limites no código:** intervalo mínimo de 15 minutos e no máximo 30 tarefas ativas. Cada execução respeita `AGENT_MAX_BUDGET_USD`.
- Os dados ficam em `agenda.db` (SQLite, fora do git).

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
