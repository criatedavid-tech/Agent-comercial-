"""Reunião semanal com o dono: dia e hora, preparo e chamada na agenda, trava de turno e entrega silenciosa."""

import asyncio
from datetime import datetime
from string import Formatter
from zoneinfo import ZoneInfo

import pytest

from agente import reuniao
from agente.core import AGENDA_TOOLS, SYSTEM_PROMPT, agenda_tools
from agente.scheduler import MAX_ACTIVE, MEETING_ID, MEETING_PREP_ID, AgendaStore, Scheduler, Task

TZ = ZoneInfo("America/Sao_Paulo")
PAUTA = "workspace/reuniao-semanal.md"


@pytest.fixture
def store(tmp_path) -> AgendaStore:
    return AgendaStore(tmp_path / "agenda.db", "America/Sao_Paulo")


def tools_for(store, by_owner=None):
    return {t.name: t for t in agenda_tools(store, by_owner, PAUTA)}


def call(tool, args) -> tuple[str, bool]:
    out = asyncio.run(tool.handler(args))
    return out["content"][0]["text"], bool(out.get("is_error"))


# --- dia e hora -----------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("segunda", 0), ("Segunda-feira", 0), ("terça", 1), ("terca", 1), ("ter", 1), ("quarta-feira", 2),
    ("sexta", 4), ("sábado", 5), ("sabado", 5), ("domingo", 6), ("3", 3), ("x", None), ("", None), ("marte", None),
])
def test_parse_day(text, expected):
    assert reuniao.parse_day(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("9", "09:00"), ("9h", "09:00"), ("09:00", "09:00"), ("14h30", "14:30"), ("às 14:30", "14:30"),
    ("18 horas", "18:00"), ("25h", None), ("9:75", None), ("de manhã", None), ("", None),
])
def test_parse_hour(text, expected):
    assert reuniao.parse_hour(text) == expected


def test_prep_two_hours_before_or_eve_at_8pm():
    assert reuniao.prep_slot(1, "09:00") == (1, "07:00", False)
    assert reuniao.prep_slot(1, "14:30") == (1, "12:30", False)
    assert reuniao.prep_slot(1, "07:00") == (0, "20:00", True)  # 05:00 seria de madrugada: véspera
    assert reuniao.prep_slot(0, "06:30") == (6, "20:00", True)  # a véspera de segunda é domingo


# --- agenda ----------------------------------------------------------------------

def test_schedule_creates_prep_and_call(store):
    text = reuniao.schedule(store, "terça", "9h", PAUTA)
    assert "marcada" in text and "terça" in text and "09:00" in text
    call_task, prep = store.get(MEETING_ID), store.get(MEETING_PREP_ID)
    assert (call_task.kind, call_task.weekdays, call_task.at, call_task.mode) == ("semanal", "ter", "09:00", "tarefa")
    assert (prep.weekdays, prep.at) == ("ter", "07:00")
    assert PAUTA in prep.prompt and "(sem mensagem)" in prep.prompt
    assert "Nunca invente número" in prep.prompt
    assert reuniao.describe(store).startswith("Reunião semanal: toda terça às 09:00")


def test_schedule_again_changes_instead_of_duplicating(store):
    reuniao.schedule(store, "terça", "09:00", PAUTA)
    assert "atualizada" in reuniao.schedule(store, "sexta", "16h", PAUTA)
    assert [t.id for t in store.list()].count(MEETING_ID) == 1
    assert (store.get(MEETING_ID).weekdays, store.get(MEETING_ID).at) == ("sex", "16:00")
    assert (store.get(MEETING_PREP_ID).weekdays, store.get(MEETING_PREP_ID).at) == ("sex", "14:00")


@pytest.mark.parametrize("day, hour, error", [
    ("marte", "9h", "dia"), ("terça", "de manhã", "hora"), ("terça", "05:00", "fora do horário"),
    ("terça", "23:00", "fora do horário"),
])
def test_schedule_rejects_bad_input(store, day, hour, error):
    with pytest.raises(ValueError, match=error):
        reuniao.schedule(store, day, hour, PAUTA)
    assert reuniao.get(store) is None and store.list() == []


def test_meeting_does_not_count_in_the_task_limit(store):
    for i in range(MAX_ACTIVE):
        store.add(Task(f"t{i}", f"Tarefa {i}", "x", kind="diaria", at="10:00"))
    with pytest.raises(ValueError, match="limite"):
        store.add(Task("extra", "Extra", "x", kind="diaria", at="10:00"))
    reuniao.schedule(store, "quarta", "10:00", PAUTA)  # as rotinas da plataforma entram mesmo assim
    assert reuniao.get(store) is not None


def test_cancel_and_reschedule(store):
    assert "Não havia" in reuniao.cancel(store)
    reuniao.schedule(store, "quinta", "11:00", PAUTA)
    assert "cancelada" in reuniao.cancel(store)
    assert reuniao.get(store) is None and store.list() == []
    reuniao.schedule(store, "quinta", "11:00", PAUTA)  # volta a ficar ativa
    assert reuniao.get(store) is not None


def test_context_line_says_if_it_is_combined(store):
    assert "ainda não combinada" in reuniao.context_line(store)
    reuniao.schedule(store, "segunda", "08:30", PAUTA)
    assert "toda segunda às 08:30" in reuniao.context_line(store)


# --- ferramenta e trava de turno ---------------------------------------------------

def test_tool_is_registered():
    assert "mcp__agenda__reuniao_semanal" in AGENDA_TOOLS
    assert "reuniao_semanal" in tools_for(AgendaStore.__new__(AgendaStore))


def test_tool_marks_when_the_owner_asked(store):
    tool = tools_for(store, by_owner=lambda: True)["reuniao_semanal"]
    text, error = call(tool, {"acao": "marcar", "dia": "terça", "hora": "09:00"})
    assert not error and "marcada" in text
    assert "terça às 09:00" in call(tool, {"acao": "situacao"})[0]
    assert "cancelada" in call(tool, {"acao": "cancelar"})[0]


def test_tool_refuses_a_turn_that_did_not_come_from_the_owner(store):
    """A agenda (ou um texto de e-mail) não cria sozinha uma rotina que manda mensagem ao dono toda semana."""
    tool = tools_for(store, by_owner=lambda: False)["reuniao_semanal"]
    text, error = call(tool, {"acao": "marcar", "dia": "terça", "hora": "09:00"})
    assert error and "mensagem do dono" in text and store.list() == []
    reuniao.schedule(store, "terça", "09:00", PAUTA)
    text, error = call(tool, {"acao": "cancelar"})
    assert error and reuniao.get(store) is not None  # nem cancelar
    assert "terça" in call(tool, {"acao": "situacao"})[0]  # ver pode


def test_tool_explains_bad_input_to_the_model(store):
    tool = tools_for(store, by_owner=lambda: True)["reuniao_semanal"]
    text, error = call(tool, {"acao": "marcar", "dia": "terça", "hora": "03:00"})
    assert error and "fora do horário" in text and store.list() == []
    assert call(tool, {"acao": "pular"})[1]


def test_agent_marks_scheduled_runs():
    from agente.core import Agent

    assert Agent.scheduled is False  # conversa normal: é o dono


# --- entrega silenciosa -------------------------------------------------------------

def test_silent_result_is_not_delivered(store):
    reuniao.schedule(store, "terça", "09:00", PAUTA)
    delivered = []

    async def runner(task):
        return "Pauta gravada.\n(sem mensagem)" if task.id == MEETING_PREP_ID else "Opa, chegou o nosso horário da semana."

    async def deliver(item):
        delivered.append(item.text)

    scheduler = Scheduler(store, runner, deliver)
    prep_time = datetime.fromisoformat("2026-11-17 07:00").replace(tzinfo=TZ)  # terça
    assert asyncio.run(scheduler.tick(prep_time)) == 1
    assert delivered == []  # o preparo trabalha calado, mesmo com uma frase antes da marca
    call_time = datetime.fromisoformat("2026-11-17 09:00").replace(tzinfo=TZ)
    assert asyncio.run(scheduler.tick(call_time)) == 1
    assert delivered[-1].startswith("Opa, chegou")


def test_exact_silent_marker_is_not_delivered(store):
    reuniao.schedule(store, "terça", "09:00", PAUTA)
    delivered = []

    async def runner(task):
        return "(sem mensagem)"

    async def deliver(item):
        delivered.append(item)

    scheduler = Scheduler(store, runner, deliver)
    when = datetime.fromisoformat("2026-11-17 07:00").replace(tzinfo=TZ)
    assert asyncio.run(scheduler.tick(when)) == 1
    assert delivered == [] and store.unread() == []


# --- prompt --------------------------------------------------------------------------

def test_prompt_placeholders_are_all_known():
    fields = {name for _, name, _, _ in Formatter().parse(SYSTEM_PROMPT) if name}
    known = {"workdir", "memory_dir", "now", "timezone", "memory", "knowledge", "search_hint", "data_dir", "data_note",
             "reuniao", "pauta"}
    assert fields <= known
    assert {"reuniao", "pauta"} <= fields


def test_prompt_teaches_the_consultant_tone():
    assert "Uma oferta por vez, e uma vez só" in SYSTEM_PROMPT
    assert '"Não" é resposta' in SYSTEM_PROMPT
    assert "(sem mensagem)" in SYSTEM_PROMPT
