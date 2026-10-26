"""Operação na VPS: backup (cópia consistente e rotação) e vigia (alerta quando cai e quando volta)."""

import dataclasses
from datetime import datetime
import json
import sqlite3
import tarfile

import httpx
import pytest

from agente import backup, vigia
from agente.history import History
from agente.knowledge import KnowledgeBase


@pytest.fixture
def data(cfg, tmp_path):
    (cfg.memory_dir / "perfil.md").write_text("- Nome: Teste", encoding="utf-8")
    KnowledgeBase(cfg.knowledge_dir).save("financas", "Aluguel", "1500")
    History(cfg.logs_dir / "conversas.db").record("s", "user", "oi")
    cfg.browser_profile.mkdir()
    (cfg.browser_profile / "Cookies").write_text("segredo")
    (cfg.logs_dir / "2026-10-26.jsonl").write_text("{}")  # log diário: fora do backup
    return cfg


def test_backup_contents(data, tmp_path):
    archive = backup.create(data, tmp_path / "backups", root=tmp_path, now=datetime(2026, 10, 26, 3, 30))
    assert archive.name == "agente-backup-20261026-033000.tar.gz"
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        tar.extractall(tmp_path / "restaurado", filter="data")
    assert "memory/perfil.md" in names and "logs/conversas.db" in names
    assert any(n.startswith("conhecimento/financas/") for n in names)
    assert not any(n.startswith("navegador/") for n in names)  # logins só com --com-navegador
    assert "logs/2026-10-26.jsonl" not in names and ".env" not in names
    # o banco restaurado abre e tem os dados
    restored = History(tmp_path / "restaurado" / "logs" / "conversas.db")
    assert restored.sessions()[0].title == "oi"


def test_backup_with_browser_profile(data, tmp_path):
    archive = backup.create(data, tmp_path / "b", root=tmp_path, with_browser=True)
    with tarfile.open(archive) as tar:
        assert "navegador/Cookies" in tar.getnames()


def test_backup_of_database_in_use(data, tmp_path):
    db = data.logs_dir / "conversas.db"
    writer = sqlite3.connect(db)
    writer.execute("INSERT INTO events (session_id, kind, text, ts) VALUES ('s', 'text', 'em uso', 'x')")  # sem commit
    archive = backup.create(data, tmp_path / "b", root=tmp_path)
    writer.close()
    with tarfile.open(archive) as tar:
        tar.extractall(tmp_path / "r", filter="data")
    assert len(History(tmp_path / "r" / "logs" / "conversas.db").events("s")) == 1  # só o que estava gravado


def test_rotation_keeps_newest(data, tmp_path):
    dest = tmp_path / "b"
    for day in range(1, 6):
        backup.create(data, dest, keep=3, root=tmp_path, now=datetime(2026, 10, day))
    assert [p.name[14:22] for p in sorted(dest.glob("*.tar.gz"))] == ["20261003", "20261004", "20261005"]


# --- vigia --------------------------------------------------------------------------


class Fake:
    """Simula o servidor do agente (no ar ou não) e a API da Meta."""

    def __init__(self):
        self.up = True
        self.sent: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.facebook.com":
            self.sent.append(json.loads(request.content)["text"]["body"])
            return httpx.Response(200, json={})
        if not self.up:
            raise httpx.ConnectError("recusado")
        return httpx.Response(200, json={"model": "x"})


@pytest.fixture
def wcfg(cfg):
    return dataclasses.replace(cfg, whatsapp_token="t", whatsapp_phone_id="1", whatsapp_verify_token="v",
                               whatsapp_app_secret="s", whatsapp_allowed=("5511999990000",))


def test_vigia_alerts_once_after_two_failures_and_on_recovery(wcfg, tmp_path):
    fake = Fake()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    state = tmp_path / "vigia.json"
    results = []
    for up in (True, False, False, False, True, True):
        fake.up = up
        results.append(vigia.check(wcfg, state, client))
    assert results == ["ok", "falhou", "alertou", "falhou", "voltou", "ok"]
    assert len(fake.sent) == 2 and fake.sent[0].startswith("🔴") and fake.sent[1].startswith("✅")


def test_vigia_without_whatsapp_only_records(cfg, tmp_path):
    fake = Fake()
    fake.up = False
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    for _ in range(3):
        vigia.check(cfg, tmp_path / "v.json", client)
    assert fake.sent == []
    assert json.loads((tmp_path / "v.json").read_text()) == {"failures": 3, "alerted": True}


def test_server_error_counts_as_down(wcfg, tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert vigia.check(wcfg, tmp_path / "v.json", client, url="http://127.0.0.1:8000/api/status") == "falhou"
