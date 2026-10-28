"""Retomada automática: quando falar (no código), o que falar (modelo falso) e por onde (simulador e WhatsApp)."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agente import retomada, web
from agente.config import EXAMPLE_COMPANY
from agente.crm import Crm
from agente.empresa import load_company
from agente.retomada import FollowupEngine, Policy, is_open, parse_when, reason_hint, wants_opt_out

WED = datetime(2026, 10, 28, 10, 0)  # quarta-feira, 10h: loja aberta


@pytest.fixture
def company():
    return load_company(EXAMPLE_COMPANY)


@pytest.fixture
def crm(tmp_path):
    return Crm(tmp_path / "crm.db")


class Composer:
    """Modelo falso: devolve o texto pedido e guarda o que recebeu."""

    def __init__(self, reply="Oi Ana! Ficou alguma dúvida sobre os pneus do Onix?"):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system, prompt):
        self.calls.append((system, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class Outbox:
    def __init__(self, ok=True):
        self.sent: list[tuple[str, str]] = []
        self.templates: list[tuple[str, str, list]] = []
        self.ok = ok

    async def send(self, phone, text):
        self.sent.append((phone, text))
        return self.ok

    async def template(self, phone, name, params):
        self.templates.append((phone, name, params))
        return True


def engine(crm, company, composer=None, outbox=None, policy=None):
    outbox = outbox or Outbox()
    eng = FollowupEngine(crm, company, composer or Composer(), outbox.send, outbox.template, policy=policy)
    eng.outbox = outbox
    return eng


def lead(crm, phone="5519900000001", stage="orcamento", at=WED, customer="Quanto fica 4 pneus pro Onix?"):
    crm.ensure(phone, "whatsapp", opt_in=True)
    crm.update(phone, stage=stage, name="Ana Souza", subject="Onix 2019", interest="4 pneus")
    crm.log(phone, "entrada", customer, ts=at)
    crm.log(phone, "saida", "Os 4 pneus ficam R$ 1.556,00. Quer agendar?", ts=at + timedelta(minutes=1))
    return phone


def tick(eng, now):
    return asyncio.run(eng.tick(now))


# --- regras puras ---------------------------------------------------------------

@pytest.mark.parametrize("text", ["PARAR", "pare.", "Sair", "não quero mais mensagens", "para de me mandar isso",
                                  "me tira da lista"])
def test_opt_out_detected(text):
    assert wants_opt_out(text)


@pytest.mark.parametrize("text", ["vou parar o carro aí amanhã", "quero parar de ouvir esse barulho", "pare de fazer barulho o freio"])
def test_opt_out_not_confused(text):
    assert not wants_opt_out(text)


@pytest.mark.parametrize("texts,reason", [
    (["achei caro"], "achou caro"),
    (["ta puxado pra mim"], "achou caro"),
    (["vou ver em outra oficina"], "comparando preços"),
    (["vou pensar e te falo"], "vai pensar"),
    (["agora tô sem tempo"], "sem tempo agora"),
    (["ok obrigado"], ""),
])
def test_reason_hint(texts, reason):
    assert reason_hint(texts) == reason


@pytest.mark.parametrize("text,expected", [
    ("amanhã às 15h", datetime(2026, 10, 29, 15, 0)),
    ("segunda de manhã", datetime(2026, 11, 2, 9, 0)),
    ("quarta à tarde", datetime(2026, 11, 4, 14, 0)),  # hoje é quarta: a próxima
    ("05/11 10:00", datetime(2026, 11, 5, 10, 0)),
    ("2026-11-03 09:30", datetime(2026, 11, 3, 9, 30)),
    ("às 16h", datetime(2026, 10, 28, 16, 0)),
    ("as 8h", datetime(2026, 10, 29, 8, 0)),  # já passou hoje: amanhã
    ("depois de amanhã", datetime(2026, 10, 30, 9, 0)),
    ("sexta 14h30", datetime(2026, 10, 30, 14, 30)),
    ("quando der", None),
    ("31/02", None),
])
def test_parse_when(text, expected):
    assert parse_when(text, WED) == expected


@pytest.mark.parametrize("when,open_", [
    (WED, True), (WED.replace(hour=19), False), (WED.replace(hour=7, minute=59), False),
    (datetime(2026, 10, 31, 12, 0), True),  # sábado até 13h
    (datetime(2026, 10, 31, 14, 0), False), (datetime(2026, 11, 1, 10, 0), False),  # domingo fechado
])
def test_business_hours(company, when, open_):
    assert is_open(company, when) is open_


def test_policy_from_company(company):
    p = Policy.from_company(company)
    assert p.active and p.delays_h == (4, 22) and "orcamento" in p.stages and p.lost_after_h == 48
    bad = replace(company, rules={**company.rules, "retomada": {"tentativas_horas": [4, 30]}})
    with pytest.raises(ValueError, match="24 horas"):
        Policy.from_company(bad)


# --- quando retomar -------------------------------------------------------------------

def test_full_cycle_two_attempts_then_lost(crm, company):
    phone = lead(crm)
    eng = engine(crm, company)
    assert tick(eng, WED + timedelta(hours=3)) == []  # ainda cedo
    [first] = tick(eng, WED + timedelta(hours=4))
    assert first.sent and first.kind == "retomada" and eng.outbox.sent[-1][0] == phone
    assert tick(eng, WED + timedelta(hours=5)) == []  # não repete
    [second] = tick(eng, WED + timedelta(hours=22))  # quinta 8h
    assert "PARAR" in second.text  # última tentativa ensina a sair
    assert crm.silence(phone).attempts == 2
    assert tick(eng, WED + timedelta(hours=40)) == []
    [lost] = tick(eng, WED + timedelta(hours=22 + 48))
    assert lost.kind == "perdido" and crm.get(phone).stage == "perdido"
    assert len(eng.outbox.sent) == 2
    assert tick(eng, WED + timedelta(hours=200)) == []  # perdido não recebe mais nada


def test_customer_reply_resets_attempts(crm, company):
    phone = lead(crm)
    eng = engine(crm, company)
    tick(eng, WED + timedelta(hours=4))
    crm.log(phone, "entrada", "oi, ainda quero", ts=WED + timedelta(hours=4, minutes=10))
    thursday = datetime(2026, 10, 29, 8, 0)  # 4 h depois cai às 18h10 (fechado): vai na abertura seguinte
    assert tick(eng, thursday) == []  # quem deve resposta agora é a empresa
    crm.log(phone, "saida", "Ótimo! Qual dia fica bom?", ts=WED + timedelta(hours=4, minutes=11))
    assert crm.silence(phone).attempts == 0
    [again] = tick(eng, thursday)
    assert again.sent


@pytest.mark.parametrize("change", ["opt_out", "novo", "ganho", "sem_opt_in"])
def test_who_never_gets_follow_up(crm, company, change):
    phone = lead(crm)
    if change == "opt_out":
        crm.set_opt_out(phone)
    elif change == "sem_opt_in":
        crm.ensure("5519900000002", "importado")  # contato que nunca falou com a empresa
        crm.log("5519900000002", "saida", "oi", ts=WED)
        crm.delete(phone)
    else:
        crm.update(phone, stage=change)
    eng = engine(crm, company)
    assert tick(eng, WED + timedelta(hours=4)) == [] and eng.outbox.sent == []


def test_waits_for_business_hours_inside_window(crm, company):
    phone = lead(crm, at=WED.replace(hour=16))  # +4h = 20h, loja fechada
    eng = engine(crm, company)
    assert tick(eng, WED.replace(hour=20)) == []
    [out] = tick(eng, datetime(2026, 10, 29, 8, 0))  # quinta 8h, ainda dentro das 24 h
    assert out.sent and out.phone == phone


def test_window_closed_over_weekend_never_sends(crm, company):
    phone = lead(crm, at=datetime(2026, 10, 31, 12, 30))  # sábado 12h30; +4h fechado; domingo fechado
    eng = engine(crm, company)
    assert tick(eng, datetime(2026, 10, 31, 16, 30)) == []
    assert tick(eng, datetime(2026, 11, 2, 8, 0)) == []  # segunda: passou das 24 h, texto livre proibido
    assert eng.outbox.sent == []
    [lost] = tick(eng, datetime(2026, 11, 2, 12, 31))  # 48 h depois da última mensagem do cliente
    assert lost.kind == "perdido" and crm.get(phone).stage == "perdido"


def test_paused_or_inactive_does_nothing(crm, company):
    lead(crm)
    eng = engine(crm, company)
    eng.paused = True
    assert tick(eng, WED + timedelta(hours=4)) == []
    off = engine(crm, company, policy=Policy(active=False))
    assert tick(off, WED + timedelta(hours=4)) == []


def test_undelivered_is_not_counted(crm, company):
    phone = lead(crm)
    eng = engine(crm, company, outbox=Outbox(ok=False))
    [out] = tick(eng, WED + timedelta(hours=4))
    assert not out.sent and crm.silence(phone).attempts == 0


# --- o que dizer ------------------------------------------------------------------------

def test_prompt_has_context_and_reason(crm, company):
    lead(crm, customer="Achei caro, vou pensar")
    composer = Composer()
    eng = engine(crm, company, composer)
    [out] = tick(eng, WED + timedelta(hours=4))
    system, prompt = composer.calls[0]
    assert "Léo" in system and "não ofereça desconto" in system
    assert "Ana Souza" in prompt and "Onix 2019" in prompt and "achou caro" in prompt
    assert "<conversa>" in prompt and "Cliente: Achei caro, vou pensar" in prompt
    assert out.text == composer.reply and out.note == "achou caro"
    assert any("motivo provável: achou caro" in i.text for i in crm.interactions(out.phone))


@pytest.mark.parametrize("reply", [
    "Oi Ana! Consigo te dar 20% de desconto nos pneus, fechado?",
    "Oi Ana, os pneus agora saem por R$ 999,00!",
    "Oi Ana, seu horário está confirmado para amanhã.",
    "",
    RuntimeError("cota do modelo acabou"),
])
def test_bad_or_failed_model_uses_ready_message(crm, company, reply):
    lead(crm)
    eng = engine(crm, company, Composer(reply))
    [out] = tick(eng, WED + timedelta(hours=4))
    assert out.sent and out.text.startswith("Oi Ana! Aqui é Léo, do Auto Center Rota Certa.")
    assert "desconto" not in out.text and "999" not in out.text


def test_model_may_repeat_values_already_said(crm, company):
    lead(crm)
    eng = engine(crm, company, Composer("Oi Ana! Os 4 pneus ficam R$ 1.556,00, montagem inclusa. Alguma dúvida?"))
    [out] = tick(eng, WED + timedelta(hours=4))
    assert "R$ 1.556,00" in out.text


# --- retornos combinados -------------------------------------------------------------------

def test_agreed_callback_inside_window(crm, company):
    phone = lead(crm)
    crm.add_followup(phone, "hoje às 15h", "confirmar os pneus", due_at=WED.replace(hour=15))
    eng = engine(crm, company)
    assert [o.kind for o in tick(eng, WED.replace(hour=14, minute=59)) if o.kind == "retorno"] == []
    outs = tick(eng, WED.replace(hour=15))
    assert [o.kind for o in outs if o.sent] == ["retorno"]
    assert crm.followups(phone) == [] and crm.followups(phone, status="feito")
    assert "confirmar os pneus" in eng.composer.calls[-1][1]


def test_agreed_callback_outside_window_goes_to_team(crm, company):
    phone = lead(crm)
    crm.add_followup(phone, "segunda", "orçamento", due_at=datetime(2026, 11, 2, 9, 0))
    eng = engine(crm, company)
    outs = tick(eng, datetime(2026, 11, 2, 9, 0))
    assert [(o.kind, o.note) for o in outs if o.kind == "retorno"] == [("retorno", "para a equipe")]
    assert crm.followups(phone, status="equipe") and eng.outbox.sent == [] or all(
        "segunda" not in t for _, t in eng.outbox.sent)


def test_agreed_callback_outside_window_with_template(crm, company):
    phone = lead(crm)
    crm.add_followup(phone, "segunda", "orçamento", due_at=datetime(2026, 11, 2, 9, 0))
    policy = replace(Policy.from_company(company), template="retomada_orcamento")
    eng = engine(crm, company, policy=policy)
    tick(eng, datetime(2026, 11, 2, 9, 0))
    assert eng.outbox.templates == [(phone, "retomada_orcamento", ["Ana"])]
    assert crm.followups(phone, status="feito")


# --- atendente: PARAR e retorno com data ----------------------------------------------------

def test_attendant_handles_opt_out_without_model(cfg, crm, company):
    from agente.atendente import Attendant

    agent = Attendant(cfg, "5519900000009", company=company, crm=crm)

    async def run():
        return [e async for e in agent.ask("PARAR")]  # sem start(): se chamasse o modelo, quebraria

    events = asyncio.run(run())
    assert events[0].text == agent.opt_out_reply and events[-1].kind == "result"
    assert crm.get("5519900000009").opt_out
    assert [i.direction for i in crm.interactions("5519900000009")] == ["entrada", "evento", "saida"]


def test_follow_up_tool_understands_the_date(cfg, crm, company):
    from agente.atendente import Attendant

    agent = Attendant(cfg, "5519900000009", company=company, crm=crm)
    tool = next(t for t in agent.tools if t.name == "agendar_retorno")
    out = asyncio.run(tool.handler({"quando": "amanhã às 10h", "motivo": "fechar pneus"}))
    assert "O sistema chama o cliente" in out["content"][0]["text"]
    [f] = crm.followups("5519900000009")
    assert f.due_at and datetime.fromisoformat(f.due_at).hour in range(24)
    out = asyncio.run(tool.handler({"quando": "quando der", "motivo": "x"}))
    assert "A equipe entra em contato" in out["content"][0]["text"]


# --- simulador ------------------------------------------------------------------------------

ORIGIN = {"origin": "http://127.0.0.1:8000"}


@pytest.fixture
def sim(monkeypatch, cfg, crm, company):
    monkeypatch.setattr(web, "crm", crm)
    eng = FollowupEngine(crm, company, Composer("Oi! Ficou alguma dúvida sobre os pneus?"), web.send_to_customer)
    monkeypatch.setattr(web, "followups", eng)
    monkeypatch.setattr(web, "simulated", {})
    return TestClient(web.app, base_url="http://127.0.0.1:8000")


def test_simulator_follow_up_button(sim, crm):
    phone = lead(crm, phone="sim-abc")
    assert sim.post(f"/api/simulador/retomar/{phone}").status_code == 403  # sem a origem da página
    out = sim.post(f"/api/simulador/retomar/{phone}", headers=ORIGIN).json()
    assert out == {"sent": True, "text": "Oi! Ficou alguma dúvida sobre os pneus?", "attempt": 1, "of": 2, "note": ""}
    assert sim.post(f"/api/simulador/retomar/{phone}", headers=ORIGIN).json()["attempt"] == 2
    assert sim.post(f"/api/simulador/retomar/{phone}", headers=ORIGIN).json()["attempt"] == 2  # não passa do máximo
    assert sim.post("/api/simulador/retomar/5519900000001", headers=ORIGIN).status_code == 404  # só simulados
    crm.set_opt_out(phone)
    assert sim.post(f"/api/simulador/retomar/{phone}", headers=ORIGIN).json()["sent"] is False


def test_simulator_receives_follow_up_live(sim, crm):
    phone = lead(crm, phone="sim-abc")
    asyncio.run(web.send_to_customer(phone, "teste"))  # sem aba aberta: só registra
    headers = {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}

    class Quiet(web.Attendant):
        async def start(self):
            pass

        async def stop(self):
            pass

    web_attendant = web.Attendant
    web.Attendant = Quiet
    try:
        with sim.websocket_connect("/ws/simulador?telefone=sim-abc", headers=headers) as ws:
            history = ws.receive_json()
            assert history["kind"] == "history"
            assert [i["kind"] for i in history["items"]] == ["user", "text"]
            assert ws.receive_json()["kind"] == "ready"
            ws.receive_json()  # ficha do lead
            assert asyncio.run(web.send_to_customer(phone, "Oi, ainda precisa dos pneus?"))
            assert ws.receive_json() == {"kind": "retomada", "text": "Oi, ainda precisa dos pneus?"}
    finally:
        web.Attendant = web_attendant


def test_whatsapp_send_needs_customer_routing(monkeypatch):
    monkeypatch.setattr(web, "whatsapp", None)
    assert asyncio.run(web.send_to_customer("5519900000001", "oi")) is False
