---
name: compras-online
description: Como pesquisar, comparar e preparar compras online até a revisão do pedido (quem finaliza é o usuário), lidando com login, CAPTCHA, carrinho já cheio e lojas como Amazon e Mercado Livre. Use quando o pedido envolver comprar, cotar, comparar preços, montar carrinho ou usar uma loja com cadastro.
---

# Compras online

Você leva a compra **até a tela de revisão do pedido**. O clique final ("Finalizar pedido", "Comprar agora", "Pagar") é **sempre do usuário**: o navegador recusa esses cliques no código.

## 1. Pesquisa
- Delegue a comparação ao subagente `pesquisador`: preço total (com frete), prazo, vendedor (loja própria × marketplace), reputação (Reclame Aqui) e troca.
- Desconfie de preço muito abaixo da média. Prefira "vendido e entregue por" uma loja conhecida.
- Se o usuário só pediu preços, pare aqui e mostre a comparação.

## 2. Entrar na loja
- Use o navegador próprio (`abrir_pagina`). Ele guarda os logins que o usuário fez nele.
- Se a página mostrar que **não está logado** ("Faça seu login", "Entrar") e o pedido é comprar: chame `pedir_ajuda_humana` pedindo para o usuário **fazer login na janela do navegador do agente** e marcar "manter conectado". Você nunca digita senha.
- CAPTCHA, "você é um robô?", código por SMS ou e-mail: **não tente passar**. `pedir_ajuda_humana` e continue depois.
- Se a verificação voltar ou "falhar" (Shopee, por exemplo), o site barrou o navegador automático: **não insista**. Avise o usuário que essa loja ele confere no próprio celular e compare preços por outras fontes.
- Aviso de cookies: recuse os não essenciais; nunca "Aceitar todos".

## 3. Produto
- Em páginas grandes, use `listar_elementos` **com filtro** ("carrinho", "cor", "quantidade") em vez de listar tudo.
- Confira **variação** (cor, tamanho, voltagem), **vendedor** e **quantidade** antes de adicionar.
- Use **"Adicionar ao carrinho"** do produto pedido: em `listar_elementos`, ele aparece como "— item: produto da página: …". Não use "Comprar agora" (é bloqueado: pode fechar a compra em um clique).
- Depois de adicionar, a loja mostra **recomendações** ("comprados juntos", "você também pode gostar") com outros botões "Adicionar ao carrinho": **nunca clique neles**. Confirme pelo aviso "Adicionado ao carrinho" e vá para o carrinho.
- Cada clique responde "Cliquei em [n] …": confira se foi o que você queria.

## 4. Carrinho (pode já ter itens do usuário!)
- O carrinho é da **conta**: ele pode ter itens que o usuário guardou e **não pediu agora**.
- **Nunca exclua** itens do usuário nem mude quantidades deles.
- Para comprar só o pedido: use `listar_elementos` com filtro "selecionar" ou o nome do item e **desmarque** (☐) as caixinhas dos itens que não fazem parte do pedido. Deixe marcado (☑) só o que foi pedido.
- Se a loja não permite desmarcar e há outros itens: **pare** e chame `pedir_ajuda_humana` explicando que o carrinho tem itens que não foram pedidos.
- Confira o subtotal: tem que bater com o preço do(s) item(ns) pedido(s).

## 4b. Ofertas no caminho (REGRA EXPRESSA: nunca assine nada)
- Entre o carrinho e a revisão, lojas oferecem assinatura (Amazon Prime, "teste grátis"), garantia estendida, seguro. **Recuse** ("Não, obrigado(a)", "Continuar sem", "Agora não"). Botões de assinar são bloqueados no código.
- **Programe e Poupe / Assine e economize** (Amazon, na página do produto): é entrega e cobrança recorrentes. Escolha sempre **"Compra única"** antes de "Adicionar ao carrinho"; o código bloqueia clicar na opção de assinatura.
- No fechamento, caixinhas como "Obter frete grátis com o Prime" ou "Experimente o Prime" ficam **desmarcadas**: o código bloqueia marcar.
- Na revisão, confira se não entrou nenhuma assinatura (Prime, Programe e Poupe, Kindle Unlimited) junto com o pedido.

## 5. Revisão do pedido
- Avance até a tela de revisão (na Amazon, "Fechar pedido" leva até ela).
- Leia a página (`ler_pagina`) e confira **item por item**: só o que foi pedido, quantidade, cor, vendedor, endereço, frete, prazo e forma de pagamento. Se aparecer **qualquer item a mais**, pare e avise.
- Chame `pedir_ajuda_humana` com o resumo, por exemplo:
  "Pedido pronto na Amazon: 1× Controle DualSense branco (vendido por Amazon), R$ 376,20, frete grátis, chega 01/11, pagamento: cartão final 1234. Confira na janela do navegador e clique em Finalizar pedido."
- Se a resposta for "não consegui" ou ele desistir, deixe como está e não tente de novo sozinho.

## 6. Depois
- Só registre a compra quando o usuário disser **com todas as letras que finalizou** ("comprei", "finalizei", "pedido feito"). "Vou conferir", "ok" ou "vou finalizar" ainda não é compra. Então salve em `financas`: o que, onde, quanto, quando, número do pedido se ele informar.
- Salve em `geral` lojas boas ou ruins.
