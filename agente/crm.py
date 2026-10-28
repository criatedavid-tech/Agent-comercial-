"""CRM básico em SQLite (crm.db): contatos, interações, retornos combinados, pedidos de não contato
e passagem para a equipe (`handoff`: o cliente chamou uma pessoa e o assistente fica quieto).

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
# Passagem para a equipe: "" (com o assistente), "aguardando" (chamou a equipe) ou "humano" (alguém assumiu).
HANDOFF_STATES = ("", "aguardando", "humano")
# Colunas que não são campos do lead, criadas em bancos antigos por _migrate().
EXTRA_COLUMNS = {
    "contacts": {"opt_out": "INTEGER NOT NULL DEFAULT 0", "handoff": "TEXT NOT NULL DEFAULT ''",
                 "handoff_reason": "TEXT NOT NULL DEFAULT ''", "handoff_at": "TEXT NOT NULL DEFAULT ''",
                 "assignee": "TEXT NOT NULL DEFAULT ''"},
    "followups": {"due_at": "TEXT"},
}

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
    opt_out INTEGER NOT NULL DEFAULT 0,  -- pediu para não receber mensagens da empresa
    handoff TEXT NOT NULL DEFAULT '',  -- '', 'aguardando' ou 'humano' (HANDOFF_STATES)
    handoff_reason TEXT NOT NULL DEFAULT '',
    handoff_at TEXT NOT NULL DEFAULT '',  -- quando chamou a equipe ou quando alguém assumiu
    assignee TEXT NOT NULL DEFAULT '',  -- quem assumiu: número da equipe ou "painel"
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    ts TEXT NOT NULL,
    direction TEXT NOT NULL,  -- "entrada" (cliente), "saida" (atendente), "humano" (equipe), "retomada" ou "evento"
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS interactions_phone ON interactions(phone, id);
CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    due TEXT NOT NULL,  -- como o cliente combinou ("segunda de manhã") ou AAAA-MM-DD HH:MM
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    created TEXT NOT NULL,
    due_at TEXT  -- a data de `due` entendida pelo código (parse_when); vazia = a equipe decide
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
    opt_out: bool = False
    handoff: str = ""
    handoff_reason: str = ""
    handoff_at: str = ""
    assignee: str = ""
    ticket: int = 0  # número curto do contato, para a equipe dizer "ASSUMIR 12"

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
    due_at: str | None = None


@dataclass
class Silence:
    """Onde a conversa de um contato parou: a base para decidir uma retomada."""

    last_inbound: datetime | None  # última mensagem do cliente
    last_outbound: datetime | None  # última mensagem da empresa (resposta ou retomada)
    attempts: int  # retomadas enviadas desde a última mensagem do cliente
    last_attempt: datetime | None

    @property
    def waiting_customer(self) -> bool:
        """A empresa falou por último: quem está devendo resposta é o cliente."""
        return bool(self.last_inbound and self.last_outbound and self.last_outbound >= self.last_inbound)


class Crm:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.executescript(SCHEMA)
            # Bancos criados antes de uma coluna existir ganham a coluna (o CREATE TABLE não mexe neles).
            wanted = {"contacts": {f: "TEXT NOT NULL DEFAULT ''" for f in LEAD_FIELDS}}
            for table, extra in EXTRA_COLUMNS.items():
                wanted.setdefault(table, {}).update(extra)
            for table, cols in wanted.items():
                columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
                for name, ddl in cols.items():
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

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
            row = db.execute(f"{SELECT} WHERE phone = ?", (clean_phone(phone),)).fetchone()
        return _contact(row) if row else None

    def by_ticket(self, ticket: int) -> Contact | None:
        with closing(self._db()) as db:
            row = db.execute(f"{SELECT} WHERE rowid = ?", (ticket,)).fetchone()
        return _contact(row) if row else None

    def set_handoff(self, phone: str, state: str, reason: str = "", assignee: str = "") -> None:
        """Muda a passagem para a equipe. Voltar para o assistente ("") limpa motivo e responsável."""
        if state not in HANDOFF_STATES:
            raise ValueError(f"estado desconhecido: {state}")
        with closing(self._db()) as db, db:
            if state:
                db.execute("UPDATE contacts SET handoff = ?, handoff_reason = CASE WHEN ? = '' THEN handoff_reason "
                           "ELSE ? END, handoff_at = ?, assignee = ?, updated = ? WHERE phone = ?",
                           (state, reason, str(reason)[:MAX_FIELD], self._now(), assignee, self._now(), clean_phone(phone)))
            else:
                db.execute("UPDATE contacts SET handoff = '', handoff_reason = '', handoff_at = '', assignee = '', "
                           "updated = ? WHERE phone = ?", (self._now(), clean_phone(phone)))

    def handoffs(self) -> list[Contact]:
        """Clientes com a equipe (chamaram ou já atendidos por alguém), os mais antigos primeiro."""
        with closing(self._db()) as db:
            rows = db.execute(f"{SELECT} WHERE handoff != '' ORDER BY handoff_at").fetchall()
        return [_contact(r) for r in rows]

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

    def log(self, phone: str, direction: str, text: str, ts: datetime | None = None) -> None:
        when = ts.isoformat(timespec="seconds") if ts else self._now()
        with closing(self._db()) as db, db:
            db.execute("INSERT INTO interactions (phone, ts, direction, text) VALUES (?, ?, ?, ?)",
                       (clean_phone(phone), when, direction, text))

    def silence(self, phone: str) -> Silence:
        """Última mensagem de cada lado e quantas retomadas já foram desde que o cliente falou."""
        last_in = last_out = last_attempt = None
        attempts = 0
        for i in self.interactions(phone, limit=500):
            ts = datetime.fromisoformat(i.ts)
            if i.direction == "entrada":
                last_in, attempts, last_attempt = ts, 0, None
            elif i.direction in ("saida", "humano", "retomada"):
                last_out = ts
                if i.direction == "retomada":
                    attempts, last_attempt = attempts + 1, ts
        return Silence(last_in, last_out, attempts, last_attempt)

    def set_opt_out(self, phone: str, value: bool = True) -> None:
        """Pedido do cliente para não receber mensagens (LGPD e regra da Meta): vale até ele pedir de novo."""
        with closing(self._db()) as db, db:
            db.execute("UPDATE contacts SET opt_out = ?, updated = ? WHERE phone = ?",
                       (int(value), self._now(), clean_phone(phone)))

    def close_followup(self, followup_id: int, status: str) -> None:
        with closing(self._db()) as db, db:
            db.execute("UPDATE followups SET status = ? WHERE id = ?", (status, followup_id))

    def interactions(self, phone: str, limit: int = 200) -> list[Interaction]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT ts, direction, text FROM (SELECT * FROM interactions WHERE phone = ? ORDER BY id DESC LIMIT ?)"
                " ORDER BY id", (clean_phone(phone), limit)).fetchall()
        return [Interaction(r["ts"], r["direction"], r["text"]) for r in rows]

    def add_followup(self, phone: str, due: str, reason: str, due_at: datetime | None = None) -> Followup:
        due, reason = str(due).strip()[:100], str(reason).strip()[:MAX_FIELD]
        if not due:
            raise ValueError("falta quando")
        when = due_at.isoformat(timespec="minutes") if due_at else None
        with closing(self._db()) as db, db:
            cur = db.execute("INSERT INTO followups (phone, due, reason, created, due_at) VALUES (?, ?, ?, ?, ?)",
                             (clean_phone(phone), due, reason, self._now(), when))
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
            rows = db.execute(f"{SELECT} ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
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


SELECT = "SELECT rowid AS ticket, * FROM contacts"


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

    def add_followup(self, due: str, reason: str, due_at: datetime | None = None) -> Followup:
        return self._crm.add_followup(self._phone, due, reason, due_at)

    def followups(self) -> list[Followup]:
        return self._crm.followups(self._phone)

    def set_handoff(self, state: str, reason: str = "") -> None:
        """O atendente só chama a equipe ("aguardando"); assumir e devolver é da equipe."""
        if state != "aguardando":
            raise ValueError("o assistente só pode chamar a equipe")
        self._crm.set_handoff(self._phone, state, reason)


def _contact(row: sqlite3.Row) -> Contact:
    data = dict(row)
    data["opt_in"] = bool(data["opt_in"])
    data["opt_out"] = bool(data.get("opt_out", 0))
    return Contact(**data)
