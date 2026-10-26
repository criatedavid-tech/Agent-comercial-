"""Configuração lida do arquivo .env."""

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    model: str
    workdir: Path
    memory_dir: Path
    logs_dir: Path
    max_budget_usd: float
    max_turns: int


def load() -> Config:
    workdir = Path(os.getenv("AGENT_WORKDIR", "./workspace"))
    if not workdir.is_absolute():
        workdir = ROOT / workdir
    cfg = Config(
        model=os.getenv("AGENT_MODEL", "claude-opus-5-5"),
        workdir=workdir,
        memory_dir=ROOT / "memory",
        logs_dir=ROOT / "logs",
        max_budget_usd=float(os.getenv("AGENT_MAX_BUDGET_USD", "2.00")),
        max_turns=int(os.getenv("AGENT_MAX_TURNS", "40")),
    )
    for d in (cfg.workdir, cfg.memory_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
