"""Histórico de conversas: sessões, eventos, gastos por dia e bloqueios."""

from datetime import datetime

import pytest

from agente.history import History


@pytest.fixture
def history(tmp_path) -> History:
    return History(tmp_path / "conversas.db")


def test_session_title_requests_and_cost(history):
    history.record("s1", "user", "Planilha de gastos\ncom detalhes")
    history.record("s1", "result", "ok", cost_usd=0.02)
    history.record("s1", "user", "agora em CSV")
    history.record("s1", "result", "ok", cost_usd=0.01)
    [s] = history.sessions()
    assert s.title == "Planilha de gastos"  # primeira linha do primeiro pedido
    assert s.requests == 2 and s.cost_usd == pytest.approx(0.03)


def test_sessions_ordered_by_last_update_and_hide_empty(history):
    history.record("velha", "user", "a", ts=datetime(2026, 10, 1, 9))
    history.record("nova", "user", "b", ts=datetime(2026, 10, 2, 9))
    history.record("so-checkpoint", "checkpoint", "x")  # sem pedido: não aparece
    assert [s.id for s in history.sessions()] == ["nova", "velha"]


def test_events_keep_order(history):
    for kind in ("user", "tool", "text", "result"):
        history.record("s", kind, kind)
    assert [e.kind for e in history.events("s")] == ["user", "tool", "text", "result"]


def test_daily_costs_fill_empty_days(history):
    history.record("s", "user", "a", ts=datetime(2026, 10, 24, 10))
    history.record("s", "result", "ok", cost_usd=0.5, ts=datetime(2026, 10, 24, 10))
    history.record("s", "user", "b", ts=datetime(2026, 10, 26, 10))
    history.record("s", "result", "ok", cost_usd=0.25, ts=datetime(2026, 10, 26, 10))
    days = history.daily_costs(days=3, today=datetime(2026, 10, 26))
    assert days == [
        {"day": "2026-10-24", "cost_usd": 0.5, "requests": 1},
        {"day": "2026-10-25", "cost_usd": 0.0, "requests": 0},
        {"day": "2026-10-26", "cost_usd": 0.25, "requests": 1},
    ]


def test_blocked_lists_reason_and_conversation(history):
    history.record("s", "user", "limpa tudo")
    history.record("s", "blocked", "comando bloqueado (apagar a raiz)")
    [b] = history.blocked()
    assert b["reason"] == "comando bloqueado (apagar a raiz)" and b["conversation"] == "limpa tudo"
