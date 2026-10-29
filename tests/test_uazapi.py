"""WhatsApp pela UAZAPI com mensagens simuladas: nada sai para o servidor de verdade."""

import asyncio
import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agente import config, vigia, web
from agente.whatsapp import Incoming, UazApi, WhatsAppError, jid_number, parse_uazapi

OWNER, CUSTOMER = "5519999990001", "5519988887777"
SECRET = "segredo-comprido-do-webhook"


@pytest.fixture
def ucfg(cfg):
    return dataclasses.replace(cfg, whatsapp_provider="uazapi", uazapi_url="https://teste.uazapi.com",
                               uazapi_token="tok-instancia", uazapi_webhook_secret=SECRET, whatsapp_allowed=(OWNER,))


def event(text="oi", chatid=f"{CUSTOMER}@s.whatsapp.net", **message):
    body = {"messageid": "3EB0ABC", "id": "1", "chatid": chatid, "sender": chatid, "senderName": "Ana",
            "fromMe": False, "isGroup": False, "messageType": "Conversation", "text": text, **message}
    return {"EventType": "messages", "owner": OWNER, "token": "tok-instancia", "instanceName": "loja", "message": body}


# --- configuração ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,url,expected", [
    ("", "", "meta"), ("", "https://x.uazapi.com", "uazapi"), ("meta", "https://x.uazapi.com", "meta"), ("UAZAPI", "", "uazapi"),
])
def test_provider_choice(value, url, expected):
    assert config.whatsapp_provider(value, url) == expected


def test_uazapi_enabled_needs_url_token_secret_and_team(ucfg):
    assert ucfg.whatsapp_enabled
    for field in ("uazapi_url", "uazapi_token", "uazapi_webhook_secret"):
        assert not dataclasses.replace(ucfg, **{field: ""}).whatsapp_enabled
    assert not dataclasses.replace(ucfg, whatsapp_allowed=()).whatsapp_enabled


# --- mensagens recebidas ----------------------------------------------------------------------

def test_parse_text_message():
    [msg] = parse_uazapi(event("quanto custa o alinhamento?"))
    assert msg == Incoming("3EB0ABC", CUSTOMER, "text", "quanto custa o alinhamento?", "Ana")
    [extended] = parse_uazapi(event("oi", messageType="ExtendedTextMessage"))
    assert extended.kind == "text"


def test_parse_ignores_ours_groups_and_other_events():
    assert parse_uazapi(event(fromMe=True)) == []
    assert parse_uazapi(event(wasSentByApi=True)) == []
    assert parse_uazapi(event(isGroup=True, chatid="120363@g.us")) == []
    assert parse_uazapi({**event(), "EventType": "messages_update"}) == []
    assert parse_uazapi({"EventType": "messages"}) == []


def test_parse_uses_phone_when_chat_is_a_lid():
    [msg] = parse_uazapi(event(chatid="2412345@lid", sender="2412345@lid", sender_pn=f"{CUSTOMER}@s.whatsapp.net"))
    assert msg.sender == CUSTOMER
    assert parse_uazapi(event(chatid="2412345@lid", sender="2412345@lid")) == []  # sem telefone, não dá para responder


def test_parse_audio_and_image():
    [audio] = parse_uazapi(event("", messageType="AudioMessage"))
    assert (audio.kind, audio.text) == ("audio", "")
    [image] = parse_uazapi(event("olha o barulho", messageType="ImageMessage"))
    assert (image.kind, image.text) == ("image", "olha o barulho")  # legenda vira texto


def test_jid_number():
    assert jid_number(f"{CUSTOMER}@s.whatsapp.net") == CUSTOMER
    assert jid_number(f"{CUSTOMER}:12@s.whatsapp.net") == CUSTOMER  # aparelho
    assert jid_number("2412345@lid") == jid_number("120363@g.us") == jid_number(None) == ""


# --- envio --------------------------------------------------------------------------------------

def mock_api(ucfg, status=200, reply=None):
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("token"), json.loads(request.content)))
        return httpx.Response(status, json=reply if reply is not None else {"ok": True})

    return UazApi(ucfg, httpx.AsyncClient(transport=httpx.MockTransport(handler))), calls


def test_send_text_mark_read_and_webhook(ucfg):
    api, calls = mock_api(ucfg)

    async def main():
        await api.send_text(CUSTOMER, "**Total:** R$ 10")
        await api.mark_read("3EB0ABC")
        await api.set_webhook("https://x.com/whatsapp/uazapi/s")

    asyncio.run(main())
    assert calls[0] == ("/send/text", "tok-instancia", {"number": CUSTOMER, "text": "*Total:* R$ 10"})
    assert calls[1] == ("/message/markread", "tok-instancia", {"id": ["3EB0ABC"]})
    assert calls[2][0] == "/webhook" and calls[2][2]["events"] == ["messages"]
    assert {"wasSentByApi", "isGroupYes"} <= set(calls[2][2]["excludeMessages"])


def test_errors_become_whatsapp_errors(ucfg):
    api, _ = mock_api(ucfg, status=401, reply={"error": "Invalid token"})
    with pytest.raises(WhatsAppError, match="Invalid token"):
        asyncio.run(api.send_text(CUSTOMER, "oi"))
    with pytest.raises(WhatsAppError, match="modelos"):
        asyncio.run(api.send_template(CUSTOMER, "retorno", []))


def test_vigia_alerts_through_uazapi(ucfg):
    calls = []

    def handler(request):
        calls.append((str(request.url), request.headers.get("token"), json.loads(request.content)))
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert vigia.send_whatsapp(ucfg, "caiu", client)
    assert calls == [("https://teste.uazapi.com/send/text", "tok-instancia", {"number": OWNER, "text": "caiu"})]


# --- webhook ------------------------------------------------------------------------------------

class FakeChannel:
    def __init__(self):
        self.handled: list[Incoming] = []

    async def handle(self, msg):
        self.handled.append(msg)


@pytest.fixture
def hook(monkeypatch, ucfg):
    channel = FakeChannel()
    monkeypatch.setattr(web, "cfg", ucfg)
    monkeypatch.setattr(web, "whatsapp", channel)
    # pelo domínio público, como a UAZAPI chama
    return TestClient(web.app, base_url="https://agente.autocenter.com.br"), channel


def test_webhook_accepts_messages_with_the_secret(hook):
    client, channel = hook
    assert client.post(f"/whatsapp/uazapi/{SECRET}", json=event("oi")).json() == {"ok": True}
    assert [m.text for m in channel.handled] == ["oi"]


@pytest.mark.parametrize("path,body", [
    ("/whatsapp/uazapi/chute", event()),
    (f"/whatsapp/uazapi/{SECRET}", {**event(), "token": "outro-token"}),
])
def test_webhook_rejects_wrong_secret_or_token(hook, path, body):
    client, channel = hook
    assert client.post(path, json=body).status_code == 403
    assert channel.handled == []


def test_public_host_still_cannot_reach_the_rest(hook):
    client, _ = hook
    assert client.get("/painel").status_code == 403
    assert client.get("/api/crm").status_code == 403


def test_meta_setup_does_not_answer_the_uazapi_route(monkeypatch, ucfg):
    monkeypatch.setattr(web, "cfg", dataclasses.replace(ucfg, whatsapp_provider="meta"))
    monkeypatch.setattr(web, "whatsapp", FakeChannel())
    client = TestClient(web.app, base_url="http://127.0.0.1:8000")
    assert client.post(f"/whatsapp/uazapi/{SECRET}", json=event()).status_code == 404


# --- áudio (Whisper pela UAZAPI) ----------------------------------------------------------------

def test_transcribe_asks_uazapi_with_the_openai_key(ucfg):
    api, calls = mock_api(dataclasses.replace(ucfg, openai_api_key="sk-teste"), reply={"transcription": " quanto custa o óleo? "})
    assert asyncio.run(api.transcribe("3EB0ABC")) == " quanto custa o óleo? "
    path, token, body = calls[0]
    assert path == "/message/download" and body["transcribe"] is True and body["id"] == "3EB0ABC"
    assert body["openai_apikey"] == "sk-teste"
    api, calls = mock_api(ucfg, reply={"transcription": "oi"})
    asyncio.run(api.transcribe("x"))
    assert "openai_apikey" not in calls[0][2]  # sem chave no .env: a UAZAPI usa a salva na instância


class AudioApi:
    def __init__(self, transcription="quanto custa o alinhamento?", fail=False):
        self.sent: list[tuple[str, str]] = []
        self.transcription, self.fail = transcription, fail

    async def send_text(self, to, text):
        self.sent.append((to, text))

    async def mark_read(self, message_id):
        pass

    async def transcribe(self, message_id):
        if self.fail:
            raise WhatsAppError("sem chave da OpenAI")
        return self.transcription


class Recorder:
    def __init__(self, cfg, resume=None):
        raise AssertionError("não deve chegar ao operador")


def customer_channel(ucfg, tmp_path, api, received):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel

    class Customer:
        def __init__(self):
            from agente.human import HumanBridge
            self.human = HumanBridge(1)
            self.session_id = None

        async def start(self):
            pass

        async def stop(self):
            pass

        async def ask(self, text):
            from agente.core import Event
            received.append(text)
            yield Event("text", "resposta")

    return WhatsAppChannel(ucfg, api, History(tmp_path / "c.db"), Recorder, customer_factory=lambda n: Customer())


def run_channel(channel, *messages):
    async def main():
        for m in messages:
            await channel.handle(m)
        for _ in range(50):
            await asyncio.sleep(0.01)
        await channel.close()
    asyncio.run(main())


def test_audio_becomes_text_for_the_attendant(ucfg, tmp_path):
    received, api = [], AudioApi()
    channel = customer_channel(ucfg, tmp_path, api, received)
    run_channel(channel, Incoming("a1", CUSTOMER, "audio", ""))
    assert received == ["🎤 (áudio) quanto custa o alinhamento?"]
    assert api.sent == [(CUSTOMER, "resposta")]


def test_audio_that_cannot_be_transcribed_asks_to_write(ucfg, tmp_path):
    received, api = [], AudioApi(fail=True)
    run_channel(customer_channel(ucfg, tmp_path, api, received), Incoming("a2", CUSTOMER, "ptt", ""))
    assert received == [] and "ouvir esse áudio" in api.sent[0][1]
    received, api = [], AudioApi()
    run_channel(customer_channel(dataclasses.replace(ucfg, transcribe_audio=False), tmp_path, api, received),
                Incoming("a3", CUSTOMER, "audio", ""))
    assert received == []  # transcrição desligada no .env


# --- tabelas e pedido de ajuda ---------------------------------------------------------------------

def test_tables_become_lists_on_whatsapp():
    from agente.whatsapp import to_whatsapp
    md = "Estoque:\n| Produto | Qtd | OS |\n|---|---|---|\n| Óleo 5W30 | 20 | 5 OS |\n| Filtro | 5 | — |\n\nfim"
    assert to_whatsapp(md) == "Estoque:\n• Óleo 5W30 — Qtd: 20 · OS: 5 OS\n• Filtro — Qtd: 5\n\nfim"
    assert to_whatsapp("a | b sem tabela") == "a | b sem tabela"


def test_help_request_brings_the_remote_screen_link(ucfg, tmp_path):
    from agente.history import History
    from agente.human import HelpRequest
    from agente.whatsapp import Contact, WhatsAppChannel
    api = AudioApi()
    channel = WhatsAppChannel(ucfg, api, History(tmp_path / "c.db"), Recorder)
    channel.remote_link = lambda: "https://vm.exemplo.com/acesso-navegador/abc"
    asyncio.run(channel.ask_help(Contact(OWNER), HelpRequest("1", "Login na Amazon para finalizar", "https://www.amazon.com.br/cart"), []))
    text = api.sent[0][1]
    # o link do site abriria o app da loja no celular: só vai o da tela remota
    assert "https://www.amazon.com.br" not in text and "amazon.com.br" not in text and "amazon·com·br" in text
    assert "https://vm.exemplo.com/acesso-navegador/abc" in text and "o agente não vê" in text
    assert "não pelo aplicativo" in text
    api.sent.clear()
    asyncio.run(channel.ask_help(Contact(OWNER), HelpRequest("2", "Qual cor você prefere?", ""), []))
    assert "acesso-navegador" not in api.sent[0][1]  # decisão sem página: sem link da tela remota


def test_transcribe_through_openrouter_when_there_is_no_openai_key(ucfg):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.host, request.url.path, request.headers.get("authorization") or request.headers.get("token"), body))
        if request.url.host == "openrouter.ai":
            return httpx.Response(200, json={"choices": [{"message": {"content": "\"quanto custa o óleo?\""}}]})
        return httpx.Response(200, json={"base64Data": "AAAA", "mimetype": "audio/mpeg"})

    cfg = dataclasses.replace(ucfg, openrouter_api_key="sk-or-teste", transcription_model="google/gemini-2.5-flash-lite")
    api = UazApi(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(api.transcribe("3EB0ABC")) == "quanto custa o óleo?"
    (h1, p1, t1, b1), (h2, p2, t2, b2) = calls
    assert (p1, b1["return_base64"], b1["generate_mp3"]) == ("/message/download", True, True) and "transcribe" not in b1
    assert h2 == "openrouter.ai" and t2 == "Bearer sk-or-teste" and b2["model"] == "google/gemini-2.5-flash-lite"
    audio = b2["messages"][0]["content"][1]
    assert audio == {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "mp3"}}


def test_openrouter_refusal_becomes_an_error(ucfg):
    def handler(request):
        if request.url.host == "openrouter.ai":
            return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})
        return httpx.Response(200, json={"base64Data": "AAAA"})

    api = UazApi(dataclasses.replace(ucfg, openrouter_api_key="k"), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(WhatsAppError, match="Insufficient credits"):
        asyncio.run(api.transcribe("x"))


def test_transcription_falls_back_when_a_model_is_rate_limited():
    from agente.whatsapp import transcribe_openrouter
    tried = []

    def handler(request):
        model = json.loads(request.content)["model"]
        tried.append(model)
        if model == "google/gemini-2.5-flash-lite":
            return httpx.Response(429, json={"error": {"message": "Provider returned error",
                                                       "metadata": {"raw": "temporarily rate-limited upstream"}}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "oi"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(transcribe_openrouter(client, "k", "google/gemini-2.5-flash-lite", "AAAA", "mp3")) == "oi"
    assert tried == ["google/gemini-2.5-flash-lite", "google/gemini-3.1-flash-lite"]


def test_transcription_stops_on_bad_key():
    from agente.whatsapp import transcribe_openrouter
    tried = []

    def handler(request):
        tried.append(1)
        return httpx.Response(401, json={"error": {"message": "User not found"}})

    with pytest.raises(WhatsAppError, match="User not found"):
        asyncio.run(transcribe_openrouter(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "k", "a", "AAAA", "mp3"))
    assert tried == [1]  # chave errada: não adianta tentar outro modelo


def test_navegador_command_sends_the_remote_link_without_the_model(ucfg, tmp_path):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel
    api = AudioApi()
    channel = WhatsAppChannel(ucfg, api, History(tmp_path / "c.db"), Recorder)
    channel.remote_link = lambda: "https://vm.exemplo.com/acesso-navegador/abc"
    run_channel(channel, Incoming("n1", OWNER, "text", "Navegador"))
    assert "https://vm.exemplo.com/acesso-navegador/abc" in api.sent[0][1] and "o agente não vê" in api.sent[0][1]


def test_site_links_in_login_talk_become_the_remote_link():
    from agente.whatsapp import LOGIN_TALK, asks_login_link, without_site_links
    reply = ("👉 **https://www.amazon.com.br/PlayStation-DualSense/dp/B0CQKLS4RP**\n"
             "Abra esse link, clique em \"faça seu login\" e entre com sua conta.")
    assert LOGIN_TALK.search(reply)
    clean = without_site_links(reply)
    assert "https://" not in clean and "amazon·com·br (aberto no navegador do agente)" in clean
    assert asks_login_link("me manda o link pra logar") and asks_login_link("cadê o link do login?")
    assert not asks_login_link("me envia o link do produto") and not asks_login_link("já loguei")
    assert asks_login_link("mande o link") and asks_login_link("manda o link de novo")  # curto: é o da VM
    assert not asks_login_link("me manda o link da amazon")  # da loja: quem responde é o agente


class Operator:
    def __init__(self, cfg, resume=None):
        from agente.human import HumanBridge
        self.human = HumanBridge(1)
        self.session_id = None

    async def start(self):
        pass

    async def stop(self):
        pass

    async def ask(self, text):
        from agente.core import Event
        yield Event("text", "Abra https://www.amazon.com.br/dp/X e faça seu login com sua conta.")


def test_operator_reply_about_login_gets_the_remote_link(ucfg, tmp_path):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel
    api = AudioApi()
    channel = WhatsAppChannel(ucfg, api, History(tmp_path / "c.db"), Operator)
    channel.remote_link = lambda: "https://vm.exemplo.com/acesso-navegador/abc"
    run_channel(channel, Incoming("o1", OWNER, "text", "põe no carrinho"), Incoming("o2", OWNER, "text", "me envia o link pra logar"))
    texts = [t for _, t in api.sent]
    [model] = [t for t in texts if t.startswith("Abra")]
    assert "https://www.amazon.com.br" not in model and "acesso-navegador/abc" in model  # resposta do modelo corrigida
    assert any(t.startswith("🖥️ *Link do navegador do agente*") for t in texts)  # pedido de link de login: respondido pelo código


class FinalizeOperator(Operator):
    async def ask(self, text):
        from agente.core import Event
        yield Event("text", "Coloquei no carrinho. Você só precisa clicar em \"Finalizar pedido\" na janela do navegador.")


def test_reply_asking_to_act_in_the_browser_brings_the_vm_link(ucfg, tmp_path):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel
    api = AudioApi()
    channel = WhatsAppChannel(ucfg, api, History(tmp_path / "c.db"), FinalizeOperator)
    channel.remote_link = lambda: "https://vm.exemplo.com/acesso-navegador/abc"
    run_channel(channel, Incoming("f1", OWNER, "text", "coloca o branco no carrinho"))
    text = api.sent[0][1]
    assert "Finalizar pedido" in text and "Link do navegador do agente" in text and "acesso-navegador/abc" in text


# --- dois números: maestro (dono) e atendente (clientes) ----------------------------------------------

ATT_SECRET = "segredo-do-numero-do-atendente"


@pytest.fixture
def two(ucfg):
    return dataclasses.replace(ucfg, uazapi_attendant_token="tok-atendente", uazapi_attendant_webhook_secret=ATT_SECRET)


def test_attendant_channel_needs_token_and_secret(ucfg, two):
    assert two.attendant_channel and not ucfg.attendant_channel
    assert not dataclasses.replace(two, uazapi_attendant_webhook_secret="").attendant_channel
    assert not dataclasses.replace(two, whatsapp_provider="meta").attendant_channel


def test_each_secret_goes_to_its_own_number(monkeypatch, two):
    maestro, attendant = FakeChannel(), FakeChannel()
    monkeypatch.setattr(web, "cfg", two)
    monkeypatch.setattr(web, "whatsapp", maestro)
    monkeypatch.setattr(web, "attendant_whatsapp", attendant)
    client = TestClient(web.app, base_url="https://agente.autocenter.com.br")
    assert client.post(f"/whatsapp/uazapi/{SECRET}", json=event("relatório de hoje")).status_code == 200
    assert client.post(f"/whatsapp/uazapi/{ATT_SECRET}", json={**event("tem pistache?"), "token": "tok-atendente"}).status_code == 200
    assert [m.text for m in maestro.handled] == ["relatório de hoje"]
    assert [m.text for m in attendant.handled] == ["tem pistache?"]
    # token de uma instância com o segredo da outra: recusado
    assert client.post(f"/whatsapp/uazapi/{ATT_SECRET}", json=event("x")).status_code == 403


def test_attendant_number_treats_everyone_as_customer(two, tmp_path):
    """No número do atendente até o dono é cliente (para testar o atendimento como um cliente faria)."""
    received, api = [], AudioApi()
    channel = customer_channel(two, tmp_path, api, received)
    channel.customers_only = True
    run_channel(channel, Incoming("c1", OWNER, "text", "tem milkshake de pistache?"))
    assert received == ["tem milkshake de pistache?"] and api.sent == [(OWNER, "resposta")]


def test_maestro_number_ignores_strangers(two, tmp_path):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel
    api = AudioApi()
    channel = WhatsAppChannel(two, api, History(tmp_path / "c.db"), Recorder)  # sem atendente: só o dono
    run_channel(channel, Incoming("s1", CUSTOMER, "text", "oi, quanto custa?"))
    assert api.sent == []


def test_customer_messages_leave_by_the_attendant_number(monkeypatch, two, tmp_path):
    from agente.history import History
    from agente.whatsapp import WhatsAppChannel
    maestro_api, attendant_api = AudioApi(), AudioApi()
    maestro = WhatsAppChannel(two, maestro_api, History(tmp_path / "a.db"), Recorder)
    attendant = WhatsAppChannel(two, attendant_api, History(tmp_path / "b.db"), Recorder,
                                customer_factory=lambda n: None, customers_only=True)
    attendant.contacts[CUSTOMER] = __import__("agente.whatsapp", fromlist=["Contact"]).Contact(
        CUSTOMER, customer=True, last_inbound=__import__("datetime").datetime.now())
    monkeypatch.setattr(web, "whatsapp", maestro)
    monkeypatch.setattr(web, "attendant_whatsapp", attendant)
    assert asyncio.run(web.send_to_customer(CUSTOMER, "Oi, aqui é a equipe!", kind="humano"))
    assert attendant_api.sent == [(CUSTOMER, "Oi, aqui é a equipe!")] and maestro_api.sent == []
