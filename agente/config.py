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
    knowledge_dir: Path
    logs_dir: Path
    max_budget_usd: float
    max_turns: int
    web_port: int
    help_timeout_min: float
    timezone: str
    daily_summary: str  # "HH:MM" ou vazio para desligar
    agenda_db: Path
    browser_profile: Path
    browser_headless: bool


def load() -> Config:
    workdir = Path(os.getenv("AGENT_WORKDIR", "./workspace"))
    if not workdir.is_absolute():
        workdir = ROOT / workdir
    cfg = Config(
        model=os.getenv("AGENT_MODEL", "claude-opus-5-5"),
        workdir=workdir,
        memory_dir=ROOT / "memory",
        knowledge_dir=ROOT / "conhecimento",
        logs_dir=ROOT / "logs",
        max_budget_usd=float(os.getenv("AGENT_MAX_BUDGET_USD", "2.00")),
        max_turns=int(os.getenv("AGENT_MAX_TURNS", "40")),
        web_port=int(os.getenv("AGENT_WEB_PORT", "8000")),
        help_timeout_min=float(os.getenv("AGENT_HELP_TIMEOUT_MIN", "10")),
        timezone=os.getenv("AGENT_TIMEZONE", "America/Sao_Paulo"),
        daily_summary=os.getenv("AGENT_DAILY_SUMMARY", "07:00").strip(),
        agenda_db=ROOT / "agenda.db",
        browser_profile=ROOT / "navegador",
        browser_headless=os.getenv("AGENT_BROWSER_HEADLESS", "false").strip().lower() in ("1", "true", "sim"),
    )
    for d in (cfg.workdir, cfg.memory_dir, cfg.knowledge_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
