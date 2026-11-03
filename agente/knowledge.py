"""Base de conhecimento por áreas: notas em Markdown + índice de busca (SQLite FTS5).

Camadas:
- cache: `summary()` vai no system prompt (o que existe em cada área);
- busca: `search()` devolve só as notas relevantes para a pergunta (RAG);
- arquivo: uma nota .md por item em conhecimento/<área>/, editável à mão.
"""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import unicodedata

AREAS = {
    "financas": "dinheiro, gastos, orçamento, investimentos, contas, impostos, compras",
    "saude": "exames, consultas, remédios, sintomas, treino, alimentação, sono",
    "lazer": "viagens, passeios, restaurantes, hobbies, eventos, descanso",
    "entretenimento": "filmes, séries, músicas, jogos, livros de ficção, criadores que segue",
    "estudos": "estudos de um nicho específico (programação, idiomas, marketing...); exige `nicho`",
    "geral": "conhecimento que não se encaixa nas outras áreas",
}

# Palavras que não ajudam a achar nada (a busca usa as demais).
STOPWORDS = set(
    "a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem e ou que "
    "qual quais quanto quanta quantos quantas como quando onde meu minha meus minhas eu me se "
    "é foi ser ter tem tenho já não sim mais menos sobre isso esse essa este esta".split()
)

# Bloqueio feito no código, não no prompt: segredos nunca vão para a base.
SECRETS = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "CPF"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "número de cartão"),
    (re.compile(r"(?i)\b(senha|password|token|api[_ -]?key)\s*[:=]\s*\S+"), "senha ou chave"),
]


# Na conversa com o operador só senha e cartão saem (CPF pode ser dado de trabalho, ex. um cliente).
REDACT = [
    (re.compile(r"(?i)\b(senha|password|pass|pin)(\s*[:=]\s*|\s+(?:é|e|eh)\s+)\S+"), "senha"),
    (re.compile(r"(?i)\b([\w.+-]+@[\w-]+\.[\w.]+)\s*/\s*\S+"), "senha"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "número de cartão"),
]


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Tira senhas ("senha: x", "email / senha") e números de cartão; diz o que tirou."""
    removed: list[str] = []

    def cut(name: str, keep: int):
        def sub(m: re.Match) -> str:
            if name == "número de cartão" and not _luhn(re.sub(r"\D", "", m.group())):
                return m.group()
            if name not in removed:
                removed.append(name)
            return (m.group(1) + (m.group(2) if keep == 2 else " / ") if keep else "") + "[removido]"
        return sub

    for (pattern, name), keep in zip(REDACT, (2, 1, 0)):
        text = pattern.sub(cut(name, keep), text)
    return text, removed


@dataclass
class Hit:
    area: str
    title: str
    path: Path
    content: str


def slugify(text: str, size: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:size] or "nota"


def find_secret(text: str) -> str | None:
    for pattern, name in SECRETS:
        for match in pattern.finditer(text):
            if name != "número de cartão" or _luhn(re.sub(r"\D", "", match.group())):
                return name
    return None


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


class KnowledgeBase:
    def __init__(self, root: Path):
        self.root = root
        self.db = root / "indice.db"
        for area in AREAS:
            (root / area).mkdir(parents=True, exist_ok=True)
        self.reindex()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Abre o índice, faz commit ao sair e fecha a conexão."""
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS notas USING fts5("
                "path UNINDEXED, area UNINDEXED, nicho, title, tags, body, mtime UNINDEXED,"
                " tokenize='unicode61 remove_diacritics 2')"
            )
            yield con

    def reindex(self) -> None:
        """Reconstrói o índice a partir dos arquivos (pega edições feitas à mão)."""
        with self._connect() as con:
            con.execute("DELETE FROM notas")
            for path in self.root.glob("*/**/*.md"):
                self._index(con, path)

    def _index(self, con: sqlite3.Connection, path: Path) -> None:
        meta, body = _parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(self.root)
        con.execute("DELETE FROM notas WHERE path = ?", (str(rel),))
        con.execute(
            "INSERT INTO notas VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(rel),
                rel.parts[0],
                rel.parts[1] if len(rel.parts) > 2 else "",
                meta.get("titulo", path.stem),
                meta.get("tags", ""),
                body,
                path.stat().st_mtime,
            ),
        )

    def save(self, area: str, title: str, content: str, tags: str = "", nicho: str = "", source: str = "") -> Path:
        if area not in AREAS:
            raise ValueError(f"área inválida: {area}. Use uma de: {', '.join(AREAS)}")
        secret = find_secret(f"{title}\n{content}")
        if secret:
            raise ValueError(f"não salvei: o texto parece conter {secret}. Remova o dado e tente de novo.")
        folder = self.root / area
        if area == "estudos":
            folder /= slugify(nicho or "outros", 40)
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = folder / f"{now:%Y-%m-%d}-{slugify(title)}.md"
        n = 2
        while path.exists():
            path = folder / f"{now:%Y-%m-%d}-{slugify(title)}-{n}.md"
            n += 1
        header = [f"titulo: {title}", f"data: {now:%Y-%m-%d %H:%M}", f"area: {area}"]
        if area == "estudos":
            header.append(f"nicho: {folder.name}")
        if tags:
            header.append(f"tags: {tags}")
        if source:
            header.append(f"fonte: {source}")
        path.write_text("---\n" + "\n".join(header) + "\n---\n\n" + content.strip() + "\n", encoding="utf-8")
        with self._connect() as con:
            self._index(con, path)
        return path

    def search(self, query: str, area: str = "", limit: int = 5) -> list[Hit]:
        words = [w for w in re.findall(r"\w+", query.lower()) if w not in STOPWORDS]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        sql = "SELECT path, area, title, body FROM notas WHERE notas MATCH ?"
        args: list = [match]
        if area:
            sql += " AND area = ?"
            args.append(area)
        sql += " ORDER BY bm25(notas, 0, 0, 2.0, 5.0, 3.0, 1.0, 0) LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            rows = con.execute(sql, args).fetchall()
        return [Hit(a, t, self.root / p, b) for p, a, t, b in rows]

    def stats(self) -> dict[str, int]:
        """Quantidade de notas por área."""
        with self._connect() as con:
            counts = dict(con.execute("SELECT area, COUNT(*) FROM notas GROUP BY area").fetchall())
        return {area: counts.get(area, 0) for area in AREAS}

    def recent(self, limit: int = 8) -> list[dict]:
        """Notas mais recentes de todas as áreas (para o painel)."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT area, nicho, title, path FROM notas ORDER BY mtime DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"area": a, "nicho": n, "title": t, "path": p} for a, n, t, p in rows]

    def summary(self, recent: int = 3) -> str:
        """Resumo curto para o system prompt: quantas notas e as mais recentes de cada área."""
        lines = []
        with self._connect() as con:
            for area in AREAS:
                rows = con.execute(
                    "SELECT title, nicho FROM notas WHERE area = ? ORDER BY mtime DESC", (area,)
                ).fetchall()
                line = f"- {area}: {len(rows)} nota(s)"
                if area == "estudos":
                    nichos = sorted({n for _, n in rows if n})
                    if nichos:
                        line += f"; nichos: {', '.join(nichos)}"
                if rows:
                    line += "; recentes: " + "; ".join(t for t, _ in rows[:recent])
                lines.append(line)
        return "\n".join(lines)


def _parse(text: str) -> tuple[dict[str, str], str]:
    """Separa o cabeçalho `---` (chave: valor) do corpo da nota."""
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, body.strip()
