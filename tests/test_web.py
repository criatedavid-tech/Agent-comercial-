"""Interface web: status, trava de origem, conversa e pedido de ajuda humana pelo WebSocket."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agente import web
from agente.core import Event
from agente.history import History
from agente.human import HumanBridge
from agente.scheduler import AgendaStore, Task

# O TestClient manda host "testserver" no WebSocket; o navegador manda o host real.
ORIGIN = {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}


class FakeAgent:
    """Agente falso: não chama a API. Pede ajuda humana quando o pedido fala em 'captcha'."""

    instances: list["FakeAgent"] = []
    to_deliver = None  # item da agenda entregue no meio de um pedido (simula o agendador)

    def __init__(self, cfg, resume=None):
        self.human = HumanBridge(0.05)
        self.session_id = resume or "sessao-nova"
        self.started = self.stopped = False
        self.resets = 0
        self.rewinds: list[str] = []
        FakeAgent.instances.append(self)

    async def resume(self, session_id):
        if session_id == "sumiu":  # o Claude Code não tem mais o registro desta conversa
            self.session_id = "sessao-nova"
            return False
        self.session_id = session_id
        return True

    async def rewind(self, checkpoint):
        if checkpoint == "invalido":
            raise ValueError("checkpoint desconhecido")
        self.rewinds.append(checkpoint)

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
        if "entrega" in text:
            await web.deliver(FakeAgent.to_deliver)
        if "quebra" in text:
            raise RuntimeError("falha no SDK")
        yield Event("result", "ok · 1 passos · US$ 0.0000")


@pytest.fixture
def store(tmp_path, monkeypatch) -> AgendaStore:
    s = AgendaStore(tmp_path / "agenda.db", "America/Sao_Paulo")
    monkeypatch.setattr(web, "agenda", s)
    monkeypatch.setattr(web, "hub", web.Hub())
    monkeypatch.setattr(web, "history", History(tmp_path / "conversas.db"))
    return s


@pytest.fixture
def client(monkeypatch, store):
    FakeAgent.instances.clear()
    monkeypatch.setattr(web, "Agent", FakeAgent)
    return TestClient(web.app, base_url="http://127.0.0.1:8000")


def add_task(store, **kw):
    return store.add(Task(**{"id": "t", "title": "Resumo do dia", "prompt": "x", "kind": "diaria", "at": "07:00", **kw}))


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
        assert {"kind": "text", "text": "Recebi: resolvido", "session": "sessao-nova"} in events


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


# --- agenda --------------------------------------------------------------------

def test_agenda_endpoint(client, store):
    add_task(store, id="gastos", title="Revisar gastos", kind="semanal", weekdays="seg", at="09:00")
    [item] = client.get("/api/agenda").json()
    assert item["id"] == "gastos" and item["when"] == "toda semana (seg) às 09:00"


def test_unread_results_arrive_when_tab_opens(client, store):
    item = store.add_inbox(add_task(store), "Hoje: dentista às 15h.")
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        assert ws.receive_json()["kind"] == "ready"
        event = ws.receive_json()
        assert event["kind"] == "proactive" and event["title"] == "Resumo do dia"
        assert event["text"] == "Hoje: dentista às 15h." and event["id"] == item.id
    assert store.unread() == []


def test_results_stay_unread_without_open_tabs(store):
    item = store.add_inbox(add_task(store), "texto")
    asyncio.run(web.deliver(item))
    assert [i.id for i in store.unread()] == [item.id]


def test_results_go_to_open_tabs(client, store):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        FakeAgent.to_deliver = store.add_inbox(add_task(store), "pronto")
        ws.send_json({"type": "ask", "text": "entrega"})
        events = receive_until(ws, "result")
        assert {"kind": "proactive", "text": "pronto"}.items() <= next(e for e in events if e["kind"] == "proactive").items()
    assert store.unread() == []


def test_help_reply_reaches_scheduled_agent(client, store):
    bridge = HumanBridge(1)
    web.hub.bridges.add(bridge)
    answers = []
    bridge.answer = lambda request_id, text: answers.append((request_id, text))
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "help_reply", "id": "abc", "text": "resolvido"})
        ws.send_json({"type": "ask", "text": "oi"})  # garante que a resposta anterior foi processada
        receive_until(ws, "result")
    assert answers == [("abc", "resolvido")]


# --- conversas, retomar e desfazer ------------------------------------------------

def seed_history():
    web.history.record("antiga", "user", "Quanto gastei em outubro?")
    web.history.record("antiga", "tool", "buscar_conhecimento gastos")
    web.history.record("antiga", "checkpoint", "uuid-1")
    web.history.record("antiga", "text", "R$ 1.820.")
    web.history.record("antiga", "rewind", "uuid-1")  # interno: não volta para a página
    web.history.record("antiga", "result", "ok · 2 passos · US$ 0.0100", cost_usd=0.01)


def test_conversation_list_and_detail(client):
    seed_history()
    [conv] = client.get("/api/conversas").json()
    assert conv["id"] == "antiga" and conv["title"] == "Quanto gastei em outubro?" and conv["requests"] == 1
    detail = client.get("/api/conversas/antiga").json()
    assert [i["kind"] for i in detail["items"]] == ["user", "tool", "checkpoint", "text", "result"]
    assert client.get("/api/conversas/nao-existe").status_code == 404


def test_resume_by_url_sends_history_first(client):
    seed_history()
    with client.websocket_connect("/ws?sessao=antiga", headers=ORIGIN) as ws:
        first = ws.receive_json()
        assert first["kind"] == "history" and first["items"][0]["text"] == "Quanto gastei em outubro?"
        assert ws.receive_json() == {"kind": "ready", "text": "", "session": "antiga"}
    assert FakeAgent.instances[0].session_id == "antiga"


def test_resume_and_undo_messages(client):
    seed_history()
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "resume", "session": "antiga"})
        assert ws.receive_json()["kind"] == "history"
        assert ws.receive_json()["text"] == "conversa retomada"

        ws.send_json({"type": "undo", "checkpoint": "uuid-1"})
        assert ws.receive_json()["text"] == "edições de arquivo desfeitas"
        ws.send_json({"type": "undo", "checkpoint": "invalido"})
        assert ws.receive_json() == {"kind": "error", "text": "ValueError: checkpoint desconhecido"}
    assert FakeAgent.instances[0].rewinds == ["uuid-1"]


def test_events_carry_session_id(client):
    with client.websocket_connect("/ws", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_json({"type": "ask", "text": "oi"})
        assert all(e["session"] == "sessao-nova" for e in receive_until(ws, "result"))


@pytest.mark.parametrize("host", ["evil.com", "evil.com:8000", "192.168.0.10:8000"])
def test_http_rejects_non_local_host(client, host):
    # DNS rebinding: o domínio do atacante aponta para 127.0.0.1, mas o Host continua sendo o dele.
    assert client.get("/api/conversas", headers={"host": host}).status_code == 403


def test_http_accepts_localhost(client):
    assert client.get("/api/status", headers={"host": "localhost:8000"}).status_code == 200


# --- painel ------------------------------------------------------------------------

@pytest.fixture
def kb(tmp_path, monkeypatch):
    from agente.knowledge import KnowledgeBase

    k = KnowledgeBase(tmp_path / "conhecimento")
    monkeypatch.setattr(web, "knowledge", k)
    return k


def test_panel_page_and_data(client, store, kb):
    assert "Painel do agente" in client.get("/painel").text
    seed_history()
    web.history.record("antiga", "blocked", "comando bloqueado (formatar disco)")
    kb.save("estudos", "Decorators", "...", nicho="python")
    add_task(store, id="gastos", title="Revisar gastos", kind="semanal", weekdays="seg", at="09:00")

    p = client.get("/api/painel").json()
    assert len(p["costs"]) == 30 and p["costs"][-1]["cost_usd"] == 0.01
    assert p["totals"]["today"] == 0.01 and p["totals"]["requests_month"] == 1
    assert p["conversations"][0]["id"] == "antiga"
    assert [a["id"] for a in p["agenda"]] == ["gastos"]
    assert p["blocked"][0]["reason"] == "comando bloqueado (formatar disco)"
    assert p["knowledge"]["counts"]["estudos"] == 1
    assert p["knowledge"]["recent"][0] == {"area": "estudos", "nicho": "python", "title": "Decorators",
                                          "path": p["knowledge"]["recent"][0]["path"]}


def test_cancel_task_from_panel(client, store):
    add_task(store, id="gastos")
    local = {"origin": "http://127.0.0.1:8000"}
    assert client.delete("/api/agenda/gastos", headers={"origin": "http://evil.com"}).status_code == 403
    assert client.delete("/api/agenda/gastos").status_code == 403  # sem Origin também não
    assert client.delete("/api/agenda/gastos", headers=local).json() == {"cancelled": "gastos"}
    assert client.delete("/api/agenda/gastos", headers=local).status_code == 404
    assert store.list() == []


def test_resume_of_missing_session_shows_history_and_starts_fresh(client):
    web.history.record("sumiu", "user", "conversa antiga")
    with client.websocket_connect("/ws?sessao=sumiu", headers=ORIGIN) as ws:
        assert ws.receive_json()["items"][0]["text"] == "conversa antiga"
        ready = ws.receive_json()
        assert ready["kind"] == "ready" and "não deu para retomar" in ready["text"]
        assert ready["session"] == "sessao-nova"
