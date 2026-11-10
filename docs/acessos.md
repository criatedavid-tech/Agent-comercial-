# Acessos aos sistemas da loja

Muitas lojas usam sistemas que só funcionam pelo site: sistema da oficina, ERP, banco, portal de nota fiscal, catálogo do fornecedor. O agente usa esses sistemas pelo **navegador próprio** (Playwright). O perfil do navegador (`navegador/`) guarda os logins, então **alguém da equipe entra uma vez e o agente segue logado** até o site encerrar a sessão. Reiniciar o agente ou a VM não desloga.

Quando o site encerra a sessão, o código (sem modelo e sem custo) percebe, avisa e segura o agente até alguém entrar de novo.

## Cadastro

`empresa/sistemas.toml` (fora do git, como o resto de `empresa/`; modelo em `exemplos/empresa/sistemas.toml`):

```toml
[[sistema]]
nome = "Sistema da oficina"
endereco = "https://app.sistemadaoficina.com.br/painel"   # página que só abre logado
logado = "Sair"                                            # texto que só aparece com a sessão ativa
```

- `endereco`: uma página interna, que redireciona para o login quando a sessão cai.
- `logado`: um texto que só aparece logado, como "Sair", "Olá, Rafael" ou o nome da empresa. Maiúsculas, acentos e espaços não importam.
- Arquivo com problema: o painel e o log do servidor dizem qual sistema e o que falta.

## O que o código faz

| Quando | O que acontece |
|---|---|
| A cada `AGENT_ACESSOS_MIN` minutos (padrão 60) | abre o endereço de cada sistema numa aba à parte (não mexe na aba que o agente está usando) e procura o texto de logado |
| Texto não apareceu (tela de login ou verificação de robô) | marca o sistema como **deslogado** e avisa no WhatsApp do dono e no painel, com um link para a tela remota |
| Continua deslogado | lembra de novo a cada 4 h, sem repetir o aviso de hora em hora |
| Site não abre 2 vezes seguidas | avisa "sistema fora do ar" (uma falha só não vira alarme) |
| Voltou a aparecer logado | avisa "acesso normalizado" |
| O agente tenta abrir um sistema deslogado | `abrir_pagina` recusa e diz que a equipe já foi avisada. O agente não tenta logar nem ficar batendo na tela de login |

O agente vê a situação com a ferramenta `ver_acessos`. O painel (`/painel`) tem o cartão **Acessos aos sistemas da loja**.

O estado fica em `logs/sessoes.json`. O aviso pelo WhatsApp segue a regra das 24 h da Meta, igual ao vigia: fora da janela, o aviso fica na caixa de entrada do chat e do painel.

## Tela remota: login numa VM sem tela

Na VM o navegador roda invisível. Para entrar, a pessoa abre o **link do aviso** no celular ou no computador e vê a aba do navegador do agente ao vivo. Ali ela clica, digita e faz o login como faria no próprio navegador. No fim, toca em **Já entrei**: o código confere os acessos na hora e responde.

- **A senha é digitada pela pessoa.** As travas do agente (não digitar senha, cartão ou CPF) continuam valendo para o agente; a tela remota é a pessoa usando o navegador.
- **O link é temporário:** vale 30 minutos e só abre no domínio da VM (`AGENT_PUBLIC_URL`). Sem link válido, a rota responde 403. O código fica só em memória, em hash, e some quando o servidor reinicia. Cada aviso gera um link novo.
- **O que fica público:** só a tela remota e o webhook do WhatsApp (`deploy/Caddyfile`; `tests/test_deploy.py` confere). Painel, chat e APIs continuam só pelo túnel SSH.
- **O que a tela aceita:** clique dentro da tela, texto (até 500 caracteres por vez), teclas comuns (Enter, Tab, setas, Apagar...), rolagem, voltar, abrir endereço (sem rede local) e os gestos de **arrastar** e **segurar** (abaixo). Nada do que a pessoa digita vai para log.
- **Captcha de arrastar e "pressione e segure":** abaixo da tela há o botão **✋ Arrastar**. Ligado, o dedo (ou o mouse) arrasta direto na imagem: a página manda o caminho com o tempo de cada ponto e o navegador o repete no mesmo ritmo (`remote()` em `browser.py`, comandos `drag` e `hold`). Segurar o dedo parado por mais de meio segundo vira "pressione e segure". Depois do captcha, desligue o botão para voltar a tocar e rolar. O gesto é sempre de uma pessoa; o agente continua sem resolver verificação sozinho. Limites: até 300 pontos, 15 s de gesto, 10 s de segurar, tudo dentro da tela.
- **No computador** (sem VM), o painel tem o botão **Abrir navegador do agente**, que gera um link local na hora.

## Aprender cada sistema (iFood, ERP...)

Na primeira vez, o agente navega no sistema como uma pessoa: procura o menu, abre a tela, preenche o filtro. Daí em diante ele **não precisa repetir a exploração** (`agente/aprendizado.py`):

- **Diário do navegador:** cada passo que deu certo (abrir página, clicar em "Relatórios", preencher "Data inicial") fica registrado, com o nome visível do elemento.
- **Rotina:** ao concluir uma tarefa nova, o agente grava os passos com `salvar_rotina` ("vendas do dia"). Os valores que mudam a cada vez viram **parâmetros**: com `parametros="data=28/10/2026"`, a data do exemplo vira `{data}`.
- **Repetição pelo código:** `executar_rotina` ("vendas do dia", `data=29/10/2026`) repete os passos sem o modelo decidir cada um. É mais rápido, gasta menos e não erra o caminho.
- **Mapa do sistema:** `anotar_sistema` guarda notas como "relatório de vendas: Financeiro > Relatórios > Vendas; filtro de data no topo".
- **Ao abrir um site conhecido**, junto com a página vem "📘 Já conheço este sistema" com as notas e as rotinas, e o agente usa a rotina em vez de navegar.
- **Se o site mudar**, a rotina para no passo que não existe mais e diz qual. O agente segue dali na mão e grava de novo. Cada rotina conta quantas vezes deu certo e falhou.

| Ferramenta | O que faz |
|---|---|
| `ver_sistema` | o que já sabe de um site (notas e rotinas) |
| `anotar_sistema` | guarda uma nota sobre o sistema |
| `ver_passos` | os últimos passos do navegador, numerados |
| `salvar_rotina` | grava passos como rotina (`passos="3-9"` para escolher; sem ele, os do site atual desde a abertura) |
| `executar_rotina` | repete a rotina com os parâmetros desta vez |

**Travas:** a repetição usa as mesmas funções do navegador, então valem as mesmas regras. Senha e cartão nunca são digitados (por isso o login nunca vira passo), botões de comprar, finalizar, pagar ou assinar são recusados, e nada é digitado em página sem HTTPS. Testado em `tests/test_aprendizado.py` com um "ERP" falso, incluindo uma rotina que tenta clicar em "Finalizar pedido" e é barrada.

Fica em `conhecimento/sistemas.db` (fora do git, entra no backup), separado por empresa como todo o resto (uma VM por empresa).

### iFood

O Portal do Parceiro (`portal.ifood.com.br`) entra como qualquer sistema: cadastre em `empresa/sistemas.toml` (há um exemplo comentado), faça o login pela tela remota (com o código que o iFood manda) e peça ao agente as tarefas ("vendas de ontem no iFood", "avaliações da semana"). Na primeira vez ele navega; nas próximas usa a rotina.

O iFood também tem uma **API oficial para parceiros** (pedidos, cardápio, financeiro), mais estável que o navegador. Ela exige cadastro como desenvolvedor no iFood e homologação. Vale a pena quando a loja depender do iFood no dia a dia; o caminho pelo navegador serve para começar já.

## Cuidados

- Sessão salva é acesso aberto ao sistema da loja. A pasta `navegador/` fica só na VM da empresa; trate como uma senha. Se a VM for comprometida, troque as senhas desses sistemas.
- Quem recebe o link controla o navegador logado por 30 minutos: não repasse o aviso.
- Sites de banco encerram a sessão em minutos. Para eles, a checagem de hora em hora vai avisar quase sempre; prefira cadastrar sistemas que mantêm a sessão por dias.
