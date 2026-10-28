"""Passagem para a equipe: o cliente chama uma pessoa, a equipe assume (WhatsApp ou painel), conversa e devolve."""

import asyncio
import dataclasses
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agente import web
from agente.atendente import Attendant
from agente.config import EXAMPLE_COMPANY
from agente.crm import Crm
from agente.empresa import load_company
from agente.history import History
from agente.passagem import PANEL, Desk, wants_human
from agente.retomada import FollowupEngine
from agente.whatsapp import Incoming, WhatsAppChannel

CUSTOMER = "5519988887777"
RAFAEL = "5519999990001"  # da equipe (empresa.toml) e permitido no WhatsApp
OPEN = datetime(2026, 10, 28, 10, 0)  # quarta, 10h: loja aberta
CLOSED = datetime(2026, 10, 28, 21, 0)


class Outbox:
    """Avisos para a equipe, para quem assumiu e para o cliente."""

    def __init__(self):
        self.team: list[tuple[str, str]] = []
        self.member: list[tuple[str, str]] = []
        self.customer: list[tuple[str, str]] = []
        self.deliver = True

    async def to_team(self, title, text):
        self.team.append((title, text))

    async def to_member(self, member, text):
        self.member.append((member, text))

    async def to_customer(self, phone, text):
        self.customer.append((phone, text))
        return self.deliver


@pytest.fixture
def company():
    return load_company(EXAMPLE_COMPANY)


@pytest.fixture
def crm(cfg):
    return Crm(cfg.crm_db)


@pytest.fixture
def out():
    return Outbox()


@pytest.fixture
def desk(crm, company, out):
    return Desk(crm, company, out.to_team, out.to_member, out.to_customer, local_now=lambda: OPEN)


@pytest.fixture
def agent(cfg, company, crm, desk):
    return Attendant(cfg, CUSTOMER, company=company, crm=crm, desk=desk)


def ask(agent, text):
    async def collect():
        return [e async for e in agent.ask(text)]
    return asyncio.run(collect())


def texts(events):
    return [e.text for e in events if e.kind == "text"]


@pytest.mark.parametrize("text", [
    "quero falar com um atendente", "Tem alguém de verdade aí?", "me passa pra um humano", "pode chamar o vendedor?",
    "não quero falar com robô", "Quero falar com uma pessoa", "atendimento humano por favor", "falar com o gerente",
])
def test_wants_human(text):
    assert wants_human(text)


@pytest.mark.parametrize("text", ["Você é um robô?", "quanto custa o alinhamento", "a pessoa que me atendeu foi ótima",
                                  "o vendedor me falou de 4 pneus"])
def test_not_a_request_for_a_human(text):
    assert not wants_human(text)


# --- cliente ----------------------------------------------------------------------------

def test_asking_for_a_person_calls_the_team_without_the_model(agent, crm, out):
    crm.update(CUSTOMER, name="Ana", subject="Onix 2019")
    agent.client = None  # se o modelo fosse chamado, quebraria
    events = ask(agent, "quero falar com um atendente")
    [reply] = texts(events)
    assert "Já chamei a equipe do Auto Center Rota Certa" in reply and "Rafael" in reply
    contact = crm.get(CUSTOMER)
    assert contact.handoff == "aguardando" and "pessoa" in contact.handoff_reason
    [(title, briefing)] = out.team
    assert f"#{contact.ticket}" in title
    assert "Onix 2019" in briefing and "Cliente: quero falar com um atendente" in briefing
    assert f"ASSUMIR {contact.ticket}" in briefing


def test_outside_business_hours_says_when_the_team_answers(cfg, company, crm, out):
    desk = Desk(crm, company, out.to_team, local_now=lambda: CLOSED)
    agent = Attendant(cfg, CUSTOMER, company=company, crm=crm, desk=desk)
    [reply] = texts(ask(agent, "quero falar com uma pessoa"))
    assert "fora do horário" in reply and "08:00" in reply


def test_assistant_stays_quiet_and_forwards_while_waiting(agent, crm, out):
    ask(agent, "quero falar com um atendente")
    events = ask(agent, "é sobre o orçamento dos pneus")
    assert texts(events) == [] and "com a equipe" in events[-1].text
    assert "💬" in out.team[-1][1] and "orçamento dos pneus" in out.team[-1][1]
    assert crm.interactions(CUSTOMER)[-1].text == "é sobre o orçamento dos pneus"  # fica no CRM


def test_nobody_took_it_the_assistant_answers_again(desk, crm):
    crm.ensure(CUSTOMER, opt_in=True)
    crm.set_handoff(CUSTOMER, "aguardando", "negociação")
    contact = crm.get(CUSTOMER)
    called = datetime.fromisoformat(contact.handoff_at)
    assert desk.silent(contact, called + timedelta(minutes=14))
    assert not desk.silent(contact, called + timedelta(minutes=16))  # espera_equipe_min = 15
    crm.set_handoff(CUSTOMER, "humano", assignee=RAFAEL)
    assert desk.silent(crm.get(CUSTOMER), called + timedelta(days=2))  # com alguém, não volta sozinho


def test_tool_calls_the_team_and_tells_the_model_what_to_say(agent, crm, out):
    tool = next(t for t in agent.tools if t.name == "chamar_vendedor")
    assert set(tool.input_schema["properties"]) == {"motivo"}  # sem telefone: só o cliente desta conversa
    reply = asyncio.run(tool.handler({"motivo": "quer desconto nos 4 pneus"}))["content"][0]["text"]
    assert "equipe avisada" in reply and "Já chamei a equipe" in reply
    assert crm.get(CUSTOMER).handoff_reason == "quer desconto nos 4 pneus" and out.team


def test_attendant_cannot_take_or_release(crm):
    crm.ensure(CUSTOMER)
    with pytest.raises(ValueError):
        crm.view(CUSTOMER).set_handoff("humano")
    with pytest.raises(ValueError):
        crm.view(CUSTOMER).set_handoff("")


# --- equipe -------------------------------------------------------------------------------

def test_take_reply_and_release(agent, desk, crm, out):
    ask(agent, "quero falar com um atendente")
    contact = crm.get(CUSTOMER)
    briefing = asyncio.run(desk.take(contact, RAFAEL))
    assert "Motivo:" in briefing
    contact = crm.get(CUSTOMER)
    assert (contact.handoff, contact.assignee) == ("humano", RAFAEL)
    ask(agent, "oi, tudo bem?")
    assert out.member[-1] == (RAFAEL, f"💬 #{contact.ticket} {CUSTOMER}: oi, tudo bem?")  # vai só para quem assumiu
    assert asyncio.run(desk.reply(contact, "Oi! Aqui é o Rafael, consigo 5% à vista.", RAFAEL))
    assert out.customer[-1] == (CUSTOMER, "Oi! Aqui é o Rafael, consigo 5% à vista.")
    assert crm.interactions(CUSTOMER)[-1].direction == "humano"
    desk.release(crm.get(CUSTOMER), RAFAEL)
    assert crm.get(CUSTOMER).handoff == "" and "Rafael devolveu" in crm.interactions(CUSTOMER)[-1].text


def test_failed_delivery_is_not_logged(desk, crm, out):
    crm.ensure(CUSTOMER)
    crm.set_handoff(CUSTOMER, "humano", assignee=PANEL)
    out.deliver = False
    assert not asyncio.run(desk.reply(crm.get(CUSTOMER), "oi", PANEL))
    assert all(i.direction != "humano" for i in crm.interactions(CUSTOMER))


def test_followups_leave_handed_off_contacts_alone(crm, company):
    crm.ensure(CUSTOMER, opt_in=True)
    crm.update(CUSTOMER, stage="orcamento")
    crm.log(CUSTOMER, "entrada", "quanto fica?", ts=datetime.now() - timedelta(hours=6))
    crm.log(CUSTOMER, "saida", "R$ 1.200", ts=datetime.now() - timedelta(hours=6))
    engine = FollowupEngine(crm, company, None, None)
    assert engine.due(datetime.now())  # sem a equipe: retomaria
    crm.set_handoff(CUSTOMER, "humano", assignee=RAFAEL)
    assert engine.due(datetime.now()) == []


# --- WhatsApp da equipe -------------------------------------------------------------------------

class FakeApi:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to, text):
        self.sent.append((to, text))

    async def mark_read(self, message_id):
        pass


class Operator:
    def __init__(self, cfg, resume=None):
        raise AssertionError("mensagem da passagem não pode ir para o operador")


def team_channel(cfg, tmp_path, desk):
    wcfg = dataclasses.replace(cfg, whatsapp_token="t", whatsapp_phone_id="1", whatsapp_verify_token="v",
                               whatsapp_app_secret="s", whatsapp_allowed=(RAFAEL,))
    channel = WhatsAppChannel(wcfg, FakeApi(), History(tmp_path / "c.db"), Operator)
    channel.desk = desk
    return channel


def team_says(channel, *messages):
    async def main():
        for i, text in enumerate(messages):
            await channel.handle(Incoming(f"m{i}{text}", RAFAEL, "text", text))
    asyncio.run(main())
    return [text for _, text in channel.api.sent]


def test_team_takes_talks_and_returns_by_whatsapp(cfg, tmp_path, agent, desk, crm, out):
    ask(agent, "quero falar com um atendente")
    ticket = crm.get(CUSTOMER).ticket
    channel = team_channel(cfg, tmp_path, desk)
    replies = team_says(channel, "fila", f"ASSUMIR {ticket}", "Oi, aqui é o Rafael!", "devolver")
    assert f"#{ticket}" in replies[0] and "aguardando" in replies[0]
    assert replies[1].startswith(f"✅ Você assumiu #{ticket}") and "DEVOLVER" in replies[1]
    assert out.customer == [(CUSTOMER, "Oi, aqui é o Rafael!")]  # foi para o cliente, não para o operador
    assert replies[-1].startswith(f"↩ #{ticket} devolvido")
    assert crm.get(CUSTOMER).handoff == ""


def test_assumir_without_number_takes_the_only_one_waiting(cfg, tmp_path, agent, desk, crm):
    ask(agent, "quero falar com um atendente")
    replies = team_says(team_channel(cfg, tmp_path, desk), "assumir")
    assert replies[0].startswith("✅") and crm.get(CUSTOMER).assignee == RAFAEL


def test_unknown_ticket_and_stale_conversation(cfg, tmp_path, agent, desk, crm):
    channel = team_channel(cfg, tmp_path, desk)
    assert "Não achei" in team_says(channel, "ASSUMIR 999")[0]
    ask(agent, "quero falar com um atendente")
    team_says(channel, f"assumir {crm.get(CUSTOMER).ticket}")
    desk.release(crm.get(CUSTOMER), PANEL)  # alguém devolveu pelo painel
    assert "não está mais com você" in team_says(channel, "ainda está aí?")[-1]


# --- painel (/atendimento) ------------------------------------------------------------------------

LOCAL = {"origin": "http://127.0.0.1:8000"}


@pytest.fixture
def panel(monkeypatch, crm, company):
    monkeypatch.setattr(web, "crm", crm)
    monkeypatch.setattr(web, "simulated", {})
    monkeypatch.setattr(web, "hub", web.Hub())
    d = Desk(crm, company, local_now=lambda: OPEN,
             to_customer=lambda phone, text: web.send_to_customer(phone, text, kind="humano"))
    monkeypatch.setattr(web, "desk", d)
    return TestClient(web.app, base_url="http://127.0.0.1:8000")


def test_panel_queue_take_reply_release(panel, crm):
    phone = "sim-ana"
    crm.ensure(phone, "simulador", opt_in=True)
    crm.set_handoff(phone, "aguardando", "quer negociar")
    [item] = panel.get("/api/atendimento").json()
    assert item["phone"] == phone and item["handoff"] == "aguardando" and item["ticket"] >= 1
    assert panel.post(f"/api/atendimento/{phone}/assumir").status_code == 403  # sem Origin da página
    assert panel.post(f"/api/atendimento/{phone}/assumir", headers=LOCAL).status_code == 200
    assert panel.get("/api/atendimento").json()[0]["member"] == "painel"
    assert panel.post(f"/api/atendimento/{phone}/responder", json={"text": "Oi Ana!"}, headers=LOCAL).status_code == 200
    conversation = panel.get(f"/api/atendimento/{phone}").json()
    assert conversation["messages"][-1] == {**conversation["messages"][-1], "direction": "humano", "text": "Oi Ana!"}
    assert panel.post(f"/api/atendimento/{phone}/devolver", headers=LOCAL).status_code == 200
    assert panel.get("/api/atendimento").json() == []
    assert "Atendimento" in panel.get("/atendimento").text


def test_simulator_shows_the_team_reply(panel, crm, cfg, monkeypatch):
    class NoModel(Attendant):
        async def start(self):  # pedir uma pessoa não passa pelo modelo
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(web, "cfg", cfg)
    monkeypatch.setattr(web, "Attendant", NoModel)
    with panel.websocket_connect("/ws/simulador?telefone=bia", headers={"host": "127.0.0.1:8000", **LOCAL}) as ws:
        while ws.receive_json()["kind"] != "lead":
            pass
        ws.send_json({"type": "ask", "text": "quero falar com um atendente"})
        events = []
        while (event := ws.receive_json())["kind"] != "lead":
            events.append(event)
        assert any(e["kind"] == "text" and "Já chamei a equipe" in e["text"] for e in events)
        assert panel.post("/api/atendimento/sim-bia/responder", json={"text": "Oi Bia, sou a Juliana"},
                          headers=LOCAL).status_code == 200
        assert ws.receive_json() == {"kind": "humano", "text": "Oi Bia, sou a Juliana"}
