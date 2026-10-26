"""Interface web local: chat no navegador via WebSocket e agendador de tarefas.

O servidor web é o processo que fica ligado, então é ele que roda a agenda
(resumo diário, tarefas recorrentes, lembretes) e entrega os resultados nas abas abertas.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import uvicorn

from . import config
from .core import Agent
from .human import HelpRequest, HumanBridge
from .scheduler import AgendaStore, InboxItem, Scheduler, Task, scheduled_prompt

STATIC = Path(__file__).resolve().parent / "static"

cfg = config.load()
agenda = AgendaStore(cfg.agenda_db, cfg.timezone)


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
    """Resultado de tarefa agendada: vai para as abas abertas; se não houver nenhuma, fica na caixa de entrada."""
    if await hub.broadcast(inbox_payload(item)):
        agenda.mark_read([item.id])


async def help_broadcast(req: HelpRequest) -> None:
    await hub.broadcast({"kind": "help", "text": req.reason, "id": req.id, "link": req.link})


async def run_scheduled(task: Task) -> str:
    """Cada tarefa agendada roda num agente próprio, sem misturar com a conversa aberta."""
    agent = Agent(cfg)
    agent.human.notify = help_broadcast
    hub.bridges.add(agent.human)
    try:
        return await agent.run_once(scheduled_prompt(task, agenda.now()))
    finally:
        hub.bridges.discard(agent.human)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    agenda.ensure_summary(cfg.daily_summary)
    job = asyncio.create_task(Scheduler(agenda, run_scheduled, deliver).run_forever())
    yield
    job.cancel()


app = FastAPI(title="Agente pessoal", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def status() -> dict:
    return {
        "model": cfg.model,
        "workdir": str(cfg.workdir),
        "max_budget_usd": cfg.max_budget_usd,
        "max_turns": cfg.max_turns,
        "api_key": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
    }


@app.get("/api/agenda")
async def list_agenda() -> list[dict]:
    return [
        {"id": t.id, "title": t.title, "mode": t.mode, "when": t.describe(),
         "next_run": t.next_run.isoformat() if t.next_run else None}
        for t in agenda.list()
    ]


@app.websocket("/ws")
async def chat(ws: WebSocket) -> None:
    """Uma conversa por aba: cada conexão tem seu próprio Agent."""
    # Bloqueia outros sites abertos no navegador de falarem com o agente.
    origin = ws.headers.get("origin", "")
    host = ws.headers.get("host", "")
    if origin not in (f"http://{host}",) or host.split(":")[0] not in ("127.0.0.1", "localhost"):
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.sockets.add(ws)
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
        await agent.start()
        await ws.send_json({"kind": "ready", "text": ""})
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
            if msg.get("type") == "reset":
                await agent.reset()
                await ws.send_json({"kind": "ready", "text": "conversa nova"})
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                async for event in agent.ask(text):
                    await ws.send_json({"kind": event.kind, "text": event.text})
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
