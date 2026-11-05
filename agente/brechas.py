"""Brechas: o que a empresa está perdendo ou deixando de ganhar, com evidência, valor e andamento.

Os alertas da gestão (`gestao.audit`) dizem o que está estranho; a brecha é o que se faz com isso: cada
achado vira uma ficha com a área, a evidência, o valor estimado (por mês, quando se repete; ou uma vez,
quando é um valor a recuperar) e o status, de "nova" até "resolvida". Fica em `brechas.db` (SQLite).

Regras no código, não só no prompt:
- sem evidência não há brecha (o modelo não registra palpite);
- quem registra (os especialistas) nunca muda o status; só o gerente, pela ferramenta de atualizar;
- o mesmo documento (NF 18777, boleto 4410...) no título não vira duas brechas;
- o valor é só uma estimativa para priorizar: nada aqui paga, transfere ou cobra.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3

from .empresa import brl, normalize

AREAS = ("financeiro", "comercial", "operacao")
STATUSES = ("nova", "proposta", "aprovada", "em_andamento", "resolvida", "descartada")
OPEN = ("nova", "proposta", "aprovada", "em_andamento")
MAX_VALUE = Decimal("10000000")  # R$ 10 milhões: acima disso é erro de digitação, não estimativa
LIMITS = {"title": 120, "evidence": 800, "action": 500, "note": 300}
# Documento citado no título: dois especialistas achando a mesma nota são uma brecha só.
DOCUMENT = re.compile(r"\b(nfs-?e|nf-?e|nf|nota fiscal|nota|boleto|documento|venda|nsu|pedido|os)\s*(?:n[ºo°.]*\s*)?[:#-]?\s*(\d{3,})", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS brechas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    area TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    monthly_cents INTEGER NOT NULL DEFAULT 0,  -- estimativa por mês, quando se repete
    once_cents INTEGER NOT NULL DEFAULT 0,  -- valor a recuperar uma vez
    status TEXT NOT NULL DEFAULT 'nova',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS brechas_status ON brechas(status, id);
CREATE TABLE IF NOT EXISTS brecha_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brecha_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    text TEXT NOT NULL
);
"""


class BrechaError(ValueError):
    """Pedido que não pode virar brecha (a mensagem diz o que corrigir)."""


@dataclass
class Brecha:
    id: int
    area: str
    title: str
    evidence: str
    action: str
    monthly_cents: int
    once_cents: int
    status: str
    created: str
    updated: str

    @property
    def monthly(self) -> Decimal:
        return Decimal(self.monthly_cents) / 100

    @property
    def once(self) -> Decimal:
        return Decimal(self.once_cents) / 100

    @property
    def weight(self) -> int:
        """Para ordenar: o que a brecha vale em um ano."""
        return self.monthly_cents * 12 + self.once_cents

    def value(self) -> str:
        parts = [f"{brl(self.monthly)}/mês" if self.monthly_cents else "", f"{brl(self.once)} uma vez" if self.once_cents else ""]
        return " + ".join(p for p in parts if p) or "sem valor estimado"

    def describe(self) -> str:
        action = f" · ação: {self.action[:160]}" if self.action else ""
        return f"#{self.id} [{self.status}] {self.area} · {self.title} · {self.value()}{action}"


def cents(value, field: str) -> int:
    """Valor em reais (número ou texto como 'R$ 1.234,56') para centavos; vazio é zero."""
    if value is None or str(value).strip() == "":
        return 0
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise BrechaError(f"{field}: '{value}' não é um valor em reais") from None
    if number < 0 or number > MAX_VALUE:
        raise BrechaError(f"{field}: {value} fora do limite (de 0 a {brl(MAX_VALUE)})")
    return int((number * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def documents(title: str) -> set[str]:
    """Documentos citados no título, com o tipo padronizado: "NF 18777" e "nota fiscal 18777" são o mesmo."""
    found = set()
    for m in DOCUMENT.finditer(title or ""):
        kind = re.sub(r"[^a-z]", "", normalize(m.group(1)))
        kind = "nota" if kind.startswith(("nf", "nota")) else kind
        found.add(kind + m.group(2))
    return found


def key_of(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(title)).strip("-")[:80]


class BrechaStore:
    def __init__(self, path: Path):
        self.path = path
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self):
        con = sqlite3.connect(self.path)
        return _Connection(con)

    def _row(self, row) -> Brecha:
        return Brecha(*row)

    COLUMNS = "id, area, title, evidence, action, monthly_cents, once_cents, status, created, updated"

    def get(self, brecha_id: int) -> Brecha | None:
        with self._connect() as con:
            row = con.execute(f"SELECT {self.COLUMNS} FROM brechas WHERE id = ?", (int(brecha_id),)).fetchone()
        return self._row(row) if row else None

    def notes(self, brecha_id: int) -> list[str]:
        with self._connect() as con:
            rows = con.execute("SELECT ts, text FROM brecha_notes WHERE brecha_id = ? ORDER BY id", (int(brecha_id),)).fetchall()
        return [f"{ts[:16].replace('T', ' ')} {text}" for ts, text in rows]

    def items(self, status: str = "", area: str = "") -> list[Brecha]:
        """Sem filtro de status: só as abertas. Ordem: o que vale mais em um ano primeiro."""
        wanted = (status,) if status else OPEN
        with self._connect() as con:
            marks = ",".join("?" * len(wanted))
            sql = f"SELECT {self.COLUMNS} FROM brechas WHERE status IN ({marks})" + (" AND area = ?" if area else "")
            rows = con.execute(sql, (*wanted, *([area] if area else []))).fetchall()
        return sorted((self._row(r) for r in rows), key=lambda b: (-b.weight, b.id))

    def register(self, title: str, area: str, evidence: str, action: str = "", monthly=None, once=None) -> tuple[Brecha, str]:
        """Cria a brecha, atualiza a aberta de mesmo título ou anota na que cita o mesmo documento.
        Devolve a brecha e o que aconteceu: "criada", "atualizada" ou "anotada"."""
        title, evidence, action = (str(v or "").strip() for v in (title, evidence, action))
        if area not in AREAS:
            raise BrechaError(f"área deve ser uma de: {', '.join(AREAS)}")
        if not title:
            raise BrechaError("dê um título curto à brecha")
        if not evidence:
            raise BrechaError("sem evidência não registro: diga de onde vem (ferramenta, período, linhas conferidas)")
        monthly_cents, once_cents = cents(monthly, "valor_mes"), cents(once, "valor_unico")
        title, evidence, action = title[:LIMITS["title"]], evidence[:LIMITS["evidence"]], action[:LIMITS["action"]]
        key, now = key_of(title), datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            open_rows = con.execute(f"SELECT {self.COLUMNS}, key FROM brechas WHERE status IN ({','.join('?' * len(OPEN))})", OPEN).fetchall()
            same = next((r for r in open_rows if r[-1] == key), None)
            if same:
                con.execute(
                    "UPDATE brechas SET area = ?, evidence = ?, action = CASE WHEN ? != '' THEN ? ELSE action END,"
                    " monthly_cents = CASE WHEN ? THEN ? ELSE monthly_cents END,"
                    " once_cents = CASE WHEN ? THEN ? ELSE once_cents END, updated = ? WHERE id = ?",
                    (area, evidence, action, action, monthly_cents, monthly_cents, once_cents, once_cents, now, same[0]))
                result = "atualizada"
            else:
                docs = documents(title)
                twin = next((r for r in open_rows if docs and docs & documents(r[2])), None)
                if twin:
                    con.execute("INSERT INTO brecha_notes (brecha_id, ts, text) VALUES (?, ?, ?)",
                                (twin[0], now, f"outro achado do mesmo documento: {title}. {evidence}"[:LIMITS["note"]]))
                    con.execute("UPDATE brechas SET updated = ? WHERE id = ?", (now, twin[0]))
                    same, result = twin, "anotada"
                else:
                    cur = con.execute(
                        "INSERT INTO brechas (key, area, title, evidence, action, monthly_cents, once_cents, status, created, updated)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, 'nova', ?, ?)",
                        (key, area, title, evidence, action, monthly_cents, once_cents, now, now))
                    same, result = (cur.lastrowid,), "criada"
        return self.get(same[0]), result

    def update(self, brecha_id: int, status: str = "", note: str = "") -> Brecha:
        """Muda o status e/ou acrescenta uma anotação. Só o gerente chama (ferramenta própria dele)."""
        brecha = self.get(brecha_id)
        if brecha is None:
            raise BrechaError(f"brecha {brecha_id} não existe: use listar_brechas")
        if status and status not in STATUSES:
            raise BrechaError(f"status deve ser um de: {', '.join(STATUSES)}")
        if not status and not note.strip():
            raise BrechaError("diga o novo status ou uma anotação")
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            if status:
                con.execute("UPDATE brechas SET status = ?, updated = ? WHERE id = ?", (status, now, brecha.id))
            if note.strip():
                con.execute("INSERT INTO brecha_notes (brecha_id, ts, text) VALUES (?, ?, ?)",
                            (brecha.id, now, note.strip()[:LIMITS["note"]]))
        return self.get(brecha.id)

    def summary(self) -> dict:
        open_ = self.items()
        return {
            "abertas": len(open_),
            "novas": sum(b.status == "nova" for b in open_),
            "mensal": sum((b.monthly for b in open_), Decimal(0)),
            "unico": sum((b.once for b in open_), Decimal(0)),
            "maior": next((b for b in open_ if b.status == "nova"), None),
        }

    def describe(self, status: str = "", area: str = "") -> str:
        found = self.items(status, area)
        if not found:
            return f"nenhuma brecha {status or 'aberta'}" + (f" em {area}" if area else "")
        monthly, once = sum((b.monthly for b in found), Decimal(0)), sum((b.once for b in found), Decimal(0))
        head = f"{len(found)} brecha(s) {status or 'abertas'}: {brl(monthly)}/mês recorrentes" + \
            (f" e {brl(once)} para recuperar uma vez" if once else "") + " (estimativas)."
        return "\n".join([head, *(b.describe() for b in found)])


class _Connection:
    """sqlite3 com commit ao sair do `with` e fechamento da conexão (o `with` puro do sqlite3 não fecha)."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, kind, error, tb):
        with closing(self.con):
            if kind is None:
                self.con.commit()
            else:
                self.con.rollback()
        return False
