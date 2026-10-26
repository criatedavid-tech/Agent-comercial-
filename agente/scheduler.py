"""Proatividade: agenda de tarefas recorrentes, lembretes e resumo diário.

- `AgendaStore` guarda as tarefas e a caixa de entrada (resultados) em SQLite, que aguenta
  o terminal e o servidor web gravando ao mesmo tempo.
- `next_run()` calcula a próxima execução no código; o modelo só preenche os campos.
- `Scheduler` acorda periodicamente, roda o que venceu (uma tarefa por vez) e entrega o resultado.

Limites rígidos, no código: intervalo mínimo de 15 minutos e no máximo 30 tarefas ativas,
para uma tarefa mal configurada não gastar a API sem parar.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import closing, contextmanager
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

KINDS = ("uma_vez", "diaria", "semanal", "mensal", "intervalo")
MODES = ("tarefa", "lembrete")
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
MIN_INTERVAL_MIN = 15
MAX_ACTIVE = 30

SUMMARY_ID = "resumo-diario"
SUMMARY_PROMPT = """\
Monte o resumo do dia para o usuário, curto e em tópicos:
1. O que está agendado para hoje (use listar_tarefas).
2. O que entrou de novo na base de conhecimento e merece atenção (use buscar_conhecimento se precisar).
3. Pendências e lembretes que você conhece pela memória.
4. Uma sugestão prática para o dia, com base no perfil e nos objetivos do usuário.
Se não houver nada relevante em um item, pule o item."""


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    mode: str = "tarefa"  # "tarefa" roda o agente; "lembrete" só entrega o texto
    kind: str = "diaria"
    at: str = ""  # "HH:MM"
    weekdays: str = ""  # "seg,qua,sex"
    month_day: int = 0
    on_date: str = ""  # "AAAA-MM-DD"
    interval_min: int = 0
    next_run: datetime | None = None
    last_run: datetime | None = None
    active: bool = True

    def describe(self) -> str:
        """Recorrência em português, para o usuário e para o modelo."""
        if self.kind == "uma_vez":
            return f"uma vez em {self.on_date} às {self.at}"
        if self.kind == "diaria":
            return f"todo dia às {self.at}"
        if self.kind == "semanal":
            return f"toda semana ({self.weekdays}) às {self.at}"
        if self.kind == "mensal":
            return f"todo mês no dia {self.month_day} às {self.at}"
        return f"a cada {self.interval_min} minutos"


@dataclass
class InboxItem:
    id: int
    task_id: str
    title: str
    text: str
    created: datetime


def validate(task: Task) -> None:
    """Confere os campos antes de salvar; a mensagem de erro volta para o modelo corrigir."""
    if not task.title.strip() or not task.prompt.strip():
        raise ValueError("título e instrução são obrigatórios")
    if task.mode not in MODES:
        raise ValueError(f"modo inválido: {task.mode}. Use: {', '.join(MODES)}")
    if task.kind not in KINDS:
        raise ValueError(f"tipo inválido: {task.kind}. Use: {', '.join(KINDS)}")
    if task.kind != "intervalo" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", task.at):
        raise ValueError("hora deve ser HH:MM, ex. 07:00")
    if task.kind == "semanal":
        days = [d.strip() for d in task.weekdays.split(",") if d.strip()]
        if not days or any(d not in WEEKDAYS for d in days):
            raise ValueError(f"dias_semana deve ser uma lista de: {', '.join(WEEKDAYS)}")
    if task.kind == "mensal" and not 1 <= task.month_day <= 31:
        raise ValueError("dia_mes deve ser de 1 a 31")
    if task.kind == "uma_vez":
        try:
            date.fromisoformat(task.on_date)
        except ValueError:
            raise ValueError("data deve ser AAAA-MM-DD") from None
    if task.kind == "intervalo" and task.interval_min < MIN_INTERVAL_MIN:
        raise ValueError(f"o intervalo mínimo é {MIN_INTERVAL_MIN} minutos")


def next_run(task: Task, after: datetime) -> datetime | None:
    """Próxima execução estritamente depois de `after` (com fuso), ou None se não houver mais."""
    tz = after.tzinfo
    if task.kind == "intervalo":
        return after + timedelta(minutes=task.interval_min)
    hh, mm = map(int, task.at.split(":"))
    clock = time(hh, mm)

    def at(d: date) -> datetime:
        return datetime.combine(d, clock, tzinfo=tz)

    today = after.date()
    if task.kind == "uma_vez":
        when = at(date.fromisoformat(task.on_date))
        return when if when > after else None
    if task.kind == "diaria":
        when = at(today)
        return when if when > after else at(today + timedelta(days=1))
    if task.kind == "semanal":
        days = {WEEKDAYS.index(d.strip()) for d in task.weekdays.split(",") if d.strip()}
        for i in range(8):
            d = today + timedelta(days=i)
            if d.weekday() in days and at(d) > after:
                return at(d)
        return None
    # mensal: no mês curto, usa o último dia (dia 31 em fevereiro vira 28 ou 29)
    year, month = today.year, today.month
    for _ in range(13):
        day = min(task.month_day, calendar.monthrange(year, month)[1])
        when = at(date(year, month, day))
        if when > after:
            return when
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


class AgendaStore:
    def __init__(self, path: Path, timezone: str):
        self.path = path
        self.tz = ZoneInfo(timezone)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT, prompt TEXT, mode TEXT, kind TEXT, at TEXT,
                    weekdays TEXT, month_day INTEGER, on_date TEXT, interval_min INTEGER,
                    next_run TEXT, last_run TEXT, active INTEGER);
                CREATE TABLE IF NOT EXISTS inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, title TEXT, text TEXT,
                    created TEXT, read INTEGER DEFAULT 0);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as con, con:
            yield con

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # --- tarefas ---------------------------------------------------------------

    def add(self, task: Task, now: datetime | None = None) -> Task:
        validate(task)
        now = now or self.now()
        if task.id != SUMMARY_ID and len(self.list()) >= MAX_ACTIVE:
            raise ValueError(f"limite de {MAX_ACTIVE} tarefas ativas; cancele alguma antes")
        task.next_run = next_run(task, now)
        if task.next_run is None:
            raise ValueError("essa data e hora já passaram")
        task.active = True
        self._save(task)
        return task

    def _save(self, t: Task) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t.id, t.title, t.prompt, t.mode, t.kind, t.at, t.weekdays, t.month_day, t.on_date,
                 t.interval_min, _iso(t.next_run), _iso(t.last_run), int(t.active)),
            )

    def get(self, task_id: str) -> Task | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task(row) if row else None

    def list(self, active_only: bool = True) -> list[Task]:
        sql = "SELECT * FROM tasks" + (" WHERE active = 1" if active_only else "") + " ORDER BY next_run"
        with self._connect() as con:
            return [_task(r) for r in con.execute(sql)]

    def cancel(self, task_id: str) -> bool:
        with self._connect() as con:
            return con.execute("UPDATE tasks SET active = 0 WHERE id = ? AND active = 1", (task_id,)).rowcount > 0

    def due(self, now: datetime | None = None) -> list[Task]:
        now = now or self.now()
        return [t for t in self.list() if t.next_run and t.next_run <= now]

    def mark_ran(self, task: Task, now: datetime | None = None) -> None:
        """Agenda a próxima antes de rodar: se o processo cair no meio, não repete em loop.
        Execuções perdidas (computador desligado) rodam uma vez só, não uma por atraso."""
        now = now or self.now()
        task.last_run = now
        task.next_run = next_run(task, now)
        task.active = task.next_run is not None
        self._save(task)

    def ensure_summary(self, at: str) -> None:
        """Mantém o resumo diário conforme AGENT_DAILY_SUMMARY ("HH:MM" liga, vazio desliga)."""
        current = self.get(SUMMARY_ID)
        if not at:
            if current and current.active:
                self.cancel(SUMMARY_ID)
            return
        if current and current.active and current.at == at:
            return
        self.add(Task(SUMMARY_ID, "Resumo do dia", SUMMARY_PROMPT, kind="diaria", at=at))

    # --- caixa de entrada ------------------------------------------------------

    def add_inbox(self, task: Task, text: str) -> InboxItem:
        created = self.now()
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO inbox (task_id, title, text, created) VALUES (?, ?, ?, ?)",
                (task.id, task.title, text, _iso(created)),
            )
        return InboxItem(cur.lastrowid, task.id, task.title, text, created)

    def unread(self) -> list[InboxItem]:
        with self._connect() as con:
            rows = con.execute("SELECT id, task_id, title, text, created FROM inbox WHERE read = 0 ORDER BY id").fetchall()
        return [InboxItem(i, t, ti, tx, datetime.fromisoformat(c)) for i, t, ti, tx, c in rows]

    def mark_read(self, ids: list[int]) -> None:
        with self._connect() as con:
            con.executemany("UPDATE inbox SET read = 1 WHERE id = ?", [(i,) for i in ids])


def new_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30]
    return f"{slug or 'tarefa'}-{uuid.uuid4().hex[:4]}"


def scheduled_prompt(task: Task, now: datetime) -> str:
    return (
        f'Tarefa agendada "{task.title}" ({task.describe()}), rodando agora: {now:%Y-%m-%d %H:%M}.\n'
        "O usuário não está acompanhando: faça o trabalho sozinho e termine com um resultado curto, "
        "pronto para ele ler depois. Só use pedir_ajuda_humana se for indispensável.\n\n"
        f"{task.prompt}"
    )


class Scheduler:
    def __init__(
        self,
        store: AgendaStore,
        runner: Callable[[Task], Awaitable[str]],
        deliver: Callable[[InboxItem], Awaitable[None]],
        tick_seconds: float = 30,
    ):
        self.store = store
        self.runner = runner
        self.deliver = deliver
        self.tick_seconds = tick_seconds
        self.paused = False  # PARAR no WhatsApp: nada da agenda roda até CONTINUAR

    async def tick(self, now: datetime | None = None) -> int:
        """Roda as tarefas vencidas, uma por vez. Devolve quantas rodou."""
        if self.paused:
            return 0  # as vencidas esperam: rodam uma vez quando voltar
        tasks = self.store.due(now)
        for task in tasks:
            self.store.mark_ran(task, now)
            if task.mode == "lembrete":
                text = task.prompt  # lembrete não gasta API
            else:
                try:
                    text = await self.runner(task)
                except Exception as e:  # uma tarefa com erro não para as outras
                    log.exception("tarefa %s falhou", task.id)
                    text = f"A tarefa falhou: {type(e).__name__}: {e}"
            await self.deliver(self.store.add_inbox(task, text))
        return len(tasks)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("erro no agendador")
            await asyncio.sleep(self.tick_seconds)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _task(row: tuple) -> Task:
    (id_, title, prompt, mode, kind, at, weekdays, month_day, on_date, interval_min, nxt, last, active) = row
    return Task(
        id_, title, prompt, mode, kind, at, weekdays, month_day, on_date, interval_min,
        datetime.fromisoformat(nxt) if nxt else None,
        datetime.fromisoformat(last) if last else None,
        bool(active),
    )
