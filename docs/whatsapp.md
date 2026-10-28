# WhatsApp

O agente conversa pelo WhatsApp de dois jeitos (`WHATSAPP_PROVEDOR`):

- **Meta** (API oficial, WhatsApp Cloud API): o caminho para clientes reais.
- **UAZAPI** (não oficial, conecta um número comum pelo QR code): o caminho rápido para **testes**. Veja [UAZAPI](#uazapi-para-testes) e os riscos.

O resto (equipe × clientes, comandos, passagem para a equipe, regras) é igual nos dois.

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
| `FILA` | clientes que chamaram a equipe ou estão com alguém |
| `ASSUMIR 12` | assume o cliente #12 (sem número, o único aguardando): daí em diante o que você manda vai para ele |
| `DEVOLVER` | devolve o cliente ao assistente e você volta a falar com o agente |

Os quatro últimos são da passagem para a equipe ([atendente.md](atendente.md#passagem-para-a-equipe)). Enquanto você atende um cliente, suas mensagens vão para ele, não para o agente.

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

## UAZAPI (para testes)

A UAZAPI conecta um número de WhatsApp comum (pelo QR code, como o WhatsApp Web) e oferece uma API para enviar e receber. É paga e não é da Meta.

**Riscos, leia antes:**
- Não é oficial: viola os termos do WhatsApp e **o número pode ser banido**, principalmente se mandar mensagem para quem não falou com ele. Use um **número de teste**, nunca o número principal da loja.
- Por isso o agente mantém as mesmas regras da Meta: só responde quem escreveu, retomada e avisos só dentro de 24 h, PARAR respeitado, sem disparo em massa.
- Não há modelos aprovados: fora das 24 h, o retorno combinado fica para a equipe.
- Para cliente pagante, o caminho é a API oficial da Meta.

**Passo a passo:**
1. No painel da UAZAPI, crie uma instância e conecte o número de teste pelo QR code.
2. No `.env`:
   - `UAZAPI_URL`: o endereço do servidor (ex. `https://suaempresa.uazapi.com`);
   - `UAZAPI_TOKEN`: o token da instância;
   - `UAZAPI_WEBHOOK_SEGREDO`: um texto longo e aleatório inventado por você (vai no caminho do webhook);
   - `WHATSAPP_ALLOWED_NUMBERS`: os números da equipe (o primeiro é o dono);
   - `AGENT_ATENDENTE_WHATSAPP=true` para que os demais números falem com o atendente.
   `WHATSAPP_PROVEDOR` pode ficar vazio: com `UAZAPI_URL` preenchida, a UAZAPI é usada.
3. **Endereço público.** A UAZAPI precisa chamar o agente:
   - no computador, um túnel: `cloudflared tunnel --url http://127.0.0.1:8000` mostra um `https://xxxx.trycloudflare.com` (muda a cada vez);
   - na VM, o domínio com HTTPS do Caddy (`AGENT_PUBLIC_URL`).
4. **Reinicie o `agente-web`** e cadastre o webhook na instância:
   ```bash
   agente-uazapi https://xxxx.trycloudflare.com
   ```
   (na VM, só `agente-uazapi`, que usa `AGENT_PUBLIC_URL`). O comando configura só mensagens recebidas, sem grupos e sem as que o próprio agente mandou.
5. Mande "oi" para o número de teste de outro celular: se ele não estiver em `WHATSAPP_ALLOWED_NUMBERS`, quem responde é o atendente.

**Segurança:** a UAZAPI não assina as chamadas. O webhook só aceita o caminho `/whatsapp/uazapi/<UAZAPI_WEBHOOK_SEGREDO>` e, quando o corpo traz o token da instância, ele precisa bater com `UAZAPI_TOKEN`. Grupos, mensagens enviadas pelo próprio número e contatos sem número de telefone (só LID) são ignorados.

## Segurança

- **Assinatura (Meta):** toda chamada do webhook precisa do cabeçalho `X-Hub-Signature-256` válido (HMAC-SHA256 do corpo com o App Secret). Sem isso, 403.
- **Lista de permitidos:** mensagens de outros números são ignoradas (e ficam no log).
- **O túnel só abre o webhook:** qualquer outra rota acessada pelo domínio público (painel, conversas, chat) é recusada, porque o servidor só aceita Host local fora dos webhooks (`/whatsapp/webhook` e `/whatsapp/uazapi/<segredo>`) e da tela remota com link válido.
- O `WHATSAPP_TOKEN` e o `UAZAPI_TOKEN` enviam mensagens em nome do número: trate como senha (ficam só no `.env`).

## Limitações atuais

- Só texto (e respostas de botão). Áudio e imagem respondem "por enquanto só leio texto".
- Avisos da agenda fora da janela de 24 h ficam na caixa de entrada (falta o template aprovado).
- Grupos não são suportados.
