---
name: leads-parados
description: Roteiro para achar clientes do WhatsApp parados no funil, entender por que se perderam e quem a equipe deve procurar. Use quando pedirem funil de vendas, leads parados, "quem sumiu", motivos de perda ou o que fazer para vender mais.
---

# Leads parados

Você só lê e recomenda: não manda mensagem, não muda etapa e não promete preço ou desconto.

1. **Panorama.** `funil_comercial` (últimos 30 dias): leads por etapa, conversão, retomadas e motivos de perda.
2. **Quem parou.** `listar_leads` com `etapa: orcamento`, depois `qualificado` e `qualificando`, olhando a data da última atualização. Quanto mais perto do orçamento, mais valioso. Ignore contatos simulados (`sim-`).
3. **Fila da equipe.** `fila_atendimento`: quem chamou uma pessoa e espera há mais tempo.
4. **Entenda cada um.** Para os 3 a 5 mais promissores, `conversa_cliente`: o que ele queria, o que foi dito e onde a conversa parou. Quem pediu para não receber mensagens (`pediu para não receber`) não entra em nenhuma ação de contato.
5. **Motivos de perda.** Agrupe ("achou caro", "comparando preços", "sem resposta") e diga o que mudaria: prazo, forma de pagamento, resposta mais rápida.
6. **Registre.** Um grupo de leads parados em orçamento é uma brecha: `registrar_brecha` (área `comercial`) com a quantidade, o período e a lista na evidência. O valor só entra se vier do orçamento que o cliente recebeu ou do ticket médio da `relatorio_gestao`; senão, deixe sem valor. Não multiplique "leads parados vezes ticket" como se todos fossem comprar.
7. **Entrega.** Quem a equipe deve procurar primeiro, com nome, o que queria e uma ação para cada. A retomada automática já cuida de quem deu opt-in e tem janela aberta; diga quem ficou de fora e por quê.
