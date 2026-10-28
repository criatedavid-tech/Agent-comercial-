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
- **O que a tela aceita:** clique dentro da tela, texto (até 500 caracteres por vez), teclas comuns (Enter, Tab, setas, Apagar...), rolagem, voltar e abrir endereço (sem rede local). Nada do que a pessoa digita vai para log.
- **No computador** (sem VM), o painel tem o botão **Abrir navegador do agente**, que gera um link local na hora.

## Cuidados

- Sessão salva é acesso aberto ao sistema da loja. A pasta `navegador/` fica só na VM da empresa; trate como uma senha. Se a VM for comprometida, troque as senhas desses sistemas.
- Quem recebe o link controla o navegador logado por 30 minutos: não repasse o aviso.
- Sites de banco encerram a sessão em minutos. Para eles, a checagem de hora em hora vai avisar quase sempre; prefira cadastrar sistemas que mantêm a sessão por dias.
