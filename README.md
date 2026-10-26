# Agente pessoal

Um assistente pessoal **autônomo** que roda na sua própria VPS. Ele recebe um pedido, decide sozinho os passos, usa ferramentas (terminal, arquivos, web e, nas próximas etapas, WhatsApp, e-mail, agenda, navegador, redes sociais e compras) e entrega o resultado.

A ideia é a mesma dos agentes das big techs (Claude Duet, OpenAI Dots, Grok Bot, Meta Muse, Instinct), mas com três diferenças:
- **Seus dados ficam com você:** tudo roda na sua VPS.
- **Você escolhe as regras:** autonomia, limites de gasto e integrações são decididos por você.
- **Funciona no Brasil hoje,** sem lista de espera.

> **Status:** etapa 1 de 7 concluída: núcleo do agente com chat no terminal. Veja o [roadmap](docs/roadmap.md).

---

## Sumário

- [Início rápido](#início-rápido)
- [Como funciona (em 30 segundos)](#como-funciona-em-30-segundos)
- [O que ele já faz](#o-que-ele-já-faz)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Configuração](#configuração)
- [Documentação completa](#documentação-completa)
- [Riscos e limites](#riscos-e-limites)

---

## Início rápido

Requisitos: **Python 3.11+** e uma **chave da API da Anthropic** ([console.anthropic.com](https://console.anthropic.com)).

```bash
git clone https://github.com/criatedavid-tech/agent.git
cd agent
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env               # edite e coloque sua ANTHROPIC_API_KEY
agente                             # ou: python -m agente.cli
```

Exemplo de conversa:

```
você › crie uma planilha CSV com meus gastos fixos: aluguel 1500, internet 120, luz 200
⚙ Write gastos.csv
Criei workspace/gastos.csv com 3 linhas e o total (R$ 1.820).
ok · 2 passos · US$ 0.0124
```

Comandos do chat:

| Comando | O que faz |
|---|---|
| `sair` | encerra |
| `/nova` | começa uma conversa do zero e relê a memória |
| `Ctrl+C` | interrompe e sai |

### Interface web (testes)

Para conversar pelo navegador em vez do terminal:

```bash
agente-web                         # abre em http://127.0.0.1:8000
```

Mostra as respostas formatadas, cada ferramenta usada e o custo de cada pedido. Só escuta em `127.0.0.1` e recusa conexões vindas de outros sites. Não exponha essa porta na VPS.

Guia detalhado: [docs/instalacao.md](docs/instalacao.md).

---

## Como funciona (em 30 segundos)

```
  você ──► pedido
            │
            ▼
   ┌──────────────────────────────────────┐
   │  LOOP DO AGENTE (agente/core.py)     │
   │                                      │
   │  1. lê a memória (memory/*.md)       │
   │  2. o modelo decide o próximo passo  │
   │  3. usa uma ferramenta               │◄──┐
   │  4. lê o resultado                   │   │ repete até
   │  5. terminou? não → volta ao passo 2 │───┘ concluir
   └──────────────────────────────────────┘
            │
            ▼
   resposta + registro em logs/
```

Um agente é um **modelo de linguagem dentro de um loop, com ferramentas**. O modelo não "sabe" fazer as coisas: ele **decide** qual ferramenta usar e com quais parâmetros. A ferramenta executa de verdade e devolve o resultado, e o modelo decide o próximo passo.

Explicação completa: [docs/conceitos.md](docs/conceitos.md) · [docs/arquitetura.md](docs/arquitetura.md).

---

## O que ele já faz

| Capacidade | Ferramenta | Exemplo de pedido |
|---|---|---|
| Rodar comandos | `Bash` | "instale o pandas e gere um gráfico das vendas" |
| Ler e escrever arquivos | `Read`, `Write`, `Edit` | "resuma o contrato.pdf da pasta" |
| Procurar em arquivos | `Glob`, `Grep` | "ache todos os orçamentos acima de R$ 5 mil" |
| Pesquisar na web | `WebSearch` | "quais as 3 melhores VPS baratas hoje?" |
| Ler páginas | `WebFetch` | "leia este link e me diga o preço" |
| Lembrar de você | `memory/*.md` | aprende preferências e as usa nas próximas conversas |
| Registrar tudo | `logs/*.jsonl` | cada pedido, ferramenta usada e custo |

---

## Estrutura do projeto

```
agent/
├── README.md              ← você está aqui
├── CLAUDE.md              ← instruções para quem (humano ou IA) for programar no projeto
├── pyproject.toml         ← dependências e o comando `agente`
├── .env.example           ← modelo do arquivo de configuração
├── agente/
│   ├── config.py          ← lê o .env e cria as pastas
│   ├── core.py            ← o loop do agente (coração do projeto)
│   ├── memory.py          ← carrega a memória de longo prazo
│   ├── cli.py             ← chat no terminal
│   ├── web.py             ← chat no navegador (localhost, para testes)
│   └── static/index.html  ← página do chat web
├── memory/
│   ├── perfil.md          ← quem é você (preencha!)
│   └── notas.md           ← o que o agente aprendeu sozinho
├── docs/                  ← documentação completa
├── workspace/             ← (criada ao rodar) onde o agente trabalha
└── logs/                  ← (criada ao rodar) registro diário de ações
```

---

## Configuração

Tudo fica no `.env`:

| Variável | Padrão | Para que serve |
|---|---|---|
| `ANTHROPIC_API_KEY` | (obrigatória) | chave da API da Anthropic |
| `AGENT_MODEL` | `claude-opus-5-5` | modelo usado pelo agente |
| `AGENT_WORKDIR` | `./workspace` | pasta onde ele cria arquivos e roda comandos |
| `AGENT_MAX_BUDGET_USD` | `2.00` | teto de gasto **por pedido**: ao atingir, ele para |
| `AGENT_MAX_TURNS` | `40` | máximo de passos por pedido |
| `AGENT_WEB_PORT` | `8000` | porta da interface web de testes |

Detalhes e dicas: [docs/configuracao.md](docs/configuracao.md).

---

## Documentação completa

| Documento | Conteúdo |
|---|---|
| [Conceitos](docs/conceitos.md) | o que é um agente, loop, ferramentas, memória, MCP, proatividade |
| [Comparativo das big techs](docs/comparativo.md) | Grok Bot, Dots, Claude Duet, Instinct, Muse: o que fazem e seus limites |
| [Arquitetura](docs/arquitetura.md) | como o código está organizado e o fluxo de um pedido |
| [Instalação](docs/instalacao.md) | passo a passo local (Linux, macOS, Windows) e na VPS |
| [Configuração](docs/configuracao.md) | todas as variáveis, memória, custos |
| [Uso](docs/uso.md) | exemplos de pedidos, boas práticas, leitura dos logs |
| [Segurança](docs/seguranca.md) | riscos reais (prompt injection, chaves, gastos) e como se proteger |
| [Roadmap](docs/roadmap.md) | as 7 etapas, com o que entra em cada uma |
| [Desenvolvimento](docs/desenvolvimento.md) | como adicionar ferramentas, conectores e canais |
| [Solução de problemas](docs/problemas.md) | erros comuns e como resolver |

---

## Riscos e limites

O agente roda com **autonomia total**: ele não pede confirmação antes de agir. Isso é poderoso e perigoso ao mesmo tempo. Leia [docs/seguranca.md](docs/seguranca.md) antes de dar a ele acesso a e-mail, dinheiro ou redes sociais. Os pontos principais:

- **Ele pode errar com confiança.** Confira o que importa.
- **Prompt injection:** um e-mail ou site pode trazer instruções escondidas.
- **Ações irreversíveis** (pagar, apagar, enviar) não têm "desfazer".
- **Custo:** cada passo consome a API. O teto por pedido limita o estrago.
- **A VPS guarda as chaves de tudo.** Proteja-a como protegeria seu celular desbloqueado.

---

## Licença

Projeto pessoal e privado.
