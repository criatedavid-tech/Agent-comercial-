# Brechas e roteiros

Os alertas da gestão ([gestao.md](gestao.md)) dizem o que está estranho. A **brecha** é o que se faz com isso: cada achado conferido vira uma ficha com a área, a evidência, o valor estimado e o andamento, para o dono ver o que perde, o que já foi tratado e o que vale resolver primeiro.

A ideia de registrar achados com valor em R$ e de dar roteiros curtos aos agentes veio do estudo do projeto Maestro (repositório `projetoiasaude/maestro`); aqui foi reescrita em Python, com as travas deste projeto.

## A ficha

| Campo | O que guarda |
|---|---|
| `area` | `financeiro`, `comercial` ou `operacao` |
| `titulo` | curto, com o documento quando houver ("NF 18777 do Boi Bom paga duas vezes") |
| `evidencia` | de onde vem: ferramenta, período, linhas conferidas. **Obrigatória** |
| `acao` | o que fazer, em uma frase |
| `valor_mes` / `valor_unico` | estimativa em R$: o que se repete por mês, ou o que se recupera uma vez. Nunca o mesmo valor nos dois |
| `status` | `nova` → `proposta` → `aprovada` → `em_andamento` → `resolvida` (ou `descartada`) |

Fica em `brechas.db` (SQLite, fora do git, como o `crm.db`). Valores são guardados em centavos e arredondados para cima na metade, sem número de ponto flutuante.

## Regras no código

- **Sem evidência não há brecha.** O registro é recusado e o agente recebe a mensagem do que faltou.
- **Quem registra não muda o status.** Os especialistas têm `registrar_brecha` e `listar_brechas`; a ferramenta `atualizar_brecha` é só do gerente (e `registrar_brecha` nem tem o parâmetro `status`). Depois de contar uma brecha ao dono, o gerente a passa para `proposta`; `aprovada` só se o dono disser sim.
- **Sem duplicar.** O mesmo título (ignorando maiúsculas e acentos) atualiza a brecha aberta. O mesmo documento no título ("NF 18777", "nota fiscal 18777") vira só uma anotação na que já existe, sem trocar área nem valor. Brecha já resolvida não absorve um achado novo.
- **Valor com limite.** Valor negativo, não numérico ou acima de R$ 10 milhões é recusado.
- **É estimativa.** Nada aqui paga, transfere, cobra ou escreve para ninguém. A listagem diz "estimativas" e separa o que é por mês do que é uma vez.

## Ferramentas

| Ferramenta | Quem usa | O que faz |
|---|---|---|
| `registrar_brecha` | comercial, financeiro, operação e gerente | cria, atualiza (mesmo título) ou anota (mesmo documento) |
| `listar_brechas` | todos | as abertas, a de maior valor no ano primeiro, com o total; filtro por status e área |
| `atualizar_brecha` | só o gerente | muda o status e/ou anota |

## Roteiros (skills)

Roteiros curtos em `plugin/skills/`, carregados quando o assunto aparece e já ligados ao especialista certo:

| Roteiro | Especialista | Para quê |
|---|---|---|
| `raio-x-financeiro` | financeiro | primeiro olhar do dinheiro: números, alertas, o que foi conferido e o que é indício |
| `fechamento-caixa` | financeiro | caixa registrado contra o contado, padrão por funcionário |
| `despesas-e-duplicidades` | financeiro | gasto fora do padrão e conta paga em dobro |
| `estoque-sem-venda` | operação | saída de estoque sem venda, causas e valor pelo custo |
| `leads-parados` | comercial | quem parou no funil, por quê e quem a equipe procura primeiro |

Todos terminam com `registrar_brecha` e deixam claro que alerta sobre pessoa é indício, não acusação.

## O que ficou de fora (de propósito)

- Roteiros de conciliação de maquininha e delivery e de inadimplência: precisam de dados que o agente ainda não tem (extrato da maquininha, contas a receber). Entram quando houver essas planilhas ou a exportação dos sistemas.
- Painel de brechas: hoje só pelo chat e WhatsApp.

## Testes

`tests/test_brechas.py`: criação, valores, evidência obrigatória, título repetido, mesmo documento, status protegido, ordenação, ferramentas e a conferência de que cada especialista tem as skills certas.
