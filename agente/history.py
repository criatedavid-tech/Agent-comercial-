"""Histórico de conversas: cada pedido, resposta, ferramenta, bloqueio e custo, por sessão.

Fica em logs/conversas.db (SQLite). Serve para retomar conversas antigas e alimenta o painel
(gastos por dia, conversas recentes, bloqueios). O log em JSONL continua sendo gravado à parte.
"""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3


@dataclass
class Session:
    id: str
    title: str
    started: str
    updated: str
    requests: int
    cost_usd: float


@dataclass
class Record:
    kind: str  # "user", "text", "tool", "blocked", "result", "checkpoint"
    text: str
    ts: str


class History:
    def __init__(self, path: Path):
        self.path = path
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT, started TEXT, updated TEXT,
                    requests INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, kind TEXT, text TEXT,
                    cost_usd REAL DEFAULT 0, ts TEXT);
                CREATE INDEX IF NOT EXISTS events_session ON events (session_id, id);
                CREATE TABLE IF NOT EXISTS channels (key TEXT PRIMARY KEY, session_id TEXT, updated TEXT);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=10)) as con, con:
            yield con

    def record(self, session_id: str, kind: str, text: str, cost_usd: float = 0.0, ts: datetime | None = None) -> None:
        now = (ts or datetime.now()).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute(
                "INSERT INTO sessions (id, title, started, updated) VALUES (?, '', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated = excluded.updated",
                (session_id, now, now),
            )
            con.execute(
                "INSERT INTO events (session_id, kind, text, cost_usd, ts) VALUES (?, ?, ?, ?, ?)",
                (session_id, kind, text, cost_usd, now),
            )
            if kind == "user":
                con.execute(
                    "UPDATE sessions SET requests = requests + 1, title = CASE WHEN title = '' THEN ? ELSE title END "
                    "WHERE id = ?",
                    (text.strip().splitlines()[0][:80] if text.strip() else "(sem título)", session_id),
                )
            elif kind == "result":
                con.execute("UPDATE sessions SET cost_usd = cost_usd + ? WHERE id = ?", (cost_usd, session_id))

    def channel_session(self, key: str) -> str | None:
        """Conversa atual de um contato de canal (ex.: "whatsapp:5511999990000")."""
        with self._connect() as con:
            row = con.execute("SELECT session_id FROM channels WHERE key = ?", (key,)).fetchone()
        return row[0] if row and row[0] else None

    def set_channel_session(self, key: str, session_id: str | None) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO channels (key, session_id, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET session_id = excluded.session_id, updated = excluded.updated",
                (key, session_id, datetime.now().isoformat(timespec="seconds")),
            )

    def sessions(self, limit: int = 50) -> list[Session]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, title, started, updated, requests, cost_usd FROM sessions "
                "WHERE requests > 0 ORDER BY updated DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Session(*r) for r in rows]

    def events(self, session_id: str) -> list[Record]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT kind, text, ts FROM events WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
        return [Record(*r) for r in rows]

    def daily_costs(self, days: int = 30, today: datetime | None = None) -> list[dict]:
        """Gasto e número de pedidos por dia, incluindo dias sem uso (para o gráfico)."""
        today = (today or datetime.now()).date()
        start = today - timedelta(days=days - 1)
        with self._connect() as con:
            rows = con.execute(
                "SELECT substr(ts, 1, 10) AS day, SUM(cost_usd), SUM(kind = 'user') FROM events "
                "WHERE ts >= ? GROUP BY day",
                (start.isoformat(),),
            ).fetchall()
        by_day = {d: (c or 0.0, n or 0) for d, c, n in rows}
        out = []
        for i in range(days):
            day = (start + timedelta(days=i)).isoformat()
            cost, requests = by_day.get(day, (0.0, 0))
            out.append({"day": day, "cost_usd": round(cost, 4), "requests": requests})
        return out

    def blocked(self, limit: int = 20) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT e.text, e.ts, s.title FROM events e JOIN sessions s ON s.id = e.session_id "
                "WHERE e.kind = 'blocked' ORDER BY e.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"reason": r, "ts": ts, "conversation": title} for r, ts, title in rows]
