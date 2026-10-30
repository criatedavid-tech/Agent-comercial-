# VM e custos mensais

Estimativas para uma loja com **20 conversas de clientes e 15 pedidos do dono por dia**. São contas de planejamento, ainda não medidas em produção: confirme com uma semana de piloto usando a API da Anthropic (o painel registra o custo de cada pedido; com o OpenRouter, o valor mostrado não é confiável).

## VM

O modelo roda fora da VM e o WhatsApp roda na UAZAPI ou na Meta. O que pesa é a **memória**: cada conversa ativa abre um processo do Claude Code (estimativa de 200 a 400 MB) e o navegador usa de 300 a 600 MB.

| Uso | vCPU | RAM | Disco |
|---|---|---|---|
| Piloto, até ~5 conversas ao mesmo tempo | 2 | 4 GB + 2 GB de swap | 40 GB |
| **Loja com movimento**, 10 a 15 conversas ao mesmo tempo | **4** | **8 GB** | **80 GB** |
| Pico, 20 ou mais conversas ao mesmo tempo | 4 a 8 | 16 GB | 80 GB |

Use Ubuntu 24.04 LTS, um data center em São Paulo e um domínio próprio apontando para a VM (HTTPS automático pelo Caddy).

**Limite conhecido:** a sessão de cada cliente fica aberta até o servidor reiniciar. Falta fechar as sessões paradas e retomá-las quando o cliente voltar; até lá, a memória cresce com o número de clientes atendidos.

## Modelo de IA

Preços da API da Anthropic por milhão de tokens (consulta de out/2026; confira os atuais):

| Modelo | Entrada | Saída | Leitura de cache |
|---|---|---|---|
| Claude Opus 5.5 | US$ 4,00 | US$ 20,00 | US$ 0,20 |
| Claude Sonnet 5.5 | US$ 2,00 | US$ 10,00 | US$ 0,20 |
| Claude Haiku 5.5 | US$ 0,10 | US$ 0,50 | não consultado |

Premissas: uma mensagem de cliente faz cerca de 3 chamadas ao modelo, uma conversa tem cerca de 8 mensagens e um pedido do dono faz cerca de 8 chamadas.

| Uso | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| Conversa de cliente | ~US$ 0,03 | ~US$ 0,22 | ~US$ 0,40 |
| Pedido do dono | não recomendado | ~US$ 0,15 | ~US$ 0,25 |
| Resumo do dia | não recomendado | ~US$ 0,30 | ~US$ 0,50 |

## Total por mês

| Item | Valor aproximado |
|---|---|
| Atendente (600 conversas) | Haiku ~US$ 18 · Sonnet ~US$ 130 · Opus ~US$ 240 |
| Maestro e especialistas (450 pedidos + 30 resumos) | Sonnet ~US$ 75 · Opus ~US$ 125 |
| VM de 8 GB em São Paulo | ~US$ 40 a 80, a confirmar no provedor |
| Domínio `.com.br` | ~R$ 40 por ano |
| Transcrição de áudio | centavos (~US$ 0,001 por minuto) |
| UAZAPI | depende do plano |

| Combinação | Total com VM, sem UAZAPI |
|---|---|
| Econômica: Haiku no atendente, Sonnet no maestro | ~US$ 140 a 180 |
| Equilibrada: Sonnet em tudo | ~US$ 250 a 290 |
| Máxima: Opus em tudo | ~US$ 400 a 450 |

Hoje `AGENT_MODEL` vale para o maestro e para o atendente: a combinação econômica ainda exige um modelo configurável por agente. Os especialistas e ajudantes usam o apelido `sonnet`.

## Teto de gasto

`AGENT_MAX_BUDGET_USD` limita cada pedido. Em produção, mantenha um valor baixo: o padrão é US$ 2,00.
