# Agente pessoal

Um assistente pessoal autônomo, no estilo de Claude Duet, OpenAI Dots, Grok Bot e Meta Muse, mas rodando na **sua** VPS, com os seus dados e as suas regras.

## Como funciona

```
você (terminal → depois WhatsApp)
        │
        ▼
   agente/core.py ── loop do Claude Agent SDK
        │   1. lê a memória (memory/*.md)
        │   2. o modelo decide o próximo passo
        │   3. usa uma ferramenta (terminal, arquivos, web…)
        │   4. lê o resultado e repete até terminar
        ▼
   resposta + log em logs/
```

- **Cérebro:** Claude, via Claude Agent SDK.
- **Ferramentas (etapa 1):** terminal, leitura e escrita de arquivos, busca e leitura na web.
- **Memória:** `memory/perfil.md` (quem você é) e `memory/notas.md` (o que o agente aprendeu).
- **Área de trabalho:** `workspace/`, onde o agente cria arquivos e roda comandos.
- **Travas automáticas:** teto de gasto por pedido (`AGENT_MAX_BUDGET_USD`) e limite de passos (`AGENT_MAX_TURNS`).

## Rodando localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env   # coloque sua ANTHROPIC_API_KEY
agente                 # ou: python -m agente.cli
```

Na conversa, digite `sair` para encerrar ou `/nova` para começar uma conversa do zero.

## Roadmap

- [x] **1. Núcleo:** loop do agente, memória, ferramentas básicas, chat no terminal
- [ ] **2. WhatsApp:** Cloud API oficial da Meta, comando PARAR, resumo diário
- [ ] **3. Conectores (MCP):** Gmail, Google Calendar, GitHub, Vercel, Supabase
- [ ] **4. Navegador:** Playwright com sessão persistente + compras com cartão virtual e teto de gasto
- [ ] **5. Redes sociais:** APIs oficiais (Instagram/Facebook, X, LinkedIn)
- [ ] **6. Ligações:** Twilio + voz
- [ ] **7. VPS:** provisionamento, systemd, HTTPS (Caddy), backups

## Riscos

- **Prompt injection:** e-mails e sites podem conter instruções maliciosas. Quanto mais acesso o agente tiver, maior o estrago possível.
- **Ações irreversíveis:** pagar, apagar e enviar não têm "desfazer". Use cartão virtual com limite e mantenha os logs.
- **Chaves:** a VPS guarda o acesso a todas as suas contas. Proteja o `.env` e use SSH só com chave.
