"""Configuração lida do arquivo .env."""

from dataclasses import dataclass
from pathlib import Path
import os
import re

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
    base_url: str = ""  # vazio = API da Anthropic; ex. https://openrouter.ai/api
    auth_token: str = ""  # token do provedor alternativo
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_allowed: tuple[str, ...] = ()  # números com DDI, só dígitos; o primeiro é o dono
    whatsapp_api_version: str = "v26.0"

    @property
    def has_credentials(self) -> bool:
        """Tem como falar com um modelo: chave da Anthropic ou token de provedor alternativo."""
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip() or (self.base_url and self.auth_token))

    @property
    def whatsapp_enabled(self) -> bool:
        return all((self.whatsapp_token, self.whatsapp_phone_id, self.whatsapp_verify_token,
                    self.whatsapp_app_secret, self.whatsapp_allowed))


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
        base_url=os.getenv("AGENT_BASE_URL", "").strip(),
        auth_token=os.getenv("AGENT_AUTH_TOKEN", "").strip(),
        whatsapp_token=os.getenv("WHATSAPP_TOKEN", "").strip(),
        whatsapp_phone_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip(),
        whatsapp_app_secret=os.getenv("WHATSAPP_APP_SECRET", "").strip(),
        whatsapp_allowed=tuple(
            re.sub(r"\D", "", n) for n in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if re.sub(r"\D", "", n)
        ),
        whatsapp_api_version=os.getenv("WHATSAPP_API_VERSION", "v26.0").strip(),
    )
    for d in (cfg.workdir, cfg.memory_dir, cfg.knowledge_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg
