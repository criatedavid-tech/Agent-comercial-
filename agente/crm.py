"""CRM básico em SQLite (crm.db): contatos, interações e retornos combinados.

O atendente recebe uma `ContactView`, presa a um único telefone: as ferramentas dele não têm
como ler nem alterar outro contato, porque o telefone não é parâmetro de nada.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sqlite3

# Etapas do funil. O atendente só move entre as de ATTENDANT_STAGES: venda ganha é da equipe.
STAGES = ("novo", "qualificando", "qualificado", "orcamento", "ganho", "perdido")
ATTENDANT_STAGES = ("novo", "qualificando", "qualificado", "orcamento", "perdido")
# Campos do lead que o atendente preenche.
# subject: o que o cliente traz para a empresa (no auto center, o carro; o rótulo vem de empresa.toml).
LEAD_FIELDS = ("name", "subject", "interest", "need", "deadline", "budget", "location", "notes")
MAX_FIELD = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    phone TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT 'novo',
    subject TEXT NOT NULL DEFAULT '',
    interest TEXT NOT NULL DEFAULT '',
    need TEXT NOT NULL DEFAULT '',
    deadline TEXT NOT NULL DEFAULT '',
    budget TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    opt_in INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    ts TEXT NOT NULL,
    direction TEXT NOT NULL,  -- "entrada" (cliente), "saida" (atendente) ou "evento"
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS interactions_phone ON interactions(phone, id);
CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    due TEXT NOT NULL,  -- como o cliente combinou ("segunda de manhã") ou AAAA-MM-DD HH:MM
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    created TEXT NOT NULL
);
"""


def clean_phone(phone: str) -> str:
    """Telefone só com dígitos; contato simulado mantém o prefixo "sim-"."""
    phone = str(phone).strip()
    if phone.startswith("sim-"):
        return "sim-" + re.sub(r"[^0-9a-z]", "", phone[4:].lower())
    return re.sub(r"\D", "", phone)


@dataclass
class Contact:
    phone: str
    name: str
    origin: str
    stage: str
    subject: str
    interest: str
    need: str
    deadline: str
    budget: str
    location: str
    notes: str
    opt_in: bool
    created: str
    updated: str

    def describe(self, subject_label: str = "objeto") -> str:
        labels = {"name": "nome", "subject": subject_label, "interest": "interesse", "need": "necessidade", "deadline": "prazo",
                  "budget": "orçamento do cliente", "location": "local", "notes": "observações"}
        rows = [f"etapa: {self.stage}"]
        rows += [f"{labels[f]}: {getattr(self, f)}" for f in LEAD_FIELDS if getattr(self, f)]
        return "\n".join(rows)


@dataclass
class Interaction:
    ts: str
    direction: str
    text: str


@dataclass
class Followup:
    id: int
    phone: str
    due: str
    reason: str
    status: str
    created: str


class Crm:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.executescript(SCHEMA)
            # Bancos criados antes de uma coluna existir ganham a coluna (o CREATE TABLE não mexe neles).
            columns = {r["name"] for r in db.execute("PRAGMA table_info(contacts)")}
            for name in LEAD_FIELDS:
                if name not in columns:
                    db.execute(f"ALTER TABLE contacts ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def ensure(self, phone: str, origin: str = "", opt_in: bool = False) -> Contact:
        """Cria o contato se não existir. Quem inicia a conversa conta como opt-in para ela."""
        phone = clean_phone(phone)
        if not phone:
            raise ValueError("telefone vazio")
        now = self._now()
        with closing(self._db()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO contacts (phone, origin, opt_in, created, updated) VALUES (?, ?, ?, ?, ?)",
                (phone, origin, int(opt_in), now, now),
            )
            if opt_in:
                db.execute("UPDATE contacts SET opt_in = 1 WHERE phone = ?", (phone,))
        return self.get(phone)  # type: ignore[return-value]

    def get(self, phone: str) -> Contact | None:
        with closing(self._db()) as db:
            row = db.execute("SELECT * FROM contacts WHERE phone = ?", (clean_phone(phone),)).fetchone()
        return _contact(row) if row else None

    def update(self, phone: str, stage: str = "", allowed_stages: tuple[str, ...] = STAGES,
               **fields: str) -> Contact:
        """Atualiza campos do lead. Campo vazio não apaga o que já existe."""
        unknown = set(fields) - set(LEAD_FIELDS)
        if unknown:
            raise ValueError(f"campo desconhecido: {', '.join(sorted(unknown))}")
        if stage and stage not in allowed_stages:
            raise ValueError(f"etapa '{stage}' não permitida; use uma de: {', '.join(allowed_stages)}")
        values = {k: str(v).strip()[:MAX_FIELD] for k, v in fields.items() if str(v or "").strip()}
        if stage:
            values["stage"] = stage
        phone = clean_phone(phone)
        if values:
            sets = ", ".join(f"{k} = ?" for k in values)
            with closing(self._db()) as db, db:
                found = db.execute(f"UPDATE contacts SET {sets}, updated = ? WHERE phone = ?",
                                   (*values.values(), self._now(), phone)).rowcount
            if not found:
                raise ValueError("contato não existe")
        contact = self.get(phone)
        if not contact:
            raise ValueError("contato não existe")
        return contact

    def log(self, phone: str, direction: str, text: str) -> None:
        with closing(self._db()) as db, db:
            db.execute("INSERT INTO interactions (phone, ts, direction, text) VALUES (?, ?, ?, ?)",
                       (clean_phone(phone), self._now(), direction, text))

    def interactions(self, phone: str, limit: int = 200) -> list[Interaction]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT ts, direction, text FROM (SELECT * FROM interactions WHERE phone = ? ORDER BY id DESC LIMIT ?)"
                " ORDER BY id", (clean_phone(phone), limit)).fetchall()
        return [Interaction(r["ts"], r["direction"], r["text"]) for r in rows]

    def add_followup(self, phone: str, due: str, reason: str) -> Followup:
        due, reason = str(due).strip()[:100], str(reason).strip()[:MAX_FIELD]
        if not due:
            raise ValueError("falta quando")
        with closing(self._db()) as db, db:
            cur = db.execute("INSERT INTO followups (phone, due, reason, created) VALUES (?, ?, ?, ?)",
                             (clean_phone(phone), due, reason, self._now()))
            row = db.execute("SELECT * FROM followups WHERE id = ?", (cur.lastrowid,)).fetchone()
        return Followup(**dict(row))

    def followups(self, phone: str = "", status: str = "pendente") -> list[Followup]:
        query, params = "SELECT * FROM followups WHERE status = ?", [status]
        if phone:
            query += " AND phone = ?"
            params.append(clean_phone(phone))
        with closing(self._db()) as db:
            rows = db.execute(query + " ORDER BY id", params).fetchall()
        return [Followup(**dict(r)) for r in rows]

    def contacts(self, limit: int = 100) -> list[Contact]:
        with closing(self._db()) as db:
            rows = db.execute("SELECT * FROM contacts ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        return [_contact(r) for r in rows]

    def delete(self, phone: str) -> bool:
        """LGPD: apaga o contato, as interações e os retornos dele."""
        phone = clean_phone(phone)
        with closing(self._db()) as db, db:
            found = db.execute("DELETE FROM contacts WHERE phone = ?", (phone,)).rowcount
            db.execute("DELETE FROM interactions WHERE phone = ?", (phone,))
            db.execute("DELETE FROM followups WHERE phone = ?", (phone,))
        return bool(found)

    def view(self, phone: str) -> "ContactView":
        return ContactView(self, clean_phone(phone))


class ContactView:
    """O CRM visto por um único contato: é tudo o que o atendente daquela conversa recebe."""

    def __init__(self, crm: Crm, phone: str):
        self._crm = crm
        self._phone = phone

    @property
    def phone(self) -> str:
        return self._phone

    def get(self) -> Contact | None:
        return self._crm.get(self._phone)

    def update(self, stage: str = "", **fields: str) -> Contact:
        return self._crm.update(self._phone, stage=stage, allowed_stages=ATTENDANT_STAGES, **fields)

    def log(self, direction: str, text: str) -> None:
        self._crm.log(self._phone, direction, text)

    def add_followup(self, due: str, reason: str) -> Followup:
        return self._crm.add_followup(self._phone, due, reason)

    def followups(self) -> list[Followup]:
        return self._crm.followups(self._phone)


def _contact(row: sqlite3.Row) -> Contact:
    data = dict(row)
    data["opt_in"] = bool(data["opt_in"])
    return Contact(**data)
