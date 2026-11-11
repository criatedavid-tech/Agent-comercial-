# Reunião semanal com o dono

Muito dono nunca para para olhar a própria semana. Com um horário fixo (10 a 15 minutos pelo WhatsApp), o agente traz os números e o que achou, e olhar a empresa vira hábito. Ideia vinda do Maestro do Hiago (commit `a562646`), refeita sobre a nossa agenda.

## Como funciona

1. O agente propõe o horário **uma vez**, quando a conversa já andou e há algo a acompanhar (um achado que acabou de contar, ou o dono perguntar como acompanhar). Se o dono não quiser agora, não volta ao assunto por duas semanas.
2. Com o dia e a hora que o dono disser, o agente chama `reuniao_semanal` (`acao: marcar`). O código cria duas tarefas semanais na agenda (`agente/reuniao.py`):
   - **preparo**, 2 horas antes (se cair de madrugada, na véspera às 20h): o agente levanta a semana com o financeiro, o comercial e a operação, compara com a semana anterior e grava a pauta em `workspace/reuniao-semanal.md`. Termina com `(sem mensagem)`, e a agenda não entrega nada ao dono;
   - **chamada**, na hora: uma mensagem curta convidando para a conversa. A resposta final dessa tarefa é a própria mensagem.
3. Se o dono topar, o agente conduz pela pauta, uma mensagem por vez: como foi a semana para ele, os 3 números com a fonte, de 1 a 3 achados com valor em R$ e um combinado (o que o agente faz sozinho e a única coisa que precisa do dono).
4. Para mudar o horário ou cancelar, a mesma ferramenta (`marcar` de novo, `cancelar`); `situacao` mostra o que está combinado.

## Travas no código

- **Marcar e cancelar só valem em resposta a uma mensagem do dono.** O turno aberto pela própria agenda (`Agent.run_once`) não consegue criar nem apagar a rotina, e um texto de e-mail ou de página não vira ordem. Ver a situação é livre.
- Hora de 06:00 a 22:00; dia e hora inválidos voltam como erro para o modelo corrigir.
- As duas tarefas são "da plataforma": não contam no limite de 30 tarefas ativas, como o resumo do dia.
- A chamada é uma mensagem só; não há insistência.

## Tom de consultor

Junto veio um ajuste no prompt do operador (`SYSTEM_PROMPT` em `core.py`): começar pela pessoa e pela dor, entrar aos poucos, **uma oferta por vez e uma vez só**, "não" é resposta (anotada em `memory/notas.md`), nem toda mensagem termina em proposta, e variar abertura e fecho.

## Testes

`tests/test_reuniao.py`: dia e hora em linguagem natural, horário do preparo, criar, mudar e cancelar, limite de tarefas, a trava de turno (agenda não marca nem cancela), entrega silenciosa e os trechos do prompt.
