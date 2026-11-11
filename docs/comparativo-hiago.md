# Comparativo com o Maestro do Hiago

Projeto do Hiago (somente leitura, clonado em `C:\Users\Criate\maestro-hiago`; Node.js). Aqui, o que o **commit `a562646`** ("Cadastro por link, consultor que não insiste, reunião semanal e agenda do Google", 30 arquivos, +2.969 linhas) trouxe, comparado com o nosso agente. Avaliado em 11/11/2026. O comparativo do commit anterior (`c7c31ec`) está no fim.

Os dois projetos têm o mesmo miolo (braço direito do dono pelo WhatsApp, com subagentes por área, brechas em R$ e navegador), mas objetivos diferentes. O Maestro é uma **plataforma com várias contas** (cada cliente tem pasta, cofre e limite próprios). O nosso é **um agente por empresa** (uma VM por empresa), com um **atendente** que vende para os clientes da empresa, coisa que o Maestro não tem.

## Placar do commit `a562646`

| # | O que o Hiago fez | Nosso hoje | Decisão |
|---|---|---|---|
| 1 | **Reunião semanal**: ferramenta `reuniao_semanal`, duas rotinas (preparo calado + chamada), pauta em arquivo, trava "só em resposta ao dono" | não tinha | **Importado** (`agente/reuniao.py`, `docs/reuniao.md`) |
| 2 | **Consultor que não insiste**: começa pela pessoa e pela dor, uma oferta por vez, "não" é resposta, varia abertura e fecho | prompt mais "executor" | **Importado** no prompt do operador |
| 3 | Resposta `(sem mensagem)` não é entregue (preparo, revisão diária) | todo resultado da agenda ia para o dono | **Importado** (`Scheduler.tick`) |
| 4 | Rotinas da plataforma fora do limite de tarefas | só o resumo do dia era exceção | **Importado** (`PLATFORM_IDS`) |
| 5 | **Agenda do Google do dono**: ver, **horários livres no expediente**, criar, mudar, cancelar, **repetição** (diária, semanal, mensal), convidados só com confirmação | temos **mais** (todas as agendas, Meet, convidados com sim, editar e cancelar), mas **sem "horário livre" e sem repetição** | **Lacuna nossa**: vale importar os dois (ver "Próximos") |
| 6 | Escopo mínimo do Google (`calendar.events` + login) e renovação do token em fila por cliente | escopos amplos e cofre Fernet para uma conta | Nosso é mais amplo de propósito; a fila por cliente só importa com várias contas |
| 7 | Travas de turno no código (marcar reunião, mexer na agenda, desconectar o Google só em resposta ao dono) | já temos para lixeira, envio e ações (`self.turn`); **desconectar** só pela página local | Equivalente; reunião agora segue o mesmo princípio |
| 8 | **Cadastro por link**: número novo recebe resposta pronta (sem IA), link com 4 campos, a conta nasce pelo WhatsApp; limites por número, por dia e de contas novas | uma empresa por VM, sem autoatendimento | **Fora de escopo** agora; só se o produto virar autoatendimento |
| 9 | **Limite diário de IA por cliente** (US$ 5 para conta de cadastro), aviso uma vez ao dia e pausa | só teto por pedido (`AGENT_MAX_BUDGET_USD`) | **Avaliar**: cabe como `AGENT_LIMITE_DIARIO_USD`, somando o custo do histórico |
| 10 | Jornada vira **bússola** (marcos em aberto, sem ordem fixa) e ganha o marco "reunião" | não temos jornada de marcos | Não importa: o nosso roteiro é por brechas e especialistas |
| 11 | `resumo.md`: o resumo da conversa guarda **ofertas sem resposta** e o estado da reunião | resumo é do Claude Code | Parcial: as ofertas sem resposta vão para `memory/notas.md` pelo prompt |
| 12 | Revisão diária: "não repita oferta sem resposta na última semana"; reunião faltada → resumo da semana em uma mensagem | resumo diário às 07:00 sem essa regra | **Pequeno ajuste a fazer** no `SUMMARY_PROMPT` |
| 13 | Texto digitado no cadastro entra no prompt **entre aspas, como dado** | n/a (sem cadastro) | Boa prática; vale para qualquer texto de cliente que entre em prompt |
| 14 | Painel: blocos de cadastro e Google, estado ao vivo e **recusa de comando vindo de outra página** (`hostsDoPainel`) | web só local, checa `Origin` e `Host` | Já cobrimos |
| 15 | Correções: resposta automática que não saía em número sem outro sistema; fila por identificação (corrida do LID); **espera do download no clique** do navegador | a UAZAPI já ignora LID sem telefone; nosso navegador **não baixa arquivo** (`accept_downloads=False`) | Nada a fazer agora |
| 16 | Testes: cadastro, agenda, Google de mentira, bancada visual e prova com IA real (`avaliar-conversa.js`) | testes com Google falso e modelo falso | A **prova com IA real** é uma boa ideia: ver "Próximos" |

## O que o nosso tem e o Maestro não

- **Atendente** que fala com clientes da empresa (só ferramentas do negócio, catálogo, orçamento, regras de desconto e de "sou humano"), **CRM** com LGPD e opt-out, **retomada** de leads, **passagem para a equipe** (`FILA`/`ASSUMIR`/`DEVOLVER`) e painel de atendimento.
- **Gestão com contas feitas pelo código** (`gestao.py`, alertas com problema plantado nos testes) e ficha de **brechas** com evidência obrigatória.
- **Google bem maior**: Gmail (ler, organizar, enviar e apagar com sim), Drive, Planilhas, Documentos e Tarefas, com lista fixa de escritas (`WRITE_ALLOWED`).
- **Acessos aos sistemas da loja** (sessões vigiadas, tela remota por link, rotinas aprendidas), backup, vigia e deploy.
- Rodar **sem custo** com modelo gratuito pelo OpenRouter.

## O que o Maestro tem e o nosso não (e o que fazer)

| Do Maestro | Faz sentido? |
|---|---|
| Cadastro por link e várias contas na mesma plataforma | Só no modelo de autoatendimento |
| Limite diário de IA por cliente | Sim, é regra de dinheiro no código |
| Cofre de acessos por link (usuário e senha uma vez, fora do modelo) | Decisão do dono; hoje o login é pela tela remota |
| `encontrar_sistema` (acha o endereço pelo nome) | Sim, já no roadmap |
| Preparo da reunião cruzando áreas | Importado |

## Próximos passos sugeridos (por valor)

1. **Agenda: horários livres e repetição.** `ver_agenda_google` já lê tudo; falta uma ferramenta `horarios_livres_agenda` (expediente configurável, até 8 janelas) e `repetir` em `criar_compromisso_agenda` (regra `RRULE`, só diária, semanal e mensal). Pequeno, com teste no Google falso.
2. **`SUMMARY_PROMPT`**: não repetir oferta sem resposta na semana e, se a reunião foi faltada, mandar o resumo da semana em uma mensagem.
3. **Limite diário de gasto de IA** (`AGENT_LIMITE_DIARIO_USD`, desligado por padrão), com aviso uma vez ao dia.
4. **Prova com IA real**: um script que conversa de verdade com o modelo gratuito em 3 ou 4 cenários (dono com pressa, "agora não", pedido de reunião) e confere o tom e as travas, como o `avaliar-conversa.js` do Hiago.
5. **Tom de consultor no atendente**: oferta uma vez só e "não" como resposta também com os clientes, respeitando as regras de venda e de LGPD.
6. Do commit anterior, ainda abertos: `encontrar_sistema`, instruções novas para conversa em andamento e leitura da tela de login por sinais (`docs/roadmap.md`).

## Avaliação do comportamento (11/11/2026) e o que aplicamos

Lida a partir do prompt, da config e de três conversas reais do Maestro. Achados: credencial digitada no chat gravada em texto puro no log; "anotei no cadastro" sem gravar nada; insistência na mesma pergunta; recusa repetida fora do tema; link de login para `localhost`. O modelo local (Nemotron gratuito) explica parte; as medições dele usam Haiku e GPT-6 Luna.

Aplicado aqui: filtro de senha na linha de baixo e no atendente (`redact_secrets`) e aviso de "anotei" sem ferramenta (`unbacked_claim`), com testes em `tests/test_afirmacoes.py`. Ainda aberto: contar insistência por oferta no código e prova com IA real.

## Commit anterior (`c7c31ec`, 10/11/2026)

"Acesso a qualquer sistema": achar o sistema pelo nome, cofre por link e login que entende a tela. As ideias estão no `docs/roadmap.md` (seis itens), nenhuma importada ainda além do que já tínhamos de acessos e tela remota.
