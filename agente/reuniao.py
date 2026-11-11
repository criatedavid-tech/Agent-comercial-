"""Reunião semanal: um horário fixo na semana em que o agente chama o dono, pelo WhatsApp, para olhar a
empresa juntos (financeiro, comercial e operação). Muito dono nunca para para olhar a própria semana;
com hora marcada vira hábito. Ideia vinda do Maestro do Hiago, refeita sobre a nossa agenda.

São duas tarefas da agenda (as duas são "da plataforma": não contam no limite de tarefas ativas):
- o preparo, antes: o agente levanta os números da semana e monta a pauta, sem falar com o dono
  (termina com "(sem mensagem)", que a agenda não entrega);
- a chamada, na hora combinada: uma mensagem curta convidando para a conversa.

Trava no código: marcar ou cancelar só vale em resposta a uma mensagem do dono (ele combinou o dia e a
hora). Um turno aberto pela própria agenda, ou por texto de e-mail ou página, não cria sozinho uma rotina
que manda mensagem ao dono toda semana.
"""

from __future__ import annotations

import unicodedata

from .scheduler import MEETING_ID, MEETING_PREP_ID, WEEKDAYS, AgendaStore, Task

DAY_NAMES = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
EARLIEST, LATEST = "06:00", "22:00"  # fora disso não se chama o dono
PREP_LEAD_MIN = 120  # o preparo roda 2 horas antes


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def parse_day(value: object) -> int | None:
    """"segunda", "Segunda-feira", "ter", "terca" ou "0" a "6" (0 = segunda) viram o índice do dia."""
    text = _plain(value).removesuffix("-feira").removesuffix(" feira").strip()
    if text in {"0", "1", "2", "3", "4", "5", "6"}:
        return int(text)
    if len(text) < 3:
        return None
    for i, name in enumerate(DAY_NAMES):
        if _plain(name)[:3] == text[:3]:
            return i
    return None


def parse_hour(value: object) -> str | None:
    """"9", "9h", "09:00", "14h30" e "às 14:30" viram "HH:MM". None se não entendeu."""
    import re

    text = _plain(value).replace(" ", "")
    text = re.sub(r"^as", "", text)
    m = re.fullmatch(r"(\d{1,2})(?:(?:h|:)(\d{2})?|hs?|horas?)?", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def prep_slot(day: int, hour: str) -> tuple[int, str, bool]:
    """Dia e hora do preparo: 2 horas antes; se cair de madrugada, na véspera às 20h."""
    h, m = map(int, hour.split(":"))
    minutes = h * 60 + m - PREP_LEAD_MIN
    if minutes >= 6 * 60:
        return day, f"{minutes // 60:02d}:{minutes % 60:02d}", False
    return (day - 1) % 7, "20:00", True


def prep_prompt(hour: str, eve: bool, pauta: str) -> str:
    when = "amanhã" if eve else "hoje"
    return "\n".join([
        f"Preparo da reunião semanal (rotina da plataforma). A conversa com o dono é {when} às {hour}. "
        "Agora ele NÃO deve receber mensagem.",
        "Levante a semana (de segunda a domingo, contra a semana anterior), nas áreas em que você tem dados:",
        "- financeiro: quanto entrou, quanto saiu, o resultado, o que mudou e o que vence nos próximos 7 dias "
        "(delegue ao financeiro; relatorio_gestao e alertas_gestao);",
        "- comercial: vendas, leads e orçamentos parados, clientes que sumiram (delegue ao comercial; funil_comercial);",
        "- operação: compras, fornecedores, estoque e pendências (delegue à operação).",
        'Peça números com a fonte e a comparação com a semana anterior; as áreas independentes podem ir em paralelo. '
        'Comece cada pedido com "Para a pauta da reunião semanal:".',
        "Confira os totais antes de usar. Veja também listar_brechas para o que já está aberto.",
        f"Com os relatórios, grave a pauta em {pauta} (substitua a anterior): 3 números da semana, o que melhorou, "
        "o que piorou, de 1 a 3 brechas com valor em R$ (cruze as áreas quando fizer sentido: venda que caiu junto "
        "com compra que subiu, cliente que sumiu depois de atraso) e um combinado sugerido para a próxima semana.",
        "Sem dado nenhum ainda, monte a pauta com o que você sabe da conversa e anote o que faria diferença enxergar. "
        "Nunca invente número.",
        'Termine a resposta com exatamente: (sem mensagem)',
    ])


def call_prompt(hour: str, pauta: str) -> str:
    return "\n".join([
        f"Chegou a hora da reunião semanal com o dono (rotina da plataforma, combinada com ele, marcada para {hour}).",
        'Sua resposta final é enviada a ele como está. Escreva UMA mensagem curta e leve chamando para a conversa, '
        'do seu jeito, por exemplo: "Opa, chegou o nosso horário da semana. Consegue conversar uns 10 minutos agora?"',
        "Não mande os números nesta mensagem, não faça perguntas além do convite e não insista: é uma mensagem só.",
        f"(Se ele topar, quem atender vai conduzir pela pauta em {pauta}.)",
    ])


def get(store: AgendaStore) -> Task | None:
    task = store.get(MEETING_ID)
    return task if task and task.active else None


def describe(store: AgendaStore) -> str:
    task = get(store)
    if not task:
        return "Ainda não há reunião semanal combinada com o dono."
    day = DAY_NAMES[WEEKDAYS.index(task.weekdays)]
    nxt = f", a próxima em {task.next_run:%d/%m às %H:%M}" if task.next_run else ""
    return f"Reunião semanal: toda {day} às {task.at}{nxt}."


def context_line(store: AgendaStore) -> str:
    """Uma linha para o prompt de cada conversa: o que está combinado, ou que ainda não foi proposto."""
    task = get(store)
    if task:
        return describe(store)
    return "Reunião semanal com o dono: ainda não combinada. Proponha o horário fixo quando houver um gancho, uma vez só."


def schedule(store: AgendaStore, day: object, hour: object, pauta: str) -> str:
    """Cria ou muda a reunião (o preparo e a chamada). Devolve o texto para o modelo ou levanta ValueError."""
    d = parse_day(day)
    h = parse_hour(hour)
    if d is None:
        raise ValueError("não entendi o dia. Use segunda, terça, quarta, quinta, sexta, sábado ou domingo")
    if h is None:
        raise ValueError("não entendi a hora. Use o formato 09:00 ou 14:30 (horário de Brasília)")
    if not EARLIEST <= h <= LATEST:
        raise ValueError(f"{h} fica fora do horário razoável para chamar o dono (das {EARLIEST} às {LATEST}); confirme a hora com ele")
    changed = get(store) is not None
    prep_day, prep_hour, eve = prep_slot(d, h)
    store.add(Task(MEETING_PREP_ID, "Preparo da reunião semanal", prep_prompt(h, eve, pauta),
                   mode="tarefa", kind="semanal", at=prep_hour, weekdays=WEEKDAYS[prep_day]))
    call = store.add(Task(MEETING_ID, "Reunião semanal com o dono", call_prompt(h, pauta),
                          mode="tarefa", kind="semanal", at=h, weekdays=WEEKDAYS[d]))
    prep_when = f"na véspera ({DAY_NAMES[prep_day]}) às {prep_hour}" if eve else f"no mesmo dia às {prep_hour}"
    return (
        f"Reunião semanal {'atualizada' if changed else 'marcada'}: toda {DAY_NAMES[d]} às {h}, a primeira em "
        f"{call.next_run:%d/%m às %H:%M}. Criei as duas rotinas: o preparo ({prep_when}) e a chamada na hora. "
        "Confirme ao dono em uma linha."
    )


def cancel(store: AgendaStore) -> str:
    had = get(store) is not None
    store.cancel(MEETING_PREP_ID)
    store.cancel(MEETING_ID)
    return "Reunião semanal cancelada; o preparo e a chamada saíram da agenda." if had else "Não havia reunião semanal combinada."
