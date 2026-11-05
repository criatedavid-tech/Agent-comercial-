---
name: fechamento-caixa
description: Roteiro para conferir o caixa do dia ou da semana (dinheiro registrado no sistema contra o contado) e achar diferenças por funcionário. Use quando pedirem fechamento de caixa, "o caixa bateu?", diferença de caixa ou conferência do dia.
---

# Fechamento de caixa

1. **Dia.** Padrão: ontem, ou o último dia com lançamento em caixa. Diga a data usada.
2. **Diferenças.** `alertas_gestao` com `area: caixa` no período. Cada alerta mostra funcionário, dia, registrado, contado e a diferença.
3. **Linhas.** `consultar_lancamentos` na planilha `caixa` (e em `vendas` do mesmo dia, se precisar) para ver os valores exatos. Não some nada de cabeça.
4. **Padrão ou acaso.** Uma diferença pequena e isolada é troco. O que importa:
   - o mesmo funcionário com diferença em vários dias;
   - diferença sempre para menos, no mesmo turno;
   - diferença perto do valor de uma venda em dinheiro do dia (venda não lançada ou lançada na forma errada).
5. **Registre.** Só o que for padrão ou valor relevante: `registrar_brecha` na área `financeiro`, com data, funcionário, registrado e contado na evidência, e o valor da diferença em `valor_unico`. Se a mesma diferença se repete todo mês, use `valor_mes` com a média dos meses conferidos.
6. **Entrega.** Total do dia (registrado, contado, diferença), depois as diferenças por funcionário. A ação é recontar junto com a pessoa e conferir as vendas em dinheiro do dia, nunca acusar: diferença de caixa é indício.

Se não houver `caixa.csv` na pasta de dados, diga isso e peça a planilha. Não invente fechamento.
