# WhatsApp

O agente conversa com você pelo WhatsApp usando a **API oficial da Meta** (WhatsApp Cloud API). Nada de bibliotecas que imitam o WhatsApp Web: essas violam os termos e o número costuma ser banido.

## Como funciona

```
você no WhatsApp ──► Meta ──► POST /whatsapp/webhook (agente-web)
                                   │ confere a assinatura (App Secret)
                                   │ só números permitidos passam
                                   ▼
                     uma conversa por contato, uma mensagem por vez
                                   │
                     resposta final ◄──┘ (Graph API v26.0)
```

- **Só a resposta final** volta pelo WhatsApp (sem os passos intermediários). Se a tarefa demorar mais de 20 s, ele avisa "⏳ Estou trabalhando nisso".
- Markdown vira formatação do WhatsApp (`**negrito**` → `*negrito*`, listas → `•`). Respostas longas são divididas em partes.
- Cada contato tem sua conversa, que continua mesmo se o `agente-web` reiniciar.
- Bloqueios de segurança aparecem no fim da resposta (🛡).

## Comandos

| Mensagem | O que faz |
|---|---|
| `PARAR` | interrompe o que estiver rodando, esvazia a fila e **pausa a agenda** |
| `CONTINUAR` | volta ao normal |
| `NOVA` | começa uma conversa do zero |

## Ponte humana e agenda pelo WhatsApp

- Quando o agente precisa de você (CAPTCHA, login, código, decisão), chega **"⚠ Preciso de você"** com o motivo e o link. **A sua próxima mensagem é a resposta** ("ok", um código, uma escolha ou "não consegui").
- Resultados da agenda (resumo do dia, tarefas, lembretes) chegam como **⏰ título**.

### A regra das 24 horas

A Meta só deixa uma empresa mandar mensagem livre até **24 horas depois da última mensagem do usuário**. Fora dessa janela, só modelos (templates) aprovados.

Na prática: se você não falou com o agente nas últimas 24 h, o resumo das 7h **não vai pelo WhatsApp**: fica na caixa de entrada e aparece quando você abrir a página ou o terminal. Mandar qualquer mensagem (até "oi") reabre a janela. Um template aprovado para o resumo diário está no roadmap.

## Passo a passo na Meta

Você vai precisar de uma conta no Facebook e, para uso real, de um **número dedicado** (que não esteja no app do WhatsApp do celular).

1. **Crie o app:** em [developers.facebook.com](https://developers.facebook.com) → *Meus apps* → *Criar app* → tipo **Empresa (Business)** → adicione o produto **WhatsApp**.
2. **Pegue os dados** em *WhatsApp → Configuração da API*:
   - **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`;
   - **Token de acesso** → `WHATSAPP_TOKEN`. O temporário dura 24 h; para uso contínuo, crie um token permanente de *usuário do sistema* no Gerenciador de Negócios.
   - Para testar com o número de teste da Meta, cadastre o **seu celular** como destinatário.
3. **App Secret:** *Configurações do app → Básico → Chave secreta do app* → `WHATSAPP_APP_SECRET`.
4. **Invente um token de verificação** (qualquer texto longo) → `WHATSAPP_VERIFY_TOKEN`.
5. **Seu número** com DDI, só dígitos → `WHATSAPP_ALLOWED_NUMBERS` (ex.: `5511999990000`). Pode ter vários, separados por vírgula; o **primeiro é o dono** e recebe os avisos da agenda.
6. **Exponha o webhook.** A Meta precisa de um endereço HTTPS público:
   - **Para testar no computador:** um túnel, por exemplo `cloudflared tunnel --url http://127.0.0.1:8000`. Ele mostra um endereço `https://xxxx.trycloudflare.com`.
   - **Na VPS (etapa 7):** domínio próprio com HTTPS (Caddy).
7. **Cadastre o webhook** em *WhatsApp → Configuração*: URL de callback `https://SEU-ENDERECO/whatsapp/webhook`, token de verificação igual ao `WHATSAPP_VERIFY_TOKEN`, e assine o campo **messages**.
8. **Reinicie o `agente-web`** e mande "oi" para o número do agente.

O WhatsApp só liga quando as cinco variáveis estão preenchidas; `/api/status` mostra `"whatsapp": true`.

## Segurança

- **Assinatura:** toda chamada do webhook precisa do cabeçalho `X-Hub-Signature-256` válido (HMAC-SHA256 do corpo com o App Secret). Sem isso, 403.
- **Lista de permitidos:** mensagens de outros números são ignoradas (e ficam no log).
- **O túnel só abre o webhook:** qualquer outra rota acessada pelo domínio público (painel, conversas, chat) é recusada, porque o servidor só aceita Host local fora de `/whatsapp/webhook`.
- O `WHATSAPP_TOKEN` envia mensagens em nome do seu número: trate como senha (fica só no `.env`).

## Limitações atuais

- Só texto (e respostas de botão). Áudio e imagem respondem "por enquanto só leio texto".
- Avisos da agenda fora da janela de 24 h ficam na caixa de entrada (falta o template aprovado).
- Grupos não são suportados.
