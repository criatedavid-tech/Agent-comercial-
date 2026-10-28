"""Vigia: confere se o agente está no ar e avisa pelo WhatsApp quando cai e quando volta.

Roda a cada poucos minutos (timer do systemd na VPS). O systemd já reinicia o serviço
sozinho; o vigia existe para você saber quando algo não se resolveu.

Só avisa depois de 2 falhas seguidas (evita alarme falso durante um reinício) e só uma vez
por queda. Pela regra das 24 h da Meta, o aviso só chega se você falou com o agente no último dia;
o log do sistema (journalctl -u agente-vigia) registra tudo de qualquer forma.
"""

import argparse
import json
from pathlib import Path
import sys

import httpx

from . import config
from .config import Config

FAILURES_BEFORE_ALERT = 2


def is_up(url: str, client: httpx.Client) -> bool:
    try:
        return client.get(url, timeout=10).status_code == 200
    except httpx.HTTPError:
        return False


def send_whatsapp(cfg: Config, text: str, client: httpx.Client) -> bool:
    if not cfg.whatsapp_enabled:
        return False
    if cfg.whatsapp_provider == "uazapi":
        try:
            resp = client.post(f"{cfg.uazapi_url}/send/text", json={"number": cfg.whatsapp_allowed[0], "text": text},
                               headers={"token": cfg.uazapi_token}, timeout=20)
            return resp.status_code < 400
        except httpx.HTTPError:
            return False
    url = f"https://graph.facebook.com/{cfg.whatsapp_api_version}/{cfg.whatsapp_phone_id}/messages"
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "+" + cfg.whatsapp_allowed[0],
            "type": "text", "text": {"preview_url": False, "body": text}}
    try:
        resp = client.post(url, json=body, headers={"Authorization": f"Bearer {cfg.whatsapp_token}"}, timeout=20)
        return resp.status_code < 400
    except httpx.HTTPError:
        return False


def check(cfg: Config, state_file: Path, client: httpx.Client, url: str | None = None) -> str:
    """Uma rodada do vigia. Devolve o que aconteceu: "ok", "falhou", "alertou", "voltou"."""
    url = url or f"http://127.0.0.1:{cfg.web_port}/api/status"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"failures": 0, "alerted": False}
    if is_up(url, client):
        result = "voltou" if state["alerted"] else "ok"
        if state["alerted"]:
            send_whatsapp(cfg, "✅ O agente voltou ao ar.", client)
        state = {"failures": 0, "alerted": False}
    else:
        state["failures"] += 1
        result = "falhou"
        if state["failures"] >= FAILURES_BEFORE_ALERT and not state["alerted"]:
            send_whatsapp(cfg, "🔴 O agente está fora do ar há alguns minutos. "
                               "Veja na VPS: sudo journalctl -u agente -n 50", client)
            state["alerted"] = True
            result = "alertou"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Confere se o agente está no ar")
    parser.add_argument("--url", help="endereço de status (padrão: http://127.0.0.1:PORTA/api/status)")
    args = parser.parse_args()
    cfg = config.load()
    with httpx.Client() as client:
        result = check(cfg, cfg.logs_dir / "vigia.json", client, args.url)
    print(f"vigia: {result}")
    sys.exit(0 if result in ("ok", "voltou") else 1)


if __name__ == "__main__":
    main()
