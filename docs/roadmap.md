# Roadmap

Objetivo: um agente tão completo quanto a soma de Claude Duet, Dots, Grok Bot, Muse e Instinct, rodando numa VPS própria.

## ✅ Etapa 1: Núcleo
- [x] Loop do agente com Claude Agent SDK
- [x] Ferramentas: terminal, arquivos, busca e leitura na web
- [x] Memória de longo prazo em Markdown
- [x] Teto de gasto e de passos
- [x] Log diário em JSONL
- [x] Chat no terminal

## ✅ Extra: Base de conhecimento
- [x] Notas por área (finanças, saúde, lazer, entretenimento, estudos por nicho, geral)
- [x] Busca por palavras-chave (SQLite FTS5) e resumo por área no prompt
- [x] Bloqueio de CPF, cartão e senhas no código
- [ ] Busca semântica (embeddings) quando a base crescer
- [ ] Classificação de área com Jev (TypeSafe), se o agente errar muito

## ✅ Extra: Ponte humana
- [x] Ferramenta `pedir_ajuda_humana`: pausa a tarefa e chama você (CAPTCHA, 2FA, login, decisões)
- [x] Cartão na interface web e pergunta no terminal, com tempo limite
- [ ] Aviso pelo WhatsApp (etapa 2)
- [ ] Resolver dentro do navegador do agente (etapa 4)

## ✅ Extra: Recursos do Claude Code no agente
- [x] Hooks de segurança (`PreToolUse`) com bloqueios no código
- [x] Subagentes: pesquisador, organizador, verificador
- [x] Skills por assunto: finanças, saúde, estudos, compras online
- [x] Testes automatizados (pytest, sem chave e sem custo)
- [x] Checkpoints de arquivos (desfazer edições do agente)
- [x] Retomar conversas antigas (`resume`)
- [x] Painel web: gastos, conversas, agenda, base de conhecimento, bloqueios

## 🟡 Etapa 2: WhatsApp e proatividade
- [x] Servidor web (FastAPI) com webhook da **WhatsApp Cloud API** oficial, com assinatura conferida
- [x] Só responde ao seu número (lista de permitidos)
- [x] Uma conversa por contato, com histórico (continua depois de reiniciar)
- [x] Comando **PARAR** / **CONTINUAR** (e **NOVA**)
- [x] Ponte humana e avisos da agenda pelo WhatsApp
- [ ] Template aprovado para o resumo diário fora da janela de 24 h
- [x] Agendador: **resumo diário** às 7h, tarefas recorrentes e lembretes (feito antes do WhatsApp; hoje entrega na web)
- [ ] Envio de áudio e imagem (receber e transcrever)

**Você vai precisar:** app no Meta for Developers, número dedicado e domínio com HTTPS (ou túnel para testes).

## ⬜ Etapa 3: Conectores (MCP)
- [ ] Gmail: ler, resumir, rascunhar e enviar
- [ ] Google Calendar: consultar, criar e remarcar
- [ ] GitHub: repositórios, issues e PRs
- [ ] Vercel e Supabase: deploy, logs e banco
- [ ] Memória em SQLite: contatos, tarefas, histórico pesquisável

## ⬜ Etapa 4: Navegador e compras
- [x] Playwright com perfil persistente (fica logado nos sites)
- [x] Preencher formulários e navegar em várias etapas (monitorar preços: com a agenda)
- [ ] Ver a janela do navegador remotamente quando estiver na VPS
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
