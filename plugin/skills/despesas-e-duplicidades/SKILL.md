---
name: despesas-e-duplicidades
description: Roteiro para achar gastos fora do padrão e contas pagas em dobro nas despesas da empresa. Use quando pedirem para revisar despesas, contas a pagar, "paguei isso duas vezes?", fornecedor mais caro ou categoria que subiu.
---

# Despesas e duplicidades

1. **Período e comparação.** Padrão: o mês corrente contra o anterior. `relatorio_gestao` mostra o total de despesas e a variação.
2. **Fora do padrão.** `alertas_gestao` com `area: financeiro`: categorias muito acima da média dos 3 períodos anteriores e contas lançadas em dobro (mesmo fornecedor, mesmo valor, datas próximas).
3. **Confira as linhas.** `consultar_lancamentos` na planilha `despesas` filtrando pelo fornecedor ou pelo documento. Duplicidade só é duplicidade se for o mesmo documento ou a mesma competência; mensalidade igual todo mês é normal.
4. **Para cada achado conferido:**
   - categoria que subiu: quanto subiu sobre a média e quais lançamentos explicam;
   - conta em dobro: as duas linhas (data, valor, documento) e o valor a recuperar.
5. **Registre.** `registrar_brecha` (área `financeiro`). Conta em dobro vai em `valor_unico` (o valor pago a mais). Gasto que subiu e continua alto vai em `valor_mes` (a diferença sobre a média). O título leva o documento, ex. "NF 18777 do Boi Bom paga duas vezes".
6. **Entrega.** O que é para recuperar uma vez e o que se repete por mês, separados. A ação costuma ser pedir estorno ou crédito ao fornecedor, ou renegociar. Você só analisa e recomenda: não paga nem pede nada sozinho.

Sem `despesas.csv`, diga que falta a planilha.
