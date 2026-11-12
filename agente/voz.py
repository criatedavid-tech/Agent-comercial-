"""Voz de entrada: áudio gravado no painel vira texto.

O navegador grava o microfone e manda um WAV (16 kHz, mono). Aqui o áudio vira texto pelo Whisper da OpenAI
(com `OPENAI_API_KEY`) ou, sem ela, por um modelo do OpenRouter que ouve áudio (a mesma rota do WhatsApp).
O áudio não é gravado em disco: só o texto volta para a tela, onde a pessoa confere antes de enviar.
"""
from __future__ import annotations

import base64
import httpx

from .config import Config
from .whatsapp import WhatsAppError, transcribe_openrouter

MAX_BYTES = 5 * 1024 * 1024  # ~2,5 min de WAV 16 kHz mono 16 bits; mais que isso o navegador nem manda
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"


class VoiceError(Exception):
    """Erro com mensagem que pode ir para a tela."""


def available(cfg: Config) -> bool:
    return bool(cfg.transcribe_audio and (cfg.openai_api_key or cfg.openrouter_api_key))


def looks_like_wav(data: bytes) -> bool:
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


async def transcribe(cfg: Config, data: bytes, client: httpx.AsyncClient | None = None) -> str:
    """WAV → texto. Levanta VoiceError com motivo legível se não der."""
    if not cfg.transcribe_audio:
        raise VoiceError("a transcrição de áudio está desligada (AGENT_TRANSCREVER_AUDIO=false)")
    if not (cfg.openai_api_key or cfg.openrouter_api_key):
        raise VoiceError("faltam a OPENAI_API_KEY ou a OPENROUTER_API_KEY no .env para transcrever áudio")
    if not data:
        raise VoiceError("áudio vazio")
    if len(data) > MAX_BYTES:
        raise VoiceError("áudio grande demais: fale em trechos de até 2 minutos")
    if not looks_like_wav(data):
        raise VoiceError("formato de áudio não aceito (esperado WAV)")
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        if cfg.openai_api_key:
            resp = await client.post(
                WHISPER_URL, headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
                data={"model": "whisper-1", "language": "pt", "response_format": "text"},
                files={"file": ("voz.wav", data, "audio/wav")})
            if resp.status_code >= 400:
                raise VoiceError(f"o Whisper recusou o áudio (HTTP {resp.status_code})")
            return resp.text.strip()
        try:
            return await transcribe_openrouter(client, cfg.openrouter_api_key, cfg.transcription_model,
                                               base64.b64encode(data).decode(), "wav")
        except WhatsAppError as err:
            raise VoiceError(str(err)) from err
    except httpx.HTTPError as err:
        raise VoiceError(f"não consegui falar com o serviço de transcrição ({type(err).__name__})") from err
    finally:
        if own:
            await client.aclose()
