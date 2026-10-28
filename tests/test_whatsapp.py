"""WhatsApp com mensagens simuladas: nada sai para a Meta (a API é substituída por uma falsa)."""

import asyncio
import dataclasses
from datetime import datetime, timedelta
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agente import web, whatsapp as wa
from agente.core import Event
from agente.history import History
from agente.human import HumanBridge
from agente.whatsapp import (
    CloudApi,
    Incoming,
    WhatsAppChannel,
    WhatsAppError,
    parse_messages,
    split_message,
    to_whatsapp,
    verify_signature,
)

OWNER, OTHER, STRANGER = "5511999990000", "5521988887777", "5531900000000"
SECRET = "segredo-do-app"


@pytest.fixture
def wcfg(cfg):
    return dataclasses.replace(
        cfg, whatsapp_token="tok", whatsapp_phone_id="123", whatsapp_verify_token="verifica",
        whatsapp_app_secret=SECRET, whatsapp_allowed=(OWNER, OTHER),
    )


def payload(sender: str, text: str = "", msg_id: str = "wamid.1", kind: str = "text") -> dict:
    msg = {"from": sender, "id": msg_id, "timestamp": "1790000000", "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": sender, "profile": {"name": "David"}}], "messages": [msg]}}]}]}


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- funções puras --------------------------------------------------------------


def test_signature():
    body = b'{"a":1}'
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body, sign(body, "outro"))
    assert not verify_signature(SECRET, b'{"a":2}', sign(body))  # corpo alterado
    assert not verify_signature(SECRET, body, "")
    assert not verify_signature("", body, sign(body, ""))  # sem App Secret configurado, nada passa


def test_parse_messages():
    [msg] = parse_messages(payload("+55 11 99999-0000", "oi"))
    assert (msg.sender, msg.text, msg.kind, msg.name) == (OWNER, "oi", "text", "David")
    status_only = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.x", "status": "read"}]}}]}]}
    assert parse_messages(status_only) == []
    [audio] = parse_messages(payload(OWNER, kind="audio"))
    assert audio.kind == "audio" and audio.text == ""


def test_markdown_to_whatsapp():
    md = "## Resumo\n**Total:** R$ 10\n- item um\n* item dois\n[site](https://x.com) ~~velho~~"
    assert to_whatsapp(md) == "*Resumo*\n*Total:* R$ 10\n• item um\n• item dois\nsite (https://x.com) ~velho~"


def test_split_long_messages():
    text = "\n\n".join(f"Parágrafo {i} " + "x" * 900 for i in range(10))
    parts = split_message(text, limit=4000)
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)
    assert parts[0].startswith("Parágrafo 0") and parts[1].startswith("Parágrafo")  # quebra entre parágrafos
    assert split_message("curto") == ["curto"]


def test_cloud_api_calls_meta(wcfg):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if json.loads(request.content).get("to") == "+000":
            return httpx.Response(400, json={"error": {"message": "Re-engagement message", "code": 131047}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    api = CloudApi(wcfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def scenario():
        await api.send_text(OWNER, "**oi**")
        await api.mark_read("wamid.1")
        with pytest.raises(WhatsAppError) as err:
            await api.send_text("000", "fora da janela")
        return err.value

    error = asyncio.run(scenario())
    assert str(calls[0].url) == "https://graph.facebook.com/v26.0/123/messages"
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert json.loads(calls[0].content) == {"messaging_product": "whatsapp", "recipient_type": "individual",
                                             "to": "+" + OWNER, "type": "text", "text": {"preview_url": False, "body": "*oi*"}}
    assert json.loads(calls[1].content)["status"] == "read"
    assert error.code == 131047


# --- canal --------------------------------------------------------------------------


class FakeApi:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.read: list[str] = []

    async def send_text(self, to, text):
        self.sent.append((to, text))

    async def mark_read(self, message_id):
        self.read.append(message_id)


class FakeAgent:
    """Responde ecoando; 'demora' espera; 'captcha' pede ajuda humana; 'rm' mostra um bloqueio."""

    def __init__(self, cfg, resume=None):
        self.human = HumanBridge(1)
        self.session_id = None
        self.calls: list[str] = []
        self.resumed = self.interrupted = None
        self.resets = 0

    async def start(self):
        pass

    async def stop(self):
        pass

    async def resume(self, session_id):
        self.resumed = self.session_id = session_id
        return True

    async def reset(self):
        self.resets += 1
        self.session_id = None

    async def interrupt(self):
        self.interrupted = True

    async def ask(self, text):
        self.calls.append(text)
        self.session_id = self.session_id or "sessao-wa"
        if text == "demora":
            await asyncio.sleep(0.3)
        if text == "captcha":
            answer = await self.human.request("Resolva o CAPTCHA da loja", "https://loja.com")
            yield Event("text", f"Recebi: {answer}. Compra preparada.")
        elif text == "rm":
            yield Event("blocked", "comando bloqueado (apagar a raiz)")
            yield Event("text", "Não consegui apagar.")
        else:
            yield Event("text", "pensando…")
            yield Event("text", f"**Resposta:** {text}")
        yield Event("result", "ok · 1 passos · US$ 0.0000")


async def wait_for(condition, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("tempo esgotado esperando a condição")
        await asyncio.sleep(0.01)


@pytest.fixture
def channel(wcfg, tmp_path):
    paused = []
    ch = WhatsAppChannel(wcfg, FakeApi(), History(tmp_path / "conversas.db"), FakeAgent, on_pause=paused.append)
    ch.paused_calls = paused
    return ch


def msg(text, sender=OWNER, msg_id=None, kind="text"):
    msg.counter = getattr(msg, "counter", 0) + 1
    return Incoming(msg_id or f"wamid.{msg.counter}", sender, kind, text)


def run(channel, scenario):
    async def main():
        try:
            return await scenario()
        finally:
            await channel.close()

    return asyncio.run(main())


def test_answers_with_final_text_only(channel):
    async def scenario():
        await channel.handle(msg("quanto gastei?"))
        await wait_for(lambda: channel.api.sent)

    run(channel, scenario)
    assert channel.api.sent == [(OWNER, "**Resposta:** quanto gastei?")]  # só a resposta final, sem o "pensando…"
    assert channel.api.read  # marcou como lida
    assert channel.history.channel_session(f"whatsapp:{OWNER}") == "sessao-wa"


def test_ignores_strangers_and_duplicates(channel):
    async def scenario():
        await channel.handle(msg("oi", sender=STRANGER))
        repeated = msg("oi")
        await channel.handle(repeated)
        await channel.handle(repeated)  # a Meta reenviou a mesma mensagem
        await wait_for(lambda: channel.api.sent)
        await asyncio.sleep(0.05)

    run(channel, scenario)
    assert channel.api.sent == [(OWNER, "**Resposta:** oi")]
    assert STRANGER not in channel.contacts


def test_each_contact_has_its_own_conversation(channel):
    async def scenario():
        await channel.handle(msg("a", sender=OWNER))
        await channel.handle(msg("b", sender=OTHER))
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    assert channel.contacts[OWNER].agent is not channel.contacts[OTHER].agent
    assert sorted(channel.api.sent) == sorted([(OWNER, "**Resposta:** a"), (OTHER, "**Resposta:** b")])


def test_messages_are_processed_in_order(channel):
    async def scenario():
        await channel.handle(msg("demora"))
        await channel.handle(msg("depois"))
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    assert [t for _, t in channel.api.sent] == ["**Resposta:** demora", "**Resposta:** depois"]


def test_stop_and_continue(channel):
    async def scenario():
        await channel.handle(msg("oi"))
        await wait_for(lambda: channel.api.sent)
        await channel.handle(msg("PARAR"))
        await channel.handle(msg("faz outra coisa"))
        await channel.handle(msg("Continuar!"))
        await channel.handle(msg("agora sim"))
        await wait_for(lambda: len(channel.api.sent) == 5)

    run(channel, scenario)
    texts = [t for _, t in channel.api.sent]
    assert texts[1].startswith("🛑 Parei tudo")
    assert texts[2].startswith("Estou pausado")
    assert texts[3].startswith("▶️ Voltei")
    assert texts[4] == "**Resposta:** agora sim"
    assert channel.contacts[OWNER].agent.interrupted
    assert channel.paused_calls == [True, False]  # a agenda pausou e voltou


def test_new_conversation(channel):
    async def scenario():
        await channel.handle(msg("oi"))
        await wait_for(lambda: channel.api.sent)
        await channel.handle(msg("nova"))
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    assert channel.api.sent[1] == (OWNER, "Conversa nova. 🙂")
    assert channel.contacts[OWNER].agent.resets == 1
    assert channel.history.channel_session(f"whatsapp:{OWNER}") is None


def test_human_help_over_whatsapp(channel):
    async def scenario():
        await channel.handle(msg("captcha"))
        await wait_for(lambda: channel.api.sent)
        await channel.handle(msg("resolvido"))  # a próxima mensagem responde ao pedido
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    question, final = channel.api.sent[0][1], channel.api.sent[1][1]
    assert "Preciso de você" in question and "https://loja.com" in question
    assert final == "Recebi: resolvido. Compra preparada."
    assert channel.contacts[OWNER].agent.calls == ["captcha"]  # "resolvido" não virou pedido novo


def test_blocked_and_non_text(channel):
    async def scenario():
        await channel.handle(msg("rm"))
        await channel.handle(msg("", kind="audio"))
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    texts = dict((t[:12], t) for _, t in channel.api.sent)
    assert any("só leio mensagens de texto" in t for t in texts.values())
    assert any("🛡 Bloqueado pela segurança: comando bloqueado (apagar a raiz)" in t for t in texts.values())


def test_resumes_previous_conversation_after_restart(channel):
    channel.history.set_channel_session(f"whatsapp:{OWNER}", "sessao-antiga")

    async def scenario():
        await channel.handle(msg("continuando"))
        await wait_for(lambda: channel.api.sent)

    run(channel, scenario)
    assert channel.contacts[OWNER].agent.resumed == "sessao-antiga"


def test_working_notice_for_slow_tasks(channel, monkeypatch):
    monkeypatch.setattr(wa, "WORKING_NOTICE_SECONDS", 0.05)

    async def scenario():
        await channel.handle(msg("demora"))
        await wait_for(lambda: len(channel.api.sent) == 2)

    run(channel, scenario)
    assert channel.api.sent[0][1].startswith("⏳") and channel.api.sent[1][1] == "**Resposta:** demora"


def test_schedule_delivery_respects_24h_window(channel):
    async def scenario():
        before = await channel.deliver("Resumo do dia", "nada hoje")  # dono nunca escreveu: janela fechada
        await channel.handle(msg("oi"))
        await wait_for(lambda: channel.api.sent)
        inside = await channel.deliver("Resumo do dia", "dentista às 15h")
        channel.contacts[OWNER].last_inbound = datetime.now() - timedelta(hours=25)
        after = await channel.deliver("Resumo do dia", "x")
        return before, inside, after

    before, inside, after = run(channel, scenario)
    assert (before, inside, after) == (False, True, False)
    assert channel.api.sent[-1] == (OWNER, "⏰ *Resumo do dia*\n\ndentista às 15h")


def test_scheduled_task_help_goes_to_owner(channel):
    bridge = HumanBridge(1)

    async def scenario():
        await channel.handle(msg("oi"))
        await wait_for(lambda: channel.api.sent)

        async def notify(req):
            await channel.help_from_schedule(req, [bridge])

        bridge.notify = notify
        waiting = asyncio.create_task(bridge.request("Login no banco", ""))
        await wait_for(lambda: len(channel.api.sent) == 2)
        await channel.handle(msg("código 4321"))
        return await waiting

    assert run(channel, scenario) == "código 4321"


# --- webhook no servidor web ------------------------------------------------------------


@pytest.fixture
def server(monkeypatch, wcfg, tmp_path):
    received = []

    class Recorder:
        async def handle(self, m):
            received.append(m)

    monkeypatch.setattr(web, "cfg", wcfg)
    monkeypatch.setattr(web, "whatsapp", Recorder())
    client = TestClient(web.app, base_url="http://127.0.0.1:8000")
    client.received = received
    return client


def test_webhook_verification(server):
    ok = server.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = server.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_webhook_requires_valid_signature(server):
    body = json.dumps(payload(OWNER, "oi")).encode()
    headers = {"content-type": "application/json", "host": "meu-tunel.exemplo.com"}  # chega pelo domínio público
    assert server.post("/whatsapp/webhook", content=body, headers=headers).status_code == 403
    assert server.post("/whatsapp/webhook", content=body,
                       headers={**headers, "x-hub-signature-256": sign(body, "outro")}).status_code == 403
    ok = server.post("/whatsapp/webhook", content=body, headers={**headers, "x-hub-signature-256": sign(body)})
    assert ok.status_code == 200
    assert [(m.sender, m.text) for m in server.received] == [(OWNER, "oi")]


def test_public_host_only_reaches_the_webhook(server):
    assert server.get("/api/painel", headers={"host": "meu-tunel.exemplo.com"}).status_code == 403


def test_webhook_off_when_not_configured(monkeypatch, cfg):
    monkeypatch.setattr(web, "whatsapp", None)
    client = TestClient(web.app, base_url="http://127.0.0.1:8000")
    assert client.post("/whatsapp/webhook", json={}).status_code == 404


def test_config_enables_whatsapp_only_when_complete(cfg, wcfg):
    assert not cfg.whatsapp_enabled and wcfg.whatsapp_enabled
    assert not dataclasses.replace(wcfg, whatsapp_app_secret="").whatsapp_enabled


def test_server_startup_turns_whatsapp_on(monkeypatch, wcfg, tmp_path):
    from agente.scheduler import AgendaStore

    monkeypatch.setattr(web, "cfg", wcfg)
    monkeypatch.setattr(web, "agenda", AgendaStore(tmp_path / "agenda.db", "America/Sao_Paulo"))
    monkeypatch.setattr(web, "whatsapp", None)
    with TestClient(web.app, base_url="http://127.0.0.1:8000") as client:  # roda o lifespan
        assert isinstance(web.whatsapp, WhatsAppChannel)
        assert client.get("/api/status").json()["whatsapp"] is True
        web.whatsapp.set_paused(True)
        assert web.scheduler.paused  # PARAR no WhatsApp pausa a agenda


# --- clientes da empresa (atendente) ---------------------------------------------------

def test_customers_go_to_attendant_when_enabled(wcfg, tmp_path):
    made = []

    def customer(number):
        agent = FakeAgent(wcfg)
        made.append((number, agent))
        return agent

    paused = []
    ch = WhatsAppChannel(wcfg, FakeApi(), History(tmp_path / "conversas.db"), FakeAgent, on_pause=paused.append,
                         customer_factory=customer)

    async def scenario():
        await ch.handle(msg("quanto custa o alinhamento?", sender=STRANGER))
        await wait_for(lambda: ch.api.sent)
        await ch.handle(msg("parar", sender=STRANGER))  # de cliente é opt-out (atendente), não pausa a agenda
        await wait_for(lambda: len(ch.api.sent) == 2)

    run(ch, scenario)
    assert [n for n, _ in made] == [STRANGER]  # um atendente por cliente
    assert ch.api.sent[0] == (STRANGER, "**Resposta:** quanto custa o alinhamento?")  # só o texto final
    assert made[0][1].calls == ["quanto custa o alinhamento?", "parar"]
    assert paused == [] and not ch.paused
    assert ch.history.channel_session(f"cliente:{STRANGER}") == "sessao-wa"


def test_customer_reply_has_no_internal_details(wcfg, tmp_path):
    ch = WhatsAppChannel(wcfg, FakeApi(), History(tmp_path / "c.db"), FakeAgent, customer_factory=lambda n: FakeAgent(wcfg))

    async def scenario():
        await ch.handle(msg("rm", sender=STRANGER))
        await wait_for(lambda: ch.api.sent)

    run(ch, scenario)
    assert ch.api.sent == [(STRANGER, "Não consegui apagar.")]  # sem "Bloqueado pela segurança" nem custo


def test_send_template_body(wcfg):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    api = CloudApi(wcfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    asyncio.run(api.send_template(STRANGER, "retomada_orcamento", ["Ana"]))
    assert calls[0]["type"] == "template" and calls[0]["template"]["name"] == "retomada_orcamento"
    assert calls[0]["template"]["components"][0]["parameters"] == [{"type": "text", "text": "Ana"}]
