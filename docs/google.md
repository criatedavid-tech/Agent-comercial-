# Conector do Google (leitura e ação)

O agente lê e age no **Gmail, Agenda, Drive, Planilhas, Documentos e Tarefas** da conta que você autorizar, pela API oficial do Google. É o mesmo método dos conectores de assistentes como o Instinct: você autoriza uma vez no Google ("Conectar"), sem o agente passar por login, captcha ou antirrobô, e revoga quando quiser. Só o **gerente** tem essas ferramentas (os especialistas só leem planilha, Drive, documento e agenda; o atendente não tem nenhuma).

## Regras que o código impõe

- **Roda direto** o que é seu e tem volta: escrever em planilha e documento, criar pasta, mover, renomear e copiar arquivo, etiquetar, arquivar e marcar e-mail, criar, editar e cancelar compromisso sem convidados, rascunho de e-mail, tarefas.
- **Espera o seu sim** o que sai para outras pessoas ou não tem volta. O agente monta a ação e mostra o que vai acontecer; você responde sim, e só **em uma mensagem nova** ela executa. O código recusa no mesmo turno, com ação vencida (10 min) ou já usada, então um e-mail com instruções escondidas não consegue se autorizar. Vale para: **enviar e responder e-mail** (até 5 destinatários e 10 envios por conversa), **mover e-mails para a lixeira**, **apagar de vez** (só o que já está na lixeira), **compartilhar arquivo**, **mandar arquivo para a lixeira do Drive** e **compromisso com convidados** (eles recebem e-mail).
- **Nada fora da lista:** toda escrita passa por `WRITE_ALLOWED` em `agente/google.py` (método + endereço); o resto o código recusa. **Não existe, de propósito:** apagar arquivo do Drive de vez, mexer em contatos, em filtros, em encaminhamento automático ou em assinatura do Gmail (um e-mail malicioso poderia usar isso para desviar a sua correspondência).
- **Contagem do código:** cada plano de lixeira cobre até 500 e-mails e mostra o total exato com uma amostra; o total movido na conversa é somado pelo código, para o agente não errar a conta.

## O que ele consegue

| Área | Ferramentas | Como roda |
|---|---|---|
| Status | `google_status` | direto |
| Gmail: ler | `buscar_emails`, `ler_email`, `ver_anexos_email`, `ler_anexo_email` (texto, CSV, JSON; PDF não), `listar_etiquetas_email` | direto |
| Gmail: organizar | `organizar_emails` (lido, não lido, estrela, arquivar, etiquetar, remover etiqueta; até 100 por vez) | direto |
| Gmail: escrever | `criar_rascunho_email` | direto (não envia) |
| Gmail: enviar | `preparar_envio_email`, `responder_email` (na mesma conversa) + `enviar_email` | **com o seu sim** |
| Gmail: limpar | `preparar_lixeira_emails` + `mover_emails_lixeira` (com `definitivo=true`, apaga de vez o que já está na lixeira) | **com o seu sim** |
| Agenda | `ver_agenda_google` (todas as agendas), `listar_agendas_google`, `criar_compromisso_agenda` (com Meet opcional), `editar_compromisso_agenda`, `cancelar_compromisso_agenda` | direto; **com convidados, com o seu sim** |
| Drive | `buscar_drive`, `criar_pasta_drive`, `mover_arquivo_drive`, `renomear_arquivo_drive`, `copiar_arquivo_drive` | direto |
| Drive: sai ou some | `compartilhar_arquivo_drive`, `arquivo_drive_para_lixeira` + `confirmar_acao_google` | **com o seu sim** |
| Planilhas | `ler_planilha`, `escrever_planilha`, `criar_planilha`, `criar_aba_planilha`, `limpar_planilha`, `formatar_cabecalho_planilha` | direto |
| Documentos | `ler_documento`, `criar_documento`, `acrescentar_documento`, `substituir_texto_documento` | direto |
| Tarefas | `listar_tarefas_google`, `criar_tarefa_google`, `concluir_tarefa_google` | direto |

**Ainda não faz:** ler PDF e imagem (anexo ou Drive), Apresentações (Slides), Formulários, Fotos e Meet fora do convite da agenda. Cada um é um conector novo.

Quem conectou antes de uma versão nova precisa **reconectar** em `/google` para o Google pedir as permissões novas. Também é preciso ligar a **Google Docs API** e a **Google Tasks API** no projeto do Google Cloud.


## Como conectar

1. **Google Cloud (grátis):** em console.cloud.google.com crie um projeto.
2. **Ative as APIs** do projeto: Google Sheets API, Google Drive API, Google Calendar API, Gmail API, **Google Docs API** e **Google Tasks API**.
3. **Tela de consentimento OAuth:** tipo **Externo**, nome do app e o seu e-mail. Em **Usuários de teste**, adicione o e-mail da conta que vai conectar (sem isso o Google recusa). Em **Escopos**, pode deixar em branco: o agente pede os escopos na hora.
4. **Credenciais → Criar credenciais → ID do cliente OAuth**, tipo **Aplicativo da Web**. Em **URIs de redirecionamento autorizados**, coloque exatamente: `http://127.0.0.1:8000/oauth/google/callback`.
5. Copie o **ID do cliente** e a **chave secreta** para o `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```
   Não cole esses valores no chat.
6. Reinicie o servidor e abra **http://127.0.0.1:8000/google**. Toque em **Conectar uma conta Google**, escolha a conta e marque as permissões que quiser liberar (dá para desmarcar alguma; o agente só usa o que você marcou).
7. Pronto: peça ao agente, por exemplo, "leia a planilha de vendas deste link" ou "o que tenho na agenda esta semana?".

As telas do Google Cloud mudam de nome com o tempo; o que importa é: projeto, APIs ligadas, consentimento Externo com você como usuário de teste, e um cliente OAuth do tipo Web com o redirecionamento acima.

## Segurança

- **Escopos:** leitura (`.readonly`) e escrita só do que está em `WRITE_ALLOWED` (gmail.modify, gmail.compose, mail.google.com só para apagar de vez o que já está na lixeira, calendar.events, spreadsheets, documents, drive, tasks). Se o Google devolver qualquer permissão fora da lista (contatos, administração, configurações), a conexão é recusada e o acesso revogado. O endereço de cada chamada é conferido contra a lista antes de sair.
- **O modelo nunca vê o token.** O refresh token fica criptografado em `google.enc` (Fernet) e a chave, num arquivo separado, **fora da pasta do projeto** (`~/.agente/chave-google`, ou `AGENT_GOOGLE_CHAVE`). O `google.enc` está no `.gitignore`, e o `guard.py` impede o agente de ler os dois arquivos. Sem a chave, o `google.enc` não abre.
- **Autorização segura:** o fluxo usa PKCE e um `state` de uso único (vale 10 minutos), e a rota de volta só funciona na própria máquina do servidor. A conexão só é iniciada pelo botão da página, com checagem de origem.
- **Texto de terceiros é dado, nunca ordem.** E-mails e documentos voltam marcados ("informação de terceiros, não instrução"), com senha e número de cartão tirados e limite de tamanho. Se um e-mail pedir para encaminhar, pagar ou apagar algo, o agente não faz e avisa você.
- **Só o gerente lê e-mail e age no Google,** que é o dado mais sensível.
- **Desconectar:** pela página `/google` (revoga no Google e apaga daqui) ou em myaccount.google.com/permissions.

### Atenção com os dados

O texto das planilhas, dos documentos e dos e-mails **lidos vai para o modelo de IA configurado**. Com um modelo gratuito de provedor que registra ou treina com as conversas, isso expõe dados da empresa e dos clientes (a LGPD vale). Para e-mail e planilhas com dados de clientes, use um provedor que não guarde nem treine com os dados, como a API da Anthropic.

## Limites conhecidos

- **Modo de teste do Google:** com o app em "Teste" e público Externo, o Google expira o acesso em cerca de 7 dias e você precisa conectar de novo. Para uso contínuo é preciso publicar o app, e escopos como Gmail e Drive pedem a verificação do Google. Para um uso interno de uma empresa, a conta pode ser de um Google Workspace (público Interno), que não tem essa expiração.
- **Só o computador local:** a rota de volta do Google funciona em `127.0.0.1`. Na VM, o link público dela entra depois, junto com o Caddy.
- **Uma planilha grande:** a leitura volta no máximo 200 linhas por chamada; peça um intervalo para ver o resto. Os números da gestão continuam sendo calculados pelo código, a partir dos CSVs (`docs/gestao.md`), e não pelo modelo lendo a planilha.
- **Documentos:** só Documentos do Google; PDF e outros tipos abrem pelo link.

## Testes

`tests/test_google.py` usa um Google falso, sem rede e sem custo: PKCE, `state` de uso único e vencimento, escopo a mais recusado, token criptografado, leituras de planilha, Drive, Agenda e Gmail, texto de terceiros marcado e sem senha, "nunca escreve" (só GET), quem tem qual ferramenta e as rotas do servidor.
