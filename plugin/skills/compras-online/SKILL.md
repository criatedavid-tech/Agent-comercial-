---
name: compras-online
description: Como pesquisar e preparar compras online, comparar preços e lojas, e lidar com sites que pedem login, CAPTCHA ou verificação. Use quando o pedido envolver comprar, cotar, comparar preços ou usar uma loja ou site com cadastro.
---

# Compras online

## Pesquisa
- Delegue a comparação ao subagente `pesquisador`: preço total (com frete), prazo, reputação da loja (Reclame Aqui) e política de troca.
- Prefira APIs oficiais e marketplaces conhecidos a sites desconhecidos. Desconfie de preço muito abaixo da média.

## Verificações e bloqueios
- CAPTCHA, "você é um robô?", login, código por SMS ou e-mail: **não tente passar nem contornar**.
  Chame `pedir_ajuda_humana` com o motivo e o link, e continue quando o usuário responder.
- Nunca crie conta, aceite termos ou digite senha ou cartão sozinho.

## Finalizar
- Hoje você **não finaliza compras**: monte o carrinho ou a lista com links, preço total e prazo, e peça ao usuário para concluir.
  O pagamento automático só virá com cartão virtual e teto de valor no código (etapa 4 do roadmap).

## Depois
- Salve em `financas` o que foi comprado (o que, onde, quanto, quando) e em `geral` lojas boas ou ruins.
