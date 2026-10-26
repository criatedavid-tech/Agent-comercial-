"""Agenda: cálculo de recorrência, limites, execução das tarefas vencidas e caixa de entrada."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agente.core import agenda_tools
from agente.scheduler import (
    MAX_ACTIVE,
    SUMMARY_ID,
    AgendaStore,
    Scheduler,
    Task,
    next_run,
    scheduled_prompt,
)

TZ = ZoneInfo("America/Sao_Paulo")


def dt(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


@pytest.fixture
def store(tmp_path) -> AgendaStore:
    return AgendaStore(tmp_path / "agenda.db", "America/Sao_Paulo")


def task(**kw) -> Task:
    base = {"id": "t", "title": "Teste", "prompt": "faça algo"}
    return Task(**{**base, **kw})


# --- recorrência ---------------------------------------------------------------

def test_daily():
    t = task(kind="diaria", at="07:00")
    assert next_run(t, dt("2026-10-26 06:59")) == dt("2026-10-26 07:00")
    assert next_run(t, dt("2026-10-26 07:00")) == dt("2026-10-27 07:00")  # estritamente depois


def test_weekly():
    t = task(kind="semanal", at="09:00", weekdays="seg,qua")  # 2026-10-26 é segunda
    assert next_run(t, dt("2026-10-26 08:00")) == dt("2026-10-26 09:00")
    assert next_run(t, dt("2026-10-26 10:00")) == dt("2026-10-28 09:00")
    assert next_run(t, dt("2026-10-29 10:00")) == dt("2026-11-02 09:00")


def test_monthly_uses_last_day_in_short_months():
    t = task(kind="mensal", at="10:00", month_day=31)
    assert next_run(t, dt("2026-10-31 11:00")) == dt("2026-11-30 10:00")
    assert next_run(t, dt("2027-02-01 00:00")) == dt("2027-02-28 10:00")
    assert next_run(task(kind="mensal", at="10:00", month_day=5), dt("2026-12-06 00:00")) == dt("2027-01-05 10:00")


def test_once_and_interval():
    once = task(kind="uma_vez", at="15:00", on_date="2026-10-30")
    assert next_run(once, dt("2026-10-26 10:00")) == dt("2026-10-30 15:00")
    assert next_run(once, dt("2026-10-30 15:00")) is None
    assert next_run(task(kind="intervalo", interval_min=30), dt("2026-10-26 10:00")) == dt("2026-10-26 10:30")


@pytest.mark.parametrize("fields, error", [
    ({"kind": "diaria", "at": "7h"}, "HH:MM"),
    ({"kind": "diaria", "at": "24:00"}, "HH:MM"),
    ({"kind": "semanal", "at": "09:00", "weekdays": "segunda"}, "dias_semana"),
    ({"kind": "mensal", "at": "09:00", "month_day": 32}, "dia_mes"),
    ({"kind": "uma_vez", "at": "09:00", "on_date": "30/10/2026"}, "AAAA-MM-DD"),
    ({"kind": "intervalo", "interval_min": 5}, "intervalo mínimo"),
    ({"kind": "toda_hora", "at": "09:00"}, "tipo inválido"),
    ({"kind": "diaria", "at": "09:00", "mode": "email"}, "modo inválido"),
])
def test_validation(store, fields, error):
    with pytest.raises(ValueError, match=error):
        store.add(task(**fields))


def test_past_date_is_refused(store):
    with pytest.raises(ValueError, match="já passaram"):
        store.add(task(kind="uma_vez", at="10:00", on_date="2020-01-01"))


def test_active_task_limit(store):
    for i in range(MAX_ACTIVE):
        store.add(task(id=f"t{i}", kind="diaria", at="08:00"))
    with pytest.raises(ValueError, match="limite"):
        store.add(task(id="extra", kind="diaria", at="08:00"))
    store.cancel("t0")
    store.add(task(id="extra", kind="diaria", at="08:00"))


# --- armazenamento ------------------------------------------------------------

def test_add_list_cancel(store):
    store.add(task(id="a", kind="diaria", at="08:00"), now=dt("2026-10-26 09:00"))
    [saved] = store.list()
    assert saved.next_run == dt("2026-10-27 08:00")
    assert store.cancel("a") and not store.cancel("a")
    assert store.list() == [] and len(store.list(active_only=False)) == 1


def test_missed_runs_run_once_and_reschedule(store):
    store.add(task(id="a", kind="diaria", at="07:00"), now=dt("2026-10-20 06:00"))
    late = dt("2026-10-26 12:00")  # computador ficou desligado uma semana
    [due] = store.due(late)
    store.mark_ran(due, late)
    assert store.due(late) == []
    assert store.get("a").next_run == dt("2026-10-27 07:00")


def test_once_deactivates_after_running(store):
    store.add(task(id="a", kind="uma_vez", at="10:00", on_date="2026-10-27"), now=dt("2026-10-26 09:00"))
    [due] = store.due(dt("2026-10-27 10:00"))
    store.mark_ran(due, dt("2026-10-27 10:00"))
    assert store.list() == []


def test_daily_summary_follows_config(store):
    store.ensure_summary("07:00")
    assert store.get(SUMMARY_ID).at == "07:00"
    store.ensure_summary("08:30")
    assert store.get(SUMMARY_ID).at == "08:30" and len(store.list()) == 1
    store.ensure_summary("")
    assert store.list() == []


def test_inbox(store):
    t = store.add(task(id="a", kind="diaria", at="08:00"))
    item = store.add_inbox(t, "resultado")
    assert [i.text for i in store.unread()] == ["resultado"]
    store.mark_read([item.id])
    assert store.unread() == []


# --- executor -----------------------------------------------------------------

def test_scheduler_runs_due_tasks_and_delivers(store):
    store.add(task(id="tarefa", kind="diaria", at="07:00"), now=dt("2026-10-26 06:00"))
    store.add(task(id="lembrete", mode="lembrete", prompt="Beber água", kind="diaria", at="07:00"),
              now=dt("2026-10-26 06:00"))
    store.add(task(id="depois", kind="diaria", at="20:00"), now=dt("2026-10-26 06:00"))
    ran, delivered = [], []

    async def runner(t):
        ran.append(t.id)
        return f"feito: {t.title}"

    async def deliver(item):
        delivered.append((item.task_id, item.text))

    count = asyncio.run(Scheduler(store, runner, deliver).tick(dt("2026-10-26 07:00")))
    assert count == 2
    assert ran == ["tarefa"]  # lembrete não chama o agente
    assert sorted(delivered) == [("lembrete", "Beber água"), ("tarefa", "feito: Teste")]
    assert asyncio.run(Scheduler(store, runner, deliver).tick(dt("2026-10-26 07:00"))) == 0


def test_failed_task_is_reported_and_others_continue(store):
    store.add(task(id="a", kind="diaria", at="07:00"), now=dt("2026-10-26 06:00"))
    store.add(task(id="b", kind="diaria", at="07:00"), now=dt("2026-10-26 06:00"))
    delivered = []

    async def runner(t):
        if t.id == "a":
            raise RuntimeError("sem internet")
        return "ok"

    async def deliver(item):
        delivered.append((item.task_id, item.text))

    asyncio.run(Scheduler(store, runner, deliver).tick(dt("2026-10-26 07:00")))
    assert ("a", "A tarefa falhou: RuntimeError: sem internet") in delivered
    assert ("b", "ok") in delivered


def test_scheduled_prompt_explains_context():
    t = task(kind="semanal", at="09:00", weekdays="seg", prompt="Revise meus gastos.")
    text = scheduled_prompt(t, dt("2026-10-26 09:00"))
    assert "toda semana (seg) às 09:00" in text and "2026-10-26 09:00" in text
    assert text.endswith("Revise meus gastos.")


# --- ferramentas do agente ----------------------------------------------------

def call(tools, name, args):
    tool = next(t for t in tools if t.name == name)
    reply = asyncio.run(tool.handler(args))
    return reply["is_error"], reply["content"][0]["text"]


def test_agenda_tools(store):
    tools = agenda_tools(store)
    args = {"titulo": "Revisar gastos", "instrucao": "Some os gastos da semana.", "modo": "tarefa",
            "tipo": "semanal", "hora": "09:00", "dias_semana": "seg", "dia_mes": 0, "data": "", "intervalo_min": 0}
    error, text = call(tools, "agendar_tarefa", args)
    assert not error and "toda semana (seg) às 09:00" in text
    task_id = text.split("[")[1].split("]")[0]

    error, text = call(tools, "listar_tarefas", {})
    assert task_id in text and "Revisar gastos" in text

    error, text = call(tools, "agendar_tarefa", {**args, "tipo": "intervalo", "intervalo_min": 1})
    assert error and "intervalo mínimo" in text

    assert call(tools, "cancelar_tarefa", {"id": task_id}) == (False, f"cancelada: {task_id}")
    assert call(tools, "cancelar_tarefa", {"id": task_id})[0] is True
    assert call(tools, "listar_tarefas", {})[1] == "nenhuma tarefa agendada"
