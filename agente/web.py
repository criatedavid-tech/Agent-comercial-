"""Interface web local para testes: chat no navegador via WebSocket."""

from pathlib import Path
import asyncio
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import uvicorn

from . import config
from .core import Agent
from .human import HelpRequest

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Agente pessoal")
cfg = config.load()


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
                agent.human.answer(str(msg.get("id", "")), str(msg.get("text", "")))
            else:
                await asks.put(msg)

    agent.human.notify = notify
    reading = asyncio.create_task(reader())
    try:
        await agent.start()
        await ws.send_json({"kind": "ready", "text": ""})
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
