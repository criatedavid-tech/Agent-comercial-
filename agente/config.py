"""Configuração lida do arquivo .env."""

from dataclasses import dataclass
from pathlib import Path
import os
import re

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
EXAMPLE_COMPANY = ROOT / "exemplos" / "empresa"  # empresa fictícia usada quando empresa/ ainda não existe
EXAMPLE_DATA = ROOT / "exemplos" / "dados"  # planilhas fictícias usadas quando dados/ ainda não existe


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
    whatsapp_provider: str = "meta"  # "meta" (API oficial) ou "uazapi" (não oficial, para testes)
    uazapi_url: str = ""  # endereço do servidor UAZAPI, ex. https://suaempresa.uazapi.com
    uazapi_token: str = ""  # token da instância (cabeçalho "token")
    uazapi_webhook_secret: str = ""  # segredo no caminho do webhook: /whatsapp/uazapi/<segredo>
    transcribe_audio: bool = True  # áudio vira texto (Whisper da OpenAI, pela UAZAPI)
    openai_api_key: str = ""  # chave da OpenAI só para transcrever áudio; vazia = a salva na instância UAZAPI
    company_dir: Path = EXAMPLE_COMPANY  # empresa.toml, catalogo.csv, faq.md, politicas.md
    crm_db: Path = ROOT / "crm.db"
    attendant_max_turns: int = 12  # passos por mensagem de cliente: o atendente responde rápido ou passa adiante
    attendant_whatsapp: bool = False  # números fora de WHATSAPP_ALLOWED_NUMBERS falam com o atendente
    data_dir: Path = EXAMPLE_DATA  # planilhas da loja para a gestão: vendas, despesas, estoque, caixa
    public_url: str = ""  # https://dominio da VM; vazio = links da tela remota só funcionam pelo túnel SSH
    access_check_min: float = 60  # de quantos em quantos minutos confere os logins dos sistemas da loja

    @property
    def has_credentials(self) -> bool:
        """Tem como falar com um modelo: chave da Anthropic ou token de provedor alternativo."""
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip() or (self.base_url and self.auth_token))

    @property
    def whatsapp_enabled(self) -> bool:
        if self.whatsapp_provider == "uazapi":
            return all((self.uazapi_url, self.uazapi_token, self.uazapi_webhook_secret, self.whatsapp_allowed))
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
        whatsapp_provider=whatsapp_provider(os.getenv("WHATSAPP_PROVEDOR", ""), os.getenv("UAZAPI_URL", "")),
        uazapi_url=os.getenv("UAZAPI_URL", "").strip().rstrip("/"),
        uazapi_token=os.getenv("UAZAPI_TOKEN", "").strip(),
        uazapi_webhook_secret=os.getenv("UAZAPI_WEBHOOK_SEGREDO", "").strip(),
        transcribe_audio=os.getenv("AGENT_TRANSCREVER_AUDIO", "true").strip().lower() in ("1", "true", "sim"),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        company_dir=company_dir(os.getenv("AGENT_EMPRESA_DIR", "").strip()),
        crm_db=ROOT / "crm.db",
        attendant_max_turns=int(os.getenv("AGENT_ATENDENTE_MAX_TURNS", "12")),
        data_dir=data_dir(os.getenv("AGENT_DADOS_DIR", "").strip()),
        public_url=os.getenv("AGENT_PUBLIC_URL", "").strip().rstrip("/"),
        access_check_min=float(os.getenv("AGENT_ACESSOS_MIN", "60")),
        attendant_whatsapp=os.getenv("AGENT_ATENDENTE_WHATSAPP", "false").strip().lower() in ("1", "true", "sim"),
    )
    for d in (cfg.workdir, cfg.memory_dir, cfg.knowledge_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg


def whatsapp_provider(value: str, uazapi_url: str) -> str:
    """WHATSAPP_PROVEDOR (meta ou uazapi); vazio: uazapi se UAZAPI_URL estiver preenchida, senão meta."""
    value = value.strip().lower()
    if value in ("meta", "uazapi"):
        return value
    return "uazapi" if uazapi_url.strip() else "meta"


def company_dir(value: str) -> Path:
    """Pasta da empresa: AGENT_EMPRESA_DIR, senão empresa/ do projeto, senão a empresa de exemplo."""
    if value:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path
    own = ROOT / "empresa"
    return own if (own / "empresa.toml").exists() else EXAMPLE_COMPANY


def data_dir(value: str) -> Path:
    """Pasta das planilhas: AGENT_DADOS_DIR, senão dados/ do projeto (se tiver algum .csv), senão o exemplo."""
    if value:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path
    own = ROOT / "dados"
    return own if any(own.glob("*.csv")) else EXAMPLE_DATA
