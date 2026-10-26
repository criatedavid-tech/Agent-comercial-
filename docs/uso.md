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

## Quando ele travar ou errar

- **Parou por teto de gasto ou de passos:** divida o pedido em partes ou aumente o limite no `.env`.
- **Fez algo diferente do pedido:** seja mais explícito e diga o que **não** fazer.
- **Insiste num erro:** `/nova` e reformule.
