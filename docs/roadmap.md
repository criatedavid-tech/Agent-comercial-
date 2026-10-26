# Roadmap

Objetivo: um agente tão completo quanto a soma de Claude Duet, Dots, Grok Bot, Muse e Instinct, rodando numa VPS própria.

## ✅ Etapa 1: Núcleo
- [x] Loop do agente com Claude Agent SDK
- [x] Ferramentas: terminal, arquivos, busca e leitura na web
- [x] Memória de longo prazo em Markdown
- [x] Teto de gasto e de passos
- [x] Log diário em JSONL
- [x] Chat no terminal

## ⬜ Etapa 2: WhatsApp e proatividade
- [ ] Servidor web (FastAPI) com webhook da **WhatsApp Cloud API** oficial
- [ ] Só responde ao seu número (lista de permitidos)
- [ ] Uma conversa por contato, com histórico
- [ ] Comando **PARAR** / **CONTINUAR**
- [ ] Agendador: **resumo diário** às 7h e tarefas recorrentes ("toda segunda…")
- [ ] Envio de áudio e imagem (receber e transcrever)

**Você vai precisar:** app no Meta for Developers, número dedicado e domínio com HTTPS (ou túnel para testes).

## ⬜ Etapa 3: Conectores (MCP)
- [ ] Gmail: ler, resumir, rascunhar e enviar
- [ ] Google Calendar: consultar, criar e remarcar
- [ ] GitHub: repositórios, issues e PRs
- [ ] Vercel e Supabase: deploy, logs e banco
- [ ] Memória em SQLite: contatos, tarefas, histórico pesquisável

## ⬜ Etapa 4: Navegador e compras
- [ ] Playwright com perfil persistente (fica logado nos sites)
- [ ] Preencher formulários, monitorar preços e páginas
- [ ] Compras com **cartão virtual** + teto por compra e por mês no código
- [ ] Marketplaces com API (ex.: Mercado Livre) para comprar e vender

## ⬜ Etapa 5: Redes sociais
- [ ] Instagram e Facebook (Meta Graph API): postar, responder comentários e DMs
- [ ] X (API oficial)
- [ ] LinkedIn
- [ ] Calendário de conteúdo e posts agendados

## ⬜ Etapa 6: Voz e ligações
- [ ] Ligações de saída e entrada (Twilio)
- [ ] Voz natural (TTS) e transcrição (STT)
- [ ] "Ligue para a clínica e remarque minha consulta"

## ⬜ Etapa 7: Produção na VPS
- [ ] Script de provisionamento (usuário, firewall, SSH, fail2ban)
- [ ] Serviço systemd com reinício automático
- [ ] Caddy com HTTPS automático para os webhooks
- [ ] Backups de `memory/` e do banco
- [ ] Monitoramento: alerta no WhatsApp se cair
- [ ] Painel web simples com logs e gastos

## Ideias futuras
- Vários agentes especializados (vendas, finanças, conteúdo) coordenados pelo principal
- Integração com bancos via Open Finance (apenas leitura)
- Painel de aprovação opcional para ações acima de um valor
