# Uso

## Como pedir bem

O agente age melhor com **objetivo + contexto + formato de entrega**.

| Fraco | Forte |
|---|---|
| "pesquisa VPS" | "compare 3 VPS com 4 GB de RAM abaixo de US$ 10/mês e salve uma tabela em vps.md" |
| "faz um texto" | "escreva um post de LinkedIn de 5 linhas sobre o lançamento da Orto-Neuro, tom profissional e animado" |
| "organiza isso" | "leia os arquivos .csv do workspace, junte num só e calcule o total por mês" |

## Exemplos por categoria

**Pesquisa**
- `pesquise as novidades de IA desta semana e me dê 5 tópicos com link`
- `quanto custa registrar uma marca no INPI? resuma o passo a passo`

**Arquivos e dados**
- `crie uma planilha de controle financeiro em CSV com categorias e meses`
- `leia relatorio.txt e gere um resumo executivo de 10 linhas`

**Programação e automação**
- `crie um script Python que baixa a cotação do dólar e salva num CSV`
- `instale as dependências e rode o script; se der erro, corrija`

**Escrita em seu nome**
- `rascunhe um e-mail para um fornecedor pedindo desconto de 10%` (o envio entra na etapa 3)

**Memória**
- `lembre que meu horário de trabalho é das 9h às 18h`: ele anota em `memory/notas.md`.

## Conversa contínua

Dentro da mesma sessão ele lembra do que foi dito: "agora transforme isso numa tabela" funciona. Use `/nova` para limpar o contexto (economiza tokens e evita confusão entre assuntos).

## Pelo navegador

Rode `agente-web` e abra http://127.0.0.1:8000. Cada aba é uma conversa separada; o botão **Nova conversa** faz o mesmo que `/nova`. Se a `ANTHROPIC_API_KEY` estiver vazia, a página mostra um aviso no topo.

- **Conversas**: lista as anteriores; clique para retomar com todo o contexto.
- **↶ desfazer edições deste pedido**: aparece embaixo de cada pedido e volta os arquivos que o agente criou ou editou a partir dali.
- **Painel**: gasto de hoje, 7 e 30 dias, gráfico por dia, conversas recentes, agenda (com cancelar), base de conhecimento e bloqueios de segurança.

No terminal: `/conversas`, `/retomar N` e `/desfazer` (último pedido).

## Compras

"Compra pra mim um controle DualSense branco na Amazon." O agente pesquisa, entra na loja pelo navegador dele, adiciona ao carrinho, **desmarca (sem excluir) os itens que já estavam no seu carrinho e você não pediu agora**, vai até a revisão do pedido e te chama com o resumo (itens, total, entrega, pagamento). **Quem clica em "Finalizar pedido" é você**: o navegador recusa esse clique no código.

Na primeira vez, ele te pede para fazer login na janela do navegador dele; depois fica logado. Funciona no seu computador (na VPS o navegador não tem janela).

## Sites com login, formulários e verificação

O agente tem um navegador próprio (uma janela do Chromium). Peça normalmente: "entra no site da loja X e vê o preço do frete para meu CEP". Se o site pedir login, CAPTCHA ou código, aparece o cartão **O agente precisa de você**: resolva **na janela do navegador do agente** e clique em *Resolvido*. Ele continua logado nas próximas vezes.

## Lendo o que ele fez

Na tela:
- linhas `⚙ Ferramenta argumento` mostram cada ação;
- a última linha traz o status, os passos e o custo.

No log:

```bash
# tudo de hoje
cat logs/$(date +%F).jsonl | jq .

# só os comandos executados
jq -r 'select(.type=="tool" and .name=="Bash") | .input.command' logs/*.jsonl

# pedidos que pararam por limite
jq 'select(.type=="result" and .subtype!="success")' logs/*.jsonl
```

## Lembretes e tarefas agendadas

Peça em linguagem natural: "me lembra sexta às 18h de comprar ração", "toda segunda às 9h revise meus gastos e me mande um resumo", "quais tarefas estão agendadas?", "cancela a revisão de gastos". Ele confirma a próxima execução.

Para funcionar sozinho, o `agente-web` precisa estar rodando (no computador ou, depois, na VPS). Os resultados chegam como cartões ⏰ na página.

## Quando ele precisar de você

Alguns bloqueios só uma pessoa resolve: CAPTCHA, verificação "você é um robô?", código de dois fatores, login, ou uma decisão sua. O agente **não tenta burlar** nada disso: ele chama `pedir_ajuda_humana` e pausa aquela tarefa.

- **Na web:** aparece o cartão **"O agente precisa de você"** com o motivo e o link, e o título da aba muda para "⚠ Precisa de você". Resolva no link e clique em **Resolvido, continuar**. Se o site pediu algo para digitar (um código, uma escolha), escreva no campo antes de clicar. **Não consegui** avisa que ele deve seguir sem isso.
- **No terminal:** a pergunta aparece em amarelo; aperte Enter quando resolver ou escreva a resposta.
- Sem resposta em `AGENT_HELP_TIMEOUT_MIN` minutos, ele continua sem isso e conta no final.

Hoje você resolve no seu próprio navegador. Quando o agente tiver navegador próprio (etapa 4), a verificação será feita dentro da sessão dele, e quando o WhatsApp entrar (etapa 2) o aviso vai para lá.

## Quando ele travar ou errar

- **Parou por teto de gasto ou de passos:** divida o pedido em partes ou aumente o limite no `.env`.
- **Fez algo diferente do pedido:** seja mais explícito e diga o que **não** fazer.
- **Insiste num erro:** `/nova` e reformule.
