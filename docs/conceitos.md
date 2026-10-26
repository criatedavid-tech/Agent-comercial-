# Conceitos: o que é um agente pessoal

Este documento explica, do zero, como funciona um agente de IA. Ele não depende de conhecer o código.

## 1. Chatbot × agente

| | Chatbot | Agente |
|---|---|---|
| O que entrega | texto | **ações** + texto |
| Quem executa | você, copiando a resposta | ele mesmo, usando ferramentas |
| Quantos passos | 1 pergunta → 1 resposta | quantos forem necessários |
| Quando trabalha | só quando você escreve | também sozinho (agendado, monitorando) |

Exemplo: "marque um café com o João na quinta".
- **Chatbot:** "Claro! Você pode abrir sua agenda e criar um evento…"
- **Agente:** consulta sua agenda, vê que quinta às 10h está livre, manda mensagem ao João, cria o evento e te avisa: "Marcado, quinta 10h. O João confirmou."

## 2. O loop

Todo agente é, no fundo, isto:

```
enquanto a tarefa não terminou:
    o modelo olha o objetivo + tudo o que aconteceu até agora
    o modelo escolhe: responder OU usar uma ferramenta
    se usou ferramenta: executa de verdade e anexa o resultado
```

O modelo de linguagem (Claude, GPT, Grok…) é o **cérebro que decide**. Ele não acessa nada por conta própria. Quem acessa são as **ferramentas**, que o programa em volta executa.

## 3. As cinco peças

### 3.1 Modelo (cérebro)
Decide o que fazer. Modelos melhores erram menos em tarefas longas. Aqui usamos Claude via **Claude Agent SDK**, que já traz o loop pronto.

### 3.2 Ferramentas (mãos)
Cada ferramenta é uma função com nome, descrição e parâmetros. O modelo lê a descrição e decide quando usá-la. Exemplos:
- terminal (`Bash`), arquivos (`Read`, `Write`), web (`WebSearch`, `WebFetch`)
- e-mail, agenda, WhatsApp, navegador, pagamentos (etapas futuras)

**O agente só é tão capaz quanto as ferramentas que tem.** Agentes "completos" das big techs se diferenciam principalmente pela quantidade e qualidade de ferramentas.

### 3.3 Memória
O modelo não lembra de nada entre conversas. A memória é **externa**:
- **Curto prazo:** o histórico da conversa atual (o SDK guarda).
- **Longo prazo:** arquivos que são lidos em toda conversa. Aqui: `memory/perfil.md` e `memory/notas.md`.
- **Futuro:** banco de dados com histórico pesquisável (contatos, tarefas, compras).

### 3.4 Interface (por onde você fala com ele)
Terminal hoje; WhatsApp, Telegram, e-mail ou ligação depois. A interface só leva mensagens até o loop e devolve a resposta: o cérebro é sempre o mesmo.

### 3.5 Gatilhos (o que o acorda)
- **Você** manda uma mensagem.
- **Relógio:** "todo dia às 7h, me mande o resumo do dia".
- **Eventos:** chegou um e-mail, um preço caiu, um site mudou.

Gatilhos são o que transforma um assistente **reativo** em **proativo**, o grande diferencial de Duet, Dots e Muse.

## 4. MCP (Model Context Protocol)

Um padrão aberto para conectar ferramentas a agentes. Em vez de programar a integração com o Gmail do zero, você conecta um **servidor MCP do Gmail** e o agente ganha as ferramentas "ler e-mail", "enviar e-mail" etc. Existem servidores MCP para Gmail, Google Calendar, GitHub, Slack, Notion, Supabase, Vercel, bancos de dados e centenas de outros. Usaremos MCP na etapa 3.

## 5. Autonomia e aprovação

Há um espectro:

```
pergunta tudo ◄──────────────────────────────► não pergunta nada
  (chato, seguro)                               (rápido, arriscado)
```

As big techs ficam no meio: agem sozinhas e pedem um "ok" para ações sensíveis. Este projeto está configurado para **autonomia total** (`bypassPermissions`), compensada por **limites rígidos**: teto de gasto, número máximo de passos, pasta de trabalho, cartão virtual com limite (etapa 4) e log de tudo. Veja [seguranca.md](seguranca.md).

## 6. Limitações de qualquer agente (inclusive os das big techs)

1. **Erra com confiança:** pode entender errado ou dizer que fez algo que não fez. Por isso existem logs.
2. **Tarefas longas acumulam erro:** cada passo tem uma chance de desvio.
3. **Prompt injection:** texto malicioso em e-mails ou sites pode tentar comandá-lo.
4. **Sites anti-robô:** captcha, 2FA, bancos e gov.br frequentemente exigem você.
5. **Custo por passo:** cada decisão consome tokens.
6. **Contexto limitado:** não cabe "tudo" na cabeça dele; a memória precisa ser organizada.
7. **Termos de uso:** automatizar WhatsApp pessoal ou redes sociais fora das APIs oficiais pode levar a bloqueio da conta.

## 7. Glossário

| Termo | Significado |
|---|---|
| **LLM** | modelo de linguagem grande (Claude, GPT…) |
| **Token** | pedaço de texto; a API cobra por token de entrada e saída |
| **System prompt** | instruções fixas que o agente recebe em toda conversa |
| **Tool / ferramenta** | ação que o agente pode executar |
| **MCP** | padrão para plugar ferramentas em agentes |
| **Turn / passo** | uma rodada do loop (decidir + executar) |
| **Webhook** | URL que um serviço (ex.: WhatsApp) chama quando algo acontece |
| **VPS** | servidor virtual alugado, ligado 24 h |
| **Prompt injection** | ataque em que um texto tenta dar ordens ao agente |
