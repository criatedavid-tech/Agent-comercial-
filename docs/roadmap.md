# Roadmap

## Produto comercial (este repositório)

Fases detalhadas em [produto.md](produto.md#fases):

- [x] **Fase 1 — Atendente:** agente com ferramentas restritas, configuração `empresa/`, CRM básico, simulador de cliente ([atendente.md](atendente.md))
- [x] **Gestão da empresa:** relatório e alertas a partir das planilhas da loja (estoque sem OS, desconto e caixa por funcionário, gastos fora do padrão, contas em dobro, gargalos) para o operador ([gestao.md](gestao.md)). Próximo: conectar direto ao sistema da loja (ERP) em vez de CSV
- [x] **Fase 2 — Passagem para humano:** chamar vendedor, modo humano por contato, caixa de entrada no painel
- [ ] **Fase 3 — Follow-up e funil:** ~~retornos automáticos~~ (feito: [retomada automática](atendente.md#retomada-automática)), etapas do funil, painel comercial
- [ ] **Fase 4 — Onboarding e custo:** instalar uma empresa nova em minutos, custo por conversa
- [ ] **Fase 5 — Extras:** propostas, prospecção, integrações

## Herdado do protótipo (agente pessoal)

Objetivo original: um agente tão completo quanto a soma de Claude Duet, Dots, Grok Bot, Muse e Instinct, rodando numa VPS própria. Tudo abaixo já está no código e vira a base do **operador**.

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
- [x] Google (Sheets, Drive, Agenda e Gmail) em **só leitura**, por OAuth, em `/google` ([google.md](google.md))
- [ ] Google: escrever (rascunho de e-mail, criar evento, linha na planilha), sempre por conector e com o ok do usuário
- [ ] GitHub: repositórios, issues e PRs
- [ ] Vercel e Supabase: deploy, logs e banco
- [ ] Memória em SQLite: contatos, tarefas, histórico pesquisável

## ⬜ Etapa 4: Navegador e compras
- [x] Playwright com perfil persistente (fica logado nos sites)
- [x] Preencher formulários e navegar em várias etapas (monitorar preços: com a agenda)
- [x] Ver a janela do navegador remotamente quando estiver na VPS (tela remota com link temporário) e aviso quando um login dos sistemas da loja expira ([acessos.md](acessos.md))
- [x] Aprendizado dos sistemas da loja (iFood, ERP): notas e rotinas gravadas, repetidas pelo código ([acessos.md](acessos.md#aprender-cada-sistema-ifood-erp))
- [x] Gerente + especialistas por área (comercial, financeiro, operação), cada um com as ferramentas da área ([agentes.md](agentes.md))
- [x] WhatsApp pela UAZAPI, com um ou dois números e áudio transcrito ([whatsapp.md](whatsapp.md))
- [x] Brechas (fichas com evidência, valor e status) e roteiros por tarefa para os especialistas ([brechas.md](brechas.md))
- [ ] Painel de brechas; roteiros de conciliação (maquininha, delivery) e inadimplência, quando houver os dados
- [ ] Medir o agente com IA real contra o gabarito dos dados de exemplo (custo e acertos por modelo)
- [ ] Quadro de solicitações entre áreas, com aprovação por limite de valor no código
- [ ] Fechar as sessões paradas dos clientes para a memória da VM não crescer ([custos.md](custos.md))
- [ ] Modelo configurável por agente (atendente, maestro, especialistas)
- [ ] **Ideias do Maestro do Hiago** (commit `c7c31ec`, "Acesso a qualquer sistema"; avaliado em 10/11/2026, a importar conforme a necessidade):
  - [ ] `encontrar_sistema`: achar o endereço oficial pelo nome ("uso o Bling"), conferindo que tem cara de login; só libera domínio vindo da busca ou confirmado pelo usuário (sem senha envolvida)
  - [ ] Conversa em andamento passa para as instruções novas quando o prompt ou as ferramentas mudam (hoje a conversa antiga mantém o comportamento antigo)
  - [ ] Código de verificação (SMS, e-mail) respondido por fora do modelo, como já fazemos com senha e cartão
  - [ ] Leitura da tela de login por sinais (campos, botão de entrar, recusa, limite de tentativas, verificação, iframes e componentes escondidos), no lugar da detecção só por texto
  - [ ] Conferir se o bloqueio de rede interna resiste a um site que aponta para dentro da rede (checar o IP na hora da conexão)
  - [ ] Cofre de acessos com página de link (usuário e senha uma vez, nunca pelo modelo): só se o objetivo for o agente logar sozinho; decisão do dono (hoje fora de escopo)
- [x] **Do Maestro do Hiago** (commit `a562646`, importado em 11/11/2026): reunião semanal com preparo e chamada (`docs/reuniao.md`) e o tom de consultor que não insiste no prompt do operador
- [ ] Ainda a avaliar do commit `a562646`: tom de consultor (oferta uma vez só, "não" é resposta) também no atendente dos clientes; limite diário de gasto de IA por empresa (`AGENT_LIMITE_DIARIO_USD`, somando o custo do histórico); cadastro de número novo por link (só se o produto passar a ter autoatendimento); atualizar o texto de uma tarefa da plataforma já criada quando o prompt muda
- [ ] iFood pela API oficial de parceiros (pedidos, cardápio, financeiro)
- [ ] Backup criptografado do perfil do navegador fora da VM
- [x] Compra assistida: carrinho só com o pedido, revisão e clique final do usuário (trava no código)
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

## ✅ Etapa 7: Produção na VPS
- [x] Script de provisionamento (usuário, firewall, SSH, fail2ban, atualizações automáticas)
- [x] Serviço systemd com reinício automático e prisão do processo
- [x] Caddy com HTTPS automático, expondo só o webhook
- [x] Backups diários (memória, conhecimento, agenda, conversas) com rotação
- [x] Vigia: alerta no WhatsApp se cair e quando voltar
- [x] Painel web (acesso pela VPS via túnel SSH)
- [ ] Cópia automática dos backups para fora da VPS

## Ideias futuras
- Vários agentes especializados (vendas, finanças, conteúdo) coordenados pelo principal
- Integração com bancos via Open Finance (apenas leitura)
- Painel de aprovação opcional para ações acima de um valor
