# Gestão da empresa

O operador (o agente do dono) lê as planilhas da loja e responde a "como foi o mês?", "onde estou perdendo dinheiro?", "tem alguém desviando?". **Todas as contas e todos os alertas são feitos pelo código** (`agente/gestao.py`); o modelo só explica, prioriza e sugere o que fazer. Assim o número não depende de o modelo fazer conta certa.

## As planilhas

Pasta de dados: `AGENT_DADOS_DIR`; sem ela, `dados/` na raiz do projeto (se tiver algum `.csv`); sem nenhuma, os dados fictícios de `exemplos/dados/` (Auto Center Rota Certa, agosto a outubro de 2026). `dados/` fica **fora do git** e entra no `agente-backup`.

CSV exportado do sistema da loja ou de uma planilha (Excel/Google Planilhas → "Salvar como CSV"). Vírgula ou ponto e vírgula; datas `2026-10-28` ou `28/10/2026`; valores `1.234,56` ou `1234.56`. Nenhuma planilha é obrigatória: o que existir é analisado.

| Arquivo | Uma linha por | Colunas (nomes alternativos aceitos) |
|---|---|---|
| `vendas.csv` | item de OS ou venda | **data**, os, cliente, veiculo, **item**, tipo (servico/peca), quantidade, valor_unitario, desconto, **total**, pagamento, funcionario (vendedor, atendente), status (fechada/cancelada) |
| `despesas.csv` | conta paga | **data**, categoria (plano de contas), descricao, fornecedor (favorecido), **valor** (valor pago) |
| `estoque.csv` | movimento de estoque | **data**, **produto**, **tipo** (entrada/saida/ajuste), **quantidade**, custo_unitario, os, funcionario (mecânico), motivo |
| `caixa.csv` | fechamento de caixa | **data**, funcionario, **registrado** (valor no sistema), **contado** (dinheiro na gaveta) |

Em negrito, as obrigatórias de cada arquivo. Coluna com outro nome: a lista completa de nomes aceitos está em `ALIASES` (`gestao.py`); se faltar, o erro diz qual coluna e quais nomes servem. Linha com data ou valor ilegível: o erro diz arquivo, linha e coluna.

## O que o código calcula

**Números do período** (comparados com o período anterior de mesmo tamanho): receita (só vendas fechadas), serviços × peças, número de OS, ticket médio, descontos dados, despesas por categoria, resultado e margem, cancelamentos.

**Alertas**, os mais graves primeiro:

| Área | Alerta | Regra |
|---|---|---|
| financeiro | Gasto acima do normal | categoria com gasto > 140% da média dos 3 períodos anteriores e pelo menos R$ 300 a mais. Período que começa no dia 1 é comparado com os meses cheios anteriores |
| financeiro | Conta paga em duplicidade | mesmo fornecedor e mesmo valor (≥ R$ 100) em até 5 dias |
| estoque | Saída de estoque sem venda | saída sem OS, com OS que não existe nas vendas ou com OS cancelada, por funcionário. Compara pela OS e não pelo nome, porque o serviço consome peças com outro nome ("troca de óleo" → "óleo 5W30") |
| estoque | Muitos ajustes de perda | 3 ou mais ajustes negativos do mesmo funcionário |
| equipe | Desconto acima da equipe | funcionário com ≥ 5% de desconto sobre o valor cheio e pelo menos o dobro dos demais |
| equipe | Cancelamentos acima do normal | 3 ou mais OS canceladas e pelo menos o dobro da taxa dos demais (venda cancelada depois de recebida é padrão comum de desvio) |
| caixa | Diferença de caixa | fechamentos com diferença acima de R$ 20, somando o que faltou por funcionário |
| funcionamento | Movimento desigual | dias da semana com 50% mais ou menos OS que a média (fila num dia, ociosidade no outro) |

Alerta sobre pessoa é **indício para conferir**, nunca acusação: um lançamento esquecido produz o mesmo sinal que um desvio. O operador é instruído a dizer o que conferir e como.

**Funcionamento**: média de OS por dia da semana, itens que mais faturam, vendas por funcionário.

**Atendimento** (do `crm.db` do atendente): leads por etapa, conversão em venda, retomadas enviadas, quem pediu para parar e os motivos prováveis de quem parou de responder.

## Como usar

Pelo operador (chat, painel ou WhatsApp da equipe), em linguagem natural: "como foi outubro?", "onde estou perdendo dinheiro?", "confere as saídas de estoque do Diego", "quanto de desconto o Paulo deu?". Ferramentas:

| Ferramenta | O que faz |
|---|---|
| `relatorio_gestao` | números, alertas, funcionamento e funil do período |
| `alertas_gestao` | só os alertas, com filtro por área |
| `consultar_lancamentos` | as linhas de uma planilha (filtro por texto, funcionário e período) para conferir um alerta |
| `funil_comercial` | o funil do atendimento no WhatsApp |

Período em palavras ("este mês", "mês passado", "outubro", "últimos 30 dias", "semana") ou datas. Sem período: os últimos 30 dias até o último dia com dados.

Sem modelo e sem custo, no terminal:

```bash
agente-gestao outubro
```

```bash
agente-gestao "mês passado" --alertas
```

Para receber toda segunda os alertas da semana, peça ao operador: "toda segunda às 8h, rode os alertas de gestão da semana e me mande o que for alta" (vira uma tarefa da agenda).

## Privacidade

As planilhas ficam na máquina ou VPS da empresa. O que o operador lê vai para o modelo configurado (`AGENT_MODEL`): com dados reais de clientes e funcionários, use um provedor com política de não treinar com os dados (a API da Anthropic não treina com dados da API). Modelos gratuitos do OpenRouter podem guardar o conteúdo: use-os só com os dados de exemplo.

## Dados de exemplo

`exemplos/dados/gerar_exemplo.py` gera as planilhas fictícias com problemas plantados em outubro: peças tiradas do estoque sem OS (Diego), desconto alto (Paulo), caixa faltando (Juliana), manutenção de equipamentos disparando e uma conta de lubrificantes paga duas vezes. Setembro não tem problemas: os testes conferem que os alertas acham os plantados e não inventam outros.
