# Agentes: gerente, especialistas e atendente

```
              DONO / EQUIPE (WhatsApp, chat)
                         │
                   ┌─────┴─────┐
                   │  GERENTE  │  conversa, distribui, junta e resume
                   └─┬───┬───┬─┘
         ┌───────────┘   │   └────────────┐
    COMERCIAL       FINANCEIRO        OPERAÇÃO
    funil, leads,   caixa, despesas,  estoque, compras,
    fila da equipe, margem, alertas   sistemas da loja pelo
    conversas       de dinheiro       navegador (Saipos, iFood, ERP)

    + ajudantes: pesquisador (web), organizador (base de conhecimento), verificador (confere o trabalho)

    ATENDENTE (com os clientes): separado de todos, só ferramentas do negócio
```

## Gerente

É o agente que fala com o dono e a equipe (`Agent` em `agente/core.py`, no WhatsApp da equipe, no chat e na agenda). Ele:

- **responde direto o que é rápido** ("vendas de hoje", "tem alguém na fila?"), com as próprias ferramentas;
- **delega o que é análise ou tem várias etapas** ao especialista da área, pela ferramenta `Agent`, passando tudo o que ele precisa saber;
- **junta as áreas** quando o pedido mistura assuntos ("como foi a semana?", "onde estou perdendo dinheiro?"): pede a cada especialista a parte dele (comercial e financeiro em paralelo) e responde com um resumo só, o que precisa de atenção primeiro;
- no **resumo do dia** (agenda), pede ao financeiro os alertas de dinheiro e ao comercial os leads parados e a fila.

## Especialistas

Cada um é um subagente (`AGENTS` em `agente/subagents.py`) com **só as ferramentas da sua área**: o que um não tem, ele não consegue fazer, por mais que o modelo erre. Nenhum especialista fala com o dono (devolve ao gerente), mexe em arquivo ou usa terminal.

| Especialista | Cuida de | Ferramentas |
|---|---|---|
| `comercial` | funil do WhatsApp, leads parados e perdidos, motivos de perda, fila da equipe, conversa de um cliente | `funil_comercial`, `relatorio_gestao`, `listar_leads`, `fila_atendimento`, `conversa_cliente` (só leitura do CRM) |
| `financeiro` | receita, despesas, resultado, caixa, gastos fora do padrão, contas em dobro, descontos | `relatorio_gestao`, `alertas_gestao`, `consultar_lancamentos` |
| `operacao` | estoque, compras e os sistemas da loja pelo navegador | `alertas_gestao`, `consultar_lancamentos`, navegador, aprendizado dos sistemas (`executar_rotina`, `salvar_rotina`...), `pedir_ajuda_humana`, skill de compras |

**Só a operação usa o navegador.** Ele tem uma aba só, e com dois agentes nele, um abria por cima do outro (visto no teste real). Por isso o pesquisador também não tem navegador: ele lê a web com `WebFetch` e, se uma página só funcionar com JavaScript, diz isso no resultado.

As regras de dinheiro continuam no código, valendo para todos: contas e alertas vêm das ferramentas de gestão, o comercial só lê o CRM, ninguém paga ou aprova, e o clique final de uma compra é sempre de uma pessoa.

Os testes (`tests/test_especialistas.py`) conferem a divisão: só a operação com navegador, cada área sem as ferramentas das outras, nenhum especialista com terminal ou arquivos, e todas as ferramentas e servidores citados existindo no gerente.

## Custo e tempo

Cada delegação é mais um agente rodando: um pedido delegado custa e demora mais que um respondido direto. Por isso o gerente resolve sozinho o que é simples e só distribui o que vale a pena.

## Próximo passo

Quadro de solicitações entre as áreas: a operação pede a compra de um insumo, o financeiro dá parecer e a aprovação segue um limite de valor no código, com registro de quem pediu e quem aprovou (roadmap).
