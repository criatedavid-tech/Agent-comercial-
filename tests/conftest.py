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
    )
    for d in (c.workdir, c.memory_dir, c.knowledge_dir, c.logs_dir):
        d.mkdir(parents=True)
    return c
