"""Interface web: status, trava de origem, conversa e pedido de ajuda humana pelo WebSocket."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agente import web
from agente.core import Event
from agente.human import HumanBridge

# O TestClient manda host "testserver" no WebSocket; o navegador manda o host real.
ORIGIN = {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}


class FakeAgent:
    """Agente falso: não chama a API. Pede ajuda humana quando o pedido fala em 'captcha'."""

    instances: list["FakeAgent"] = []

    def __init__(self, cfg):
        self.human = HumanBridge(0.05)
        self.started = self.stopped = False
        self.resets = 0
        FakeAgent.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def reset(self):
        self.resets += 1

    async def ask(self, text):
        yield Event("tool", "WebFetch https://loja.exemplo.com")
        if "captcha" in text:
            answer = await self.human.request("Verificação de robô na loja.", "https://loja.exemplo.com")
            yield Event("text", f"Recebi: {answer}")
        if "quebra" in text:
            raise RuntimeError("falha no SDK")
        yield Event("result", "ok · 1 passos · US$ 0.0000")


@pytest.fixture
def client(monkeypatch):
    FakeAgent.instances.clear()
    monkeypatch.setattr(web, "Agent", FakeAgent)
    return TestClient(web.app, base_url="http://127.0.0.1:8000")


def receive_until(ws, kind):
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event["kind"] == kind:
            return events


def test_index_and_status(client):
    assert "Agente pessoal" in client.get("/").text
    status = client.get("/api/status").json()
    assert set(status) == {"model", "workdir", "max_budget_usd", "max_turns", "api_key"}


@pytest.mark.parametrize("origin", ["http://evil.com", "http://127.0.0.1:9999", ""])
def test_rejects_other_origins(client, origin):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"host": "127.0.0.1:8000", "origin": origin}) as ws:
            ws.receive_json()


def test_rejects_non_local_host(monkeypatch):
    monkeypatch.setattr(web, "Agent", FakeAgent)
    remote = TestClient(web.app)
    headers = {"host": "192.168.0.10:8000", "origin": "http://192.168.0.10:8000"}
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect("/ws", headers=headers) as ws:
            ws.receive_json()


def test_conversation_flow(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        assert ws.receive_json()["kind"] == "ready"
        ws.send_json({"type": "ask", "text": "oi"})
        kinds = [e["kind"] for e in receive_until(ws, "result")]
        assert kinds == ["tool", "result"]

        ws.send_json({"type": "reset"})
        assert ws.receive_json() == {"kind": "ready", "text": "conversa nova"}
    agent = FakeAgent.instances[0]
    assert agent.started and agent.stopped and agent.resets == 1


def test_human_help_round_trip(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "ask", "text": "compra, tem captcha"})
        help_event = receive_until(ws, "help")[-1]
        assert help_event["text"] == "Verificação de robô na loja."
        assert help_event["link"] == "https://loja.exemplo.com"

        # a resposta chega enquanto o agente ainda está no meio do pedido
        ws.send_json({"type": "help_reply", "id": help_event["id"], "text": "resolvido"})
        events = receive_until(ws, "result")
        assert {"kind": "text", "text": "Recebi: resolvido"} in events


def test_help_times_out_without_answer(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "ask", "text": "captcha"})
        receive_until(ws, "help")
        text = next(e for e in receive_until(ws, "result") if e["kind"] == "text")["text"]
        assert "sem resposta" in text


def test_sdk_error_does_not_drop_connection(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "ask", "text": "quebra"})
        error = receive_until(ws, "error")[-1]
        assert error["text"] == "RuntimeError: falha no SDK"
        ws.send_json({"type": "ask", "text": "oi de novo"})
        assert receive_until(ws, "result")[-1]["kind"] == "result"


def test_empty_message_is_ignored(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "ask", "text": "   "})
        ws.send_json({"type": "ask", "text": "oi"})
        assert receive_until(ws, "result")[0]["kind"] == "tool"
