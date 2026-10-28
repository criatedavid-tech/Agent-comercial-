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
