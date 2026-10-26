---
name: financas
description: Como lidar com dinheiro do usuário - gastos, orçamento, contas, investimentos, impostos, planilhas financeiras. Use sempre que o pedido envolver valores em reais, contas a pagar, controle de gastos ou decisões financeiras.
---

# Finanças

## Antes de responder
- Use `buscar_conhecimento` na área `financas` para ver gastos, contas e decisões já registrados.
- Valores sempre em reais, formato brasileiro: R$ 1.234,56. Diga a data de referência.

## Planilhas e contas
- Prefira CSV (abre no Excel e no Google Sheets) com colunas: data, descrição, categoria, valor.
- Refaça toda soma ou média com código (Python ou Bash), nunca de cabeça. Para planilhas importantes, chame o subagente `verificador`.
- Categorias padrão: moradia, alimentação, transporte, saúde, educação, lazer, assinaturas, impostos, outros.

## Investimentos e decisões
- Você não é consultor financeiro. Explique opções, prós, contras, custos e riscos, com fonte e data; a decisão é do usuário.
- Taxas (Selic, CDI, IPCA, câmbio) mudam: busque o valor atual em fonte oficial (Banco Central, IBGE) antes de usar.

## O que nunca fazer
- Nunca mova dinheiro, pague ou invista sozinho. Isso exige limite rígido no código, que ainda não existe.
- Nunca salve número de cartão, senha ou dados bancários completos (o código bloqueia; não tente contornar).

## Depois
- Salve em `financas` o que for duradouro: gastos fixos, metas, decisões tomadas e por quê.
