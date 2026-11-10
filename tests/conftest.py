"""Fixtures compartilhadas: configuração apontando para pastas temporárias."""

import pytest

from agente.config import Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    """Config isolada: nada é escrito nas pastas reais do projeto."""
    c = Config(
        model="claude-opus-5-5",
        workdir=tmp_path / "workspace",
        memory_dir=tmp_path / "memory",
        knowledge_dir=tmp_path / "conhecimento",
        logs_dir=tmp_path / "logs",
        max_budget_usd=1.0,
        max_turns=10,
        web_port=8000,
        help_timeout_min=0.01,
        timezone="America/Sao_Paulo",
        daily_summary="07:00",
        agenda_db=tmp_path / "agenda.db",
        browser_profile=tmp_path / "navegador",
        browser_headless=True,
        crm_db=tmp_path / "crm.db",
        brechas_db=tmp_path / "brechas.db",
        google_vault=tmp_path / "google.enc",
        google_key_file=tmp_path / "chave" / "chave-google",
    )
    for d in (c.workdir, c.memory_dir, c.knowledge_dir, c.logs_dir):
        d.mkdir(parents=True)
    return c
