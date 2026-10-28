"""Acessos aos sistemas da loja: cadastro, checagem de login, avisos, trava do agente e tela remota."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agente import sessoes, web
from agente.core import browser_tools
from agente.sessoes import (OK, OUT, ERROR, Probe, RemoteAccess, SessionStore, SessionWatch, State, System,
                            SystemsError, blocked_message, classify, load_systems)

OFICINA = System("Sistema da oficina", "https://app.oficina.com.br/painel", "Sair")
T0 = datetime(2026, 10, 28, 9, 0).astimezone()
TOML = """
[[sistema]]
nome = "Sistema da oficina"
endereco = "https://app.oficina.com.br/painel"
logado = "Sair"

[[sistema]]
nome = "Banco"
endereco = "https://banco.com.br/empresas"
logado = "Olá, Rota Certa"
"""


def write_systems(folder, text=TOML):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sistemas.toml").write_text(text, encoding="utf-8")
    return folder


# --- cadastro -------------------------------------------------------------------------------

def test_load_systems(tmp_path):
    systems = load_systems(write_systems(tmp_path))
    assert [s.name for s in systems] == ["Sistema da oficina", "Banco"]
    assert systems[1].host == "banco.com.br" and systems[1].marker == "Olá, Rota Certa"
    assert load_systems(tmp_path / "nada") == []


@pytest.mark.parametrize("text,error", [
    ('[[sistema]]\nnome = "X"\nendereco = "https://x.com"\n', "falta logado"),
    ('[[sistema]]\nnome = "X"\nendereco = "x.com"\nlogado = "Sair"\n', "https://"),
    ('[[sistema]]\nnome = "X"\nendereco = "https://x.com"\nlogado = "a"\n'
     '[[sistema]]\nnome = "x"\nendereco = "https://y.com"\nlogado = "b"\n', "duas vezes"),
    ('[[sistema]\n', "sistemas.toml"),
])
def test_bad_systems_file_says_what(tmp_path, text, error):
    with pytest.raises(SystemsError, match=error):
        load_systems(write_systems(tmp_path, text))


def test_example_company_has_no_active_system():
    from agente.config import EXAMPLE_COMPANY
    assert (EXAMPLE_COMPANY / "sistemas.toml").exists() and load_systems(EXAMPLE_COMPANY) == []


# --- logado ou não ------------------------------------------------------------------------------

def test_classify():
    assert classify(Probe("u", "Painel", "Bem-vindo, Rafael · SAIR"), OFICINA) == OK
    assert classify(Probe("u", "Entrar", "Usuário Senha Esqueci a senha", has_password=True), OFICINA) == OUT
    assert classify(Probe("u", "Just a moment", "Sair", challenge=True), OFICINA) == OUT  # verificação de robô
    banco = System("Banco", "https://banco.com.br", "Olá, Rota Certa")
    assert classify(Probe("u", "Banco", "ola, rota   certa"), banco) == OK  # sem acento e com espaços


def test_owns_and_blocked_message():
    assert OFICINA.owns("https://app.oficina.com.br/os/123") and OFICINA.owns("app.oficina.com.br")
    assert not OFICINA.owns("https://oficina.com.br.golpe.com") and not OFICINA.owns("https://google.com")
    assert blocked_message("https://app.oficina.com.br/os", [OFICINA], {OFICINA.name: State(status=OUT)})
    assert blocked_message("https://app.oficina.com.br/os", [OFICINA], {OFICINA.name: State(status=OK)}) == ""
    assert blocked_message("https://outro.com", [OFICINA], {OFICINA.name: State(status=OUT)}) == ""


# --- checagem e avisos --------------------------------------------------------------------------

class Fake:
    """Site falso (responde logado, deslogado ou fora do ar) e caixa de avisos."""

    def __init__(self):
        self.mode = OK
        self.alerts: list[tuple[str, str]] = []

    async def probe(self, url):
        if self.mode == ERROR:
            raise RuntimeError("timeout")
        return Probe(url, "Painel", "Sair" if self.mode == OK else "Entrar Senha", has_password=self.mode == OUT)

    async def notify(self, title, text):
        self.alerts.append((title, text))


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def watch(tmp_path, fake):
    return SessionWatch([OFICINA], fake.probe, SessionStore(tmp_path / "sessoes.json"), fake.notify,
                        link=lambda: "https://vm.exemplo.com/acesso-navegador/abc")


def tick(watch, when):
    return asyncio.run(watch.tick(when))[OFICINA.name]


def test_logout_alerts_once_reminds_and_announces_return(watch, fake):
    assert tick(watch, T0) == "ok" and fake.alerts == []
    fake.mode = OUT
    assert tick(watch, T0 + timedelta(hours=1)) == "caiu"
    title, text = fake.alerts[-1]
    assert "Login expirou: Sistema da oficina" == title
    assert "https://vm.exemplo.com/acesso-navegador/abc" in text and "o agente não vê nem guarda" in text
    assert watch.store.load()[OFICINA.name].status == OUT
    assert tick(watch, T0 + timedelta(hours=2)) == "fora" and len(fake.alerts) == 1  # sem repetir a cada hora
    assert tick(watch, T0 + timedelta(hours=5, minutes=1)) == "lembrete" and len(fake.alerts) == 2
    fake.mode = OK
    assert tick(watch, T0 + timedelta(hours=6)) == "voltou"
    assert fake.alerts[-1][0] == "Acesso normalizado: Sistema da oficina"
    assert tick(watch, T0 + timedelta(hours=7)) == "ok" and len(fake.alerts) == 3


def test_site_down_alerts_only_after_two_failures(watch, fake):
    tick(watch, T0)
    fake.mode = ERROR
    assert tick(watch, T0 + timedelta(hours=1)) == "erro" and fake.alerts == []
    assert watch.store.load()[OFICINA.name].status == OK  # uma falha não muda nada
    tick(watch, T0 + timedelta(hours=2))
    assert fake.alerts[-1][0] == "Sistema fora do ar: Sistema da oficina"
    fake.mode = OUT  # voltou, mas deslogado: é outro problema, avisa na hora
    assert tick(watch, T0 + timedelta(hours=3)) == "caiu" and fake.alerts[-1][0].startswith("Login expirou")


def test_without_public_link_points_to_panel(tmp_path, fake):
    w = SessionWatch([OFICINA], fake.probe, SessionStore(tmp_path / "s.json"), fake.notify)
    fake.mode = OUT
    tick(w, T0)
    assert "painel do agente, em Navegador" in fake.alerts[-1][1]


def test_removed_system_leaves_the_state(tmp_path, fake):
    store = SessionStore(tmp_path / "s.json")
    store.save({"Antigo": State(status=OUT)})
    asyncio.run(SessionWatch([OFICINA], fake.probe, store, fake.notify).tick(T0))
    assert set(store.load()) == {OFICINA.name}


def test_broken_state_file_starts_over(tmp_path):
    (tmp_path / "s.json").write_text("{quebrado", encoding="utf-8")
    assert SessionStore(tmp_path / "s.json").load() == {}


# --- trava do agente ------------------------------------------------------------------------------

def test_agent_does_not_open_a_logged_out_system(cfg, tmp_path):
    from agente.browser import Browser
    cfg = replace(cfg, company_dir=write_systems(tmp_path / "empresa"))
    SessionStore(cfg.logs_dir / "sessoes.json").save({OFICINA.name: State(status=OUT, checked=T0.isoformat())})
    tools = {t.name: t for t in browser_tools(Browser(tmp_path / "p", tmp_path / "c", headless=True), cfg)}
    reply = asyncio.run(tools["abrir_pagina"].handler({"url": "https://app.oficina.com.br/os/1"}))
    text = reply["content"][0]["text"]
    assert reply["is_error"] and "expirou" in text and "Não tente fazer login" in text
    status = asyncio.run(tools["ver_acessos"].handler({}))["content"][0]["text"]
    assert "Sistema da oficina (app.oficina.com.br): deslogado" in status and "Banco" in status


# --- link temporário ------------------------------------------------------------------------------

def test_remote_access_links_expire():
    now = [1000.0]
    access = RemoteAccess(minutes=30, clock=lambda: now[0])
    token = access.issue()
    assert len(token) > 30 and access.valid(token)
    assert not access.valid("chute") and not access.valid("")
    now[0] += 30 * 60 + 1
    assert not access.valid(token)


class FakeBrowser:
    def __init__(self):
        self.actions = []

    async def view(self):
        return b"\xff\xd8jpeg"

    async def remote(self, action):
        self.actions.append(action)
        return {"url": "https://app.oficina.com.br/login", "field": {"name": "Usuário", "length": 6, "secret": False}}


@pytest.fixture
def remote(monkeypatch):
    access = RemoteAccess()
    fake_browser = FakeBrowser()
    monkeypatch.setattr(web, "remote_access", access)
    monkeypatch.setattr(web, "browser", lambda: fake_browser)
    monkeypatch.setattr(web, "cfg", replace(web.cfg, public_url="https://vm.exemplo.com"))
    return access, fake_browser


def test_remote_page_needs_a_valid_link(remote):
    access, _ = remote
    token = access.issue()
    public = TestClient(web.app, base_url="https://vm.exemplo.com")
    assert public.get(f"/acesso-navegador/{token}").status_code == 200
    assert public.get("/acesso-navegador/chute").status_code == 403
    assert public.get("/painel").status_code == 403  # o resto continua fechado para fora
    assert public.get(f"/painel?{token}").status_code == 403
    other = TestClient(web.app, base_url="https://golpe.com")
    assert other.get(f"/acesso-navegador/{token}").status_code == 403  # só no domínio da VM
    page = public.get(f"/acesso-navegador/{token}")
    assert page.headers["cache-control"] == "no-store" and "Navegador do agente" in page.text


def test_remote_screen_streams_and_forwards_input(remote):
    access, fake_browser = remote
    token = access.issue()
    client = TestClient(web.app, base_url="https://vm.exemplo.com")
    headers = {"host": "vm.exemplo.com", "origin": "https://vm.exemplo.com"}
    with client.websocket_connect(f"/ws/acesso-navegador/{token}", headers=headers) as ws:
        assert ws.receive_bytes().startswith(b"\xff\xd8")
        ws.send_json({"type": "type", "text": "rafael"})
        replies = []
        while len(replies) < 2:
            msg = ws.receive()
            if "text" in msg:
                replies.append(json.loads(msg["text"]))  # pula as imagens
        assert replies[1] == {"kind": "field", "field": {"name": "Usuário", "length": 6, "secret": False}, "after": "type"}
    assert fake_browser.actions == [{"type": "type", "text": "rafael"}]


@pytest.mark.parametrize("headers,token_ok", [
    ({"host": "vm.exemplo.com", "origin": "https://golpe.com"}, True),
    ({"host": "vm.exemplo.com", "origin": "https://vm.exemplo.com"}, False),
])
def test_remote_screen_rejects_other_origins_and_bad_links(remote, headers, token_ok):
    access, _ = remote
    token = access.issue() if token_ok else "chute"
    client = TestClient(web.app, base_url="https://vm.exemplo.com")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/acesso-navegador/{token}", headers=headers) as ws:
            ws.receive_bytes()


def test_panel_button_gives_a_local_link(remote):
    client = TestClient(web.app, base_url="http://127.0.0.1:8000")
    assert client.post("/api/navegador/link").status_code == 403  # sem Origin: outro site não pede link
    url = client.post("/api/navegador/link", headers={"origin": "http://127.0.0.1:8000"}).json()["url"]
    assert url.startswith("/acesso-navegador/") and remote[0].valid(url.rsplit("/", 1)[1])


def test_alert_goes_to_inbox_when_nobody_is_listening(tmp_path, monkeypatch):
    from agente.scheduler import AgendaStore
    store = AgendaStore(tmp_path / "agenda.db", "America/Sao_Paulo")
    monkeypatch.setattr(web, "agenda", store)
    monkeypatch.setattr(web, "hub", web.Hub())
    monkeypatch.setattr(web, "whatsapp", None)
    asyncio.run(web.alert_team("Login expirou: Banco", "Entre por este link"))
    [item] = store.unread()
    assert item.title == "Login expirou: Banco" and "link" in item.text
