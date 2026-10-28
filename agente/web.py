"""Interface web local, agendador de tarefas e webhook do WhatsApp.

O servidor web é o processo que fica ligado, então é ele que roda a agenda
(resumo diário, tarefas recorrentes, lembretes), recebe as mensagens do WhatsApp
e entrega os resultados nas abas abertas e no WhatsApp.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import hmac
import logging
import os

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from urllib.parse import urlparse
import uvicorn

from . import config, sessoes
from .atendente import Attendant, company_now
from .core import Agent
from .crm import Crm, clean_phone
from .empresa import CompanyError, load_company
from .history import History
from .knowledge import KnowledgeBase
from .passagem import PANEL, Desk, member_name
from .human import HelpRequest, HumanBridge
from .retomada import FollowupEngine, model_composer
from .scheduler import AgendaStore, InboxItem, Scheduler, Task, scheduled_prompt
from .browser import BrowserError, close_browsers, shared_browser
from .whatsapp import CloudApi, UazApi, WhatsAppChannel, parse_messages, parse_uazapi, spawn, verify_signature

STATIC = Path(__file__).resolve().parent / "static"

cfg = config.load()
agenda = AgendaStore(cfg.agenda_db, cfg.timezone)
history = History(cfg.logs_dir / "conversas.db")
knowledge = KnowledgeBase(cfg.knowledge_dir)
crm = Crm(cfg.crm_db)
LOCAL_HOSTS = ("127.0.0.1", "localhost")
SHOWN = ("user", "text", "tool", "blocked", "result", "checkpoint")  # eventos que a página redesenha
WEBHOOK = "/whatsapp/webhook"
UAZAPI_HOOK = "/whatsapp/uazapi"  # + "/<UAZAPI_WEBHOOK_SEGREDO>"

whatsapp: WhatsAppChannel | None = None  # ligado quando as variáveis WHATSAPP_* estão preenchidas
scheduler: Scheduler | None = None
followups: FollowupEngine | None = None  # retomada automática (ligada quando a empresa carrega)
background: set[asyncio.Task] = set()
simulated: dict[str, set[WebSocket]] = {}  # abas do simulador por contato "sim-...": recebem as retomadas
watch: sessoes.SessionWatch | None = None  # checagem dos logins dos sistemas da loja
desk: Desk | None = None  # passagem do atendente para a equipe (ligada quando a empresa carrega)
remote_access = sessoes.RemoteAccess()  # links temporários da tela remota do navegador
REMOTE = sessoes.REMOTE_PATH
FRAME_S = 0.7  # intervalo entre imagens da tela remota
EXPIRED_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link expirado</title></head>
<body style="margin:0;background:#161615;color:#ecebe6;font:17px/1.5 system-ui,sans-serif;padding:32px 20px">
<h1 style="font-size:20px">⚠ Este link expirou</h1>
<p>O link do navegador do agente vale 30 minutos e cai quando o agente reinicia.</p>
<p>Mande <b>NAVEGADOR</b> no WhatsApp do agente para receber um link novo.</p></body></html>"""
log = logging.getLogger(__name__)


class Hub:
    """Abas abertas e agentes da agenda: entrega avisos e encaminha respostas de ajuda."""

    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()
        self.bridges: set[HumanBridge] = set()  # pontes dos agentes rodando tarefas agendadas

    async def broadcast(self, payload: dict) -> int:
        """Manda para todas as abas; devolve em quantas chegou."""
        delivered = 0
        for ws in list(self.sockets):
            try:
                await ws.send_json(payload)
                delivered += 1
            except Exception:
                self.sockets.discard(ws)
        return delivered

    def answer(self, request_id: str, text: str) -> None:
        for bridge in list(self.bridges):
            bridge.answer(request_id, text)


hub = Hub()


def inbox_payload(item: InboxItem) -> dict:
    return {"kind": "proactive", "id": item.id, "title": item.title, "text": item.text,
            "time": item.created.strftime("%d/%m %H:%M")}


async def deliver(item: InboxItem) -> None:
    """Resultado de tarefa agendada: vai para as abas abertas e para o WhatsApp do dono.
    Se não chegou a lugar nenhum, fica na caixa de entrada."""
    on_web = await hub.broadcast(inbox_payload(item))
    on_whatsapp = bool(whatsapp) and await whatsapp.deliver(item.title, item.text)
    if on_web or on_whatsapp:
        agenda.mark_read([item.id])


async def help_broadcast(req: HelpRequest) -> None:
    await hub.broadcast({"kind": "help", "text": req.reason, "id": req.id, "link": req.link})
    if whatsapp:
        await whatsapp.help_from_schedule(req, list(hub.bridges))


async def run_scheduled(task: Task) -> str:
    """Cada tarefa agendada roda num agente próprio, sem misturar com a conversa aberta."""
    agent = Agent(cfg)
    agent.human.notify = help_broadcast
    hub.bridges.add(agent.human)
    try:
        return await agent.run_once(scheduled_prompt(task, agenda.now()))
    finally:
        hub.bridges.discard(agent.human)


def set_paused(paused: bool) -> None:
    if scheduler:
        scheduler.paused = paused
    if followups:
        followups.paused = paused  # PARAR da equipe também segura as retomadas


async def send_to_customer(phone: str, text: str, kind: str = "retomada") -> bool:
    """Saída da retomada e da equipe: contato simulado vai para as abas do simulador; o resto, pelo WhatsApp."""
    if phone.startswith("sim-"):
        for ws in list(simulated.get(phone, ())):
            try:
                await ws.send_json({"kind": kind, "text": text})
            except Exception:
                simulated[phone].discard(ws)
        return True  # fica no CRM e aparece quando a aba do contato abrir de novo
    if whatsapp is None or whatsapp.customer_factory is None:
        return False
    if not whatsapp.in_service_window(phone):
        return False  # o canal reiniciou e perdeu a hora da última mensagem: não arrisca fora da janela
    return await whatsapp.send(phone, text)


async def send_template_to_customer(phone: str, name: str, params: list[str]) -> bool:
    if phone.startswith("sim-") or whatsapp is None:
        return False
    try:
        await whatsapp.api.send_template(phone, name, params)
        return True
    except Exception as e:
        log.warning("modelo %s não enviado para %s: %s", name, phone, e)
        return False


async def to_team(title: str, text: str) -> None:
    """Cliente chamando a equipe: abas abertas (chat e /atendimento) e WhatsApp de cada pessoa da equipe na janela de 24 h."""
    item = agenda.add_inbox(Task("atendimento", title, ""), text)
    delivered = await hub.broadcast(inbox_payload(item)) > 0
    if whatsapp and not whatsapp.paused:
        for number in cfg.whatsapp_allowed:
            if whatsapp.in_service_window(number):
                delivered = await whatsapp.send(number, f"🙋 *{title}*\n\n{text}") or delivered
    if delivered:
        agenda.mark_read([item.id])


async def to_member(member: str, text: str) -> None:
    """Mensagem do cliente para quem assumiu. Quem assumiu pelo painel vê lá; pelo WhatsApp, recebe lá."""
    if member != PANEL and whatsapp and whatsapp.in_service_window(member) and await whatsapp.send(member, text):
        return
    await hub.broadcast({"kind": "atendimento", "text": text})


def build_desk() -> Desk | None:
    try:
        company = load_company(cfg.company_dir)
    except (CompanyError, ValueError) as e:
        log.warning("passagem para a equipe desligada: %s", e)
        return None
    return Desk(crm, company, to_team, to_member, lambda phone, text: send_to_customer(phone, text, kind="humano"),
                local_now=lambda: company_now(cfg.timezone))


def build_followups() -> FollowupEngine | None:
    try:
        company = load_company(cfg.company_dir)
        return FollowupEngine(crm, company, model_composer(cfg), send_to_customer, send_template_to_customer,
                              cfg.timezone)
    except (CompanyError, ValueError) as e:
        log.warning("retomada automática desligada: %s", e)
        return None


def remote_link() -> str:
    """Link novo para a tela remota. Com AGENT_PUBLIC_URL, abre no celular; sem ela, só na VM (túnel SSH)."""
    base = cfg.public_url or f"http://127.0.0.1:{cfg.web_port}"
    return f"{base}{REMOTE}/{remote_access.issue()}"


async def alert_team(title: str, text: str) -> None:
    """Aviso de acesso: abas abertas e WhatsApp do dono; se não chegou a lugar nenhum, fica na caixa de entrada."""
    item = agenda.add_inbox(Task("acessos", title, ""), text)
    on_web = await hub.broadcast(inbox_payload(item))
    on_whatsapp = bool(whatsapp) and await whatsapp.deliver(title, text, icon="🔐")
    if on_web or on_whatsapp:
        agenda.mark_read([item.id])


def browser():
    return shared_browser(cfg.browser_profile, cfg.workdir / "capturas", cfg.browser_headless)


def build_watch() -> sessoes.SessionWatch | None:
    try:
        systems = sessoes.load_systems(cfg.company_dir)
    except sessoes.SystemsError as e:
        log.warning("checagem dos acessos desligada: %s", e)
        return None
    store = sessoes.SessionStore(cfg.logs_dir / "sessoes.json")
    return sessoes.SessionWatch(systems, browser().probe, store, alert_team, remote_link)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler, whatsapp, followups, watch, desk
    agenda.ensure_summary(cfg.daily_summary)
    scheduler = Scheduler(agenda, run_scheduled, deliver)
    desk = build_desk()
    if cfg.whatsapp_enabled:
        customers = (lambda phone: Attendant(cfg, phone, origin="whatsapp", crm=crm, desk=desk)) if cfg.attendant_whatsapp else None
        api = UazApi(cfg) if cfg.whatsapp_provider == "uazapi" else CloudApi(cfg)
        whatsapp = WhatsAppChannel(cfg, api, history, Agent, on_pause=set_paused, customer_factory=customers)
        whatsapp.desk = desk
        whatsapp.remote_link = remote_link
    followups = build_followups()
    watch = build_watch()
    jobs = [asyncio.create_task(scheduler.run_forever())]
    if watch and watch.systems:
        jobs.append(asyncio.create_task(watch.run_forever(cfg.access_check_min)))
    if followups:
        jobs.append(asyncio.create_task(followups.run_forever()))
    yield
    for job in jobs:
        job.cancel()
    if whatsapp:
        await whatsapp.close()
    await close_browsers()


app = FastAPI(title="Agente pessoal", lifespan=lifespan)


def is_local(host: str) -> bool:
    return host.rsplit(":", 1)[0] in LOCAL_HOSTS


def remote_allowed(host: str, path: str) -> bool:
    """Tela remota: só com link válido, e de fora só pelo domínio de AGENT_PUBLIC_URL."""
    if not path.startswith((REMOTE + "/", "/ws" + REMOTE + "/")):
        return False
    public = urlparse(cfg.public_url).hostname if cfg.public_url else None
    if not (is_local(host) or (public and host.rsplit(":", 1)[0] == public)):
        return False
    return remote_access.valid(path.removeprefix("/ws").removeprefix(REMOTE + "/"))


@app.middleware("http")
async def local_only(request: Request, call_next):
    # DNS rebinding: um site malicioso pode apontar o domínio dele para 127.0.0.1 e ler esta API.
    # O navegador mantém o Host original, então basta recusar qualquer Host que não seja local.
    # Exceção: o webhook do WhatsApp chega pelo túnel/proxy com o domínio público e é autenticado pela assinatura.
    host, path = request.headers.get("host", ""), request.url.path
    webhook = path == WEBHOOK or path.startswith(UAZAPI_HOOK + "/")
    if not is_local(host) and not webhook and not remote_allowed(host, path):
        return PlainTextResponse("host não permitido", status_code=403)
    return await call_next(request)


async def open_session(agent: Agent, session_id: str) -> str:
    """Retoma a conversa; se o contexto não existir mais, avisa (o histórico já foi mostrado)."""
    if await agent.resume(session_id):
        return ""
    return "não deu para retomar o contexto desta conversa (o registro dela não existe mais); o histórico está acima, mas o agente começa do zero"


def history_payload(session_id: str) -> dict:
    items = [{"kind": r.kind, "text": r.text} for r in history.events(session_id) if r.kind in SHOWN]
    return {"kind": "history", "items": items, "session": session_id}


@app.get(WEBHOOK)
async def whatsapp_verify(request: Request) -> PlainTextResponse:
    """Verificação que a Meta faz ao cadastrar o webhook: devolve o desafio se o token bater."""
    q = request.query_params
    token_ok = hmac.compare_digest(q.get("hub.verify_token", ""), cfg.whatsapp_verify_token)
    if q.get("hub.mode") == "subscribe" and cfg.whatsapp_verify_token and token_ok:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "token de verificação inválido")


@app.post(WEBHOOK)
async def whatsapp_receive(request: Request) -> dict:
    """Mensagens do WhatsApp. Responde 200 na hora (senão a Meta reenvia) e processa em segundo plano."""
    if whatsapp is None:
        raise HTTPException(404, "WhatsApp não configurado")
    body = await request.body()
    if not verify_signature(cfg.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(403, "assinatura inválida")
    for msg in parse_messages(await request.json()):
        spawn(background, whatsapp.handle(msg))
    return {"ok": True}


@app.post(UAZAPI_HOOK + "/{secret}")
async def uazapi_receive(secret: str, request: Request) -> dict:
    """Mensagens pela UAZAPI. Ela não assina: vale o segredo no caminho e, quando vem, o token da instância."""
    if whatsapp is None or cfg.whatsapp_provider != "uazapi":
        raise HTTPException(404, "UAZAPI não configurada")
    if not hmac.compare_digest(secret, cfg.uazapi_webhook_secret):
        raise HTTPException(403, "segredo inválido")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "corpo inválido") from None
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or (token and not hmac.compare_digest(str(token), cfg.uazapi_token)):
        raise HTTPException(403, "token da instância inválido")
    for msg in parse_uazapi(payload):
        spawn(background, whatsapp.handle(msg))
    return {"ok": True}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/painel")
async def panel_page() -> FileResponse:
    return FileResponse(STATIC / "painel.html")


@app.get("/simulador")
async def simulator_page() -> FileResponse:
    return FileResponse(STATIC / "simulador.html")


@app.get("/atendimento")
async def desk_page() -> FileResponse:
    return FileResponse(STATIC / "atendimento.html")


def same_origin(request: Request) -> None:
    if request.headers.get("origin") != f"http://{request.headers.get('host', '')}":
        raise HTTPException(403, "origem não permitida")


def need_desk() -> Desk:
    if desk is None:
        raise HTTPException(503, "passagem para a equipe desligada: confira a pasta da empresa")
    return desk


def ticket_payload(d: Desk, contact) -> dict:
    return {**vars(contact), "member": member_name(d.company, contact.assignee) if contact.assignee else ""}


@app.get("/api/atendimento")
async def desk_queue() -> list[dict]:
    """Clientes com a equipe: aguardando alguém ou já atendidos por alguém."""
    d = need_desk()
    return [ticket_payload(d, c) for c in d.queue()]


@app.get("/api/atendimento/{phone}")
async def desk_conversation(phone: str) -> dict:
    d = need_desk()
    contact = crm.get(phone)
    if contact is None:
        raise HTTPException(404, "contato não encontrado")
    messages = [{"direction": i.direction, "text": i.text, "ts": i.ts} for i in crm.interactions(phone, limit=80)]
    return {"contact": ticket_payload(d, contact), "messages": messages}


@app.post("/api/atendimento/{phone}/assumir")
async def desk_take(phone: str, request: Request) -> dict:
    same_origin(request)
    d = need_desk()
    contact = crm.get(phone)
    if contact is None:
        raise HTTPException(404, "contato não encontrado")
    await d.take(contact, PANEL)
    return {"ok": True}


@app.post("/api/atendimento/{phone}/responder")
async def desk_reply(phone: str, request: Request) -> dict:
    same_origin(request)
    d = need_desk()
    contact = crm.get(phone)
    text = str((await request.json()).get("text", "")).strip()
    if contact is None:
        raise HTTPException(404, "contato não encontrado")
    if not text:
        raise HTTPException(400, "mensagem vazia")
    if not await d.reply(contact, text[:4000], PANEL):
        raise HTTPException(409, "não consegui entregar: o cliente não escreve há mais de 24 h ou o WhatsApp está desligado")
    return {"ok": True}


@app.post("/api/atendimento/{phone}/devolver")
async def desk_release(phone: str, request: Request) -> dict:
    same_origin(request)
    d = need_desk()
    contact = crm.get(phone)
    if contact is None:
        raise HTTPException(404, "contato não encontrado")
    d.release(contact, PANEL)
    return {"ok": True}


def contact_payload(phone: str) -> dict:
    """Ficha do contato no CRM, para o painel lateral do simulador."""
    contact = crm.get(phone)
    return {"kind": "lead", "contact": vars(contact) if contact else None,
            "followups": [vars(f) for f in crm.followups(phone)]}


@app.get(REMOTE + "/{token}")
async def remote_page(token: str) -> FileResponse:
    if not remote_access.valid(token):
        return HTMLResponse(EXPIRED_PAGE, status_code=404)
    return FileResponse(STATIC / "navegador.html",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.post("/api/navegador/link")
async def new_remote_link(request: Request) -> dict:
    """Botão do painel (local): link novo para a tela remota, aberto na mesma máquina."""
    if request.headers.get("origin") != f"http://{request.headers.get('host', '')}":
        raise HTTPException(403, "origem não permitida")
    return {"url": f"{REMOTE}/{remote_access.issue()}"}


async def access_report() -> str:
    """Confere os acessos agora (botão "Já entrei" da tela remota) e devolve o resumo."""
    if watch is None or not watch.systems:
        return "nenhum sistema cadastrado em empresa/sistemas.toml"
    await watch.tick()
    return sessoes.describe(watch.systems, watch.store.load())


@app.websocket("/ws" + REMOTE + "/{token}")
async def remote_screen(ws: WebSocket, token: str) -> None:
    """Tela remota do navegador do agente: a pessoa vê a aba e clica/digita para fazer login."""
    origin, host = ws.headers.get("origin", ""), ws.headers.get("host", "")
    if origin not in (f"http://{host}", f"https://{host}") or not remote_allowed(host, f"/ws{REMOTE}/{token}"):
        await ws.close(code=1008)
        return
    await ws.accept()

    async def frames() -> None:
        while remote_access.valid(token):
            try:
                await ws.send_bytes(await browser().view())
            except BrowserError as e:
                await ws.send_json({"kind": "error", "text": str(e)})
                await asyncio.sleep(3)
            await asyncio.sleep(FRAME_S)
        await ws.send_json({"kind": "expired"})
        await ws.close()

    sending = asyncio.create_task(frames())
    try:
        while True:
            msg = await ws.receive_json()
            if not remote_access.valid(token):
                break
            if msg.get("type") == "done":
                await ws.send_json({"kind": "status", "text": await access_report()})
                continue
            try:
                state = await browser().remote(msg)  # o que a pessoa digita não vai para log nenhum
                await ws.send_json({"kind": "url", "text": state["url"]})
                await ws.send_json({"kind": "field", "field": state.get("field"), "after": msg.get("type")})
            except (BrowserError, KeyError, ValueError) as e:
                await ws.send_json({"kind": "error", "text": str(e)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sending.cancel()


@app.post("/api/simulador/retomar/{phone}")
async def simulator_follow_up(phone: str, request: Request) -> dict:
    """Simula o cliente ter sumido: manda agora a próxima retomada para o contato simulado (sem esperar as horas)."""
    if request.headers.get("origin") != f"http://{request.headers.get('host', '')}":
        raise HTTPException(403, "origem não permitida")
    phone = clean_phone(phone)
    contact = crm.get(phone)
    if not phone.startswith("sim-") or contact is None:
        raise HTTPException(404, "contato simulado não encontrado")
    if followups is None:
        raise HTTPException(503, "retomada desligada: confira empresa.toml [retomada]")
    if contact.opt_out:
        return {"sent": False, "note": "o cliente pediu para não receber mensagens (PARAR)"}
    total = len(followups.policy.delays_h)
    attempt = min(crm.silence(phone).attempts + 1, total)
    outcome = await followups.run(contact, attempt)
    lead = contact_payload(phone)
    for ws in list(simulated.get(phone, ())):
        try:
            await ws.send_json(lead)
        except Exception:
            pass
    return {"sent": outcome.sent, "text": outcome.text, "attempt": attempt, "of": total, "note": outcome.note}


@app.get("/api/crm")
async def crm_contacts() -> list[dict]:
    return [vars(c) for c in crm.contacts()]


@app.delete("/api/crm/{phone}")
async def crm_delete(phone: str, request: Request) -> dict:
    """LGPD: apaga o contato e todo o histórico dele no CRM."""
    if request.headers.get("origin") != f"http://{request.headers.get('host', '')}":
        raise HTTPException(403, "origem não permitida")
    if not crm.delete(phone):
        raise HTTPException(404, "contato não encontrado")
    return {"deleted": clean_phone(phone)}


@app.get("/api/painel")
async def panel() -> dict:
    """Tudo o que o painel mostra, numa chamada só."""
    days = history.daily_costs(days=30)
    knowledge.reindex()  # pega notas criadas por outros processos ou à mão
    return {
        "costs": days,
        "totals": {
            "today": round(days[-1]["cost_usd"], 4),
            "week": round(sum(d["cost_usd"] for d in days[-7:]), 4),
            "month": round(sum(d["cost_usd"] for d in days), 4),
            "requests_month": sum(d["requests"] for d in days),
            "budget_per_request": cfg.max_budget_usd,
            "provider": cfg.base_url,  # provedor alternativo: o custo real fica no painel dele
        },
        "conversations": [vars(s) for s in history.sessions(limit=8)],
        "agenda": await list_agenda(),
        "blocked": history.blocked(limit=10),
        "knowledge": {"counts": knowledge.stats(), "recent": knowledge.recent(limit=8)},
        "access": access_summary(),
    }


def access_summary() -> list[dict]:
    try:
        systems = sessoes.load_systems(cfg.company_dir)
    except sessoes.SystemsError as e:
        return [{"name": "sistemas.toml", "status": "erro", "note": str(e)}]
    states = sessoes.SessionStore(cfg.logs_dir / "sessoes.json").load()
    return [{"name": s.name, "host": s.host, **vars(states.get(s.name, sessoes.State()))} for s in systems]


@app.get("/api/status")
async def status() -> dict:
    return {
        "model": cfg.model,
        "workdir": str(cfg.workdir),
        "max_budget_usd": cfg.max_budget_usd,
        "max_turns": cfg.max_turns,
        "api_key": cfg.has_credentials,
        "whatsapp": whatsapp is not None,
    }


@app.get("/api/conversas")
async def list_conversations() -> list[dict]:
    return [vars(s) for s in history.sessions()]


@app.get("/api/conversas/{session_id}")
async def conversation(session_id: str) -> dict:
    if not any(s.id == session_id for s in history.sessions(limit=10_000)):
        raise HTTPException(404, "conversa não encontrada")
    return history_payload(session_id)


@app.get("/api/agenda")
async def list_agenda() -> list[dict]:
    return [
        {"id": t.id, "title": t.title, "mode": t.mode, "when": t.describe(),
         "next_run": t.next_run.isoformat() if t.next_run else None}
        for t in agenda.list()
    ]


@app.delete("/api/agenda/{task_id}")
async def cancel_task(task_id: str, request: Request) -> dict:
    # Ação que muda dados: além do Host, exige que o pedido venha da própria página.
    if request.headers.get("origin") != f"http://{request.headers.get('host', '')}":
        raise HTTPException(403, "origem não permitida")
    if not agenda.cancel(task_id):
        raise HTTPException(404, "tarefa não encontrada")
    return {"cancelled": task_id}


@app.websocket("/ws")
async def chat(ws: WebSocket) -> None:
    """Uma conversa por aba: cada conexão tem seu próprio Agent."""
    # Bloqueia outros sites abertos no navegador de falarem com o agente.
    origin = ws.headers.get("origin", "")
    host = ws.headers.get("host", "")
    if origin != f"http://{host}" or not is_local(host):
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.sockets.add(ws)
    resume = ws.query_params.get("sessao") or None  # ?sessao=... retoma uma conversa (links do painel)
    agent = Agent(cfg)
    asks: asyncio.Queue[dict] = asyncio.Queue()

    async def notify(req: HelpRequest) -> None:
        await ws.send_json({"kind": "help", "text": req.reason, "id": req.id, "link": req.link})

    async def reader() -> None:
        # Lê o WebSocket o tempo todo: a resposta a um pedido de ajuda chega
        # enquanto o agente ainda está no meio da tarefa.
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "help_reply":
                request_id, text = str(msg.get("id", "")), str(msg.get("text", ""))
                agent.human.answer(request_id, text)
                hub.answer(request_id, text)  # pode ser de uma tarefa agendada
            else:
                await asks.put(msg)

    agent.human.notify = notify
    reading = asyncio.create_task(reader())
    try:
        if resume:
            await ws.send_json(history_payload(resume))
            note = await open_session(agent, resume)
        else:
            await agent.start()
            note = ""
        await ws.send_json({"kind": "ready", "text": note, "session": agent.session_id})
        unread = agenda.unread()  # o que a agenda fez enquanto nenhuma aba estava aberta
        for item in unread:
            await ws.send_json(inbox_payload(item))
        agenda.mark_read([i.id for i in unread])
        while True:
            next_msg = asyncio.create_task(asks.get())
            await asyncio.wait({next_msg, reading}, return_when=asyncio.FIRST_COMPLETED)
            if not next_msg.done():  # o leitor terminou: a aba foi fechada
                next_msg.cancel()
                break
            msg = next_msg.result()
            kind = msg.get("type")
            try:
                if kind == "reset":
                    await agent.reset()
                    await ws.send_json({"kind": "ready", "text": "conversa nova"})
                    continue
                if kind == "resume":
                    session_id = str(msg.get("session", ""))
                    await ws.send_json(history_payload(session_id))
                    note = await open_session(agent, session_id) or "conversa retomada"
                    await ws.send_json({"kind": "ready", "text": note, "session": agent.session_id})
                    continue
                if kind == "undo":
                    await agent.rewind(str(msg.get("checkpoint", "")))
                    await ws.send_json({"kind": "ready", "text": "edições de arquivo desfeitas"})
                    continue
            except Exception as e:
                await ws.send_json({"kind": "error", "text": f"{type(e).__name__}: {e}"})
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                async for event in agent.ask(text):
                    await ws.send_json({"kind": event.kind, "text": event.text, "session": agent.session_id})
            except Exception as e:  # erro do SDK não derruba a conexão
                await ws.send_json({"kind": "error", "text": f"{type(e).__name__}: {e}"})
    except (WebSocketDisconnect, RuntimeError):  # aba fechada no meio de um envio
        pass
    finally:
        hub.sockets.discard(ws)
        reading.cancel()
        agent.human.cancel_all()
        await agent.stop()


@app.websocket("/ws/simulador")
async def simulator(ws: WebSocket) -> None:
    """Simulador de cliente: a aba faz o papel de um cliente e conversa com o atendente (não com o operador)."""
    origin, host = ws.headers.get("origin", ""), ws.headers.get("host", "")
    if origin != f"http://{host}" or not is_local(host):
        await ws.close(code=1008)
        return
    await ws.accept()
    # Contato simulado sempre tem o prefixo "sim-": nunca se confunde com um número de verdade.
    raw = (ws.query_params.get("telefone") or "").strip()
    phone = clean_phone(raw if raw.startswith("sim-") else f"sim-{raw}") if raw else ""
    if phone == "sim-":
        phone = ""
    phone = phone or f"sim-{os.urandom(3).hex()}"
    try:
        agent = Attendant(cfg, phone, origin="simulador", crm=crm, desk=desk)
    except CompanyError as e:
        await ws.send_json({"kind": "error", "text": f"configuração da empresa: {e}"})
        await ws.close()
        return
    try:
        await agent.start()
        simulated.setdefault(phone, set()).add(ws)
        shown = {"entrada": "user", "saida": "text", "retomada": "retomada", "humano": "humano"}
        items = [{"kind": shown[i.direction], "text": i.text} for i in crm.interactions(phone, limit=60) if i.direction in shown]
        if items:
            await ws.send_json({"kind": "history", "items": items})
        await ws.send_json({"kind": "ready", "phone": phone, "company": agent.company.name,
                            "assistant": agent.company.assistant, "subject": agent.company.subject_label})
        await ws.send_json(contact_payload(phone))
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "reset":
                await agent.reset()
                await ws.send_json({"kind": "ready", "phone": phone, "text": "conversa nova (o cadastro continua)"})
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                async for event in agent.ask(text):
                    await ws.send_json({"kind": event.kind, "text": event.text})
            except Exception as e:  # erro do SDK não derruba a conexão
                await ws.send_json({"kind": "error", "text": f"{type(e).__name__}: {e}"})
            await ws.send_json(contact_payload(phone))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        simulated.get(phone, set()).discard(ws)
        await agent.stop()


def main() -> None:
    # Só escuta em 127.0.0.1: o agente roda comandos sem pedir confirmação.
    port = cfg.web_port
    print(f"Agente pessoal em http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
