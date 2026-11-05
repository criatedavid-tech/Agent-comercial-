---
name: raio-x-financeiro
description: Roteiro do primeiro olhar financeiro numa empresa (ou da revisão mensal), do número ao achado com valor em R$. Use quando pedirem um raio-x, "como está o financeiro", "onde estou perdendo dinheiro" ou ao receber dados novos da loja.
---

# Raio-x financeiro

Objetivo: sair com poucos achados concretos, cada um com evidência, valor e uma ação, e não com um relatório genérico.

1. **Período.** Confirme o período (padrão: o mês corrente e o anterior). Diga na resposta qual usou.
2. **Números.** `relatorio_gestao` do período: receita, despesas, resultado e a comparação com o período anterior. Não refaça conta nenhuma: os números são do código.
3. **Alertas.** `alertas_gestao` (sem filtro): comece pelos de gravidade alta. Para cada um, `consultar_lancamentos` e confira as linhas que o sustentam antes de falar dele.
4. **O que dá para afirmar.** Separe em três grupos e deixe claro qual é qual:
   - conferido: você viu as linhas;
   - indício: o alerta aponta, mas pode ter explicação (esquecimento, garantia, uso interno);
   - não deu para conferir: faltou planilha ou coluna. Diga qual.
5. **Registre.** Para cada achado conferido, `registrar_brecha` com título curto (com o número da nota ou da venda, quando houver), a área, a evidência (ferramenta, período, linhas) e a ação. Valor só se veio de uma ferramenta: `valor_mes` se o problema se repete, `valor_unico` se é um valor a recuperar. Nunca estime no olho.
6. **Entrega.** Faturamento e resultado em duas linhas, depois as brechas por valor, a maior primeiro, e a pergunta de sim ou não sobre a primeira ("quer que eu confira a nota X com o fornecedor?"). Alertas sobre pessoas são indício: diga o que conferir, nunca acuse.

Você não paga, não transfere e não corrige lançamento: só analisa e recomenda.
