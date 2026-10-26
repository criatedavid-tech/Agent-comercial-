# Comparativo: agentes pessoais das big techs

Situação em **outubro de 2026**. Todos são produtos recentes e preços e disponibilidade mudam rápido: confira o site oficial antes de decidir.

## Resumo

| Agente | Empresa | Lançamento | Canais | Preço (aprox.) | Disponível no Brasil? |
|---|---|---|---|---|---|
| **Grok Bot** | xAI | ago/2026 (beta) | app desktop/mobile | US$ 120–200/mês | restrito |
| **Dots** | OpenAI | set/2026 | ChatGPT, Slack, Teams, ligação, SMS (em breve) | plano Pro (≥ US$ 100/mês) | restrito |
| **Claude Duet** | Anthropic | out/2026 (prévia) | app próprio (Android/iOS) | planos Pro/Max, lista de espera | só EUA |
| **Instinct** | startup (Noah Shinn) | ago/2026 | texto e ligação | por convite | por convite |
| **Muse** (modelo Muse Spark) | Meta | set/2026 | app, web, **WhatsApp** | grátis, US$ 20 e US$ 100/mês | só EUA (teste) |

## Detalhes

### Grok Bot (xAI)
- **Faz:** roda num computador na nuvem sempre ligado, com navegador, arquivos e terminal; conecta Gmail, Slack e Google Calendar; você cria "funcionários" com nome que executam tarefas agendadas.
- **Limites:** beta; caro; só modelos da xAI; não roda no seu servidor. Pela documentação, todos os seus bots dividem o mesmo computador, então um não fica isolado do outro.

### Dots (OpenAI)
- **Faz:** agentes sempre ligados que perseguem um objetivo em segundo plano. Cada um tem computador, navegador e memória próprios e se conecta a mais de 4.000 apps. Liga e escreve em seu nome.
- **Limites:** só no plano Pro e nos planos empresariais; fora da Europa e do Reino Unido; só modelos da OpenAI.

### Claude Duet (Anthropic)
- **Faz:** proativo. Manda um resumo diário de manhã, agenda reuniões, monta dashboards e previsões financeiras, cria protótipos e apps. Roda numa máquina virtual própria, em segundo plano.
- **Limites:** prévia de pesquisa, só EUA, lista de espera; pede confirmação antes de agir; divide o limite de uso com o Claude Code; ainda erra ao julgar o que é urgente.

### Instinct
- **Faz:** foco no mundo real. Liga e manda mensagens para planejar viagens, comprar mercado e cancelar assinaturas. Tem concierge e uma "rede de pessoas de confiança".
- **Limites:** só por convite; produto muito novo e fechado.

### Muse (Meta)
- **Faz:** executa tarefas longas (agendar, preencher formulários, monitorar câmeras). Monta um plano, trabalha com o app fechado e volta quando precisa de aprovação. **Funciona no WhatsApp.** Paga com cartão de uso único (Link by Stripe) sem ver seus dados.
- **Limites:** teste limitado nos EUA; exige entregar e-mail, agenda e navegador para a Meta.

## O padrão comum

Os cinco seguem a mesma receita, e este projeto a reproduz:

| Peça | Nas big techs | Neste projeto |
|---|---|---|
| Computador sempre ligado | VM na nuvem deles | sua VPS (etapa 7) |
| Navegador + terminal + arquivos | sim | terminal e arquivos ✅, navegador (etapa 4) |
| Conectores (e-mail, agenda, apps) | sim | MCP (etapa 3) |
| Memória persistente | sim | `memory/*.md` ✅, banco de dados (futuro) |
| Proatividade | resumo diário, monitoramento | agendador (etapa 2) |
| Vários canais | app, WhatsApp, SMS, ligação | terminal ✅, WhatsApp (2), ligação (6) |
| Pagamento seguro | cartão de uso único | cartão virtual com limite (etapa 4) |
| Aprovação de ações sensíveis | sim | substituída por limites rígidos + log |

## Por que construir o próprio

| | Big techs | Agente próprio |
|---|---|---|
| Disponibilidade no Brasil | quase nenhum | já funciona |
| Modelo | preso a um | você escolhe e pode trocar |
| Dados | com a empresa | na sua VPS |
| Integrações | as que liberarem | qualquer API, script ou site |
| Regras de autonomia | definidas por eles | definidas por você |
| Custo | US$ 20–200/mês + limites | VPS (~US$ 5–10/mês) + uso da API |

**O que é mais difícil sozinho:** ligações de voz, polimento e segurança (eles têm equipes dedicadas) e WhatsApp (a Meta tem acesso nativo; você usa a API oficial paga ou vias não oficiais com risco de bloqueio).

## Referência open-source

**OpenClaw:** framework open-source de agente pessoal (o fundador foi contratado pela OpenAI). Vale estudar como fonte de ideias.

## Fontes

- Grok Bot: [Vellum](https://www.vellum.ai/blog/official-grok-bot-breakdown), [VentureBeat](https://venturebeat.com/orchestration/spacexais-grok-bot-turns-agents-into-persistent-digital-coworkers-that-can-operate-your-apps-for-120-per-month), [MindStudio](https://www.mindstudio.ai/blog/grokbot-xai-agent-app)
- Dots: [TechCrunch](https://techcrunch.com/2026/09/29/openai-launches-dots-its-bubbly-agentic-avatar/), [MindStudio](https://www.mindstudio.ai/blog/openai-dots-personal-agents)
- Claude Duet: [Anthropic](https://claude.com/resources/articles/claude-duet), [CNBC](https://www.cnbc.com/2026/10/21/anthropic-preview-of-claude-duet-personal-ai-agent-take-on-muse-dots.html), [Dataconomy](https://dataconomy.com/2026/10/22/anthropic-claude-duet-personal-ai-agent-research-preview/)
- Instinct: [Vellum](https://www.vellum.ai/blog/official-instinct-breakdown), [AI Weekly](https://aiweekly.co/alerts/ai-personal-agent-startup-instinct-raises-1b-series-c-at-10b-from-sequoia)
- Muse: [Meta](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/), [CNBC](https://www.cnbc.com/2026/09/08/meta-personal-ai-agents-public-reckoning-privacy-safety.html), [eesel](https://www.eesel.ai/blog/meta-muse-agent-review)
