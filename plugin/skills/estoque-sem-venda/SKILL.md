---
name: estoque-sem-venda
description: Roteiro para conferir saídas de estoque sem venda correspondente (esquecimento, garantia, uso interno ou desvio) e o que pode faltar. Use quando pedirem para conferir estoque, perdas, "sumiu peça" ou reposição.
---

# Estoque sem venda

1. **Período.** Padrão: últimos 30 dias.
2. **Alertas.** `alertas_gestao` com `area: estoque`: saídas de estoque sem uma venda ou OS ligada.
3. **Linhas.** `consultar_lancamentos` nas planilhas `estoque` e `vendas` para o item. Confira se existe venda do mesmo item perto da data: a saída pode ter sido lançada em outro dia.
4. **Causas, da mais comum à menos:** lançamento esquecido na venda, garantia ou retrabalho, uso interno da loja, ajuste de inventário, desvio. Diga a causa mais provável e o que a confirmaria (a OS, a nota, o responsável do dia). Quando o alerta apontar uma pessoa, é indício.
5. **Valor.** Saída sem venda vale o custo do item (quantidade vezes custo unitário, como a ferramenta traz). Vai em `valor_unico`.
6. **Registre.** `registrar_brecha` (área `operacao`) por item ou grupo de itens com a mesma causa provável.
7. **Se for preciso olhar o sistema da loja** (Saipos, ERP) para achar a venda ou o pedido ao fornecedor: use o navegador pela rotina do sistema (`ver_sistema`, `executar_rotina`). Compra e pedido você leva até a revisão e para: o clique final é do usuário.

Reposição: com a saída média do período, diga o que acaba primeiro, mas só recomende; não faça pedido.
