"""Canal WhatsApp: API oficial da Meta (WhatsApp Cloud API) ou UAZAPI (não oficial, para testes).

Fluxo: a Meta chama POST /whatsapp/webhook com cada mensagem → conferimos a assinatura
(HMAC-SHA256 com o App Secret) → números da equipe (WHATSAPP_ALLOWED_NUMBERS) falam com o operador;
os demais, se AGENT_ATENDENTE_WHATSAPP estiver ligado, com o atendente (clientes); senão são ignorados
→ cada contato tem sua conversa, uma mensagem por vez → a resposta final volta pelo WhatsApp.

Comandos: PARAR (interrompe tudo e pausa a agenda), CONTINUAR, NOVA (conversa do zero).
Passagem para a equipe (agente/passagem.py): FILA, ASSUMIR 12 (daí em diante o que a pessoa manda vai
para o cliente), DEVOLVER (o assistente volta a atender).
Ponte humana: quando o agente pede ajuda, a pergunta vai pelo WhatsApp e a próxima
mensagem do usuário é a resposta.

Regra da Meta: mensagem livre só até 24h depois da última mensagem do usuário. Fora disso,
avisos da agenda ficam na caixa de entrada (web/terminal) em vez de ir pelo WhatsApp.
Com a UAZAPI a regra vale do mesmo jeito: mandar para quem não falou com a empresa é o que faz
o WhatsApp banir o número.

UAZAPI: o webhook chega em /whatsapp/uazapi/<UAZAPI_WEBHOOK_SEGREDO> (a UAZAPI não assina as
chamadas; o segredo no caminho e o token da instância no corpo fazem esse papel). Para cadastrar
o webhook na instância: agente-uazapi https://seu-endereco-publico.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import re
from typing import Any

import httpx

from .config import Config
from .history import History
from .human import HelpRequest

log = logging.getLogger(__name__)

TEXT_LIMIT = 4000  # a Meta aceita 4096; folga para não cortar no meio de um caractere especial
SERVICE_WINDOW = timedelta(hours=24)
WORKING_NOTICE_SECONDS = 20  # tarefa demorada: avisa uma vez que está trabalhando

STOP_WORDS = {"parar", "pare", "stop"}
CONTINUE_WORDS = {"continuar", "continue", "voltar"}
NEW_WORDS = {"nova", "/nova", "nova conversa"}
AUDIO_KINDS = {"audio", "ptt", "voice"}  # áudio comum e mensagem de voz


@dataclass
class Incoming:
    id: str
    sender: str  # número com DDI, só dígitos
    kind: str  # "text", "audio", "image"...
    text: str
    name: str = ""


class WhatsAppError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def verify_signature(app_secret: str, body: bytes, header: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 ("sha256=<hex>") que a Meta manda em cada webhook."""
    if not app_secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_messages(payload: dict) -> list[Incoming]:
    """Extrai as mensagens recebidas do corpo do webhook (ignora avisos de status de entrega)."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                kind = msg.get("type", "")
                if kind == "text":
                    text = msg.get("text", {}).get("body", "")
                elif kind == "button":
                    text = msg.get("button", {}).get("text", "")
                elif kind == "interactive":
                    reply = msg.get("interactive", {})
                    text = (reply.get("button_reply") or reply.get("list_reply") or {}).get("title", "")
                else:
                    text = ""
                sender = re.sub(r"\D", "", msg.get("from", ""))
                out.append(Incoming(msg.get("id", ""), sender, kind, text, names.get(msg.get("from"), "")))
    return out


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables_to_lists(text: str) -> str:
    """Tabela Markdown → lista: o WhatsApp não desenha tabela (mostraria os | e ---)."""
    lines, out, i = text.split("\n"), [], 0
    row = re.compile(r"^\s*\|.*\|\s*$")
    while i < len(lines):
        if row.match(lines[i]) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            header = _cells(lines[i])
            i += 2
            while i < len(lines) and row.match(lines[i]):
                cells = _cells(lines[i])
                i += 1
                pairs = [f"{h}: {v}" for h, v in zip(header[1:], cells[1:]) if v and v not in ("—", "-", "–")]
                out.append(f"- {cells[0]}" + (f" — {' · '.join(pairs)}" if pairs else ""))
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def to_whatsapp(markdown: str) -> str:
    """Markdown do agente → formatação do WhatsApp (*negrito*, _itálico_, ~riscado~, tabela vira lista)."""
    text = tables_to_lists(markdown)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.M)  # títulos viram negrito
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)  # [texto](link) → texto (link)
    text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.M)
    return text.strip()


def split_message(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Divide textos longos em partes, preferindo quebrar entre parágrafos e linhas."""
    parts, rest = [], text.strip()
    while len(rest) > limit:
        cut = max(rest.rfind("\n\n", 0, limit), rest.rfind("\n", 0, limit))
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


class CloudApi:
    """Cliente mínimo da WhatsApp Cloud API: enviar texto e marcar como lida."""

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.url = f"https://graph.facebook.com/{cfg.whatsapp_api_version}/{cfg.whatsapp_phone_id}/messages"
        self.headers = {"Authorization": f"Bearer {cfg.whatsapp_token}"}
        self.client = client or httpx.AsyncClient(timeout=20)

    async def _post(self, body: dict) -> dict:
        resp = await self.client.post(self.url, json=body, headers=self.headers)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err = data.get("error", {})
            raise WhatsAppError(err.get("message", f"HTTP {resp.status_code}"), err.get("code"))
        return data

    async def send_text(self, to: str, text: str) -> None:
        for part in split_message(to_whatsapp(text)):
            await self._post({
                "messaging_product": "whatsapp", "recipient_type": "individual", "to": "+" + to,
                "type": "text", "text": {"preview_url": False, "body": part},
            })

    async def send_template(self, to: str, name: str, params: list[str], language: str = "pt_BR") -> None:
        """Modelo aprovado na Meta: o único jeito de falar com alguém fora da janela de 24 h."""
        body = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}] if params else []
        await self._post({
            "messaging_product": "whatsapp", "to": "+" + to, "type": "template",
            "template": {"name": name, "language": {"code": language}, "components": body},
        })

    async def mark_read(self, message_id: str) -> None:
        await self._post({"messaging_product": "whatsapp", "status": "read", "message_id": message_id})


class UazApi:
    """Cliente da UAZAPI: enviar texto, marcar como lida e cadastrar o webhook. Mesma interface do CloudApi."""

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.base = cfg.uazapi_url.rstrip("/")
        self.headers = {"token": cfg.uazapi_token}
        self.openai_key = cfg.openai_api_key
        self.client = client or httpx.AsyncClient(timeout=60)

    async def _post(self, path: str, body: dict) -> dict:
        resp = await self.client.post(self.base + path, json=body, headers=self.headers)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            message = (data.get("error") or data.get("message")) if isinstance(data, dict) else ""
            raise WhatsAppError(str(message or f"HTTP {resp.status_code}"), resp.status_code)
        return data if isinstance(data, dict) else {}

    async def send_text(self, to: str, text: str) -> None:
        for part in split_message(to_whatsapp(text)):
            await self._post("/send/text", {"number": to, "text": part})

    async def send_template(self, to: str, name: str, params: list[str], language: str = "pt_BR") -> None:
        raise WhatsAppError("a UAZAPI não tem modelos aprovados da Meta: fora das 24 h a equipe fala com o cliente")

    async def mark_read(self, message_id: str) -> None:
        await self._post("/message/markread", {"id": [message_id]})

    async def transcribe(self, message_id: str) -> str:
        """Texto de um áudio recebido (Whisper da OpenAI, feito pela UAZAPI)."""
        body = {"id": message_id, "transcribe": True, "generate_mp3": False}
        if self.openai_key:
            body["openai_apikey"] = self.openai_key
        return str((await self._post("/message/download", body)).get("transcription") or "")

    async def set_webhook(self, url: str) -> dict:
        """Só mensagens recebidas, de pessoas (sem grupos), sem as que o próprio agente mandou."""
        return await self._post("/webhook", {"enabled": True, "url": url, "events": ["messages"],
                                             "excludeMessages": ["wasSentByApi", "fromMeYes", "isGroupYes"]})


TEXT_TYPES = ("conversation", "extendedtext", "text")


def jid_number(jid: str) -> str:
    """Número de um JID de pessoa (5511...@s.whatsapp.net). LID e grupo não são número de telefone: vazio."""
    jid = str(jid or "")
    if not jid.endswith(("@s.whatsapp.net", "@c.us")):
        return ""
    return re.sub(r"\D", "", jid.split("@")[0].split(":")[0])


def parse_uazapi(payload: dict) -> list[Incoming]:
    """Mensagem recebida pela UAZAPI (EventType "messages"). Ignora as nossas, grupos e quem não tem número."""
    if payload.get("EventType") != "messages":
        return []
    m = payload.get("message") or {}
    if m.get("fromMe") or m.get("isGroup") or m.get("wasSentByApi"):
        return []
    sender = jid_number(m.get("sender_pn")) or jid_number(m.get("chatid")) or jid_number(m.get("sender"))
    if not sender:
        log.warning("mensagem da UAZAPI sem número de telefone (chatid %s): ignorada", m.get("chatid"))
        return []
    kind = str(m.get("messageType") or "").lower()
    kind = "text" if not kind or any(t in kind for t in TEXT_TYPES) else kind.removesuffix("message")
    msg_id = str(m.get("messageid") or m.get("id") or "")
    return [Incoming(msg_id, sender, kind, str(m.get("text") or ""), str(m.get("senderName") or ""))]


def uazapi_main() -> None:
    """agente-uazapi [endereço público]: cadastra o webhook na instância da UAZAPI."""
    import argparse
    import sys

    from . import config

    parser = argparse.ArgumentParser(description="Cadastra o webhook do agente na instância da UAZAPI")
    parser.add_argument("endereco", nargs="?", default="",
                        help="endereço público do agente (padrão: AGENT_PUBLIC_URL), ex. https://abc.trycloudflare.com")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = config.load()
    base = (args.endereco or cfg.public_url).rstrip("/")
    missing = [n for n, v in (("UAZAPI_URL", cfg.uazapi_url), ("UAZAPI_TOKEN", cfg.uazapi_token),
                              ("UAZAPI_WEBHOOK_SEGREDO", cfg.uazapi_webhook_secret)) if not v]
    if missing:
        sys.exit(f"preencha no .env: {', '.join(missing)}")
    if not base.startswith("https://"):
        sys.exit("informe o endereço público com https:// (ou preencha AGENT_PUBLIC_URL)")

    async def configure() -> dict:
        api = UazApi(cfg)
        try:
            return await api.set_webhook(f"{base}/whatsapp/uazapi/{cfg.uazapi_webhook_secret}")
        finally:
            await api.client.aclose()

    try:
        asyncio.run(configure())
    except (WhatsAppError, httpx.HTTPError) as e:
        sys.exit(f"a UAZAPI recusou: {e}")
    print(f"webhook cadastrado: {base}/whatsapp/uazapi/<segredo>")


NOT_UNDERSTOOD = {
    "audio": "Não consegui ouvir esse áudio agora. Pode escrever, por favor?",
    "ptt": "Não consegui ouvir esse áudio agora. Pode escrever, por favor?",
}


@dataclass
class Contact:
    number: str
    agent: Any = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None
    help_id: str | None = None  # pedido de ajuda esperando a próxima mensagem deste contato
    help_targets: list = field(default_factory=list)  # pontes que podem estar esperando essa resposta
    last_inbound: datetime | None = None
    customer: bool = False  # cliente da empresa (atendente), não alguém da equipe (operador)
    talking_to: str | None = None  # equipe: telefone do cliente que esta pessoa assumiu (ASSUMIR)


class WhatsAppChannel:
    def __init__(
        self,
        cfg: Config,
        api: Any,
        history: History,
        agent_factory: Callable[..., Any],
        on_pause: Callable[[bool], None] = lambda paused: None,
        customer_factory: Callable[[str], Any] | None = None,
    ):
        self.cfg = cfg
        self.api = api
        self.history = history
        self.agent_factory = agent_factory
        self.on_pause = on_pause  # avisa a agenda (PARAR/CONTINUAR)
        self.customer_factory = customer_factory  # telefone → atendente; None = só a equipe é atendida
        self.contacts: dict[str, Contact] = {}
        self.paused = False
        self._seen: deque[str] = deque(maxlen=500)  # a Meta pode reenviar a mesma mensagem
        self.desk: Any = None  # passagem para a equipe (web.py liga quando a empresa carrega)
        self.remote_link: Callable[[], str] | None = None  # link da tela remota do navegador (web.py)

    @property
    def owner(self) -> str:
        return self.cfg.whatsapp_allowed[0]

    def allowed(self, number: str) -> bool:
        return number in self.cfg.whatsapp_allowed

    def in_service_window(self, number: str, now: datetime | None = None) -> bool:
        contact = self.contacts.get(number)
        return bool(contact and contact.last_inbound and (now or datetime.now()) - contact.last_inbound < SERVICE_WINDOW)

    async def send(self, number: str, text: str) -> bool:
        try:
            await self.api.send_text(number, text)
            return True
        except Exception as e:
            log.warning("não consegui enviar para %s: %s", number, e)
            return False

    # --- entrada -----------------------------------------------------------------

    async def handle(self, msg: Incoming) -> None:
        if not msg.id or msg.id in self._seen:
            return
        self._seen.append(msg.id)
        if not self.allowed(msg.sender):
            if self.customer_factory is None:
                log.warning("mensagem ignorada de número não permitido: %s", msg.sender)
                return
            await self.handle_customer(msg)
            return
        contact = self.contacts.setdefault(msg.sender, Contact(msg.sender))
        contact.last_inbound = datetime.now()
        try:
            await self.api.mark_read(msg.id)
        except Exception:
            pass
        msg = await self._listen(msg)
        if msg.kind != "text" and not msg.text:
            await self.send(msg.sender, NOT_UNDERSTOOD.get(msg.kind, "Por enquanto só leio texto e áudio. Pode escrever?"))
            return
        text = msg.text.strip()
        word = text.lower().strip(" .!")

        if word in STOP_WORDS:
            await self.stop_all()
            await self.send(msg.sender, "🛑 Parei tudo e pausei a agenda. Mande CONTINUAR quando quiser que eu volte.")
            return
        if word in CONTINUE_WORDS:
            self.set_paused(False)
            await self.send(msg.sender, "▶️ Voltei. Pode mandar.")
            return
        if contact.help_id:  # a mensagem é a resposta ao pedido de ajuda
            request_id, targets = contact.help_id, contact.help_targets
            contact.help_id, contact.help_targets = None, []
            for bridge in targets:
                bridge.answer(request_id, text)
            return
        if self.desk and await self._team_command(contact, text, word):
            return
        if self.paused:
            await self.send(msg.sender, "Estou pausado. Mande CONTINUAR para eu voltar a trabalhar.")
            return
        if word in NEW_WORDS:
            await contact.queue.put(None)  # None = recomeçar conversa
            self._ensure_worker(contact)
            return
        await contact.queue.put(text)
        self._ensure_worker(contact)

    async def handle_customer(self, msg: Incoming) -> None:
        """Cliente da empresa: vai para o atendente. PARAR de cliente é opt-out (o atendente trata), não pausa nada."""
        contact = self.contacts.setdefault(msg.sender, Contact(msg.sender, customer=True))
        contact.last_inbound = datetime.now()
        try:
            await self.api.mark_read(msg.id)
        except Exception:
            pass
        msg = await self._listen(msg)
        if msg.kind != "text" and not msg.text:
            await self.send(msg.sender, NOT_UNDERSTOOD.get(msg.kind, "Por enquanto consigo ler texto e áudio. Pode escrever, por favor?"))
            return
        await contact.queue.put(msg.text.strip())
        self._ensure_worker(contact)

    async def _listen(self, msg: Incoming) -> Incoming:
        """Áudio vira texto antes de seguir (quem ouve é o Whisper, pela UAZAPI). Sem transcrição, segue como veio."""
        transcribe = getattr(self.api, "transcribe", None)
        if msg.kind not in AUDIO_KINDS or msg.text or transcribe is None or not self.cfg.transcribe_audio:
            return msg
        try:
            text = (await transcribe(msg.id)).strip()
        except Exception as e:
            log.warning("não consegui transcrever o áudio de %s: %s", msg.sender, e)
            return msg
        return replace(msg, kind="text", text=f"🎤 (áudio) {text}") if text else msg

    async def _team_command(self, member: Contact, text: str, word: str) -> bool:
        """Passagem para a equipe: FILA, ASSUMIR n, DEVOLVER e o repasse para o cliente assumido.
        Devolve True quando a mensagem era da passagem (não vai para o operador)."""
        desk = self.desk
        taking = re.match(r"^(assumir|atender)\s*#?\s*(\d+)?$", word)
        if taking:
            contact = desk.find(int(taking[2]) if taking[2] else None, member.number)
            if contact is None:
                await self.send(member.number, "Não achei esse cliente na fila.\n\n" + desk.describe_queue())
                return True
            briefing = await desk.take(contact, member.number)
            member.talking_to = contact.phone
            await self.send(member.number, f"✅ Você assumiu #{contact.ticket}.\n\n{briefing}\n\n"
                                           "Agora o que você mandar aqui vai para o cliente. "
                                           "Mande DEVOLVER quando terminar: o assistente volta a atender.")
            return True
        if word in ("fila", "clientes"):
            await self.send(member.number, desk.describe_queue())
            return True
        if member.talking_to is None:
            if word == "devolver":
                await self.send(member.number, "Você não está atendendo nenhum cliente agora. Mande FILA para ver quem espera.")
                return True
            return False
        contact = desk.crm.get(member.talking_to)
        if contact is None or contact.handoff != "humano" or contact.assignee != member.number:
            member.talking_to = None
            await self.send(member.number, "Esse atendimento não está mais com você (foi devolvido ou outra pessoa "
                                           "assumiu). Esta mensagem não foi enviada ao cliente.")
            return True
        if word in ("devolver", "encerrar"):
            desk.release(contact, member.number)
            member.talking_to = None
            await self.send(member.number, f"↩ #{contact.ticket} devolvido ao assistente. Você voltou a falar com o agente.")
            return True
        if not await desk.reply(contact, text, member.number):
            await self.send(member.number, "⚠ Não consegui entregar ao cliente. Se ele não escreve há mais de 24 h, "
                                           "a Meta só deixa falar com ele por modelo aprovado.")
        return True

    def _ensure_worker(self, contact: Contact) -> None:
        if contact.worker is None or contact.worker.done():
            contact.worker = asyncio.create_task(self._work(contact))

    # --- trabalho por contato -------------------------------------------------------

    async def _agent(self, contact: Contact) -> Any:
        if contact.agent is None and contact.customer:
            key = f"cliente:{contact.number}"
            agent = self.customer_factory(contact.number)
            previous = self.history.channel_session(key)
            if not (previous and await agent.resume(previous)):
                await agent.start()
            contact.agent = agent
        if contact.agent is None:
            key = f"whatsapp:{contact.number}"
            agent = self.agent_factory(self.cfg)
            agent.human.notify = lambda req, c=contact, a=agent: self.ask_help(c, req, [a.human])
            previous = self.history.channel_session(key)
            if previous:
                await agent.resume(previous)
            else:
                await agent.start()
            contact.agent = agent
        return contact.agent

    async def _work(self, contact: Contact) -> None:
        # Fica esperando a fila para sempre (cancelado em close): sem corrida entre "fila vazia" e mensagem nova.
        while True:
            text = await contact.queue.get()
            try:
                agent = await self._agent(contact)
                if text is None:
                    await agent.reset()
                    self.history.set_channel_session(f"whatsapp:{contact.number}", None)
                    await self.send(contact.number, "Conversa nova. 🙂")
                    continue
                await self._answer(contact, agent, text)
            except Exception as e:
                log.exception("erro no WhatsApp de %s", contact.number)
                await self.send(contact.number, f"Deu um erro aqui: {type(e).__name__}: {e}")

    async def _answer(self, contact: Contact, agent: Any, text: str) -> None:
        if contact.customer:
            await self._answer_customer(contact, agent, text)
            return
        notice = asyncio.get_running_loop().call_later(
            WORKING_NOTICE_SECONDS,
            lambda: asyncio.ensure_future(self.send(contact.number, "⏳ Estou trabalhando nisso, já te respondo.")),
        )
        texts, blocked, status = [], [], ""
        try:
            async for event in agent.ask(text):
                if event.kind == "text":
                    texts.append(event.text)
                elif event.kind == "blocked":
                    blocked.append(event.text)
                elif event.kind == "result":
                    status = event.text
        finally:
            notice.cancel()
        if agent.session_id:
            self.history.set_channel_session(f"whatsapp:{contact.number}", agent.session_id)
        reply = texts[-1] if texts else "(terminei sem resposta)"
        if blocked:
            reply += "\n\n🛡 Bloqueado pela segurança: " + "; ".join(blocked)
        if status and not status.startswith("ok"):
            reply += f"\n\n⚠ {status}"
        await self.send(contact.number, reply)

    async def _answer_customer(self, contact: Contact, agent: Any, text: str) -> None:
        """Para o cliente vai só a resposta final (já filtrada pelo atendente): sem custos, bloqueios ou avisos internos."""
        texts = [e.text async for e in agent.ask(text) if e.kind == "text"]
        if agent.session_id:
            self.history.set_channel_session(f"cliente:{contact.number}", agent.session_id)
        if texts:
            await self.send(contact.number, texts[-1])

    # --- PARAR / CONTINUAR -------------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.on_pause(paused)

    async def stop_all(self) -> None:
        self.set_paused(True)
        for contact in self.contacts.values():
            while not contact.queue.empty():
                contact.queue.get_nowait()
            if contact.agent is not None:
                try:
                    await contact.agent.interrupt()
                except Exception:
                    pass
                contact.agent.human.cancel_all("o usuário mandou PARAR")

    # --- saída: ajuda humana e avisos da agenda -------------------------------------------

    async def ask_help(self, contact: Contact, req: HelpRequest, targets: list) -> None:
        contact.help_id, contact.help_targets = req.id, targets
        text = f"⚠ *Preciso de você:* {req.reason}"
        if req.link:
            text += f"\nPágina: {req.link}"
            if self.remote_link:  # o link acima abriria o site no SEU celular; o login tem de ser no navegador do agente
                text += ("\n\nPara resolver no navegador do agente pelo celular (login, código, verificação), abra: "
                         f"{self.remote_link()}\nVocê digita a senha; o agente não vê.")
        text += "\n\nQuando resolver, responda aqui: OK, um código, uma escolha ou \"não consegui\"."
        await self.send(contact.number, text)

    async def help_from_schedule(self, req: HelpRequest, bridges: list) -> None:
        """Pedido de ajuda de uma tarefa agendada: vai para o dono, se a janela de 24h permitir."""
        if self.in_service_window(self.owner):
            contact = self.contacts.setdefault(self.owner, Contact(self.owner))
            await self.ask_help(contact, req, bridges)

    async def deliver(self, title: str, text: str, icon: str = "⏰") -> bool:
        """Resultado da agenda (ou aviso) para o dono. Fora da janela de 24h a Meta não deixa: fica na caixa de entrada."""
        if self.paused or not self.in_service_window(self.owner):
            return False
        return await self.send(self.owner, f"{icon} *{title}*\n\n{text}")

    async def close(self) -> None:
        for contact in self.contacts.values():
            if contact.worker:
                contact.worker.cancel()
            if contact.agent is not None:
                await contact.agent.stop()


def spawn(tasks: set, coro: Awaitable) -> None:
    """Roda em segundo plano guardando a referência até terminar (senão o Python pode descartá-la no meio)."""
    task = asyncio.ensure_future(coro)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
