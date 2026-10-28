# Agent comercial

**Vendedor digital no WhatsApp para pequenas e médias empresas de qualquer segmento.** Atende na hora, tira dúvidas com base no catálogo da empresa, qualifica, faz follow-up sozinho e passa o cliente pronto para o vendedor humano fechar. O dono acompanha tudo num painel.

> **Status:** em construção a partir do protótipo de agente pessoal ([criatedavid-tech/agent](https://github.com/criatedavid-tech/agent), congelado). O motor, a segurança, a agenda, o WhatsApp e o deploy vêm de lá. O desenho do produto, a arquitetura (atendente × operador) e as fases estão em **[docs/produto.md](docs/produto.md)**.

O restante deste README descreve o agente herdado do protótipo, que vira o **operador** (o agente do dono e da equipe).

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

Mostra as respostas formatadas, cada ferramenta usada e o custo de cada pedido. **Conversas** retoma uma conversa antiga com todo o contexto; cada pedido tem **desfazer edições**; **Painel** (http://127.0.0.1:8000/painel) mostra gastos por dia, conversas, agenda, base de conhecimento e bloqueios. Só escuta em `127.0.0.1` e recusa conexões e endereços de outros sites. Não exponha essa porta na VPS.

**Simulador de cliente** (http://127.0.0.1:8000/simulador): você escreve como um cliente no WhatsApp e conversa com o **atendente** da empresa configurada em `empresa/` (sem ela, a empresa fictícia de `exemplos/empresa/`), vendo a ficha do lead no CRM atualizar a cada resposta. Detalhes: [docs/atendente.md](docs/atendente.md).

Navegador próprio: na primeira vez, baixe o Chromium com `playwright install chromium`.

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
| Organizar o que aprende | `salvar_conhecimento` | guarda notas por área: finanças, saúde, lazer, entretenimento, estudos (por nicho) e geral |
| Consultar o que já sabe | `buscar_conhecimento` | "quanto gastei com aluguel?" busca nas notas antes de responder |
| Agir sozinho na hora certa | `agendar_tarefa`, `listar_tarefas`, `cancelar_tarefa` | resumo diário às 7h, "toda segunda revise meus gastos", "me lembra às 15h do dentista" |
| Delegar | subagentes `pesquisador`, `organizador`, `verificador` | pesquisa em paralelo, arruma a base, confere o trabalho antes de entregar |
| Saber agir por assunto | skills `financas`, `saude`, `estudos`, `compras-online` | regras especializadas carregadas só quando o assunto aparece |
| Se proteger | hooks de segurança | barra `rm -rf /`, script baixado e executado, leitura do `.env`, escrita fora das pastas dele |
| Navegar como gente | `abrir_pagina`, `listar_elementos`, `clicar`, `preencher`, `ler_pagina`, `capturar_tela` | Chromium próprio que fica logado; você resolve CAPTCHA e login na janela dele |
| Falar pelo WhatsApp | webhook da API oficial da Meta | conversa por contato, PARAR/CONTINUAR, ajuda humana e avisos da agenda no celular |
| Chamar você quando trava | `pedir_ajuda_humana` | CAPTCHA, "você é um robô?", código 2FA, login: ele pausa, te chama e continua quando você resolve |
| Lembrar de você | `memory/*.md` | aprende preferências e as usa nas próximas conversas |
| Registrar tudo | `logs/*.jsonl` | cada pedido, ferramenta usada e custo |

**Gestão** (para o dono, pelo operador; contas e alertas feitos pelo código a partir das planilhas da loja, detalhes em [docs/gestao.md](docs/gestao.md)):

| Capacidade | Ferramenta | Exemplo de pedido |
|---|---|---|
| Números do período | `relatorio_gestao` | "como foi outubro?": receita, despesas, resultado, descontos, ticket médio, comparação |
| Achar onde vaza dinheiro | `alertas_gestao` | gasto fora do padrão, conta paga duas vezes, peça que saiu do estoque sem OS, desconto e cancelamento por funcionário, caixa faltando, gargalos da semana |
| Conferir um alerta | `consultar_lancamentos` | "mostra as saídas de estoque do Diego em outubro" |
| Funil do WhatsApp | `funil_comercial` | leads por etapa, conversão, retomadas, motivos de perda |
| Sem modelo, no terminal | `agente-gestao outubro --alertas` | o mesmo relatório, sem custo |

**Atendente** (fala com os clientes da empresa; só ferramentas do negócio, detalhes em [docs/atendente.md](docs/atendente.md)):

| Capacidade | Ferramenta | Exemplo de mensagem do cliente |
|---|---|---|
| Tirar dúvidas do catálogo | `consultar_catalogo` | "quanto custa a troca de óleo?" |
| Orçamento pelo preço de tabela | `calcular_orcamento` | "4 pneus 175/70 R14 com alinhamento e balanceamento, quanto fica?" (a conta é do código) |
| FAQ e políticas | `consultar_informacoes` | "tem leva e traz?", "parcela no cartão?" |
| Qualificar e registrar o lead | `registrar_lead`, `ver_cadastro` | nome, interesse, necessidade, prazo, orçamento e etapa no CRM |
| Combinar retorno | `agendar_retorno` | "me chama segunda de manhã" (o código entende a data e chama na hora) |
| Retomar quem sumiu | retomada automática (`agente/retomada.py`) | cliente achou caro e parou de responder: 4 h e 22 h depois recebe uma mensagem baseada na conversa; PARAR encerra |
| Passar para a equipe | `chamar_vendedor` e pedido de pessoa no código | "quero falar com um atendente": a equipe recebe o resumo, assume (`ASSUMIR 12` no WhatsApp ou em `/atendimento`), conversa e devolve |
| Regras no código | `regras.screen`, hook e `tools=[]` | sem desconto, sem fechar venda, sem fingir ser humano, sem dados de outros clientes |

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
│   ├── atendente.py       ← atendente: agente dos clientes, só com ferramentas do negócio
│   ├── empresa.py         ← empresa/: catálogo, FAQ, políticas; preço calculado no código
│   ├── crm.py             ← CRM em SQLite: contatos, interações, retornos
│   ├── regras.py          ← filtro da resposta do atendente (desconto, preço, venda, "sou humano")
│   ├── passagem.py        ← passagem para a equipe: chamar, assumir, responder, devolver
│   ├── retomada.py        ← retomada automática de quem parou de responder, retornos combinados, PARAR
│   ├── gestao.py          ← gestão: planilhas da loja, números, alertas (estoque, desconto, caixa, gastos)
│   ├── gestao_cli.py      ← agente-gestao: o relatório no terminal, sem modelo
│   ├── core.py            ← o loop do agente (coração do projeto)
│   ├── memory.py          ← carrega a memória de longo prazo
│   ├── knowledge.py       ← base de conhecimento por áreas (notas + busca)
│   ├── human.py           ← ponte humana: pausa e pede ajuda quando trava
│   ├── guard.py           ← hooks de segurança (bloqueios no código)
│   ├── scheduler.py       ← agenda: lembretes, tarefas recorrentes, resumo diário
│   ├── history.py         ← histórico de conversas (retomar, painel)
│   ├── sessoes.py         ← confere os logins dos sistemas da loja, avisa quando caem, links da tela remota
│   ├── browser.py         ← navegador próprio (Playwright, perfil persistente)
│   ├── whatsapp.py        ← canal WhatsApp (Cloud API: webhook, envio, comandos)
│   ├── backup.py          ← agente-backup: cópia consistente dos dados, com rotação
│   ├── vigia.py           ← agente-vigia: avisa no WhatsApp quando cai e quando volta
│   ├── subagents.py       ← pesquisador, organizador, verificador
│   ├── cli.py             ← chat no terminal
│   ├── web.py             ← chat no navegador (localhost, para testes)
│   └── static/            ← index.html (chat), painel.html (painel), simulador.html (cliente)
├── exemplos/empresa/      ← empresa fictícia de exemplo (Auto Center Rota Certa)
├── exemplos/dados/        ← planilhas fictícias da loja (vendas, despesas, estoque, caixa) + gerador
├── dados/                 ← (você cria) planilhas da sua loja; fora do git
├── empresa/               ← (você cria) configuração da sua empresa; fora do git
├── deploy/                ← VPS: provisionar.sh, atualizar.sh, serviços systemd, Caddyfile
├── plugin/skills/         ← skills: financas, saude, estudos, compras-online (SKILL.md)
├── memory/
│   ├── perfil.md          ← quem é você (preencha!)
│   └── notas.md           ← o que o agente aprendeu sozinho
├── conhecimento/          ← (criada ao rodar) notas por área + indice.db; fora do git
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
| `AGENT_BASE_URL`, `AGENT_AUTH_TOKEN` | (vazio) | provedor alternativo compatível com a API da Anthropic, ex. OpenRouter para testar de graça |
| `AGENT_WORKDIR` | `./workspace` | pasta onde ele cria arquivos e roda comandos |
| `AGENT_MAX_BUDGET_USD` | `2.00` | teto de gasto **por pedido**: ao atingir, ele para |
| `AGENT_MAX_TURNS` | `40` | máximo de passos por pedido |
| `AGENT_WEB_PORT` | `8000` | porta da interface web de testes |
| `AGENT_TIMEZONE` | `America/Sao_Paulo` | fuso da agenda |
| `AGENT_DAILY_SUMMARY` | `07:00` | hora do resumo diário; vazio desliga |
| `AGENT_BROWSER_HEADLESS` | `false` | navegador próprio sem janela (use `true` só na VPS) |
| `AGENT_PUBLIC_URL` | (vazio) | `https://` da VM: os avisos de login expirado levam link da tela remota com este domínio |
| `AGENT_ACESSOS_MIN` | `60` | de quantos em quantos minutos conferir os logins de `empresa/sistemas.toml` |
| `WHATSAPP_PROVEDOR`, `UAZAPI_*` | (vazio) | WhatsApp pela UAZAPI (não oficial, para testes): endereço, token da instância e segredo do webhook; veja [docs/whatsapp.md](docs/whatsapp.md#uazapi-para-testes) |
| `WHATSAPP_*` | (vazio) | token, ID do número, App Secret, token de verificação e números permitidos: veja [docs/whatsapp.md](docs/whatsapp.md) |
| `AGENT_EMPRESA_DIR` | `empresa/` ou o exemplo | pasta da empresa que o atendente atende |
| `AGENT_ATENDENTE_MAX_TURNS` | `12` | máximo de passos do atendente por mensagem de cliente |
| `AGENT_DADOS_DIR` | `dados/` ou o exemplo | pasta das planilhas da loja para a gestão |
| `AGENT_ATENDENTE_WHATSAPP` | `false` | clientes (números fora da equipe) falam com o atendente pelo WhatsApp |
| `AGENT_HELP_TIMEOUT_MIN` | `10` | quanto tempo ele espera você resolver um CAPTCHA, código ou login |

Detalhes e dicas: [docs/configuracao.md](docs/configuracao.md).

---

## Documentação completa

| Documento | Conteúdo |
|---|---|
| [Conceitos](docs/conceitos.md) | o que é um agente, loop, ferramentas, memória, MCP, proatividade |
| [Comparativo das big techs](docs/comparativo.md) | Grok Bot, Dots, Claude Duet, Instinct, Muse: o que fazem e seus limites |
| [Produto](docs/produto.md) | público, MVP, atendente × operador, fases |
| [Acessos aos sistemas](docs/acessos.md) | login salvo no navegador, aviso quando expira, tela remota na VM |
| [Gestão](docs/gestao.md) | planilhas da loja, números, alertas, como o operador usa |
| [Atendente](docs/atendente.md) | empresa/, ferramentas, CRM, regras no código, simulador |
| [Arquitetura](docs/arquitetura.md) | como o código está organizado e o fluxo de um pedido |
| [Instalação](docs/instalacao.md) | passo a passo local (Linux, macOS, Windows) e na VPS |
| [Configuração](docs/configuracao.md) | todas as variáveis, memória, custos |
| [Uso](docs/uso.md) | exemplos de pedidos, boas práticas, leitura dos logs |
| [Segurança](docs/seguranca.md) | riscos reais (prompt injection, chaves, gastos) e como se proteger |
| [Roadmap](docs/roadmap.md) | as 7 etapas, com o que entra em cada uma |
| [VPS](docs/vps.md) | colocar em produção: instalação, serviço, HTTPS, backups, vigia |
| [WhatsApp](docs/whatsapp.md) | passo a passo na Meta, comandos, regra das 24 h e segurança |
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
