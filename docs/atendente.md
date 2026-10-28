# Atendente (fase 1)

O atendente é o agente que conversa com os **clientes da empresa**: pessoas desconhecidas, que podem tentar enganá-lo. Ele é separado do operador (o agente completo do dono, herdado do protótipo) e tem poderes mínimos. Visão do produto em [produto.md](produto.md).

## O que ele faz

- Tira dúvidas com base no **catálogo**, no **FAQ** e nas **políticas** da empresa.
- Passa **preço do catálogo** e calcula orçamentos de vários itens (a conta é do código).
- **Qualifica** o cliente (o que precisa, prazo, orçamento, local) e registra o lead no **CRM**.
- Combina **retornos** ("me chama segunda") para a equipe.
- Em negociação, desconto, fechamento, reclamação ou dúvida fora da base: diz que a equipe continua e anota o motivo. A passagem de verdade para o vendedor (`chamar_vendedor`, modo humano) é a fase 2.

## Configuração da empresa

Uma pasta por instalação. O código procura, nesta ordem: `AGENT_EMPRESA_DIR`, `empresa/` na raiz do projeto e, se nenhuma existir, a empresa fictícia de exemplo em `exemplos/empresa/` (Auto Center Rota Certa: óleo, pneus, freios, suspensão, elétrica e ar-condicionado). `empresa/` fica **fora do git**: são dados do cliente.

Para começar uma empresa nova:

```bash
cp -r exemplos/empresa empresa
```

| Arquivo | Conteúdo |
|---|---|
| `empresa.toml` | `nome`, `preposicao` ("do" ou "da": "assistente virtual **do** Auto Center"), `segmento`, `cidade`, `tom` (como fala), `assistente` (nome do assistente virtual), `[horario]` da equipe, `[[equipe]]` (nome, função, WhatsApp) e `[regras]` |
| `catalogo.csv` | `codigo,nome,categoria,preco,unidade,condicoes,descricao`. Preço aceita `39.90` ou `39,90` |
| `faq.md` | dúvidas frequentes; cada `## Pergunta` vira um trecho pesquisável |
| `politicas.md` | pagamento, trocas, cancelamento, preços; mesmo formato |

`[regras]` em `empresa.toml`:

| Regra | Padrão | Efeito |
|---|---|---|
| `objeto` | (vazio) | o que o cliente traz, ex. `"veículo (modelo e ano)"`; vira um campo do lead no CRM e uma pergunta de qualificação |
| `informar_preco` | `true` | `false`: o catálogo aparece sem preço e `calcular_orcamento` recusa |
| `agendar_retorno` | `true` | `false`: `agendar_retorno` recusa |
| `qualificacao` | o que precisa, para quando | perguntas que ele faz para qualificar |
| `chamar_humano` | negociação, reclamação, pedido de pessoa | quando ele diz que a equipe continua |

O WhatsApp da equipe **não** vai para o modelo (só nomes e funções). Erro na pasta (arquivo faltando, preço inválido, TOML quebrado) aparece com o arquivo e a linha.

## Ferramentas (servidor MCP `negocio`)

| Ferramenta | O que faz |
|---|---|
| `consultar_catalogo` | busca por nome, código, categoria ou descrição (sem acento e plural simples) |
| `calcular_orcamento` | total pelo preço de tabela, com `Decimal`; ignora qualquer "desconto" que o modelo mandar; move o lead para `orcamento` |
| `consultar_informacoes` | busca no FAQ e nas políticas, sempre com o horário da equipe |
| `registrar_lead` | nome, objeto (no auto center, o carro: aceita `carro`, `veiculo`, `modelo`), interesse, necessidade, prazo, orçamento, local, observação, etapa |
| `agendar_retorno` | quando e motivo; fica pendente no CRM para a equipe (execução automática: fase 3) |
| `ver_cadastro` | o cadastro **desta** conversa e os retornos combinados |

Nenhuma ferramenta recebe telefone: todas ficam presas ao contato da conversa (`ContactView`). Os nomes de parâmetro aceitam formas naturais (`produto`, `busca`, `orçamento`, `bairro`...) porque os modelos inventam nomes; erros voltam com exemplo.

## CRM (`crm.db`)

SQLite em `crm.db` (fora do git, entra no `agente-backup`). Colunas novas entram sozinhas em bancos antigos.

- **contacts**: telefone, nome, objeto (o carro, no auto center), origem (`whatsapp`, `simulador`), etapa, interesse, necessidade, prazo, orçamento, local, observações, opt-in, criado e atualizado. Quem inicia a conversa conta como opt-in.
- **interactions**: cada mensagem do cliente (`entrada`), cada resposta já filtrada (`saida`) e eventos (`evento`: orçamento, cadastro, retorno).
- **followups**: retornos combinados, com estado `pendente`.

Etapas: `novo`, `qualificando`, `qualificado`, `orcamento`, `ganho`, `perdido`. O atendente **não** marca `ganho`: venda fechada é da equipe.

LGPD: `Crm.delete(telefone)` apaga contato, interações e retornos; na interface local, `DELETE /api/crm/{telefone}` (exige a origem da própria página).

## Regras no código

| Regra | Onde |
|---|---|
| Só ferramentas do negócio | `tools=[]` (nenhuma embutida do Claude Code), só o servidor `negocio`, `disallowed_tools` com as embutidas e um hook `PreToolUse` que recusa qualquer nome fora da lista. Sem subagentes, plugins, skills e configurações da máquina (`setting_sources=[]`) |
| Sem dados de outros clientes | ferramentas presas ao contato; o modelo não tem como pedir outro telefone |
| Preço só do catálogo | `Catalog.quote` calcula; `regras.screen` tira da resposta valor em R$ que não veio do catálogo, das políticas, de um orçamento calculado ou do orçamento que o próprio cliente disse |
| Sem desconto | não existe ferramenta de desconto; `regras.screen` tira frases que oferecem desconto ou percentual fora das políticas ("não posso dar desconto" passa) |
| Sem fechar venda nem agendamento | `registrar_lead` recusa `ganho`; `regras.screen` tira "pedido confirmado", "seu horário está confirmado", "já vou agendar seu horário", "pode fazer o PIX". O atendente anota a preferência e a equipe confirma o dia |
| Não finge ser humano | `regras.screen` tira "sou uma pessoa"/"não sou robô"; se o cliente pergunta "você é um robô?" e a resposta não deixa claro, o código acrescenta "Aqui é Léo, assistente virtual do ..." |

Frase tirada vira um aviso para o cliente ("Essa parte quem confirma é a equipe..."), um evento `blocked` na interface e uma linha `blocked` no log. O filtro é por padrões de texto: segura o que um modelo enganado costuma escrever, mas não substitui a falta de ferramenta, que é a defesa principal.

## Simulador de cliente

```bash
agente-web          # depois abra http://127.0.0.1:8000/simulador
```

A página faz o papel de um cliente no WhatsApp e conversa com o atendente (não com o operador). Do lado, a **ficha no CRM** atualiza a cada resposta. Cada aba é um contato `sim-xxxxxx` (o prefixo garante que nunca se confunde com um número real); **Outro cliente** começa um contato novo, **Conversa nova** zera o contexto e mantém o cadastro. Há atalhos com testes de prompt injection.

Conversas do atendente ficam em `logs/atendimento.db` (separadas das do operador em `logs/conversas.db`); o log diário `logs/AAAA-MM-DD.jsonl` marca as linhas com `"agent": "atendente"` e o telefone.

## Limites

- `AGENT_ATENDENTE_MAX_TURNS` (padrão 12) limita os passos por mensagem; o teto de gasto é `AGENT_MAX_BUDGET_USD`.
- O WhatsApp ainda leva tudo ao operador (só números permitidos). Rotear "equipe → operador, resto → atendente" entra junto com a passagem para humano (fase 2).
- Modelo gratuito erra mais e tem cota diária: serve para testar, não para cliente pagante.
