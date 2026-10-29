"""Aprendizado dos sistemas da loja (iFood, ERP, banco...): o agente navega uma vez e da próxima vai direto.

Por sistema (pelo domínio do site) o agente guarda:
- anotações: o mapa do sistema ("relatório de vendas fica em Financeiro > Relatórios; o filtro de data é no topo");
- rotinas: a sequência de passos que deu certo para uma tarefa ("vendas do dia"), gravada do diário do navegador
  (`Browser.journal`). Os valores que mudam a cada vez (datas, números de pedido) viram parâmetros.

`executar_rotina` repete os passos no código, sem o modelo decidir passo a passo: mais rápido, mais barato e
sem errar o caminho. As travas do navegador continuam valendo (senha, cartão, botão de compra, HTTPS), porque a
repetição usa as mesmas funções `open`, `click` e `fill`. Se o site mudou e um passo não existe mais, a rotina
para ali e diz onde: o agente segue na mão e grava de novo.

Fica em `conhecimento/sistemas.db` (fora do git, entra no backup). Senha nunca entra: o navegador não preenche
campo de senha, então login não vira passo.
"""

from collections.abc import Awaitable, Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse

PARAM = re.compile(r"\{(\w+)\}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS routines (
    host TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, steps TEXT NOT NULL, params TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0, fail INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL,
    PRIMARY KEY (host, name)
);
"""


class LearningError(ValueError):
    """Pedido inválido (rotina inexistente, parâmetro faltando...): a mensagem diz o quê."""


def host_of(url: str) -> str:
    host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host.removeprefix("www.")


def _slug(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())[:60]


@dataclass
class Routine:
    host: str
    name: str
    description: str
    steps: list[dict]
    params: list[str]
    ok: int = 0
    fail: int = 0
    updated: str = ""

    def describe(self) -> str:
        args = f" (parâmetros: {', '.join(self.params)})" if self.params else ""
        track = f"; deu certo {self.ok}x, falhou {self.fail}x" if self.ok or self.fail else ""
        return f"- {self.name}{args}: {self.description} [{len(self.steps)} passos{track}]"


def describe_step(step: dict) -> str:
    if step["action"] == "open":
        return f"abrir {step['url']}"
    if step["action"] == "click":
        return f"clicar em \"{step['label']}\""
    return f"preencher \"{step['label']}\" com \"{step.get('value', '')}\"" + (" e Enter" if step.get("submit") else "")


def numbered(journal: Iterable[dict]) -> list[tuple[int, dict]]:
    return list(enumerate(journal, 1))


def parse_range(text: str, total: int) -> tuple[int, int]:
    """"3-9", "3", "" → intervalo de passos (1-based, inclusivo)."""
    text = (text or "").strip()
    if not text:
        return 1, total
    m = re.fullmatch(r"(\d+)\s*(?:-|a|até)\s*(\d+)", text) or re.fullmatch(r"(\d+)", text)
    if not m:
        raise LearningError("passos no formato '3-9'")
    start, end = int(m[1]), int(m[2] if m.lastindex == 2 else total)
    if not (1 <= start <= end <= total):
        raise LearningError(f"passos fora do diário: há {total} passos")
    return start, end


def parse_params(raw) -> dict[str, str]:
    """{"data": "01/10/2026"} ou "data=01/10/2026; pedido=123"."""
    if isinstance(raw, dict):
        return {str(k).strip(): str(v) for k, v in raw.items() if str(k).strip()}
    raw = str(raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            return parse_params(json.loads(raw))
        except ValueError:
            raise LearningError("parâmetros: JSON inválido") from None
    out = {}
    for part in re.split(r"[;\n]+", raw):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                out[re.sub(r"\W+", "_", k.strip().lower())] = v.strip()
    return out


def steps_from_journal(journal: list[dict], params: dict[str, str]) -> list[dict]:
    """Passos do diário com os valores do exemplo trocados por {parâmetro} (ex. a data que muda a cada vez)."""
    steps = []
    for entry in journal:
        step = dict(entry)
        for name, value in params.items():
            if not value:
                continue
            for field in ("value", "url"):
                if field in step and value in str(step[field]):
                    step[field] = str(step[field]).replace(value, "{" + name + "}")
        steps.append(step)
    return steps


def fill_in(step: dict, values: dict[str, str]) -> dict:
    out = dict(step)
    for field in ("value", "url", "label"):
        if field in out:
            missing = [p for p in PARAM.findall(str(out[field])) if p not in values]
            if missing:
                raise LearningError(f"falta o parâmetro {', '.join(missing)}")
            out[field] = PARAM.sub(lambda m: values[m[1]], str(out[field]))
    return out


class SystemMemory:
    """Mapa e rotinas por sistema, num SQLite."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.executescript(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def note(self, host: str, text: str) -> None:
        text = re.sub(r"\s+", " ", text).strip()[:500]
        if not host or not text:
            raise LearningError("falta o site ou a anotação")
        with closing(self._db()) as db, db:
            db.execute("INSERT INTO notes (host, text, created) VALUES (?, ?, ?)", (host, text, self._now()))

    def notes(self, host: str) -> list[str]:
        with closing(self._db()) as db:
            return [r["text"] for r in db.execute("SELECT text FROM notes WHERE host = ? ORDER BY id", (host,))]

    def save(self, host: str, name: str, description: str, steps: list[dict], params: list[str]) -> Routine:
        if not steps:
            raise LearningError("rotina sem passos")
        name = _slug(name)
        if not name:
            raise LearningError("falta o nome da rotina")
        with closing(self._db()) as db, db:
            db.execute("INSERT OR REPLACE INTO routines (host, name, description, steps, params, ok, fail, updated)"
                       " VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
                       (host, name, description.strip()[:300], json.dumps(steps, ensure_ascii=False),
                        json.dumps(params), self._now()))
        return self.routine(name, host)

    def routines(self, host: str = "") -> list[Routine]:
        query, args = "SELECT * FROM routines", ()
        if host:
            query, args = query + " WHERE host = ?", (host,)
        with closing(self._db()) as db:
            rows = db.execute(query + " ORDER BY host, name", args).fetchall()
        return [_routine(r) for r in rows]

    def routine(self, name: str, host: str = "") -> Routine:
        found = [r for r in self.routines(host) if r.name == _slug(name)]
        if not found:
            known = ", ".join(r.name for r in self.routines(host)) or "nenhuma"
            raise LearningError(f"não conheço a rotina '{name}'. Rotinas gravadas: {known}")
        if len(found) > 1:
            raise LearningError(f"há '{name}' em mais de um sistema: informe o site")
        return found[0]

    def mark(self, routine: Routine, ok: bool) -> None:
        column = "ok" if ok else "fail"
        with closing(self._db()) as db, db:
            db.execute(f"UPDATE routines SET {column} = {column} + 1, updated = ? WHERE host = ? AND name = ?",
                       (self._now(), routine.host, routine.name))

    def describe(self, host: str) -> str:
        notes, routines = self.notes(host), self.routines(host)
        if not notes and not routines:
            return ""
        lines = [f"📘 Já conheço {host}:"]
        lines += [f"- nota: {n}" for n in notes[-10:]]
        lines += [r.describe() for r in routines]
        if routines:
            lines.append("Para repetir uma rotina, use executar_rotina com o nome e os parâmetros: é mais rápido que navegar.")
        return "\n".join(lines)

    def hosts(self) -> list[str]:
        with closing(self._db()) as db:
            rows = db.execute("SELECT host FROM notes UNION SELECT host FROM routines ORDER BY 1").fetchall()
        return [r[0] for r in rows]


def _routine(row: sqlite3.Row) -> Routine:
    return Routine(row["host"], row["name"], row["description"], json.loads(row["steps"]), json.loads(row["params"]),
                   row["ok"], row["fail"], row["updated"])


async def replay(browser, routine: Routine, values: dict[str, str],
                 gate: Callable[[str], str] = lambda url: "") -> tuple[bool, str]:
    """Repete a rotina no navegador. Devolve (deu_certo, texto da página no fim ou onde parou)."""
    from .browser import BrowserError

    missing = [p for p in routine.params if p not in values]
    if missing:
        return False, f"faltam os parâmetros: {', '.join(missing)} (a rotina usa {', '.join(routine.params)})"
    page = ""
    for i, raw in enumerate(routine.steps, 1):
        step = fill_in(raw, values)
        try:
            if step["action"] == "open":
                blocked = gate(step["url"])
                if blocked:
                    raise BrowserError(blocked)
                page = await browser.open(step["url"])
            elif step["action"] == "click":
                page = await browser.click(await browser.find_ref(step["label"]))
            elif step["action"] == "fill":
                page = await browser.fill(await browser.find_ref(step["label"]), step.get("value", ""),
                                          bool(step.get("submit")))
            if "VERIFICAÇÃO DE ROBÔ OU LOGIN" in page:
                raise BrowserError("a página pediu login ou verificação (a sessão pode ter expirado)")
        except BrowserError as e:
            return False, (f"a rotina '{routine.name}' parou no passo {i} de {len(routine.steps)} "
                           f"({describe_step(step)}): {e}\nSiga daqui navegando normalmente; se der certo, "
                           "grave a rotina de novo com salvar_rotina (o site pode ter mudado).")
    return True, page if page.startswith("Página:") or page.startswith("Cliquei") else await browser.read()
