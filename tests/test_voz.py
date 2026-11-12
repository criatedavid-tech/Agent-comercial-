"""Voz de entrada: áudio do painel vira texto. Serviços de transcrição simulados: nada sai para a internet."""

import asyncio
import dataclasses
import struct

import httpx
import pytest
from fastapi.testclient import TestClient

from agente import voz, web


def wav(n=100) -> bytes:
    pcm = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_whisper_com_chave_da_openai(cfg):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], request.content
        return httpx.Response(200, text=" quanto custa o óleo? \n")

    c = dataclasses.replace(cfg, openai_api_key="sk-teste")
    assert asyncio.run(voz.transcribe(c, wav(), mock(handler))) == "quanto custa o óleo?"
    assert seen["url"] == voz.WHISPER_URL and seen["auth"] == "Bearer sk-teste"
    assert b"whisper-1" in seen["body"] and b"RIFF" in seen["body"]


def test_sem_openai_usa_o_openrouter(cfg):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "openrouter.ai" in str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "oi tudo bem"}}]})

    c = dataclasses.replace(cfg, openrouter_api_key="k")
    assert asyncio.run(voz.transcribe(c, wav(), mock(handler))) == "oi tudo bem"


def test_recusas_com_motivo_legivel(cfg):
    c = dataclasses.replace(cfg, openai_api_key="sk")
    with pytest.raises(voz.VoiceError, match="vazio"):
        asyncio.run(voz.transcribe(c, b""))
    with pytest.raises(voz.VoiceError, match="WAV"):
        asyncio.run(voz.transcribe(c, b"x" * 200))
    with pytest.raises(voz.VoiceError, match="grande"):
        asyncio.run(voz.transcribe(c, wav() + b"0" * voz.MAX_BYTES))
    with pytest.raises(voz.VoiceError, match="faltam"):
        asyncio.run(voz.transcribe(dataclasses.replace(cfg, openai_api_key="", openrouter_api_key=""), wav()))
    with pytest.raises(voz.VoiceError, match="desligada"):
        asyncio.run(voz.transcribe(dataclasses.replace(c, transcribe_audio=False), wav()))


def test_erro_do_servico_nao_vaza_a_chave(cfg):
    c = dataclasses.replace(cfg, openai_api_key="sk-segredo")
    with pytest.raises(voz.VoiceError) as err:
        asyncio.run(voz.transcribe(c, wav(), mock(lambda r: httpx.Response(401, text="Bearer sk-segredo invalido"))))
    assert "sk-segredo" not in str(err.value) and "401" in str(err.value)


def test_disponivel_so_com_chave(cfg):
    assert not voz.available(cfg)
    assert voz.available(dataclasses.replace(cfg, openai_api_key="sk"))
    assert not voz.available(dataclasses.replace(cfg, openai_api_key="sk", transcribe_audio=False))


def test_endpoint_exige_origem_local_e_devolve_texto(cfg, monkeypatch):
    async def fake(_cfg, data, client=None):
        return "texto falado"

    monkeypatch.setattr(web, "cfg", dataclasses.replace(cfg, openai_api_key="sk"))
    monkeypatch.setattr(voz, "transcribe", fake)
    client = TestClient(web.app, base_url="http://127.0.0.1:8000")
    assert client.get("/api/voz").json() == {"available": True}
    assert client.post("/api/voz", content=wav()).status_code == 403  # sem Origin
    assert client.post("/api/voz", content=wav(), headers={"origin": "http://evil.example"}).status_code == 403
    ok = client.post("/api/voz", content=wav(), headers={"origin": "http://127.0.0.1:8000"})
    assert ok.status_code == 200 and ok.json() == {"text": "texto falado"}
    assert client.post("/api/voz", content=wav(), headers={"origin": "http://127.0.0.1:8000", "host": "evil.example"}).status_code == 403
