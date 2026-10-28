"""Acessos aos sistemas da loja pelo navegador do agente: confere se continuam logados e avisa quando caem.

O navegador guarda os logins no perfil (navegador/), então a pessoa entra uma vez e o agente segue usando.
Os sites encerram a sessão de tempos em tempos; quando isso acontece, o código (sem modelo e sem custo):
- percebe na checagem periódica (`SessionWatch.tick`);
- avisa a equipe no WhatsApp e no painel com um link temporário para a tela remota do navegador,
  onde a pessoa entra de novo (ela digita a senha; o agente não vê nem guarda);
- segura o agente: `abrir_pagina` num sistema deslogado responde que o acesso caiu, em vez de
  deixar o agente batendo numa tela de login;
- avisa de novo depois de algumas horas se ninguém entrou, e avisa quando volta.

Cadastro em empresa/sistemas.toml (fora do git, como o resto de empresa/):

    [[sistema]]
    nome = "Sistema da oficina"
    endereco = "https://app.exemplo.com.br/painel"
    logado = "Sair"      # texto que só aparece na página com a sessão ativa (ex. "Sair", o nome do usuário)
"""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time
import tomllib
import unicodedata
from urllib.parse import urlparse

FILE = "sistemas.toml"
OK, OUT, ERROR, UNKNOWN = "ok", "deslogado", "erro", "desconhecido"
ERRORS_BEFORE_ALERT = 2  # site fora do ar por um instante não vira alarme
REMIND_AFTER = timedelta(hours=4)  # ninguém entrou de novo: lembra
LINK_MINUTES = 30
REMOTE_PATH = "/acesso-navegador"  # tela remota; pública pelo Caddy, protegida pelo link temporário

log = logging.getLogger(__name__)


class SystemsError(ValueError):
    """sistemas.toml com problema; a mensagem diz o quê."""


@dataclass(frozen=True)
class System:
    name: str
    url: str
    marker: str  # texto que só aparece logado

    @property
    def host(self) -> str:
        return (urlparse(self.url).hostname or "").lower()

    def owns(self, url: str) -> bool:
        host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        return bool(host) and (host == self.host or host.endswith("." + self.host))


@dataclass(frozen=True)
class Probe:
    """O que a checagem viu ao abrir o endereço do sistema."""
    url: str
    title: str
    text: str
    has_password: bool = False
    challenge: bool = False


@dataclass
class State:
    status: str = UNKNOWN
    since: str = ""  # desde quando está neste status (ISO)
    checked: str = ""  # última checagem (ISO)
    errors: int = 0  # falhas seguidas ao abrir o site
    alerted: str = ""  # quando avisou da queda atual; vazio = não avisou


def load_systems(company_dir: Path) -> list[System]:
    path = company_dir / FILE
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SystemsError(f"{FILE}: {e}") from None
    systems: list[System] = []
    for i, item in enumerate(data.get("sistema", []), 1):
        name = str(item.get("nome", "")).strip()
        url = str(item.get("endereco", item.get("url", ""))).strip()
        marker = str(item.get("logado", "")).strip()
        missing = [k for k, v in (("nome", name), ("endereco", url), ("logado", marker)) if not v]
        if missing:
            raise SystemsError(f"{FILE}, sistema {i}: falta {', '.join(missing)}")
        if not url.startswith(("http://", "https://")):
            raise SystemsError(f"{FILE}, sistema {name}: o endereço precisa começar com https://")
        if any(s.name.lower() == name.lower() for s in systems):
            raise SystemsError(f"{FILE}: o nome {name!r} aparece duas vezes")
        systems.append(System(name, url, marker))
    return systems


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def classify(probe: Probe, system: System) -> str:
    """Logado só quando o texto de logado aparece e a página não é verificação de robô."""
    if probe.challenge:
        return OUT
    return OK if _plain(system.marker) in _plain(f"{probe.title}\n{probe.text}") else OUT


class SessionStore:
    """Estado das sessões num JSON (logs/sessoes.json): o servidor escreve, as ferramentas do agente leem."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, State]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {name: State(**value) for name, value in raw.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def save(self, states: dict[str, State]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({n: asdict(s) for n, s in states.items()}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)


def blocked_message(url: str, systems: list[System], states: dict[str, State]) -> str:
    """Mensagem para o agente quando ele tenta abrir um sistema com o acesso caído; vazio = pode abrir."""
    for system in systems:
        if system.owns(url) and states.get(system.name, State()).status == OUT:
            return (f"o acesso ao {system.name} expirou e a equipe já foi avisada para entrar de novo. "
                    "Não tente fazer login nem contornar; diga ao usuário que o sistema volta assim que "
                    "alguém entrar pelo link do aviso (ou pelo painel, em Navegador).")
    return ""


def describe(systems: list[System], states: dict[str, State]) -> str:
    if not systems:
        return f"nenhum sistema cadastrado (empresa/{FILE})"
    labels = {OK: "logado", OUT: "deslogado (equipe avisada)", ERROR: "não abre (site fora do ar?)",
              UNKNOWN: "ainda não conferido"}
    lines = []
    for system in systems:
        state = states.get(system.name, State())
        when = f", conferido em {datetime.fromisoformat(state.checked):%d/%m %H:%M}" if state.checked else ""
        lines.append(f"- {system.name} ({system.host}): {labels.get(state.status, state.status)}{when}")
    return "\n".join(lines)


class RemoteAccess:
    """Links temporários para a tela remota do navegador. Guarda só o hash do código, em memória."""

    def __init__(self, minutes: int = LINK_MINUTES, clock: Callable[[], float] = time.time):
        self.minutes = minutes
        self.clock = clock
        self._tokens: dict[str, float] = {}

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self) -> str:
        now = self.clock()
        self._tokens = {h: exp for h, exp in self._tokens.items() if exp > now}
        token = secrets.token_urlsafe(32)
        self._tokens[self._hash(token)] = now + self.minutes * 60
        return token

    def valid(self, token: str) -> bool:
        expires = self._tokens.get(self._hash(token or ""))
        return expires is not None and expires > self.clock()


class SessionWatch:
    """Checagem periódica dos sistemas cadastrados, com aviso quando cai e quando volta."""

    def __init__(
        self,
        systems: list[System],
        probe: Callable[[str], Awaitable[Probe]],
        store: SessionStore,
        notify: Callable[[str, str], Awaitable[None]],
        link: Callable[[], str] | None = None,
    ):
        self.systems = systems
        self.probe = probe
        self.store = store
        self.notify = notify
        self.link = link
        self.paused = False

    def _login_hint(self) -> str:
        if self.link:
            return (f"Entre por este link (vale {LINK_MINUTES} min): {self.link()}\n"
                    "Você digita a senha; o agente não vê nem guarda.")
        return "Entre pelo painel do agente, em Navegador. Você digita a senha; o agente não vê nem guarda."

    async def check(self, system: System, state: State, now: datetime) -> str:
        """Confere um sistema e atualiza o estado. Devolve o que aconteceu: ok, caiu, lembrete, voltou, erro, fora."""
        try:
            result = classify(await self.probe(system.url), system)
        except Exception as e:  # site fora do ar, DNS, tempo esgotado
            log.info("checagem de %s falhou: %s", system.name, e)
            result = ERROR
        stamp = now.isoformat(timespec="seconds")
        state.checked = stamp
        previous = state.status
        if result == OK:
            event = "voltou" if state.alerted else "ok"
            if state.alerted:
                await self.notify(f"Acesso normalizado: {system.name}",
                                  f"O {system.name} voltou a funcionar e o agente já pode usar de novo.")
            state.status, state.errors, state.alerted = OK, 0, ""
        elif result == OUT:
            if previous == ERROR:
                state.alerted = ""  # o aviso anterior era de site fora do ar; este é outro problema
            state.status, state.errors = OUT, 0
            event = self._due(state, now, "caiu")
            if event != "fora":
                await self.notify(f"Login expirou: {system.name}",
                                  f"O acesso ao {system.name} saiu (a sessão do site expirou). "
                                  f"O agente parou de usar esse sistema até alguém entrar de novo.\n{self._login_hint()}")
                state.alerted = stamp
        else:
            state.errors += 1
            event = "erro"
            if state.errors >= ERRORS_BEFORE_ALERT:
                if previous == OUT:
                    state.alerted = ""
                state.status = ERROR
                if self._due(state, now, "caiu") != "fora":
                    await self.notify(f"Sistema fora do ar: {system.name}",
                                      f"Não consegui abrir o {system.name} ({system.url}) nas últimas checagens. "
                                      "Pode ser o site fora do ar ou a internet da VM.")
                    state.alerted = stamp
        if state.status != previous:
            state.since = stamp
        return event

    @staticmethod
    def _due(state: State, now: datetime, first: str) -> str:
        if not state.alerted:
            return first
        return "lembrete" if now - datetime.fromisoformat(state.alerted) >= REMIND_AFTER else "fora"

    async def tick(self, now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.now().astimezone()
        states = self.store.load()
        events = {}
        for system in self.systems:
            state = states.setdefault(system.name, State())
            events[system.name] = await self.check(system, state, now)
            self.store.save(states)  # a cada sistema: o agente já vê o bloqueio enquanto os outros são checados
        for name in [n for n in states if n not in {s.name for s in self.systems}]:
            del states[name]  # sistema descadastrado
        self.store.save(states)
        return events

    async def run_forever(self, interval_min: float) -> None:
        await asyncio.sleep(30)  # deixa o servidor terminar de subir
        while True:
            if not self.paused and self.systems:
                try:
                    await self.tick()
                except Exception:
                    log.exception("checagem dos acessos falhou")
            await asyncio.sleep(interval_min * 60)
