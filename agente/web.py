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
import os

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
import uvicorn

from . import config
from .core import Agent
from .history import History
from .knowledge import KnowledgeBase
from .human import HelpRequest, HumanBridge
from .scheduler import AgendaStore, InboxItem, Scheduler, Task, scheduled_prompt
from .browser import close_browsers
from .whatsapp import CloudApi, WhatsAppChannel, parse_messages, spawn, verify_signature

STATIC = Path(__file__).resolve().parent / "static"

cfg = config.load()
agenda = AgendaStore(cfg.agenda_db, cfg.timezone)
history = History(cfg.logs_dir / "conversas.db")
knowledge = KnowledgeBase(cfg.knowledge_dir)
LOCAL_HOSTS = ("127.0.0.1", "localhost")
SHOWN = ("user", "text", "tool", "blocked", "result", "checkpoint")  # eventos que a página redesenha
WEBHOOK = "/whatsapp/webhook"

whatsapp: WhatsAppChannel | None = None  # ligado quando as variáveis WHATSAPP_* estão preenchidas
scheduler: Scheduler | None = None
background: set[asyncio.Task] = set()


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler, whatsapp
    agenda.ensure_summary(cfg.daily_summary)
    scheduler = Scheduler(agenda, run_scheduled, deliver)
    if cfg.whatsapp_enabled:
        whatsapp = WhatsAppChannel(cfg, CloudApi(cfg), history, Agent, on_pause=set_paused)
    job = asyncio.create_task(scheduler.run_forever())
    yield
    job.cancel()
    if whatsapp:
        await whatsapp.close()
    await close_browsers()


app = FastAPI(title="Agente pessoal", lifespan=lifespan)


def is_local(host: str) -> bool:
    return host.rsplit(":", 1)[0] in LOCAL_HOSTS


@app.middleware("http")
async def local_only(request: Request, call_next):
    # DNS rebinding: um site malicioso pode apontar o domínio dele para 127.0.0.1 e ler esta API.
    # O navegador mantém o Host original, então basta recusar qualquer Host que não seja local.
    # Exceção: o webhook do WhatsApp chega pelo túnel/proxy com o domínio público e é autenticado pela assinatura.
    if not is_local(request.headers.get("host", "")) and request.url.path != WEBHOOK:
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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/painel")
async def panel_page() -> FileResponse:
    return FileResponse(STATIC / "painel.html")


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
        },
        "conversations": [vars(s) for s in history.sessions(limit=8)],
        "agenda": await list_agenda(),
        "blocked": history.blocked(limit=10),
        "knowledge": {"counts": knowledge.stats(), "recent": knowledge.recent(limit=8)},
    }


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


def main() -> None:
    # Só escuta em 127.0.0.1: o agente roda comandos sem pedir confirmação.
    port = cfg.web_port
    print(f"Agente pessoal em http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
